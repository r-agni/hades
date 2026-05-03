"""HADESEnv — Isaac Lab DirectMARLEnv for the convoy-escort task."""

from __future__ import annotations

import math
from typing import Any

import torch

# Isaac Lab imports (guarded so unit tests can import without Isaac Sim)
try:
    from isaaclab.envs import DirectMARLEnv
    _ISAAC_AVAILABLE = True
except ImportError:
    _ISAAC_AVAILABLE = False
    # Minimal stub so the module is importable in headless/test mode
    class DirectMARLEnv:  # type: ignore[no-redef]
        def __init__(self, cfg, **kwargs):
            self.cfg = cfg
            self.num_envs = cfg.scene.num_envs
            self.device = "cpu"

from hades.env.action_executor import ActionExecutor
from hades.env.hades_env_cfg import HADESEnvCfg
from hades.env.obs_builder import ObsBuilder
from hades.env.reward import RewardCalculator
from hades.state import SimFrame


class HADESEnv(DirectMARLEnv):
    """Convoy-escort MARL environment.

    8 RL agents: 2 parent drones + 6 small drones.
    Convoy follows a Dijkstra route (not an RL agent).
    """

    cfg: HADESEnvCfg

    def __init__(self, cfg: HADESEnvCfg, **kwargs) -> None:
        self._publisher = None
        self._last_sensor_data: dict[str, Any] = {}
        self._validated_asset_root: str | None = None

        super().__init__(cfg, **kwargs)

        self._obs_builder = ObsBuilder(cfg)
        self._reward_calc = RewardCalculator(cfg)
        self._action_exec = ActionExecutor(cfg)

        # Runtime state
        self._prev_frame: SimFrame | None = None
        self._curr_frame: SimFrame | None = None
        self._sim_t: float = 0.0
        self._step_dt: float = cfg.sim.dt

        # Per-env episode state
        ne = cfg.scene.num_envs
        self._convoy_hit = torch.zeros(ne, dtype=torch.bool)
        self._convoy_done = torch.zeros(ne, dtype=torch.bool)

    # ------------------------------------------------------------------
    # Isaac Lab lifecycle
    # ------------------------------------------------------------------

    def _setup_scene(self) -> None:
        """Create Isaac stage actors and configure sensors."""
        if not _ISAAC_AVAILABLE:
            return

        # Import here to avoid circular / missing deps at module load
        from bridge.sim_publisher import SyntheticWorldLayout, Track2SimPublisher
        self._publisher = Track2SimPublisher(
            layout=SyntheticWorldLayout.demo_60s(),
            stub=not getattr(self.cfg, "use_real_models", False),
        )

        # Isaac Lab will automatically register scene assets from HADESSceneCfg;
        # we only need to add terrain and clone to all envs.
        self.scene.clone_environments(copy_from_source=False)
        self.scene.filter_collisions(global_prim_paths=[])
        if getattr(self.cfg, "require_real_assets", False):
            self.validate_real_runtime(require_sensors=False)

    def _pre_physics_step(self, actions: dict[str, torch.Tensor]) -> None:
        """Store actions; they are applied in _apply_action."""
        self._last_actions = actions

    def _apply_action(self) -> None:
        """Advance sim time and update publisher state."""
        self._sim_t += self._step_dt
        if self._publisher is not None:
            self._prev_frame = self._curr_frame
            self._curr_frame = self._publisher.frame_at(self._sim_t)

        # Commands decoded from actions (used for future physics writes)
        if hasattr(self, "_last_actions") and self._curr_frame is not None:
            self._action_exec.execute(self._last_actions, self._curr_frame)

    def _get_observations(self) -> dict[str, dict[str, torch.Tensor]]:
        """Build per-agent observation dicts."""
        if self._curr_frame is None:
            return {
                aid: {"obs": torch.zeros(self.num_envs, self.cfg.observation_spaces[aid])}
                for aid in self.cfg.possible_agents
            }

        frame = self._curr_frame
        positions = {d.id: (d.pose.x, d.pose.y, d.pose.z) for d in frame.drones}
        convoy_pos = (
            (frame.convoy[0].pose.x, frame.convoy[0].pose.y, frame.convoy[0].pose.z)
            if frame.convoy else (0.0, 0.0, 0.0)
        )
        convoy_progress = frame.convoy[0].route_progress_pct if frame.convoy else 0.0

        # Comms graph — import lazily to avoid circular imports at module level
        from hades.comms import CommsGraph
        comms = CommsGraph()
        comms.step(frame.drones, frame.edges, frame.convoy)

        sensor_data = self._collect_sensor_data()
        if getattr(self.cfg, "require_real_sensors", False):
            from hades.env.validation import validate_sensor_payload
            validate_sensor_payload(sensor_data)

        return self._obs_builder.build(
            sensor_data=sensor_data,
            comms=comms,
            compute_events=frame.compute_events,
            positions=positions,
            convoy_pos=convoy_pos,
            convoy_progress=convoy_progress,
            threats=frame.threats,
        )

    def _get_rewards(self) -> dict[str, torch.Tensor]:
        """Compute per-agent reward tensors."""
        if self._curr_frame is None:
            return {
                aid: torch.zeros(self.num_envs)
                for aid in self.cfg.possible_agents
            }

        return self._reward_calc.compute(
            prev_frame=self._prev_frame,
            curr_frame=self._curr_frame,
            actions=getattr(self, "_last_actions", {}),
            convoy_hit=self._convoy_hit,
            convoy_done=self._convoy_done,
        )

    def _get_states(self) -> torch.Tensor:
        """Return centralized state as concatenated per-agent observations."""
        obs = self._get_observations()
        return torch.cat(
            [obs[aid]["obs"].reshape(self.num_envs, -1) for aid in self.cfg.possible_agents],
            dim=-1,
        )

    def _get_dones(self) -> tuple[dict[str, torch.Tensor], dict[str, torch.Tensor]]:
        """Return (terminated, truncated) dicts per agent."""
        if self._curr_frame is None:
            zeros = {aid: torch.zeros(self.num_envs, dtype=torch.bool)
                     for aid in self.cfg.possible_agents}
            return zeros, zeros

        frame = self._curr_frame
        ne = self.num_envs

        # Check convoy terminal conditions (env-0 drives shared flag)
        if frame.convoy:
            progress = frame.convoy[0].route_progress_pct
            self._convoy_done[:] = progress >= 100.0
            # Convoy hit: any threat within 20 m of convoy
            cx = frame.convoy[0].pose.x
            cy = frame.convoy[0].pose.y
            for th in frame.threats:
                dist = math.sqrt((th.pose.x - cx) ** 2 + (th.pose.y - cy) ** 2)
                if dist < 20.0:
                    self._convoy_hit[:] = True

        # Episode truncation: time limit (handled by Isaac Lab base class)
        terminated = {
            aid: (self._convoy_done | self._convoy_hit).clone()
            for aid in self.cfg.possible_agents
        }
        truncated = {
            aid: torch.zeros(ne, dtype=torch.bool)
            for aid in self.cfg.possible_agents
        }
        return terminated, truncated

    def _reset_idx(self, env_ids: torch.Tensor) -> None:
        """Reset specific environments by index."""
        self._convoy_hit[env_ids] = False
        self._convoy_done[env_ids] = False
        self._sim_t = 0.0
        self._prev_frame = None
        self._curr_frame = None

        if self._publisher is not None:
            self._publisher.reset(env_ids)

    def validate_real_runtime(self, *, require_sensors: bool | None = None) -> dict[str, Any]:
        """Fail fast if the real Isaac assets or sensor tensors are unavailable."""
        if not _ISAAC_AVAILABLE:
            raise RuntimeError("Isaac Lab is not available; real HADES runtime cannot be validated")

        from hades.env.validation import validate_sensor_payload, validate_stage_assets

        import omni.usd

        stage = omni.usd.get_context().get_stage()
        env_root = f"{self.scene.env_ns}/env_0/hades_phase_1"
        self._validated_asset_root = validate_stage_assets(
            stage,
            candidate_roots=(env_root, "/hades_phase_1"),
        )

        sensor_data = self._collect_sensor_data()
        if require_sensors is None:
            require_sensors = getattr(self.cfg, "require_real_sensors", False)
        if require_sensors:
            validate_sensor_payload(sensor_data)

        return {
            "asset_root": self._validated_asset_root,
            "sensor_keys": sorted(sensor_data.keys()),
        }

    def _collect_sensor_data(self) -> dict[str, Any]:
        if not _ISAAC_AVAILABLE or not hasattr(self, "scene"):
            self._last_sensor_data = {}
            return {}

        sensors = getattr(self.scene, "sensors", {})
        sensor_data: dict[str, Any] = {}

        def _sensor(name: str) -> Any:
            return sensors.get(name) if isinstance(sensors, dict) else None

        def _camera_output(sensor_name: str, output_name: str) -> Any:
            sensor = _sensor(sensor_name)
            output = getattr(getattr(sensor, "data", None), "output", None)
            if isinstance(output, dict):
                return output.get(output_name)
            return None

        def _data_attr(sensor_name: str, attr: str) -> Any:
            sensor = _sensor(sensor_name)
            return getattr(getattr(sensor, "data", None), attr, None)

        mappings = {
            "parent_nav_rgb": _camera_output("parent_nav_cam", "rgb"),
            "parent_nav_depth": _camera_output("parent_nav_cam", "distance_to_camera"),
            "parent_thermal": _camera_output("parent_thermal", "rgb"),
            "parent_lidar": _data_attr("parent_lidar", "ray_hits_w"),
            "parent_imu_acc": _data_attr("parent_imu", "lin_acc_b"),
            "parent_imu_gyr": _data_attr("parent_imu", "ang_vel_b"),
            "small_rgb": _camera_output("small_cam", "rgb"),
            "small_imu_acc": _data_attr("small_imu", "lin_acc_b"),
            "small_imu_gyr": _data_attr("small_imu", "ang_vel_b"),
        }
        sensor_data.update({key: value for key, value in mappings.items() if value is not None})
        self._last_sensor_data = sensor_data
        return sensor_data
