"""Launch real SKRL MAPPO training on the HADES Isaac Lab environment."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from isaaclab_bootstrap import add_isaaclab_source_paths, ensure_isaaclab_api


def _preparse_sim_device() -> str:
    for index, arg in enumerate(sys.argv):
        if arg == "--sim-device" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith("--sim-device="):
            return arg.split("=", 1)[1]
    return os.environ.get("HADES_SIM_DEVICE", "cuda:0")


add_isaaclab_source_paths()
from isaaclab.app import AppLauncher

_app_launcher = AppLauncher(
    {"headless": True, "anti_aliasing": 0, "enable_cameras": True, "device": _preparse_sim_device()}
)
_app = _app_launcher.app
print(f"[HADES] Isaac Lab app launched: sim_device={_preparse_sim_device()} cameras=enabled", flush=True)

ensure_isaaclab_api()

import gymnasium as gym
import torch
import torch.nn as nn
from skrl.envs.wrappers.torch import wrap_env
from skrl.memories.torch import RandomMemory
from skrl.models.torch import CategoricalMixin, DeterministicMixin, GaussianMixin, Model
from skrl.multi_agents.torch.mappo import MAPPO
from skrl.trainers.torch import ParallelTrainer

from hades.env.hades_env import HADESEnv
from hades.env.hades_env_cfg import HADESEnvCfg


class ContinuousPolicy(GaussianMixin, Model):
    def __init__(self, observation_space, action_space, device, hidden: int = 256) -> None:
        Model.__init__(self, observation_space, action_space, device)
        GaussianMixin.__init__(self, clip_actions=True)
        obs_dim = observation_space.shape[0]
        act_dim = action_space.shape[0]
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ELU(),
            nn.Linear(hidden, hidden), nn.ELU(),
            nn.Linear(hidden, act_dim),
        )
        self.log_std = nn.Parameter(torch.zeros(act_dim))

    def compute(self, inputs, role=""):
        mean = self.net(inputs["observations"])
        return mean, self.log_std.expand_as(mean), {}


class DiscretePolicy(CategoricalMixin, Model):
    def __init__(self, observation_space, action_space, device, hidden: int = 256) -> None:
        Model.__init__(self, observation_space, action_space, device)
        CategoricalMixin.__init__(self, unnormalized_log_prob=True)
        obs_dim = observation_space.shape[0]
        self.net = nn.Sequential(
            nn.Linear(obs_dim, hidden), nn.ELU(),
            nn.Linear(hidden, hidden), nn.ELU(),
            nn.Linear(hidden, action_space.n),
        )

    def compute(self, inputs, role=""):
        return self.net(inputs["observations"]), {}


class CentralValue(DeterministicMixin, Model):
    def __init__(self, state_space, action_space, device, hidden: int = 512) -> None:
        Model.__init__(self, state_space, action_space, device)
        DeterministicMixin.__init__(self)
        state_dim = state_space.shape[0]
        self.net = nn.Sequential(
            nn.Linear(state_dim, hidden), nn.ELU(),
            nn.Linear(hidden, 256), nn.ELU(),
            nn.Linear(256, 1),
        )

    def compute(self, inputs, role=""):
        return self.net(inputs["states"]), {}


def parse_args():
    parser = argparse.ArgumentParser(description="Train HADES MAPPO on real Isaac assets")
    parser.add_argument("--num-envs", type=int, default=64)
    parser.add_argument("--timesteps", type=int, default=500_000)
    parser.add_argument("--checkpoint-dir", default="checkpoints/hades_mappo")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--sim-device", default=os.environ.get("HADES_SIM_DEVICE", "cuda:0"))
    parser.add_argument("--rollouts", type=int, default=512)
    parser.add_argument("--checkpoint-interval", type=int, default=10_000)
    return parser.parse_args()


def _spaces(cfg: HADESEnvCfg) -> tuple[dict, dict, dict]:
    observation_spaces = {}
    action_spaces = {}
    state_spaces = {}
    state_dim = sum(cfg.observation_spaces[aid] for aid in cfg.possible_agents)
    global_state_space = gym.spaces.Box(low=-float("inf"), high=float("inf"), shape=(state_dim,))

    for agent_id in cfg.possible_agents:
        observation_spaces[agent_id] = gym.spaces.Box(
            low=-float("inf"),
            high=float("inf"),
            shape=(cfg.observation_spaces[agent_id],),
        )
        action_spaces[agent_id] = (
            gym.spaces.Box(low=-1.0, high=1.0, shape=(cfg.action_spaces[agent_id],))
            if agent_id.startswith("parent_")
            else gym.spaces.Discrete(cfg.action_spaces[agent_id])
        )
        state_spaces[agent_id] = global_state_space
    return observation_spaces, state_spaces, action_spaces


def _build_mappo(cfg: HADESEnvCfg, args, observation_spaces, state_spaces, action_spaces) -> MAPPO:
    models = {}
    memories = {}
    for agent_id in cfg.possible_agents:
        policy_cls = ContinuousPolicy if agent_id.startswith("parent_") else DiscretePolicy
        policy = policy_cls(observation_spaces[agent_id], action_spaces[agent_id], args.device)
        value = CentralValue(state_spaces[agent_id], action_spaces[agent_id], args.device)
        models[agent_id] = {"policy": policy, "value": value}
        memories[agent_id] = RandomMemory(
            memory_size=args.rollouts,
            num_envs=args.num_envs,
            device=args.device,
        )

    checkpoint_dir = Path(args.checkpoint_dir)
    mappo_cfg = {
        "rollouts": args.rollouts,
        "learning_epochs": 8,
        "mini_batches": 4,
        "discount_factor": 0.99,
        "gae_lambda": 0.95,
        "learning_rate": 3e-4,
        "grad_norm_clip": 1.0,
        "ratio_clip": 0.2,
        "value_loss_scale": 2.5,
        "entropy_loss_scale": 0.01,
        "experiment": {
            "directory": str(checkpoint_dir.parent),
            "experiment_name": checkpoint_dir.name,
            "write_interval": 1_000,
            "checkpoint_interval": args.checkpoint_interval,
            "store_separately": False,
        },
    }
    return MAPPO(
        possible_agents=cfg.possible_agents,
        models=models,
        memories=memories,
        observation_spaces=observation_spaces,
        state_spaces=state_spaces,
        action_spaces=action_spaces,
        device=args.device,
        cfg=mappo_cfg,
    )


def main() -> None:
    args = parse_args()
    os.makedirs(args.checkpoint_dir, exist_ok=True)

    cfg = HADESEnvCfg()
    cfg.scene.num_envs = args.num_envs
    cfg.sim.device = args.sim_device
    cfg.state_space = sum(cfg.observation_spaces[aid] for aid in cfg.possible_agents)
    cfg.require_real_assets = True
    cfg.require_real_sensors = True
    cfg.use_real_models = True

    print(f"[HADES] constructing real HADESEnv: num_envs={args.num_envs} sim_device={args.sim_device}", flush=True)
    raw_env = HADESEnv(cfg)
    print("[HADES] environment constructed; resetting and validating assets/sensors", flush=True)
    raw_env.reset()
    report = raw_env.validate_real_runtime(require_sensors=True)
    print(f"[HADES] real runtime validated: {report}", flush=True)

    env = wrap_env(raw_env, wrapper="isaaclab-multi-agent")
    observation_spaces, state_spaces, action_spaces = _spaces(cfg)
    agent = _build_mappo(cfg, args, observation_spaces, state_spaces, action_spaces)

    trainer = ParallelTrainer(
        env=env,
        agents=agent,
        cfg={"timesteps": args.timesteps, "headless": True},
    )
    trainer.train()
    _app.close()


if __name__ == "__main__":
    main()
