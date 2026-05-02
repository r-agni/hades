"""Temporary demo publisher for the browser visualizer.

This module intentionally owns the scripted route, threat, jamming, and visual
drama used by `/viz`. Future tracks should import `SyntheticSimPublisher` from
`bridge.sim_publisher` for reusable simulation behavior.
"""

from __future__ import annotations

import math
import random
import time
import uuid
from dataclasses import dataclass
from typing import Literal

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


ScenarioPhase = Literal[
    "normal_escort",
    "edge_offload_burst",
    "weak_link_zone",
    "threat_contact",
    "rf_jamming",
    "recovery",
]

_SCENARIO_PERIOD_S = 120.0
_ROUTE_POINTS: tuple[tuple[float, float], ...] = (
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
_THREAT_POSE = Pose(x=84.0, y=66.0, z=0.0)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class RouteSample:
    pose: Pose
    progress_pct: float
    speed_mps: float


@dataclass(frozen=True)
class ScenarioState:
    phase: ScenarioPhase
    phase_t: float
    alerts: tuple[str, ...] = ()
    threat_active: bool = False
    jamming_active: bool = False
    link_degraded: bool = False
    forced_payload: bool = False


@dataclass(frozen=True)
class SyntheticWorldLayout:
    route_period_s: float = _SCENARIO_PERIOD_S
    parent_hover_altitude_m: float = config.SCENE.parent_hover_altitude_m
    small_hover_altitude_m: float = config.SCENE.small_hover_altitude_m


class ParentBrain:
    """Per-parent wrapper that holds the offload policy and swarm allocator."""

    def __init__(self, parent_id: str, small_ids: list[str]) -> None:
        self.parent_id = parent_id
        self.policy = HeuristicOffloadPolicy()
        self.allocator = SwarmAllocator(small_ids)
        self._next_task_t: float = 3.0
        self._task_interval: float = 3.5
        self._threat_active = False

    def tick(
        self,
        t: float,
        frame_drones: list[DroneState],
        frame_edges: list[EdgeState],
        links: list[CommsLink],
        scenario: ScenarioState,
    ) -> list[OffloadEvent]:
        """Called once per frame. Returns any new OffloadEvents produced."""

        if scenario.phase == "edge_offload_burst":
            task_interval = 1.7
        elif scenario.phase in {"weak_link_zone", "rf_jamming"}:
            task_interval = 2.4
        else:
            task_interval = 3.5

        events: list[OffloadEvent] = []
        if t < self._next_task_t:
            return events

        self._next_task_t = t + task_interval
        ctx = self._build_ctx(frame_drones, frame_edges, links)
        task = Task(
            id=f"task_{uuid.uuid4().hex[:6]}",
            name="classify_target",
            compute_cost_gflops=260.0 if scenario.phase == "edge_offload_burst" else 200.0,
            latency_budget_ms=105.0 if scenario.phase in {"weak_link_zone", "rf_jamming"} else 120.0,
        )
        _, event = self.policy.decide(task, ctx)
        expected = event.expected_latency_ms
        jitter = random.gauss(0, 0.08 * expected)
        spike = random.choices([1.0, random.uniform(1.5, 3.0)], weights=[19, 1])[0]
        if scenario.phase == "rf_jamming":
            spike *= 1.35
        actual = round(max(1.0, (expected + jitter) * spike), 1)

        events.append(OffloadEvent(
            parent_id=event.parent_id,
            task_id=event.task_id,
            chosen_target=event.chosen_target,
            expected_latency_ms=expected,
            actual_latency_ms=actual,
            reason=event.reason,
        ))
        return events

    def current_task(self, small_id: str) -> str:
        return self.allocator.current_task(small_id)

    def sync_threat(self, active: bool) -> None:
        if active and not self._threat_active:
            self._threat_active = True
            self.allocator.on_event(ThreatDetected(
                threat_id="scripted_contact",
                x=_THREAT_POSE.x,
                y=_THREAT_POSE.y,
                confidence=0.91,
            ))
        elif not active and self._threat_active:
            self._threat_active = False
            self.allocator.resolve_threat("scripted_contact")

    def inject_threat(self, x: float, y: float, confidence: float = 0.94) -> None:
        self._threat_active = True
        self.allocator.on_event(ThreatDetected(
            threat_id=f"threat_{uuid.uuid4().hex[:4]}",
            x=x,
            y=y,
            confidence=confidence,
        ))

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


class DemoSimPublisher:
    """Produces deterministic moving frames with scripted autonomy demo beats."""

    def __init__(
        self,
        *,
        layout: SyntheticWorldLayout | None = None,
        environment: str = config.SCENE.environment_emergency,
    ) -> None:
        self.layout = layout or SyntheticWorldLayout()
        self.environment = environment
        self.started_at = time.monotonic()
        self._comms = CommsModel()
        self._route_lengths = self._build_route_lengths()

        all_smalls = [f"small_{i}" for i in range(config.COUNTS.small_drones)]
        mid = config.COUNTS.small_drones // 2
        self._brains: dict[str, ParentBrain] = {
            "parent_0": ParentBrain("parent_0", all_smalls[:mid]),
            "parent_1": ParentBrain("parent_1", all_smalls[mid:]),
        }
        self._event_log: list[OffloadEvent] = []

    def inject_threat(
        self,
        x: float = _THREAT_POSE.x,
        y: float = _THREAT_POSE.y,
        confidence: float = 0.94,
    ) -> None:
        primary = self._brains.get("parent_0")
        if primary is not None:
            primary.inject_threat(x, y, confidence)

    def now_frame(self) -> SimFrame:
        return self.frame_at(time.monotonic() - self.started_at)

    def frame_at(self, t: float) -> SimFrame:
        scenario = self._scenario_at(t)
        lead = self._route_at(t)
        convoy = self._convoy(lead)
        edges = self._edges(t, scenario)
        drones = self._drones(lead.pose, t, scenario)

        for parent_id, brain in self._brains.items():
            brain.sync_threat(scenario.threat_active and parent_id == "parent_0")
        drones = self._apply_roles(drones, scenario)

        links = self._comms.tick(drones, edges)
        links = self._degrade_links(links, drones, edges, scenario)

        new_events: list[OffloadEvent] = []
        for brain in self._brains.values():
            new_events.extend(brain.tick(t, drones, edges, links, scenario))
        if scenario.forced_payload and not new_events:
            new_events.extend(self._scripted_payload_events(t, drones, edges))

        self._event_log.extend(new_events)
        self._event_log = self._event_log[-24:]

        active_pairs = {(event.parent_id, event.chosen_target) for event in new_events}
        if scenario.forced_payload:
            active_pairs.update(self._scripted_active_pairs(drones, edges))
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
            scenario_phase=scenario.phase,
            alerts=list(scenario.alerts),
            threats=self._threats(scenario),
            environment=self.environment,
        )

    def _scenario_at(self, t: float) -> ScenarioState:
        phase_t = t % _SCENARIO_PERIOD_S
        if phase_t < 18.0:
            return ScenarioState("normal_escort", phase_t)
        if phase_t < 36.0:
            return ScenarioState(
                "edge_offload_burst",
                phase_t,
                alerts=("EDGE OFFLOAD BURST",),
                forced_payload=True,
            )
        if phase_t < 54.0:
            return ScenarioState(
                "weak_link_zone",
                phase_t,
                alerts=("LINK DEGRADED", "DEAD ZONE AHEAD"),
                link_degraded=True,
            )
        if phase_t < 80.0:
            return ScenarioState(
                "threat_contact",
                phase_t,
                alerts=("CONTACT", "SMALL TEAM INVESTIGATING"),
                threat_active=True,
                forced_payload=True,
            )
        if phase_t < 94.0:
            return ScenarioState(
                "rf_jamming",
                phase_t,
                alerts=("JAMMING", "LINK DEGRADED"),
                threat_active=True,
                jamming_active=True,
                link_degraded=True,
            )
        if phase_t < 110.0:
            return ScenarioState(
                "recovery",
                phase_t,
                alerts=("RECOVERY", "SWARM REFORMING"),
                forced_payload=True,
            )
        return ScenarioState("normal_escort", phase_t, alerts=("ROUTE CLEAR",))

    def _build_route_lengths(self) -> tuple[float, ...]:
        lengths = [0.0]
        for idx in range(1, len(_ROUTE_POINTS)):
            ax, ay = _ROUTE_POINTS[idx - 1]
            bx, by = _ROUTE_POINTS[idx]
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
                ax, ay = _ROUTE_POINTS[idx - 1]
                bx, by = _ROUTE_POINTS[idx]
                x = ax + (bx - ax) * u
                y = ay + (by - ay) * u
                yaw = math.atan2(by - ay, bx - ax)
                return RouteSample(
                    pose=Pose(x=x, y=y, z=0.8, yaw=yaw),
                    progress_pct=100.0 * distance / total,
                    speed_mps=speed,
                )

        x, y = _ROUTE_POINTS[-1]
        return RouteSample(
            pose=Pose(x=x, y=y, z=0.8, yaw=0.0),
            progress_pct=100.0,
            speed_mps=speed,
        )

    def _convoy(self, lead: RouteSample) -> list[ConvoyState]:
        trail = self._route_at(lead.progress_pct / 100.0 * self.layout.route_period_s, -18.0)
        return [
            ConvoyState(
                id="convoy_0",
                pose=lead.pose,
                speed_mps=lead.speed_mps,
                route_progress_pct=lead.progress_pct,
            ),
            ConvoyState(
                id="convoy_1",
                pose=Pose(
                    x=trail.pose.x,
                    y=trail.pose.y,
                    z=trail.pose.z,
                    yaw=trail.pose.yaw,
                ),
                speed_mps=trail.speed_mps,
                route_progress_pct=trail.progress_pct,
            ),
        ]

    def _drones(self, lead: Pose, t: float, scenario: ScenarioState) -> list[DroneState]:
        drones: list[DroneState] = []
        forward = (math.cos(lead.yaw), math.sin(lead.yaw))
        right = (math.sin(lead.yaw), -math.cos(lead.yaw))
        hover = 0.8 * math.sin(t * 0.8)
        swap = 0.5 + 0.5 * math.sin(t / 18.0)
        parent_specs = [
            ("parent_0", 54.0 - 18.0 * swap, -30.0, "forward_scout"),
            ("parent_1", -45.0 + 15.0 * swap, 34.0, "rear_overwatch"),
        ]
        for idx, (drone_id, along, lateral, task) in enumerate(parent_specs):
            x, y = self._offset_from(lead, forward, right, along, lateral)
            drones.append(DroneState(
                id=drone_id,
                tier="PARENT",
                pose=Pose(
                    x=x,
                    y=y,
                    z=self.layout.parent_hover_altitude_m + hover,
                    yaw=lead.yaw + 0.05 * math.sin(t / 5.0 + idx),
                ),
                battery_pct=round(config.COMPUTE.parent_default_battery_pct - 0.002 * t, 2),
                compute_load=round(0.65 + 0.2 * math.sin(t * 0.35 + idx), 3),
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
            z = self.layout.small_hover_altitude_m + 1.2 * math.sin(t * 0.9 + idx)
            drones.append(DroneState(
                id=f"small_{idx}",
                tier="SMALL",
                pose=Pose(x=x, y=y, z=z, yaw=lead.yaw + 0.2 * math.sin(t / 5.0 + idx)),
                battery_pct=round(config.COMPUTE.small_default_battery_pct - 0.004 * t, 2),
                compute_load=round(0.05 + 0.03 * math.sin(t * 0.7 + idx), 3),
                current_task=role,
            ))
        return drones

    def _apply_roles(
        self,
        drones: list[DroneState],
        scenario: ScenarioState,
    ) -> list[DroneState]:
        result: list[DroneState] = []
        for drone in drones:
            if drone.tier != "SMALL":
                result.append(drone)
                continue

            task = None
            for brain in self._brains.values():
                current = brain.current_task(drone.id)
                if current and current != "idle":
                    task = current
                    break

            if task == "investigate_threat" and scenario.threat_active:
                phase_u = _clamp((scenario.phase_t - 54.0) / 14.0, 0.0, 1.0)
                orbit = 10.0 + 6.0 * math.sin(scenario.phase_t * 0.7 + int(drone.id[-1]))
                target_x = _THREAT_POSE.x + math.cos(scenario.phase_t + int(drone.id[-1])) * orbit
                target_y = _THREAT_POSE.y + math.sin(scenario.phase_t + int(drone.id[-1])) * orbit
                x = drone.pose.x + (target_x - drone.pose.x) * phase_u
                y = drone.pose.y + (target_y - drone.pose.y) * phase_u
                drone = DroneState(
                    id=drone.id,
                    tier=drone.tier,
                    pose=Pose(x=x, y=y, z=drone.pose.z + 3.0, yaw=math.atan2(target_y - y, target_x - x)),
                    battery_pct=drone.battery_pct,
                    compute_load=drone.compute_load,
                    current_task=task,
                )
            elif task and task != drone.current_task:
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

    def _edges(self, t: float, scenario: ScenarioState) -> list[EdgeState]:
        clusters = [
            (-172.0, -71.0), (-142.0, -58.0), (-126.0, -82.0),
            (-86.0, 52.0), (-58.0, 67.0), (-35.0, 48.0),
            (10.0, -55.0), (35.0, -72.0), (62.0, -50.0),
            (92.0, 37.0), (123.0, 54.0), (148.0, 33.0),
            (177.0, -14.0), (198.0, 9.0), (-205.0, 13.0),
            (-12.0, 83.0), (73.0, 84.0), (211.0, 56.0),
        ]
        edges: list[EdgeState] = []
        for idx, (x, y) in enumerate(clusters[:config.COUNTS.edge_nodes]):
            alive = idx != 7
            if scenario.phase == "rf_jamming" and idx in {8, 9}:
                alive = False
            base_load = 0.18 + 0.12 * (0.5 + 0.5 * math.sin(t / 7.0 + idx))
            if scenario.phase == "edge_offload_burst" and idx in {8, 9, 10, 11}:
                base_load += 0.42 + 0.1 * math.sin(t + idx)
            if scenario.phase == "rf_jamming" and idx in {10, 11}:
                base_load += 0.35

            edges.append(EdgeState(
                id=f"edge_{idx}",
                pose=Pose(x=x, y=y, z=1.2),
                battery_pct=round(config.COMPUTE.edge_default_battery_pct - 0.0007 * t, 2),
                compute_load=round(_clamp(base_load, 0.02, 0.98), 3),
                alive=alive,
                compute_capacity_tops=config.COMPUTE.edge_tops,
                wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
                lora_radius_m=config.COMMS.lora_radius_m,
            ))
        return edges

    def _degrade_links(
        self,
        links: list[CommsLink],
        drones: list[DroneState],
        edges: list[EdgeState],
        scenario: ScenarioState,
    ) -> list[CommsLink]:
        if not scenario.link_degraded and not scenario.jamming_active:
            return links

        actors = {actor.id: actor.pose for actor in [*drones, *edges]}
        degraded: list[CommsLink] = []
        for link in links:
            pose_a = actors.get(link.from_id)
            pose_b = actors.get(link.to_id)
            if pose_a is None or pose_b is None:
                continue
            mx = (pose_a.x + pose_b.x) / 2.0
            my = (pose_a.y + pose_b.y) / 2.0
            in_dead_zone = -20.0 <= mx <= 95.0 and -72.0 <= my <= 20.0
            in_jam_zone = 55.0 <= mx <= 125.0 and 18.0 <= my <= 88.0
            quality = link.quality
            if scenario.link_degraded and in_dead_zone:
                quality *= 0.42
            if scenario.jamming_active and in_jam_zone:
                quality *= 0.20
            if quality < 0.045:
                continue
            degraded.append(CommsLink(
                from_id=link.from_id,
                to_id=link.to_id,
                type=link.type,
                quality=round(_clamp(quality, 0.0, 1.0), 3),
                active_payload=link.active_payload,
            ))
        return degraded

    def _scripted_payload_events(
        self,
        t: float,
        drones: list[DroneState],
        edges: list[EdgeState],
    ) -> list[OffloadEvent]:
        pairs = self._scripted_active_pairs(drones, edges)
        events: list[OffloadEvent] = []
        for idx, (parent_id, target_id) in enumerate(sorted(pairs)):
            events.append(OffloadEvent(
                parent_id=parent_id,
                task_id=f"script_{int(t * 10):04d}_{idx}",
                chosen_target=target_id,
                expected_latency_ms=42.0 + idx * 8.0,
                actual_latency_ms=round(45.0 + idx * 9.0 + 5.0 * math.sin(t), 1),
                reason="min_cost",
            ))
        return events[:2]

    def _scripted_active_pairs(
        self,
        drones: list[DroneState],
        edges: list[EdgeState],
    ) -> set[tuple[str, str]]:
        parents = [drone for drone in drones if drone.tier == "PARENT"]
        alive_edges = [edge for edge in edges if edge.alive]
        pairs: set[tuple[str, str]] = set()
        for parent in parents:
            candidates = sorted(
                alive_edges,
                key=lambda edge: math.hypot(edge.pose.x - parent.pose.x, edge.pose.y - parent.pose.y),
            )
            if candidates:
                pairs.add((parent.id, candidates[0].id))
        return pairs

    def _link_has_active_payload(
        self,
        link: CommsLink,
        active_pairs: set[tuple[str, str]],
    ) -> bool:
        return (
            (link.from_id, link.to_id) in active_pairs
            or (link.to_id, link.from_id) in active_pairs
        )

    def _threats(self, scenario: ScenarioState) -> list[ThreatState]:
        if not scenario.threat_active:
            return []
        return [
            ThreatState(
                id="scripted_contact",
                pose=_THREAT_POSE,
                confidence=0.91,
                active=True,
            )
        ]

