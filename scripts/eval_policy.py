"""Evaluate a trained MAPPO checkpoint and print mean EpisodeScore."""

from __future__ import annotations

import argparse
import os
import statistics
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
from skrl.models.torch import CategoricalMixin, DeterministicMixin, GaussianMixin, Model

from hades.env.hades_env import HADESEnv
from hades.env.hades_env_cfg import HADESEnvCfg
from hades.scoring import EpisodeScore, ScoreCalculator


class ContinuousPolicy(GaussianMixin, Model):
    def __init__(self, observation_space, action_space, device, hidden: int = 256) -> None:
        Model.__init__(self, observation_space, action_space, device)
        GaussianMixin.__init__(self, clip_actions=True)
        self.net = nn.Sequential(
            nn.Linear(observation_space.shape[0], hidden), nn.ELU(),
            nn.Linear(hidden, hidden), nn.ELU(),
            nn.Linear(hidden, action_space.shape[0]),
        )
        self.log_std = nn.Parameter(torch.zeros(action_space.shape[0]))

    def compute(self, inputs, role=""):
        mean = self.net(inputs["observations"])
        return mean, self.log_std.expand_as(mean), {}


class DiscretePolicy(CategoricalMixin, Model):
    def __init__(self, observation_space, action_space, device, hidden: int = 256) -> None:
        Model.__init__(self, observation_space, action_space, device)
        CategoricalMixin.__init__(self, unnormalized_log_prob=True)
        self.net = nn.Sequential(
            nn.Linear(observation_space.shape[0], hidden), nn.ELU(),
            nn.Linear(hidden, hidden), nn.ELU(),
            nn.Linear(hidden, action_space.n),
        )

    def compute(self, inputs, role=""):
        return self.net(inputs["observations"]), {}


class CentralValue(DeterministicMixin, Model):
    def __init__(self, state_space, action_space, device, hidden: int = 512) -> None:
        Model.__init__(self, state_space, action_space, device)
        DeterministicMixin.__init__(self)
        self.net = nn.Sequential(
            nn.Linear(state_space.shape[0], hidden), nn.ELU(),
            nn.Linear(hidden, 256), nn.ELU(),
            nn.Linear(256, 1),
        )

    def compute(self, inputs, role=""):
        return self.net(inputs["states"]), {}


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluate HADES MAPPO checkpoint")
    parser.add_argument("--checkpoint-dir", required=True)
    parser.add_argument("--episodes", type=int, default=20)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--sim-device", default=os.environ.get("HADES_SIM_DEVICE", "cuda:0"))
    parser.add_argument("--max-steps", type=int, default=600)
    return parser.parse_args()


def _latest_checkpoint(checkpoint_dir: str) -> Path:
    root = Path(checkpoint_dir)
    candidates = list(root.rglob("best_agent.pt")) + list(root.rglob("agent_*.pt"))
    if not candidates:
        raise FileNotFoundError(f"No MAPPO checkpoint found under {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _spaces(cfg: HADESEnvCfg):
    obs_spaces = {}
    action_spaces = {}
    state_dim = sum(cfg.observation_spaces[aid] for aid in cfg.possible_agents)
    state_space = gym.spaces.Box(low=-float("inf"), high=float("inf"), shape=(state_dim,))
    for agent_id in cfg.possible_agents:
        obs_spaces[agent_id] = gym.spaces.Box(
            low=-float("inf"),
            high=float("inf"),
            shape=(cfg.observation_spaces[agent_id],),
        )
        action_spaces[agent_id] = (
            gym.spaces.Box(low=-1.0, high=1.0, shape=(cfg.action_spaces[agent_id],))
            if agent_id.startswith("parent_")
            else gym.spaces.Discrete(cfg.action_spaces[agent_id])
        )
    return obs_spaces, state_space, action_spaces


def _build_models(cfg: HADESEnvCfg, device: str):
    obs_spaces, state_space, action_spaces = _spaces(cfg)
    models = {}
    for agent_id in cfg.possible_agents:
        policy_cls = ContinuousPolicy if agent_id.startswith("parent_") else DiscretePolicy
        models[agent_id] = {
            "policy": policy_cls(obs_spaces[agent_id], action_spaces[agent_id], device),
            "value": CentralValue(state_space, action_spaces[agent_id], device),
        }
    return models


def _load_policies(models: dict, checkpoint: Path, device: str) -> None:
    modules = torch.load(checkpoint, map_location=device, weights_only=False)
    for agent_id, agent_modules in models.items():
        agent_modules["policy"].load_state_dict(modules[agent_id]["policy"])
        agent_modules["policy"].eval()


def _obs_tensors(obs: dict, cfg: HADESEnvCfg, device: str) -> dict[str, torch.Tensor]:
    tensors = {}
    for agent_id in cfg.possible_agents:
        value = obs[agent_id]["obs"] if isinstance(obs[agent_id], dict) else obs[agent_id]
        tensors[agent_id] = value.to(device)
    return tensors


def _done(terminated: dict, truncated: dict, cfg: HADESEnvCfg) -> bool:
    return any(bool(terminated[aid][0] or truncated[aid][0]) for aid in cfg.possible_agents)


def _run_episode(env: HADESEnv, cfg: HADESEnvCfg, models: dict, device: str, max_steps: int) -> EpisodeScore:
    obs = env.reset()
    if isinstance(obs, tuple):
        obs = obs[0]
    scorer = ScoreCalculator()

    for _ in range(max_steps):
        tensors = _obs_tensors(obs, cfg, device)
        state = torch.cat([tensors[aid].reshape(1, -1) for aid in cfg.possible_agents], dim=-1)
        actions = {}
        with torch.no_grad():
            for agent_id in cfg.possible_agents:
                action, _ = models[agent_id]["policy"].act(
                    {"observations": tensors[agent_id], "states": state},
                    role="policy",
                )
                actions[agent_id] = action.detach().cpu()

        obs, rewards, terminated, truncated, _ = env.step(actions)
        if env._curr_frame is not None:
            scorer.record_step(
                env._curr_frame,
                rewards,
                convoy_hit=bool(env._convoy_hit[0].item()),
            )
        if _done(terminated, truncated, cfg):
            break

    return scorer.finalize()


def main() -> None:
    args = parse_args()
    checkpoint = _latest_checkpoint(args.checkpoint_dir)
    print(f"[HADES] loading checkpoint: {checkpoint}", flush=True)

    cfg = HADESEnvCfg()
    cfg.scene.num_envs = 1
    cfg.sim.device = args.sim_device
    cfg.state_space = sum(cfg.observation_spaces[aid] for aid in cfg.possible_agents)
    cfg.require_real_assets = True
    cfg.require_real_sensors = True
    cfg.use_real_models = True

    print(f"[HADES] constructing real HADESEnv: num_envs=1 sim_device={args.sim_device}", flush=True)
    env = HADESEnv(cfg)
    print("[HADES] environment constructed; resetting and validating assets/sensors", flush=True)
    env.reset()
    print(f"[HADES] real runtime validated: {env.validate_real_runtime(require_sensors=True)}", flush=True)

    models = _build_models(cfg, args.device)
    _load_policies(models, checkpoint, args.device)

    scores = [_run_episode(env, cfg, models, args.device, args.max_steps) for _ in range(args.episodes)]
    returns = [score.total_return for score in scores]
    print(
        "EpisodeScore "
        f"convoy_survived={statistics.mean(1.0 if s.convoy_survived else 0.0 for s in scores):.3f} "
        f"route_completion_pct={statistics.mean(s.route_completion_pct for s in scores):.2f} "
        f"threats_neutralized={statistics.mean(s.threats_neutralized for s in scores):.2f} "
        f"compute_drop_rate={statistics.mean(s.compute_drop_rate for s in scores):.4f} "
        f"mean_link_quality={statistics.mean(s.mean_link_quality for s in scores):.4f} "
        f"total_return_mean={statistics.mean(returns):.2f} "
        f"total_return_std={statistics.stdev(returns) if len(returns) > 1 else 0.0:.2f} "
        f"n={len(scores)}",
        flush=True,
    )
    _app.close()


if __name__ == "__main__":
    main()
