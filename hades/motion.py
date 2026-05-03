"""Deterministic smooth motion for the HADES convoy and drone swarm."""

from __future__ import annotations

import math
from dataclasses import dataclass

from hades import config
from hades.state import ConvoyState, DroneState, Pose, ThreatState


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def smoothstep(value: float) -> float:
    t = clamp01(value)
    return t * t * (3.0 - 2.0 * t)


def route_pose(route_id: str, progress_pct: float, z: float) -> Pose:
    """Sample a configured route by percentage of path length."""
    waypoints = config.ROUTE_WAYPOINTS.get(route_id, config.ROUTE_WAYPOINTS["main"])
    segments: list[tuple[float, float, float, float, float]] = []
    total = 0.0
    for (ax, ay), (bx, by) in zip(waypoints, waypoints[1:]):
        length = math.hypot(bx - ax, by - ay)
        segments.append((float(ax), float(ay), float(bx), float(by), length))
        total += length

    if not segments or total <= 0.0:
        x, y = waypoints[-1]
        return Pose(x=float(x), y=float(y), z=z)

    target = clamp01(progress_pct / 100.0) * total
    travelled = 0.0
    for ax, ay, bx, by, length in segments:
        if travelled + length >= target:
            ratio = 0.0 if length == 0.0 else (target - travelled) / length
            x = ax + (bx - ax) * ratio
            y = ay + (by - ay) * ratio
            yaw = math.atan2(by - ay, bx - ax)
            return Pose(x=x, y=y, z=z, yaw=yaw)
        travelled += length

    ax, ay, bx, by, _ = segments[-1]
    return Pose(x=bx, y=by, z=z, yaw=math.atan2(by - ay, bx - ax))


def blend_pose(a: Pose, b: Pose, alpha: float) -> Pose:
    """Blend pose position and shortest-path yaw for visual reroutes."""
    t = smoothstep(alpha)
    yaw_delta = math.atan2(math.sin(b.yaw - a.yaw), math.cos(b.yaw - a.yaw))
    return Pose(
        x=a.x + (b.x - a.x) * t,
        y=a.y + (b.y - a.y) * t,
        z=a.z + (b.z - a.z) * t,
        roll=a.roll + (b.roll - a.roll) * t,
        pitch=a.pitch + (b.pitch - a.pitch) * t,
        yaw=a.yaw + yaw_delta * t,
    )


@dataclass(frozen=True)
class _ScoutRole:
    ahead_m: float
    lateral_m: float
    altitude_m: float
    task: str


class DroneMotionModel:
    """Seeded, smooth drone trajectories for repeatable demo videos.

    The model is deliberately stateless: any frame can be sampled directly,
    tests remain deterministic, and the visual motion still reads as
    exploration rather than a rigid scripted formation.
    """

    _SCOUT_ROLES: tuple[_ScoutRole, ...] = (
        _ScoutRole(76.0, 44.0, 22.0, "lead_left_scout"),
        _ScoutRole(68.0, -40.0, 21.5, "lead_right_scout"),
        _ScoutRole(24.0, 80.0, 20.0, "left_flank_sweep"),
        _ScoutRole(12.0, -76.0, 19.5, "right_flank_sweep"),
        _ScoutRole(-42.0, 38.0, 18.5, "rear_left_check"),
        _ScoutRole(-56.0, -32.0, 18.0, "rear_right_check"),
    )

    def __init__(self, *, seed: int = 1701) -> None:
        self.seed = seed

    def drones_at(
        self,
        *,
        t: float,
        convoy: list[ConvoyState],
        active_route: str = "main",
        threats: list[ThreatState] | None = None,
    ) -> list[DroneState]:
        if not convoy:
            origin = Pose(x=0.0, y=0.0, z=0.0)
        else:
            origin = convoy[0].pose
        threats = threats or []

        drones: list[DroneState] = []
        for idx in range(config.COUNTS.parent_drones):
            pose = self._parent_pose(idx, t, origin, bool(threats))
            drones.append(
                DroneState(
                    id=f"parent_{idx}",
                    tier="PARENT",
                    pose=pose,
                    battery_pct=round(max(0.0, config.COMPUTE.parent_default_battery_pct - 0.002 * t), 2),
                    compute_load=round(0.18 + 0.035 * math.sin(0.62 * t + idx), 3),
                    current_task="wide_area_relay" if threats else "escort_overwatch",
                )
            )

        for idx in range(config.COUNTS.small_drones):
            pose, task = self._small_pose(idx, t, origin, active_route, threats)
            drones.append(
                DroneState(
                    id=f"small_{idx}",
                    tier="SMALL",
                    pose=pose,
                    battery_pct=round(max(0.0, config.COMPUTE.small_default_battery_pct - 0.004 * t), 2),
                    compute_load=round(0.055 + 0.025 * math.sin(0.73 * t + idx * 0.9), 3),
                    current_task=task,
                )
            )

        return drones

    def _parent_pose(self, idx: int, t: float, origin: Pose, threat_active: bool) -> Pose:
        sign = 1.0 if idx == 0 else -1.0
        base_ahead = 32.0 if idx == 0 else 8.0
        base_lateral = sign * (54.0 if not threat_active else 72.0)
        ahead = base_ahead + self._wave(idx, 0, t, 10.0, 18.0) + self._wave(idx, 1, t, 4.0, 7.0)
        lateral = base_lateral + self._wave(idx, 2, t, 11.0, 15.0)
        altitude = (
            config.SCENE.parent_hover_altitude_m
            + (3.0 if threat_active else 0.0)
            + self._wave(idx, 3, t, 1.2, 11.0)
        )
        pose = self._local_pose(origin, ahead, lateral, altitude)
        return self._with_attitude(pose, origin.yaw + 0.22 * sign * math.sin(t / 8.0 + idx), idx, t, scale=0.6)

    def _small_pose(
        self,
        idx: int,
        t: float,
        origin: Pose,
        active_route: str,
        threats: list[ThreatState],
    ) -> tuple[Pose, str]:
        role = self._SCOUT_ROLES[idx]
        ahead = role.ahead_m + self._wave(idx, 4, t, 13.0, 13.0) + self._wave(idx, 5, t, 5.0, 5.8)
        lateral = role.lateral_m + self._wave(idx, 6, t, 15.0, 16.0)
        altitude = role.altitude_m + self._wave(idx, 7, t, 1.0, 8.5)
        if threats and idx in (2, 3):
            ahead += 16.0
            lateral *= 1.18
            altitude += 1.5

        scout_pose = self._local_pose(origin, ahead, lateral, altitude)
        task = role.task

        if threats and idx in (0, 1):
            threat = threats[idx % len(threats)]
            blend = smoothstep((t - 15.0) / 5.0)
            orbit = (0.48 * t) + (math.pi if idx == 0 else 0.0) + self._phase(idx, 8)
            radius = 36.0 + 5.0 * math.sin(0.31 * t + idx)
            inspect_pose = Pose(
                x=threat.pose.x + radius * math.cos(orbit),
                y=threat.pose.y + radius * math.sin(orbit),
                z=config.SCENE.small_hover_altitude_m + 6.0 + 1.0 * math.sin(0.7 * t + idx),
                yaw=orbit + math.pi,
            )
            pose = blend_pose(scout_pose, inspect_pose, blend)
            task = f"investigate_{threat.id}"
        else:
            pose = scout_pose
            if threats and idx in (2, 3):
                task = f"reroute_corridor_{active_route}"

        heading = math.atan2(math.sin(pose.yaw), math.cos(pose.yaw))
        if abs(heading) < 1e-6:
            heading = origin.yaw + 0.35 * math.sin(t / 5.0 + idx)
        return self._with_attitude(pose, heading, idx, t, scale=1.0), task

    def _local_pose(self, origin: Pose, ahead: float, lateral: float, altitude: float) -> Pose:
        forward_x = math.cos(origin.yaw)
        forward_y = math.sin(origin.yaw)
        lateral_x = -math.sin(origin.yaw)
        lateral_y = math.cos(origin.yaw)
        return Pose(
            x=origin.x + ahead * forward_x + lateral * lateral_x,
            y=origin.y + ahead * forward_y + lateral * lateral_y,
            z=altitude,
            yaw=origin.yaw,
        )

    def _with_attitude(self, pose: Pose, yaw: float, idx: int, t: float, *, scale: float) -> Pose:
        roll = scale * 0.055 * math.sin(0.9 * t + self._phase(idx, 9))
        pitch = scale * 0.04 * math.sin(0.7 * t + self._phase(idx, 10))
        return Pose(x=pose.x, y=pose.y, z=pose.z, roll=roll, pitch=pitch, yaw=yaw)

    def _phase(self, idx: int, channel: int) -> float:
        return math.radians((self.seed + idx * 73 + channel * 191) % 360)

    def _wave(self, idx: int, channel: int, t: float, amplitude: float, period_s: float) -> float:
        return amplitude * math.sin((2.0 * math.pi * t / period_s) + self._phase(idx, channel))
