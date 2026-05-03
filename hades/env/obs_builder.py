"""Flatten raw sensor tensors into per-agent observation vectors."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from hades.comms import CommsGraph
    from hades.compute import ComputeScheduler
    from hades.env.hades_env_cfg import HADESEnvCfg
    from hades.state import ComputeEvent


# Small drone action indices
HOLD, MOVE_N, MOVE_S, MOVE_E, MOVE_W, MOVE_UP, RELAY = range(7)

# Conversion: RL normalised [-1,1] → physical units
VX_MAX = 15.0   # m/s
VZ_MAX = 5.0    # m/s
YAW_MAX = math.pi / 4  # rad/s


class ObsBuilder:
    """Builds per-agent observation dicts from raw Isaac Lab sensor outputs.

    In headless / test mode the sensor dicts may be None — ObsBuilder
    returns zero tensors of the correct shape so the env can be stepped
    without a live Isaac stage.
    """

    def __init__(self, cfg: "HADESEnvCfg") -> None:
        self._cfg = cfg
        self._num_envs: int = cfg.scene.num_envs

    def build(
        self,
        sensor_data: dict,
        comms: "CommsGraph",
        compute_events: list["ComputeEvent"],
        positions: dict,      # agent_id → (x, y, z) world coords
        convoy_pos: tuple,    # (x, y, z) of convoy_0
        convoy_progress: float,
        threats: list,
    ) -> dict[str, dict[str, torch.Tensor]]:
        """Return {agent_id: {"obs": tensor([num_envs, obs_dim])}}."""
        obs: dict[str, dict[str, torch.Tensor]] = {}
        ne = self._num_envs

        # Build threat histogram (8 octants, 200 m ahead corridor)
        threat_hist = self._threat_histogram(threats, convoy_pos, ne)

        for agent_id in self._cfg.possible_agents:
            pos = positions.get(agent_id, (0.0, 0.0, 0.0))
            if agent_id.startswith("parent_"):
                obs[agent_id] = {
                    "obs": self._parent_obs(
                        agent_id, pos, sensor_data, comms, positions,
                        convoy_pos, convoy_progress, threat_hist, ne,
                    )
                }
            else:
                obs[agent_id] = {
                    "obs": self._small_obs(
                        agent_id, pos, sensor_data, comms, positions,
                        convoy_pos, convoy_progress, compute_events, threats, ne,
                    )
                }
        return obs

    # ------------------------------------------------------------------
    # Parent obs (dim 64)
    # pose(6) + battery(1) + compute_load(1) + convoy_relative(3) +
    # route_progress(1) + per_small[rel(3)+batt(1)+lq(1)]×6=30 +
    # 4×4_threat_grid(16) + nearest_3_edges[tops+latency]×3=6
    # ------------------------------------------------------------------
    def _parent_obs(
        self, agent_id, pos, sensor_data, comms, positions,
        convoy_pos, convoy_progress, threat_hist, ne,
    ) -> torch.Tensor:
        vec = torch.zeros(ne, 64)
        x, y, z = pos
        # pose (6)
        vec[:, 0] = x / 600.0
        vec[:, 1] = y / 200.0
        vec[:, 2] = z / 50.0
        # roll/pitch/yaw = 0 for now (IMU not yet wired to pose)
        # battery (1) — placeholder 0.9
        vec[:, 6] = 0.9
        # compute_load (1) — placeholder 0.2
        vec[:, 7] = 0.2
        # convoy relative (3)
        cx, cy, cz = convoy_pos
        vec[:, 8]  = (cx - x) / 600.0
        vec[:, 9]  = (cy - y) / 200.0
        vec[:, 10] = convoy_progress / 100.0
        # route_progress (1)
        vec[:, 11] = convoy_progress / 100.0
        # per-small (30 = 6 × 5)
        for i, small_id in enumerate([f"small_{j}" for j in range(6)]):
            sp = positions.get(small_id, (0.0, 0.0, 0.0))
            base = 12 + i * 5
            vec[:, base]     = (sp[0] - x) / 300.0
            vec[:, base + 1] = (sp[1] - y) / 300.0
            vec[:, base + 2] = (sp[2] - z) / 50.0
            vec[:, base + 3] = 0.9   # battery placeholder
            vec[:, base + 4] = comms.link_quality(agent_id, small_id)
        # threat grid uses threat_hist (16)
        vec[:, 42:58] = threat_hist
        vec[:, 58] = _tensor_mean(sensor_data.get("parent_nav_rgb"), scale=255.0)
        vec[:, 59] = _tensor_mean(sensor_data.get("parent_nav_depth"), scale=100.0)
        vec[:, 60] = _tensor_mean(sensor_data.get("parent_thermal"), scale=255.0)
        vec[:, 61] = _finite_ratio(sensor_data.get("parent_lidar"))
        vec[:, 62] = _tensor_norm(sensor_data.get("parent_imu_acc"), scale=9.81)
        vec[:, 63] = _tensor_norm(sensor_data.get("parent_imu_gyr"), scale=10.0)
        return vec

    # ------------------------------------------------------------------
    # Small obs (dim 32)
    # pose(6) + battery(1) + compute_load(1) + nearest_threat_rel(3) +
    # threat_conf(1) + nearest_parent_rel(3) + parent_lq(1) +
    # 8bin_histogram(8) + time_since_relay(1) + offload_queue(1) +
    # convoy_rel(3) + convoy_progress(1) + padding(3)
    # ------------------------------------------------------------------
    def _small_obs(
        self, agent_id, pos, sensor_data, comms, positions,
        convoy_pos, convoy_progress, compute_events, threats, ne,
    ) -> torch.Tensor:
        vec = torch.zeros(ne, 32)
        x, y, z = pos
        vec[:, 0] = x / 600.0
        vec[:, 1] = y / 200.0
        vec[:, 2] = z / 50.0
        # battery (1), compute_load (1) — placeholders
        vec[:, 6] = 0.9
        vec[:, 7] = 0.1
        nearest = _nearest_threat(pos, threats)
        if nearest is not None:
            dx, dy, dz, conf = nearest
            vec[:, 8] = dx / 300.0
            vec[:, 9] = dy / 300.0
            vec[:, 10] = dz / 50.0
            vec[:, 11] = conf
        # nearest parent relative (3) + link_quality (1)
        best_parent = "parent_0"
        pp = positions.get(best_parent, (0.0, 0.0, 0.0))
        vec[:, 12] = (pp[0] - x) / 300.0
        vec[:, 13] = (pp[1] - y) / 300.0
        vec[:, 14] = (pp[2] - z) / 50.0
        vec[:, 15] = comms.link_quality(agent_id, best_parent)
        # convoy relative (3) + progress (1)
        cx, cy, cz = convoy_pos
        vec[:, 24] = (cx - x) / 600.0
        vec[:, 25] = (cy - y) / 200.0
        vec[:, 26] = convoy_progress / 100.0
        vec[:, 27] = convoy_progress / 100.0
        vec[:, 28] = _tensor_mean(sensor_data.get("small_rgb"), scale=255.0)
        vec[:, 29] = _tensor_norm(sensor_data.get("small_imu_acc"), scale=9.81)
        vec[:, 30] = _tensor_norm(sensor_data.get("small_imu_gyr"), scale=10.0)
        vec[:, 31] = sum(1 for ev in compute_events if ev.actor_id == agent_id and ev.dropped)
        return vec

    def _threat_histogram(self, threats, convoy_pos, ne) -> torch.Tensor:
        """4×4 grid of threat counts in 400m×400m box ahead of convoy."""
        grid = torch.zeros(ne, 16)
        cx, cy, _ = convoy_pos
        for th in threats:
            dx = th.pose.x - cx
            dy = th.pose.y - cy
            col = int((dx + 200) / 100)
            row = int((dy + 200) / 100)
            if 0 <= col < 4 and 0 <= row < 4:
                grid[:, row * 4 + col] += 1.0 / max(1, len(threats))
        return grid


def _tensor_mean(value, *, scale: float = 1.0) -> float:
    if value is None or not hasattr(value, "float"):
        return 0.0
    tensor = value.float()
    if tensor.numel() == 0:
        return 0.0
    return float(torch.nan_to_num(tensor).mean().clamp(-scale, scale) / scale)


def _tensor_norm(value, *, scale: float = 1.0) -> float:
    if value is None or not hasattr(value, "float"):
        return 0.0
    tensor = value.float()
    if tensor.numel() == 0:
        return 0.0
    flat = torch.nan_to_num(tensor).reshape(-1)
    return float(torch.linalg.vector_norm(flat).clamp(0.0, scale) / scale)


def _finite_ratio(value) -> float:
    if value is None or not hasattr(value, "float"):
        return 0.0
    tensor = value.float()
    if tensor.numel() == 0:
        return 0.0
    return float(torch.isfinite(tensor).float().mean())


def _nearest_threat(pos, threats) -> tuple[float, float, float, float] | None:
    if not threats:
        return None
    x, y, z = pos
    threat = min(
        threats,
        key=lambda th: math.sqrt((th.pose.x - x) ** 2 + (th.pose.y - y) ** 2 + (th.pose.z - z) ** 2),
    )
    return threat.pose.x - x, threat.pose.y - y, threat.pose.z - z, float(threat.confidence)
