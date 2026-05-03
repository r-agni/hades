"""Run the 60-second HADES Phase 4 scored demo with real Isaac assets."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path


def _preparse_headless() -> bool:
    return "--headless" in sys.argv or "--gui" not in sys.argv


def _preparse_sim_device() -> str:
    for index, arg in enumerate(sys.argv):
        if arg == "--sim-device" and index + 1 < len(sys.argv):
            return sys.argv[index + 1]
        if arg.startswith("--sim-device="):
            return arg.split("=", 1)[1]
    return os.environ.get("HADES_SIM_DEVICE", "cuda:0")


from isaaclab_bootstrap import add_isaaclab_source_paths, ensure_isaaclab_api


add_isaaclab_source_paths()
from isaaclab.app import AppLauncher

_app_launcher = AppLauncher(
    {
        "headless": _preparse_headless(),
        "anti_aliasing": 0,
        "enable_cameras": True,
        "device": _preparse_sim_device(),
    }
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
    parser = argparse.ArgumentParser(description="Run HADES Phase 4 demo")
    parser.add_argument("--checkpoint-dir", default="checkpoints/hades_mappo")
    parser.add_argument("--duration-s", type=float, default=60.0)
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--sim-device", default=os.environ.get("HADES_SIM_DEVICE", "cuda:0"))
    parser.add_argument("--headless", action="store_true", default=True)
    parser.add_argument("--gui", action="store_true", help="Launch with a visible viewport")
    parser.add_argument("--artifact-jsonl", default="artifacts/hades_phase4_demo.jsonl")
    return parser.parse_args()


def _latest_checkpoint(checkpoint_dir: str) -> Path:
    root = Path(checkpoint_dir)
    candidates = list(root.rglob("best_agent.pt")) + list(root.rglob("agent_*.pt"))
    if not candidates:
        raise FileNotFoundError(f"No trained MAPPO checkpoint found under {root}")
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


class DebugOverlay:
    def __init__(self) -> None:
        self._draw = None
        try:
            from omni.isaac.debug_draw import _debug_draw

            self._draw = _debug_draw.acquire_debug_draw_interface()
        except Exception as exc:
            print(f"[HADES] debug draw unavailable: {exc}", flush=True)

    def update(self, frame) -> None:
        if self._draw is None:
            return
        try:
            self._draw.clear_lines()
            self._draw.clear_points()
            starts = []
            ends = []
            colors = []
            for link in frame.links:
                src = _actor_pose(frame, link.from_id)
                dst = _actor_pose(frame, link.to_id)
                if src is None or dst is None:
                    continue
                starts.append((src.x, src.y, src.z))
                ends.append((dst.x, dst.y, dst.z))
                colors.append((1.0 - link.quality, link.quality, 0.1, 1.0))
            if starts:
                self._draw.draw_lines(starts, ends, colors, [2.0] * len(starts))

            points = [(th.pose.x, th.pose.y, th.pose.z + 2.0) for th in frame.threats]
            if points:
                self._draw.draw_points(points, [(1.0, 0.05, 0.05, 1.0)] * len(points), [16.0] * len(points))
        except Exception as exc:
            print(f"[HADES] debug overlay update failed: {exc}", flush=True)
            self._draw = None


def _actor_pose(frame, actor_id: str):
    for collection in (frame.drones, frame.edges, frame.convoy):
        for actor in collection:
            if actor.id == actor_id:
                return actor.pose
    return None


class DemoOrchestrator:
    def __init__(self, args) -> None:
        self.args = args
        self.cfg = HADESEnvCfg()
        self.cfg.scene.num_envs = 1
        self.cfg.sim.device = args.sim_device
        self.cfg.state_space = sum(self.cfg.observation_spaces[aid] for aid in self.cfg.possible_agents)
        self.cfg.require_real_assets = True
        self.cfg.require_real_sensors = True
        self.cfg.use_real_models = True
        print(f"[HADES] constructing real HADESEnv: num_envs=1 sim_device={args.sim_device}", flush=True)
        self.env = HADESEnv(self.cfg)
        print("[HADES] environment constructed; waiting for reset-time asset/sensor validation", flush=True)
        self.models = _build_models(self.cfg, args.device)
        self.overlay = DebugOverlay()

    def load(self) -> Path:
        checkpoint = _latest_checkpoint(self.args.checkpoint_dir)
        _load_policies(self.models, checkpoint, self.args.device)
        obs = self.env.reset()
        if isinstance(obs, tuple):
            obs = obs[0]
        report = self.env.validate_real_runtime(require_sensors=True)
        print(f"[HADES] real environment/assets/sensors validated: {report}", flush=True)
        print(f"[HADES] checkpoint loaded: {checkpoint}", flush=True)
        self._obs = obs
        return checkpoint

    def run(self) -> EpisodeScore:
        self.load()
        artifact_path = Path(self.args.artifact_jsonl)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        scorer = ScoreCalculator()
        act_name = None
        max_steps = int(self.args.duration_s / self.cfg.sim.dt)

        with artifact_path.open("w", encoding="utf-8") as handle:
            for _ in range(max_steps):
                frame_t = self.env._sim_t
                next_act = self._act_name(frame_t)
                if next_act != act_name:
                    act_name = next_act
                    print(f"[HADES] {act_name}", flush=True)

                actions = self._policy_actions(self._obs)
                self._obs, rewards, terminated, truncated, _ = self.env.step(actions)
                frame = self.env._curr_frame
                if frame is None:
                    continue

                self.overlay.update(frame)
                scorer.record_step(frame, rewards, convoy_hit=bool(self.env._convoy_hit[0].item()))
                handle.write(json.dumps({
                    "act": act_name,
                    "score_so_far": asdict(scorer.finalize()),
                    "frame": frame.to_full_dict(),
                }, separators=(",", ":")) + "\n")

                if any(bool(terminated[aid][0] or truncated[aid][0]) for aid in self.cfg.possible_agents):
                    break

        score = scorer.finalize()
        print(f"[HADES] EpisodeScore {score}", flush=True)
        print(f"[HADES] telemetry artifact: {artifact_path}", flush=True)
        return score

    def _policy_actions(self, obs: dict) -> dict[str, torch.Tensor]:
        tensors = {}
        for agent_id in self.cfg.possible_agents:
            value = obs[agent_id]["obs"] if isinstance(obs[agent_id], dict) else obs[agent_id]
            tensors[agent_id] = value.to(self.args.device)
        state = torch.cat([tensors[aid].reshape(1, -1) for aid in self.cfg.possible_agents], dim=-1)
        actions = {}
        with torch.no_grad():
            for agent_id in self.cfg.possible_agents:
                action, _ = self.models[agent_id]["policy"].act(
                    {"observations": tensors[agent_id], "states": state},
                    role="policy",
                )
                actions[agent_id] = action.detach().cpu()
        return actions

    @staticmethod
    def _act_name(t: float) -> str:
        if t < 15.0:
            return "Act 1: convoy departure, escort formation, comms graph live"
        if t < 30.0:
            return "Act 2: choke threat, north bypass reroute, compute offload"
        return "Act 3: bypass/arrival, fallback if needed, final scoring"


def main() -> None:
    args = parse_args()
    try:
        DemoOrchestrator(args).run()
    finally:
        _app.close()


if __name__ == "__main__":
    main()
