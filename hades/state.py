"""Serializable state models shared by bridge and Isaac adapters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


DroneTier = Literal["PARENT", "SMALL"]
LinkType = Literal["LORA", "WIFI_MESH"]
OffloadReason = Literal["phase_1_placeholder", "min_cost", "no_wifi_in_range", "edge_overloaded"]


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
class ConvoyState:
    id: str
    pose: Pose
    speed_mps: float
    route_progress_pct: float


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
    environment: str = "generated_flat_road"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
