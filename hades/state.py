"""Serializable state models shared by bridge and Isaac adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


DroneTier = Literal["PARENT", "SMALL"]
LinkType = Literal["LORA", "WIFI_MESH"]
OffloadReason = Literal["phase_1_placeholder", "min_cost", "no_wifi_in_range", "edge_overloaded"]
SpawnZone = Literal["choke_a", "flank_b"]


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


@dataclass(frozen=True)
class DroneState:
    id: str
    tier: DroneTier
    pose: Pose
    battery_pct: float
    compute_load: float
    current_task: str


@dataclass(frozen=True)
class EdgeState:
    id: str
    pose: Pose
    battery_pct: float
    compute_load: float
    alive: bool
    compute_capacity_tops: float
    wifi_radius_m: float
    lora_radius_m: float


@dataclass(frozen=True)
class ThreatState:
    id: str
    pose: Pose
    spawn_zone: str
    confidence: float
    detected_by: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ComputeEvent:
    tick: int
    actor_id: str
    task_name: str
    tops_required: float
    scheduled_on: str
    latency_ms: float
    dropped: bool


@dataclass(frozen=True)
class ConvoyState:
    id: str
    pose: Pose
    speed_mps: float
    route_progress_pct: float
    active_route_id: str = "main"
    threat_ahead: bool = False


@dataclass(frozen=True)
class CommsLink:
    from_id: str
    to_id: str
    type: LinkType
    quality: float
    active_payload: bool = False


@dataclass(frozen=True)
class OffloadEvent:
    parent_id: str
    task_id: str
    chosen_target: str
    expected_latency_ms: float
    actual_latency_ms: float
    reason: OffloadReason


@dataclass(frozen=True)
class SimFrame:
    t: float
    drones: list[DroneState] = field(default_factory=list)
    edges: list[EdgeState] = field(default_factory=list)
    convoy: list[ConvoyState] = field(default_factory=list)
    links: list[CommsLink] = field(default_factory=list)
    events: list[OffloadEvent] = field(default_factory=list)
    environment: str = "nvidia_jetracer_track_real_assets"
    threats: list[ThreatState] = field(default_factory=list)
    compute_events: list[ComputeEvent] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Phase 1 protocol shape — preserves backward compat with existing tests."""
        return {
            "t": self.t,
            "drones": [asdict(d) for d in self.drones],
            "edges": [asdict(e) for e in self.edges],
            "convoy": [asdict(c) for c in self.convoy],
            "links": [asdict(lk) for lk in self.links],
            "events": [asdict(ev) for ev in self.events],
            "environment": self.environment,
        }

    def to_full_dict(self) -> dict[str, Any]:
        """Full Track 2 payload including threats and compute_events."""
        return asdict(self)
