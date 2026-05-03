"""Launch SKRL MAPPO training on the HADES convoy-escort environment."""

from __future__ import annotations

import argparse
import os

# Isaac Sim must be bootstrapped before any carb/omni imports
from isaacsim import SimulationApp
_app = SimulationApp({"headless": True, "anti_aliasing": 0})

import torch
from skrl.agents.torch.ppo import PPO, PPO_DEFAULT_CONFIG
from skrl.envs.wrappers.torch import wrap_env
from skrl.memories.torch import RandomMemory
from skrl.models.torch import DeterministicMixin, GaussianMixin, Model
from skrl.trainers.torch import SequentialTrainer

from hades.env.hades_env import HADESEnv
from hades.env.hades_env_cfg import HADESEnvCfg


# ------------------------------------------------------------------
# Shared policy/value network (per agent tier)
# ------------------------------------------------------------------

class SharedPolicy(GaussianMixin, Model):
    def __init__(self, obs_space, act_space, device, hidden=256):
        Model.__init__(self, obs_space, act_space, device)
        GaussianMixin.__init__(self, clip_actions=True)
        import torch.nn as nn
        obs_dim = obs_space.shape[0]
        act_dim = act_space.shape[0] if hasattr(act_space, "shape") else act_space.n
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ELU(),
            nn.Linear(hidden, hidden),  nn.ELU(),
            nn.Linear(hidden, act_dim),
        )
        self.log_std = nn.Parameter(torch.zeros(act_dim))

    def compute(self, inputs, role=""):
        x = self.net(inputs["states"])
        return x, self.log_std.expand_as(x), {}


class SharedValue(DeterministicMixin, Model):
    def __init__(self, obs_space, act_space, device, hidden=256):
        Model.__init__(self, obs_space, act_space, device)
        DeterministicMixin.__init__(self)
        import torch.nn as nn
        obs_dim = obs_space.shape[0]
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ELU(),
            nn.Linear(hidden, hidden),  nn.ELU(),
            nn.Linear(hidden, 1),
        )

    def compute(self, inputs, role=""):
        return self.net(inputs["states"]), {}


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Train HADES MAPPO")
    p.add_argument("--num-envs", type=int, default=64)
    p.add_argument("--timesteps", type=int, default=500_000)
    p.add_argument("--checkpoint-dir", default="checkpoints/hades_mappo")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.checkpoint_dir, exist_ok=True)

    cfg = HADESEnvCfg()
    cfg.scene.num_envs = args.num_envs
    env = HADESEnv(cfg)
    env = wrap_env(env, wrapper="isaaclab-multi-agent")

    device = args.device

    # Build one PPO agent per logical tier: parents share weights, smalls share weights
    agents = {}
    memories = {}

    for agent_id in cfg.possible_agents:
        obs_dim = cfg.observation_spaces[agent_id]
        act_dim = cfg.action_spaces[agent_id]

        import gymnasium as gym
        obs_space = gym.spaces.Box(low=-1.0, high=1.0, shape=(obs_dim,))
        act_space = (
            gym.spaces.Box(low=-1.0, high=1.0, shape=(act_dim,))
            if agent_id.startswith("parent_")
            else gym.spaces.Discrete(act_dim)
        )

        policy = SharedPolicy(obs_space, act_space, device)
        value  = SharedValue(obs_space, act_space, device)

        ppo_cfg = PPO_DEFAULT_CONFIG.copy()
        ppo_cfg.update({
            "rollouts": 512,
            "learning_epochs": 8,
            "mini_batches": 4,
            "discount_factor": 0.99,
            "lambda": 0.95,
            "learning_rate": 3e-4,
            "grad_norm_clip": 1.0,
            "checkpoint_interval": 10_000,
            "directory": args.checkpoint_dir,
        })

        mem = RandomMemory(memory_size=512, num_envs=args.num_envs, device=device)
        agents[agent_id] = PPO(
            models={"policy": policy, "value": value},
            memory=mem,
            cfg=ppo_cfg,
            observation_space=obs_space,
            action_space=act_space,
            device=device,
        )
        memories[agent_id] = mem

    trainer = SequentialTrainer(
        cfg={"timesteps": args.timesteps, "headless": True},
        env=env,
        agents=list(agents.values()),
    )
    trainer.train()
    _app.close()


if __name__ == "__main__":
    main()
