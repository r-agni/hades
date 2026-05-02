"""Parent-side small drone swarm allocator.

Maintains {small_id -> role} and produces SmallCommands on events.
v1 is rule-based; same interface for a learned policy in Track 5.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Role(str, Enum):
    ESCORT_QUADRANT_0 = "escort_quadrant_0"
    ESCORT_QUADRANT_1 = "escort_quadrant_1"
    ESCORT_QUADRANT_2 = "escort_quadrant_2"
    ESCORT_QUADRANT_3 = "escort_quadrant_3"
    ESCORT_QUADRANT_4 = "escort_quadrant_4"
    ESCORT_QUADRANT_5 = "escort_quadrant_5"
    INVESTIGATE_THREAT = "investigate_threat"
    RECOVER = "recover"
    IDLE = "idle"

    @staticmethod
    def escort(idx: int) -> "Role":
        return Role(f"escort_quadrant_{idx % 6}")

    @property
    def is_escort(self) -> bool:
        return self.value.startswith("escort_quadrant_")


@dataclass
class ThreatDetected:
    threat_id: str
    x: float
    y: float
    confidence: float = 0.94


@dataclass
class DroneDown:
    small_id: str
    reason: Literal["low_battery", "comms_lost", "crash"] = "low_battery"


@dataclass
class SensorAnomaly:
    small_id: str
    sensor: str


SwarmEvent = ThreatDetected | DroneDown | SensorAnomaly


@dataclass
class SmallCommand:
    small_id: str
    new_role: Role
    target_x: float | None = None
    target_y: float | None = None


class SwarmAllocator:
    """Manages role assignments for all smalls supervised by one parent drone."""

    def __init__(self, small_ids: list[str]) -> None:
        self._assignments: dict[str, Role] = {
            sid: Role.escort(i) for i, sid in enumerate(small_ids)
        }
        self._active_threats: dict[str, tuple[float, float]] = {}

    @property
    def assignments(self) -> dict[str, Role]:
        return dict(self._assignments)

    def current_task(self, small_id: str) -> str:
        return self._assignments.get(small_id, Role.IDLE).value

    def on_event(self, event: SwarmEvent) -> list[SmallCommand]:
        if isinstance(event, ThreatDetected):
            return self._handle_threat(event)
        if isinstance(event, DroneDown):
            return self._handle_drone_down(event)
        if isinstance(event, SensorAnomaly):
            return self._handle_anomaly(event)
        return []

    def resolve_threat(self, threat_id: str) -> list[SmallCommand]:
        self._active_threats.pop(threat_id, None)
        cmds: list[SmallCommand] = []
        for i, sid in enumerate(s for s, r in self._assignments.items()
                                 if r == Role.INVESTIGATE_THREAT):
            role = Role.escort(i)
            self._assignments[sid] = role
            cmds.append(SmallCommand(small_id=sid, new_role=role))
        return cmds

    def _handle_threat(self, event: ThreatDetected) -> list[SmallCommand]:
        self._active_threats[event.threat_id] = (event.x, event.y)
        cmds: list[SmallCommand] = []
        available = [s for s, r in self._assignments.items() if r.is_escort]
        for sid in available[:2]:
            self._assignments[sid] = Role.INVESTIGATE_THREAT
            cmds.append(SmallCommand(
                small_id=sid, new_role=Role.INVESTIGATE_THREAT,
                target_x=event.x, target_y=event.y,
            ))
        remaining = [s for s, r in self._assignments.items() if r.is_escort]
        for i, sid in enumerate(remaining):
            role = Role.escort(i)
            self._assignments[sid] = role
            cmds.append(SmallCommand(small_id=sid, new_role=role))
        return cmds

    def _handle_drone_down(self, event: DroneDown) -> list[SmallCommand]:
        cmds: list[SmallCommand] = []
        sid = event.small_id
        if sid not in self._assignments:
            return cmds
        self._assignments[sid] = Role.RECOVER
        cmds.append(SmallCommand(small_id=sid, new_role=Role.RECOVER))
        active = [s for s, r in self._assignments.items() if r.is_escort]
        for i, s in enumerate(active):
            role = Role.escort(i)
            self._assignments[s] = role
            cmds.append(SmallCommand(small_id=s, new_role=role))
        return cmds

    def _handle_anomaly(self, event: SensorAnomaly) -> list[SmallCommand]:
        self._assignments[event.small_id] = Role.IDLE
        return [SmallCommand(small_id=event.small_id, new_role=Role.IDLE)]
