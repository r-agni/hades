"""Reusable synthetic and Isaac-facing simulation publishers.

This module avoids browser-demo choreography. Temporary visualization behavior
lives in `bridge.demo_publisher` so future tracks can build on this publisher
without inheriting scripted contacts, jamming, or presentation-only payloads.
"""

from __future__ import annotations

import math
import random
import time
import uuid
from dataclasses import dataclass

from hades import config
from hades.autonomy.comms import CommsModel
from hades.autonomy.offload_policy import (
    HeuristicOffloadPolicy,
    OffloadCtx,
    PeerInfo,
    Task,
)
from hades.autonomy.swarm_allocator import SwarmAllocator, ThreatDetected
from hades.state import (
    CommsLink,
    ConvoyState,
    DroneState,
    EdgeState,
    OffloadEvent,
    Pose,
    SimFrame,
    ThreatState,
)


ROUTE_POINTS: tuple[tuple[float, float], ...] = (
    (-210.0, -42.0),
    (-170.0, -54.0),
    (-125.0, -26.0),
    (-83.0, 16.0),
    (-31.0, 28.0),
    (18.0, 7.0),
    (56.0, -31.0),
    (112.0, -22.0),
    (162.0, 18.0),
    (208.0, 31.0),
)
EDGE_POSITIONS: tuple[tuple[float, float], ...] = (
    (-172.0, -71.0), (-142.0, -58.0), (-126.0, -82.0),
    (-86.0, 52.0), (-58.0, 67.0), (-35.0, 48.0),
    (10.0, -55.0), (35.0, -72.0), (62.0, -50.0),
    (92.0, 37.0), (123.0, 54.0), (148.0, 33.0),
    (177.0, -14.0), (198.0, 9.0), (-205.0, 13.0),
    (-12.0, 83.0), (73.0, 84.0), (211.0, 56.0),
)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RouteSample:
    pose: Pose
    progress_pct: float
    speed_mps: float


@dataclass(frozen=True)
class SyntheticWorldLayout:
    route_period_s: float = 120.0
    parent_hover_altitude_m: float = config.SCENE.parent_hover_altitude_m
    small_hover_altitude_m: float = config.SCENE.small_hover_altitude_m


class ParentBrain:
    """Parent-side compute routing and small-drone assignment state."""

    def __init__(self, parent_id: str, small_ids: list[str]) -> None:
        self.parent_id = parent_id
        self.policy = HeuristicOffloadPolicy()
        self.allocator = SwarmAllocator(small_ids)
        self._next_task_t: float = 3.0

    def tick(
        self,
        t: float,
        frame_drones: list[DroneState],
        frame_edges: list[EdgeState],
        links: list[CommsLink],
    ) -> list[OffloadEvent]:
        if t < self._next_task_t:
            return []
        self._next_task_t = t + 3.5

        ctx = self._build_ctx(frame_drones, frame_edges, links)
        task = Task(
            id=f"task_{uuid.uuid4().hex[:6]}",
            name="classify_target",
            compute_cost_gflops=200.0,
            latency_budget_ms=120.0,
        )
        _, event = self.policy.decide(task, ctx)
        expected = event.expected_latency_ms
        jitter = random.gauss(0, 0.08 * expected)
        actual = round(max(1.0, expected + jitter), 1)
        return [OffloadEvent(
            parent_id=event.parent_id,
            task_id=event.task_id,
            chosen_target=event.chosen_target,
            expected_latency_ms=expected,
            actual_latency_ms=actual,
            reason=event.reason,
        )]

    def inject_threat(self, x: float, y: float, confidence: float = 0.94) -> None:
        self.allocator.on_event(ThreatDetected(
            threat_id=f"threat_{uuid.uuid4().hex[:4]}",
            x=x,
            y=y,
            confidence=confidence,
        ))

    def current_task(self, small_id: str) -> str:
        return self.allocator.current_task(small_id)

    def _build_ctx(
        self,
        drones: list[DroneState],
        edges: list[EdgeState],
        links: list[CommsLink],
    ) -> OffloadCtx:
        own = next((d for d in drones if d.id == self.parent_id), None)
        if own is None:
            return OffloadCtx(
                own_id=self.parent_id,
                own_load=0.5,
                own_battery_pct=80.0,
                own_tops=config.COMPUTE.parent_tops,
            )

        wifi_link_map: dict[str, float] = {}
        for link in links:
            if link.type != "WIFI_MESH":
                continue
            if link.from_id == self.parent_id:
                wifi_link_map[link.to_id] = link.quality
            elif link.to_id == self.parent_id:
                wifi_link_map[link.from_id] = link.quality

        peers = [
            PeerInfo(
                id=d.id,
                link_quality=wifi_link_map[d.id],
                compute_load=d.compute_load,
                battery_pct=d.battery_pct,
            )
            for d in drones
            if d.tier == "PARENT" and d.id != self.parent_id and d.id in wifi_link_map
        ]
        edges_in_wifi = [edge for edge in edges if edge.id in wifi_link_map and edge.alive]

        return OffloadCtx(
            own_id=self.parent_id,
            own_load=own.compute_load,
            own_battery_pct=own.battery_pct,
            own_tops=config.COMPUTE.parent_tops,
            peers_in_wifi=peers,
            edges_in_wifi=edges_in_wifi,
            edge_link_qualities={edge.id: wifi_link_map[edge.id] for edge in edges_in_wifi},
        )


class SyntheticSimPublisher:
    """Produces reusable synthetic frames without visualization-only events."""

    def __init__(
        self,
        *,
        layout: SyntheticWorldLayout | None = None,
        environment: str = config.SCENE.environment_emergency,
    ) -> None:
        self.layout = layout or SyntheticWorldLayout()
        self.environment = environment
        self.started_at = time.monotonic()
        self._route_lengths = self._build_route_lengths()
        self._comms = CommsModel()
        all_smalls = [f"small_{i}" for i in range(config.COUNTS.small_drones)]
        mid = config.COUNTS.small_drones // 2
        self._brains = {
            "parent_0": ParentBrain("parent_0", all_smalls[:mid]),
            "parent_1": ParentBrain("parent_1", all_smalls[mid:]),
        }
        self._event_log: list[OffloadEvent] = []

    def inject_threat(self, x: float = 84.0, y: float = 66.0, confidence: float = 0.94) -> None:
        primary = self._brains.get("parent_0")
        if primary is not None:
            primary.inject_threat(x, y, confidence)

    def now_frame(self) -> SimFrame:
        return self.frame_at(time.monotonic() - self.started_at)

    def frame_at(self, t: float) -> SimFrame:
        lead = self._route_at(t)
        convoy = self._convoy(lead)
        drones = self._apply_roles(self._drones(lead.pose, t))
        edges = self._edges(t)
        links = self._comms.tick(drones, edges)

        new_events: list[OffloadEvent] = []
        for brain in self._brains.values():
            new_events.extend(brain.tick(t, drones, edges, links))
        self._event_log.extend(new_events)
        self._event_log = self._event_log[-24:]

        active_pairs = {(event.parent_id, event.chosen_target) for event in new_events}
        links = [
            CommsLink(
                from_id=link.from_id,
                to_id=link.to_id,
                type=link.type,
                quality=link.quality,
                active_payload=self._link_has_active_payload(link, active_pairs),
            )
            for link in links
        ]

        return SimFrame(
            t=round(t, 3),
            drones=drones,
            edges=edges,
            convoy=convoy,
            links=links,
            events=list(self._event_log),
            environment=self.environment,
        )

    def _build_route_lengths(self) -> tuple[float, ...]:
        lengths = [0.0]
        for idx in range(1, len(ROUTE_POINTS)):
            ax, ay = ROUTE_POINTS[idx - 1]
            bx, by = ROUTE_POINTS[idx]
            lengths.append(lengths[-1] + math.hypot(bx - ax, by - ay))
        return tuple(lengths)

    def _route_at(self, t: float, offset_m: float = 0.0) -> RouteSample:
        total = self._route_lengths[-1]
        speed = total / self.layout.route_period_s
        distance = (t * speed + offset_m) % total
        for idx in range(1, len(self._route_lengths)):
            if distance <= self._route_lengths[idx]:
                seg_start = self._route_lengths[idx - 1]
                seg_len = self._route_lengths[idx] - seg_start
                u = (distance - seg_start) / seg_len if seg_len else 0.0
                ax, ay = ROUTE_POINTS[idx - 1]
                bx, by = ROUTE_POINTS[idx]
                x = ax + (bx - ax) * u
                y = ay + (by - ay) * u
                return RouteSample(
                    pose=Pose(x=x, y=y, z=0.8, yaw=math.atan2(by - ay, bx - ax)),
                    progress_pct=100.0 * distance / total,
                    speed_mps=speed,
                )
        x, y = ROUTE_POINTS[-1]
        return RouteSample(pose=Pose(x=x, y=y, z=0.8), progress_pct=100.0, speed_mps=speed)

    def _convoy(self, lead: RouteSample) -> list[ConvoyState]:
        trail_t = lead.progress_pct / 100.0 * self.layout.route_period_s
        trail = self._route_at(trail_t, -18.0)
        return [
            ConvoyState("convoy_0", lead.pose, lead.speed_mps, lead.progress_pct),
            ConvoyState("convoy_1", trail.pose, trail.speed_mps, trail.progress_pct),
        ]

    def _drones(self, lead: Pose, t: float) -> list[DroneState]:
        drones: list[DroneState] = []
        forward = (math.cos(lead.yaw), math.sin(lead.yaw))
        right = (math.sin(lead.yaw), -math.cos(lead.yaw))
        hover = 0.8 * math.sin(t * 0.8)
        parent_specs = [
            ("parent_0", 45.0, -30.0, "forward_scout"),
            ("parent_1", -36.0, 34.0, "rear_overwatch"),
        ]
        for idx, (drone_id, along, lateral, task) in enumerate(parent_specs):
            x, y = self._offset_from(lead, forward, right, along, lateral)
            drones.append(DroneState(
                id=drone_id,
                tier="PARENT",
                pose=Pose(x=x, y=y, z=self.layout.parent_hover_altitude_m + hover, yaw=lead.yaw),
                battery_pct=round(config.COMPUTE.parent_default_battery_pct - 0.002 * t, 2),
                compute_load=round(0.55 + 0.16 * math.sin(t * 0.35 + idx), 3),
                current_task=task,
            ))

        role_offsets = [
            ("left_flank", 10.0, 45.0),
            ("right_flank", 12.0, -45.0),
            ("forward_scout", 66.0, 10.0),
            ("rear_guard", -54.0, -8.0),
            ("high_scan", 36.0, 31.0),
            ("reserve", -18.0, 31.0),
        ]
        for idx in range(config.COUNTS.small_drones):
            role, along, lateral = role_offsets[idx % len(role_offsets)]
            bob = 5.0 * math.sin(t / 4.0 + idx)
            weave = 7.0 * math.sin(t / 6.0 + idx * 0.7)
            x, y = self._offset_from(lead, forward, right, along + bob, lateral + weave)
            drones.append(DroneState(
                id=f"small_{idx}",
                tier="SMALL",
                pose=Pose(
                    x=x,
                    y=y,
                    z=self.layout.small_hover_altitude_m + 1.2 * math.sin(t * 0.9 + idx),
                    yaw=lead.yaw,
                ),
                battery_pct=round(config.COMPUTE.small_default_battery_pct - 0.004 * t, 2),
                compute_load=round(0.05 + 0.03 * math.sin(t * 0.7 + idx), 3),
                current_task=role,
            ))
        return drones

    def _apply_roles(self, drones: list[DroneState]) -> list[DroneState]:
        result: list[DroneState] = []
        for drone in drones:
            if drone.tier == "SMALL":
                task = next(
                    (
                        brain.current_task(drone.id)
                        for brain in self._brains.values()
                        if brain.current_task(drone.id) != "idle"
                    ),
                    drone.current_task,
                )
                if task != drone.current_task:
                    drone = DroneState(
                        id=drone.id,
                        tier=drone.tier,
                        pose=drone.pose,
                        battery_pct=drone.battery_pct,
                        compute_load=drone.compute_load,
                        current_task=task,
                    )
            result.append(drone)
        return result

    def _edges(self, t: float) -> list[EdgeState]:
        edges: list[EdgeState] = []
        for idx, (x, y) in enumerate(EDGE_POSITIONS[:config.COUNTS.edge_nodes]):
            edges.append(EdgeState(
                id=f"edge_{idx}",
                pose=Pose(x=x, y=y, z=1.2),
                battery_pct=round(config.COMPUTE.edge_default_battery_pct - 0.0005 * t, 2),
                compute_load=round(_clamp(0.18 + 0.12 * (0.5 + 0.5 * math.sin(t / 7.0 + idx)), 0.02, 0.98), 3),
                alive=True,
                compute_capacity_tops=config.COMPUTE.edge_tops,
                wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
                lora_radius_m=config.COMMS.lora_radius_m,
            ))
        return edges

    def _offset_from(
        self,
        pose: Pose,
        forward: tuple[float, float],
        right: tuple[float, float],
        along: float,
        lateral: float,
    ) -> tuple[float, float]:
        return (
            pose.x + forward[0] * along + right[0] * lateral,
            pose.y + forward[1] * along + right[1] * lateral,
        )

    def _link_has_active_payload(
        self,
        link: CommsLink,
        active_pairs: set[tuple[str, str]],
    ) -> bool:
        return (
            (link.from_id, link.to_id) in active_pairs
            or (link.to_id, link.from_id) in active_pairs
        )


class IsaacSimPublisher:
    """Placeholder adapter boundary for the future Isaac extension."""

    def now_frame(self) -> SimFrame:
        raise NotImplementedError("Isaac stage scraping is not implemented in Phase 1")
