"""Distance-gated communications link model.

Recomputes LoRa + Wi-Fi mesh reachability for every (actor, actor) pair each
tick. Output is a list of CommsLink values published inside SimFrame.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from hades import config
from hades.state import CommsLink, DroneState, EdgeState, Pose


def _dist(a: Pose, b: Pose) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


@dataclass
class JamRegion:
    """Axis-aligned bounding box that kills all comms inside it."""
    x_min: float
    x_max: float
    y_min: float
    y_max: float

    def contains(self, pose: Pose) -> bool:
        return self.x_min <= pose.x <= self.x_max and self.y_min <= pose.y <= self.y_max


class CommsModel:
    """Distance-gated LoRa + Wi-Fi mesh link model.

    Call tick() each simulation step to get a fresh CommsLink list.
    Call jam() / clear_jam() to simulate RF jamming for demo scenarios.
    """

    def __init__(self) -> None:
        self._jam_regions: list[JamRegion] = []
        self._active_payloads: set[tuple[str, str]] = set()

    def jam(self, region: JamRegion) -> None:
        self._jam_regions.append(region)

    def clear_jam(self) -> None:
        self._jam_regions.clear()

    def mark_payload_active(self, from_id: str, to_id: str) -> None:
        self._active_payloads.add((from_id, to_id))

    def clear_payload(self, from_id: str, to_id: str) -> None:
        self._active_payloads.discard((from_id, to_id))

    def tick(self, drones: list[DroneState], edges: list[EdgeState]) -> list[CommsLink]:
        links: list[CommsLink] = []
        parents = [d for d in drones if d.tier == "PARENT"]
        smalls  = [d for d in drones if d.tier == "SMALL"]
        alive_edges = [e for e in edges if e.alive]

        # Small to nearest parent over LoRa control plane.
        if not parents:
            return links

        for small in smalls:
            if self._jammed(small.pose):
                continue
            parent = min(parents, key=lambda p: _dist(p.pose, small.pose))
            if self._jammed(parent.pose):
                continue
            dist = _dist(parent.pose, small.pose)
            if dist <= config.COMMS.lora_radius_m:
                quality = _clamp01(1.0 - dist / config.COMMS.lora_radius_m)
                links.append(CommsLink(
                    from_id=small.id, to_id=parent.id,
                    type="LORA", quality=round(quality, 3), active_payload=False,
                ))

        # Parent peer compute channel over Wi-Fi mesh.
        for i, p1 in enumerate(parents):
            for p2 in parents[i + 1:]:
                if self._jammed(p1.pose) or self._jammed(p2.pose):
                    continue
                dist = _dist(p1.pose, p2.pose)
                if dist <= config.COMMS.wifi_mesh_radius_m:
                    quality = _clamp01(1.0 - dist / config.COMMS.wifi_mesh_radius_m)
                    active = (p1.id, p2.id) in self._active_payloads or \
                             (p2.id, p1.id) in self._active_payloads
                    links.append(CommsLink(
                        from_id=p1.id, to_id=p2.id,
                        type="WIFI_MESH", quality=round(quality, 3), active_payload=active,
                    ))

        # Parent to edge compute offload channel over Wi-Fi mesh.
        for parent in parents:
            if self._jammed(parent.pose):
                continue
            for edge in alive_edges:
                if self._jammed(edge.pose):
                    continue
                dist = _dist(parent.pose, edge.pose)
                if dist <= config.COMMS.wifi_mesh_radius_m:
                    quality = _clamp01(1.0 - dist / config.COMMS.wifi_mesh_radius_m)
                    active = (
                        (parent.id, edge.id) in self._active_payloads
                        or (edge.id, parent.id) in self._active_payloads
                    )
                    links.append(CommsLink(
                        from_id=parent.id, to_id=edge.id,
                        type="WIFI_MESH", quality=round(quality, 3), active_payload=active,
                    ))

        return links

    def _jammed(self, pose: Pose) -> bool:
        return any(r.contains(pose) for r in self._jam_regions)
