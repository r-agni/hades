"""Synthetic and Isaac-facing simulation publishers.

The synthetic publisher is intentionally useful on day one: it emits the
same shape of data the Isaac adapter will later publish, so Tracks 2 and 3
can be developed before the final visual environment is locked.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

from hades import config
from hades.state import CommsLink, ConvoyState, DroneState, EdgeState, Pose, SimFrame


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _distance(a: Pose, b: Pose) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


@dataclass(frozen=True)
class SyntheticWorldLayout:
    route_start_x: float = -190.0
    route_end_x: float = 190.0
    edge_y_offset_m: float = 42.0
    small_ring_radius_m: float = 24.0
    parent_y_offset_m: float = 32.0


class SyntheticSimPublisher:
    """Produces deterministic moving frames for Phase 1 verification."""

    def __init__(
        self,
        *,
        layout: SyntheticWorldLayout | None = None,
        environment: str = config.SCENE.environment_emergency,
    ) -> None:
        self.layout = layout or SyntheticWorldLayout()
        self.environment = environment
        self.started_at = time.monotonic()

    def now_frame(self) -> SimFrame:
        return self.frame_at(time.monotonic() - self.started_at)

    def frame_at(self, t: float) -> SimFrame:
        convoy_x = self._convoy_x(t)
        convoy = self._convoy(convoy_x, t)
        drones = self._drones(convoy_x, t)
        edges = self._edges(t)
        links = self._links(drones, edges)
        return SimFrame(
            t=round(t, 3),
            drones=drones,
            edges=edges,
            convoy=convoy,
            links=links,
            events=[],
            environment=self.environment,
        )

    def _convoy_x(self, t: float) -> float:
        route = self.layout.route_end_x - self.layout.route_start_x
        # Slow loop for demos: one full route pass every 160 seconds.
        progress = (t % 160.0) / 160.0
        return self.layout.route_start_x + route * progress

    def _route_progress_pct(self, x: float) -> float:
        route = self.layout.route_end_x - self.layout.route_start_x
        return 100.0 * (x - self.layout.route_start_x) / route

    def _convoy(self, convoy_x: float, t: float) -> list[ConvoyState]:
        speed_mps = (self.layout.route_end_x - self.layout.route_start_x) / 160.0
        progress = self._route_progress_pct(convoy_x)
        return [
            ConvoyState(
                id="convoy_0",
                pose=Pose(x=convoy_x, y=-3.0, z=0.8, yaw=0.0),
                speed_mps=speed_mps,
                route_progress_pct=progress,
            ),
            ConvoyState(
                id="convoy_1",
                pose=Pose(x=convoy_x - 14.0, y=3.0, z=0.8, yaw=0.0),
                speed_mps=speed_mps,
                route_progress_pct=max(0.0, progress - 3.5),
            ),
        ]

    def _drones(self, convoy_x: float, t: float) -> list[DroneState]:
        drones: list[DroneState] = []
        hover = 0.8 * math.sin(t * 0.8)
        parent_offsets = [(-18.0, self.layout.parent_y_offset_m), (18.0, -self.layout.parent_y_offset_m)]
        for idx, (dx, dy) in enumerate(parent_offsets):
            drones.append(
                DroneState(
                    id=f"parent_{idx}",
                    tier="PARENT",
                    pose=Pose(
                        x=convoy_x + dx,
                        y=dy,
                        z=config.SCENE.parent_hover_altitude_m + hover,
                        yaw=0.0,
                    ),
                    battery_pct=round(config.COMPUTE.parent_default_battery_pct - 0.002 * t, 2),
                    compute_load=round(0.18 + 0.04 * math.sin(t + idx), 3),
                    current_task="escort_overwatch",
                )
            )

        for idx in range(config.COUNTS.small_drones):
            angle = (2.0 * math.pi * idx / config.COUNTS.small_drones) + 0.15 * math.sin(t / 5.0)
            drones.append(
                DroneState(
                    id=f"small_{idx}",
                    tier="SMALL",
                    pose=Pose(
                        x=convoy_x + self.layout.small_ring_radius_m * math.cos(angle),
                        y=self.layout.small_ring_radius_m * math.sin(angle),
                        z=config.SCENE.small_hover_altitude_m + 0.5 * math.sin(t + idx),
                        yaw=angle,
                    ),
                    battery_pct=round(config.COMPUTE.small_default_battery_pct - 0.004 * t, 2),
                    compute_load=round(0.05 + 0.02 * math.sin(t * 0.7 + idx), 3),
                    current_task=f"escort_quadrant_{idx}",
                )
            )
        return drones

    def _edges(self, t: float) -> list[EdgeState]:
        edges: list[EdgeState] = []
        count = config.COUNTS.edge_nodes
        if count <= 1:
            xs = [0.0]
        else:
            step = (self.layout.route_end_x - self.layout.route_start_x) / (count - 1)
            xs = [self.layout.route_start_x + i * step for i in range(count)]

        for idx, x in enumerate(xs):
            side = -1.0 if idx % 2 else 1.0
            edges.append(
                EdgeState(
                    id=f"edge_{idx}",
                    pose=Pose(x=x, y=side * self.layout.edge_y_offset_m, z=1.2),
                    battery_pct=round(config.COMPUTE.edge_default_battery_pct - 0.0005 * t, 2),
                    compute_load=round(0.12 + 0.08 * (0.5 + 0.5 * math.sin(t / 8.0 + idx)), 3),
                    alive=True,
                    compute_capacity_tops=config.COMPUTE.edge_tops,
                    wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
                    lora_radius_m=config.COMMS.lora_radius_m,
                )
            )
        return edges

    def _links(self, drones: list[DroneState], edges: list[EdgeState]) -> list[CommsLink]:
        links: list[CommsLink] = []
        parents = [d for d in drones if d.tier == "PARENT"]
        smalls = [d for d in drones if d.tier == "SMALL"]

        for small in smalls:
            parent = min(parents, key=lambda p: _distance(p.pose, small.pose))
            dist = _distance(parent.pose, small.pose)
            quality = _clamp01(1.0 - dist / config.COMMS.lora_radius_m)
            links.append(
                CommsLink(
                    from_id=small.id,
                    to_id=parent.id,
                    type="LORA",
                    quality=round(quality, 3),
                )
            )

        for parent in parents:
            for edge in edges:
                dist = _distance(parent.pose, edge.pose)
                if dist <= config.COMMS.wifi_mesh_radius_m:
                    quality = _clamp01(1.0 - dist / config.COMMS.wifi_mesh_radius_m)
                    links.append(
                        CommsLink(
                            from_id=parent.id,
                            to_id=edge.id,
                            type="WIFI_MESH",
                            quality=round(quality, 3),
                        )
                    )
        return links


class IsaacSimPublisher:
    """Placeholder adapter boundary for the future Isaac extension.

    Later tracks should replace the synthetic frame generation with USD prim
    scraping and sensor metadata from the live Isaac stage while preserving
    the returned SimFrame contract.
    """

    def now_frame(self) -> SimFrame:
        raise NotImplementedError("Isaac stage scraping is not implemented in Phase 1")
