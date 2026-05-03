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
from hades.layout import EDGE_DEPLOYMENTS, ROUTE_DURATION_S, ROUTE_END_X, ROUTE_START_X
from hades.motion import DroneMotionModel, blend_pose, route_pose
from hades.state import CommsLink, ConvoyState, DroneState, EdgeState, Pose, SimFrame, ThreatState


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _distance(a: Pose, b: Pose) -> float:
    return math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2 + (a.z - b.z) ** 2)


@dataclass(frozen=True)
class SyntheticWorldLayout:
    route_start_x: float = ROUTE_START_X
    route_end_x: float = ROUTE_END_X
    route_duration_s: float = ROUTE_DURATION_S
    loop: bool = False
    edge_y_offset_m: float = 42.0
    small_ring_radius_m: float = 24.0
    parent_y_offset_m: float = 32.0

    @classmethod
    def demo_60s(cls) -> "SyntheticWorldLayout":
        return cls(route_start_x=ROUTE_START_X, route_end_x=ROUTE_END_X, route_duration_s=ROUTE_DURATION_S, loop=False)


class SyntheticSimPublisher:
    """Produces deterministic moving frames for Phase 1 verification."""

    def __init__(
        self,
        *,
        layout: SyntheticWorldLayout | None = None,
        environment: str = config.SCENE.environment,
    ) -> None:
        self.layout = layout or SyntheticWorldLayout()
        self.environment = environment
        self._motion = DroneMotionModel()
        self.started_at = time.monotonic()

    def now_frame(self) -> SimFrame:
        return self.frame_at(time.monotonic() - self.started_at)

    def frame_at(self, t: float) -> SimFrame:
        convoy_x = self._convoy_x(t)
        convoy = self._convoy(convoy_x, t)
        drones = self._drones(convoy, t)
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
        if self.layout.loop:
            progress = (t % self.layout.route_duration_s) / self.layout.route_duration_s
        else:
            progress = _clamp01(t / self.layout.route_duration_s)
        return self.layout.route_start_x + route * progress

    def _route_progress_pct(self, x: float) -> float:
        route = self.layout.route_end_x - self.layout.route_start_x
        return 100.0 * (x - self.layout.route_start_x) / route

    def _convoy(self, convoy_x: float, t: float) -> list[ConvoyState]:
        speed_mps = (self.layout.route_end_x - self.layout.route_start_x) / self.layout.route_duration_s
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

    def _drones(self, convoy: list[ConvoyState], t: float) -> list[DroneState]:
        return self._motion.drones_at(t=t, convoy=convoy, active_route="main", threats=[])

    def _edges(self, t: float) -> list[EdgeState]:
        edges: list[EdgeState] = []
        for idx, placement in enumerate(EDGE_DEPLOYMENTS):
            edges.append(
                EdgeState(
                    id=placement.id,
                    pose=Pose(
                        x=placement.x,
                        y=placement.y,
                        z=placement.z,
                        yaw=math.radians(placement.yaw_deg),
                    ),
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


class Track2SimPublisher:
    """Full Track 2 pipeline: comms graph, compute scheduler, threats, navigation.

    Composes SyntheticSimPublisher for base actor positions and adds the
    constraint layers on top. Uses stub=True by default so tests work
    without real ONNX models installed.
    """

    def __init__(
        self,
        *,
        layout: SyntheticWorldLayout | None = None,
        environment: str = config.SCENE.environment,
        stub: bool = True,
    ) -> None:
        from hades.comms import CommsGraph
        from hades.compute import ComputeScheduler
        from hades.models import ModelRegistry
        from hades.navigation import ConvoyRouter, DroneNavigator
        from hades.threats import ThreatSpawner

        self._base = SyntheticSimPublisher(layout=layout, environment=environment)
        self._comms = CommsGraph()
        self._scheduler = ComputeScheduler()
        self._spawner = ThreatSpawner(mode="deterministic")
        registry = ModelRegistry(stub=stub)
        self._navigator = DroneNavigator(registry)
        self._router = ConvoyRouter(registry)
        self.started_at = time.monotonic()
        self._active_route: str = "main"
        self._route_switch_t: float | None = None

    def now_frame(self) -> SimFrame:
        return self.frame_at(time.monotonic() - self.started_at)

    def frame_at(self, t: float) -> SimFrame:
        base_frame = self._base.frame_at(t)

        # Step threats
        threats = self._spawner.step(t)

        # Update convoy route when choke_a threats are active
        if any(th.spawn_zone == "choke_a" for th in threats):
            selected_route = self._router.select_route(base_frame.convoy[0], threats)
            if selected_route != self._active_route:
                self._active_route = selected_route
                self._route_switch_t = min(t, 15.0)

        convoy_states: list[ConvoyState] = []
        for c in base_frame.convoy:
            main_pose = route_pose("main", c.route_progress_pct, c.pose.z)
            target_pose = route_pose(self._active_route, c.route_progress_pct, c.pose.z)
            if self._active_route == "main":
                routed_pose = main_pose
            else:
                switch_t = self._route_switch_t if self._route_switch_t is not None else 15.0
                routed_pose = blend_pose(main_pose, target_pose, (t - switch_t) / 5.0)
            convoy_states.append(ConvoyState(
                id=c.id,
                pose=routed_pose,
                speed_mps=c.speed_mps,
                route_progress_pct=c.route_progress_pct,
                active_route_id=self._active_route,
                threat_ahead=any(
                    math.sqrt((th.pose.x - routed_pose.x) ** 2 + (th.pose.y - routed_pose.y) ** 2) < 80.0
                    for th in threats
                ),
            ))

        drones = self._base._motion.drones_at(
            t=t,
            convoy=convoy_states,
            active_route=self._active_route,
            threats=threats,
        )

        # Update comms topology
        self._comms.step(drones, base_frame.edges, convoy_states)

        # Build interim frame for scheduler
        interim = SimFrame(
            t=t,
            drones=drones,
            edges=base_frame.edges,
            convoy=convoy_states,
            links=self._comms.links(),
            events=[],
            environment=base_frame.environment,
            threats=threats,
        )

        compute_events = self._scheduler.schedule_all(interim, self._comms)

        return SimFrame(
            t=round(t, 3),
            drones=drones,
            edges=base_frame.edges,
            convoy=convoy_states,
            links=self._comms.links(),
            events=[],
            environment=base_frame.environment,
            threats=threats,
            compute_events=compute_events,
        )

    def reset(self, env_ids=None) -> None:
        """Reset publisher state (called by HADESEnv._reset_idx)."""
        self._spawner.reset(env_ids)
        self._active_route = "main"
        self._route_switch_t = None
        self.started_at = time.monotonic()


class IsaacSimDriver:
    """Writes SimFrame actor poses back into a running Isaac Sim stage.

    Must be called from within an Isaac Sim Kit process where omni.usd
    and pxr are available. Prim paths match the names in isaac/scene.usda
    (lowercase root names, e.g. /hades_phase_1/convoy_0).
    """

    _PRIM_PATHS: dict[str, str] = {
        "convoy_0": "/hades_phase_1/convoy_0",
        "convoy_1": "/hades_phase_1/convoy_1",
        "parent_0": "/hades_phase_1/parent_0",
        "parent_1": "/hades_phase_1/parent_1",
        **{f"small_{i}": f"/hades_phase_1/small_{i}" for i in range(config.COUNTS.small_drones)},
        **{f"edge_{i}": f"/hades_phase_1/edge_{i}" for i in range(config.COUNTS.edge_nodes)},
    }

    def apply(self, frame: SimFrame) -> None:
        import omni.usd
        from pxr import Gf, UsdGeom

        stage = omni.usd.get_context().get_stage()
        for actor_list in (frame.drones, frame.edges, frame.convoy):
            for actor in actor_list:
                path = self._PRIM_PATHS.get(actor.id)
                if path is None:
                    continue
                prim = stage.GetPrimAtPath(path)
                if not prim.IsValid():
                    continue
                xf = UsdGeom.Xformable(prim)
                ops = {op.GetOpName(): op for op in xf.GetOrderedXformOps()}
                pose = actor.pose
                if "xformOp:translate" in ops:
                    ops["xformOp:translate"].Set(Gf.Vec3d(pose.x, pose.y, pose.z))
                if "xformOp:rotateXYZ" in ops:
                    ops["xformOp:rotateXYZ"].Set(
                        Gf.Vec3f(
                            math.degrees(pose.roll),
                            math.degrees(pose.pitch),
                            math.degrees(pose.yaw),
                        )
                    )


class IsaacSimPublisher:
    """Scrapes live prim state from a running Isaac Sim stage.

    Must be instantiated from within an Isaac Sim Kit process where
    omni.usd and omni.isaac.core are available.
    """

    def now_frame(self) -> SimFrame:
        import omni.usd
        from pxr import UsdGeom

        stage = omni.usd.get_context().get_stage()
        t = time.monotonic()
        root = "/hades_phase_1"

        drones: list[DroneState] = []
        edges: list[EdgeState] = []
        convoy: list[ConvoyState] = []

        for prim in stage.GetPrimAtPath(root).GetChildren():
            name = prim.GetName()
            xf = UsdGeom.Xformable(prim)
            ops = xf.GetOrderedXformOps()
            pos = ops[0].Get() if ops else (0.0, 0.0, 0.0)
            pose = Pose(x=float(pos[0]), y=float(pos[1]), z=float(pos[2]))

            if name.startswith("parent_"):
                drones.append(DroneState(
                    id=name, tier="PARENT", pose=pose,
                    battery_pct=config.COMPUTE.parent_default_battery_pct,
                    compute_load=0.0, current_task="idle",
                ))
            elif name.startswith("small_"):
                drones.append(DroneState(
                    id=name, tier="SMALL", pose=pose,
                    battery_pct=config.COMPUTE.small_default_battery_pct,
                    compute_load=0.0, current_task="idle",
                ))
            elif name.startswith("edge_"):
                edges.append(EdgeState(
                    id=name, pose=pose,
                    battery_pct=config.COMPUTE.edge_default_battery_pct,
                    compute_load=0.0, alive=True,
                    compute_capacity_tops=config.COMPUTE.edge_tops,
                    wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
                    lora_radius_m=config.COMMS.lora_radius_m,
                ))
            elif name.startswith("convoy_"):
                convoy.append(ConvoyState(
                    id=name, pose=pose, speed_mps=0.0, route_progress_pct=0.0,
                ))

        return SimFrame(
            t=round(t, 3),
            drones=drones,
            edges=edges,
            convoy=convoy,
            links=[],
            events=[],
            environment=config.SCENE.environment,
        )
