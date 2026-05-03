"""Geo-aware simulation publisher for analyzed real-world scenarios."""

from __future__ import annotations

import math
import time
from dataclasses import asdict

from hades import config
from hades.autonomy.offload_policy import HeuristicOffloadPolicy, OffloadCtx, PeerInfo, Task
from hades.realworld.capabilities import PARENT_CAPABILITY, SMALL_CAPABILITY
from hades.realworld.geo import LatLng, cumulative_distances, haversine_m, local_xy, offset_point, sample_route
from hades.realworld.optimizer import EdgeAnalysis
from hades.state import EdgeState, OffloadEvent, Pose


class RealWorldSimPublisher:
    def __init__(
        self,
        *,
        scenario_id: str,
        route_points: list[LatLng],
        analysis: EdgeAnalysis,
        wifi_radius_m: float,
        approved_stationary_edge_ids: set[str] | None = None,
        edge_statuses: dict[str, str] | None = None,
        parent_count: int = 4,
        small_count: int = 16,
        route_speed_mps: float = 11.0,
    ) -> None:
        if len(route_points) < 2:
            raise ValueError("Real-world publisher requires at least two route points")
        self.scenario_id = scenario_id
        self.route_points = route_points
        self.route_distances = cumulative_distances(route_points)
        self.reference = route_points[0]
        self.analysis = analysis
        self.wifi_radius_m = wifi_radius_m
        self.parent_count = parent_count
        self.small_count = small_count
        self.route_speed_mps = route_speed_mps
        self.started_at = time.monotonic()
        self._route_distance_offset_m = 0.0
        self._route_revision = 0
        self._last_live_reroute: dict[str, object] | None = None
        self._started = False
        self._policy = HeuristicOffloadPolicy()
        self._next_task_t = 2.0
        self._event_log: list[OffloadEvent] = []
        self._approved_stationary_edge_ids = approved_stationary_edge_ids or set()
        self._edge_statuses = edge_statuses or {}
        self._attack_vectors = self._build_attack_vectors()
        self._search_targets = self._build_search_targets()

    @property
    def attack_vectors(self) -> list[dict[str, object]]:
        return self._attack_vectors

    def start(self) -> None:
        self._started = True
        self.started_at = time.monotonic()
        self._next_task_t = 2.0
        self._event_log.clear()

    def set_analysis(
        self,
        analysis: EdgeAnalysis,
        *,
        approved_stationary_edge_ids: set[str] | None = None,
        edge_statuses: dict[str, str] | None = None,
    ) -> None:
        self.analysis = analysis
        if approved_stationary_edge_ids is not None:
            self._approved_stationary_edge_ids = set(approved_stationary_edge_ids)
        if edge_statuses is not None:
            self._edge_statuses = dict(edge_statuses)
        self._attack_vectors = self._build_attack_vectors()
        self._search_targets = self._build_search_targets()

    def update_route(
        self,
        route_points: list[LatLng],
        analysis: EdgeAnalysis,
        *,
        applied_reroute_id: str | None = None,
        current_t: float | None = None,
        start_at_route_beginning: bool = False,
    ) -> None:
        if len(route_points) < 2:
            raise ValueError("Real-world publisher requires at least two route points")
        old_length = max(1.0, self.route_distances[-1])
        if current_t is None:
            current_t = self.elapsed_s()
        old_distance = self._route_distance_at(current_t, old_length)
        progress = old_distance / old_length

        self.route_points = route_points
        self.route_distances = cumulative_distances(route_points)
        new_length = max(1.0, self.route_distances[-1])
        if self._started:
            new_distance = 0.0 if start_at_route_beginning else progress * new_length
            self._route_distance_offset_m = new_distance - current_t * self.route_speed_mps
        else:
            self._route_distance_offset_m = 0.0
        self.reference = route_points[0]
        self._route_revision += 1
        if applied_reroute_id is not None:
            self._last_live_reroute = {
                "proposal_id": applied_reroute_id,
                "route_revision": self._route_revision,
                "applied_at_t": round(current_t, 3),
                "preserved_progress_pct": 0.0 if start_at_route_beginning else round(progress * 100.0, 2),
                "mode": "live_route_from_current_position" if start_at_route_beginning else "live_route_swap",
            }
        self.set_analysis(analysis, approved_stationary_edge_ids=set(), edge_statuses={})

    def elapsed_s(self) -> float:
        return time.monotonic() - self.started_at

    def current_route_anchor(self, t: float | None = None) -> dict[str, object]:
        if t is None:
            t = self.elapsed_s()
        route_length = self.route_distances[-1]
        base_distance = self._route_distance_at(t, route_length)
        mission = self._mission_state(base_distance, route_length)
        distance = max(0.0, min(route_length, base_distance - float(mission["holdback_m"])))
        point, heading = sample_route(self.route_points, self.route_distances, distance)
        return {
            "point": point,
            "route_distance_m": distance,
            "route_progress_pct": 100.0 * distance / max(1.0, route_length),
            "heading_rad": heading,
            "elapsed_s": t,
        }

    def now_frame(self) -> dict[str, object]:
        return self.frame_at(self.elapsed_s())

    def frame_at(self, t: float) -> dict[str, object]:
        route_length = self.route_distances[-1]
        base_distance = self._route_distance_at(t, route_length)
        search_mission = self._mission_state(base_distance, route_length)
        convoy_mission = self._screening_mission(search_mission)
        convoy, lead_point, heading, _ = self._convoy_state(base_distance, route_length, convoy_mission)
        edges = self._edges(t, convoy)
        edge_plan = self._edge_support_plan(edges, base_distance, route_length, search_mission)
        drones = self._drones(lead_point, heading, t, search_mission, base_distance, route_length, edge_plan)
        links = self._links(drones, edges)
        self._apply_connectivity_rules(drones, links, edges)
        sensing = self._sensing_state(drones, links)
        route_control = self._route_control_from_sensing(search_mission, sensing)
        if route_control["mode"] != convoy_mission["mode"]:
            convoy, lead_point, heading, _ = self._convoy_state(base_distance, route_length, route_control)
            edges = self._edges(t, convoy)
            edge_plan = self._edge_support_plan(edges, base_distance, route_length, search_mission)
            drones = self._drones(lead_point, heading, t, search_mission, base_distance, route_length, edge_plan)
            links = self._links(drones, edges)
            self._apply_connectivity_rules(drones, links, edges)
            sensing = self._sensing_state(drones, links)
            route_control = self._route_control_from_sensing(search_mission, sensing)
        new_events = self._events(t, drones, edges, links)

        active_pairs = {(event.parent_id, event.chosen_target) for event in new_events}
        for link in links:
            if (link["from_id"], link["to_id"]) in active_pairs or (link["to_id"], link["from_id"]) in active_pairs:
                link["active_payload"] = True

        alerts = []
        if self.analysis.coverage_percent < 95.0:
            alerts.append(f"COVERAGE {self.analysis.coverage_percent:.1f}%")
        if sensing["route_adaptation"]["recommended"]:
            alerts.append("AUTO REROUTE")

        return {
            "t": round(t, 3),
            "drones": drones,
            "edges": edges,
            "convoy": convoy,
            "links": links,
            "events": [asdict(event) for event in self._event_log],
            "scenario_phase": "realworld_running" if self._started else "realworld_preflight",
            "alerts": alerts,
            "threats": [],
            "environment": "google_maps_realworld_ukraine_civic",
            "sensing": sensing,
            "reroute": {
                "recommended": sensing["route_adaptation"]["recommended"],
                "reason": sensing["route_adaptation"]["reason"] or route_control["reason"],
                "mode": route_control["mode"],
                "active_vector_id": route_control["vector_id"],
                "convoy_speed_mps": route_control["speed_mps"],
                "route_revision": self._route_revision,
                "applied": self._last_live_reroute,
            },
            "geo": {
                "scenario_id": self.scenario_id,
                "route_revision": self._route_revision,
                "route_distance_m": round(route_length, 1),
                "coverage_percent": round(self.analysis.coverage_percent, 1),
                "edge_support_plan": _serializable_edge_plan(edge_plan),
                "coverage_gaps": [
                    {"start": start.to_dict(), "end": end.to_dict()}
                    for start, end in self.analysis.coverage_gaps
                ],
                "search_targets": self._search_targets,
                "attack_vectors": self._attack_vectors,
            },
        }

    def _convoy_state(
        self,
        base_distance: float,
        route_length: float,
        mission: dict[str, object],
    ) -> tuple[list[dict[str, object]], LatLng, float, float]:
        distance = max(0.0, min(route_length, base_distance - mission["holdback_m"]))
        lead_point, heading = sample_route(self.route_points, self.route_distances, distance)
        if mission["convoy_lateral_offset_m"]:
            lead_point = self._offset_from_heading(lead_point, heading, 0.0, mission["convoy_lateral_offset_m"])
        trail_point, trail_heading = sample_route(
            self.route_points,
            self.route_distances,
            max(0.0, distance - 18.0),
        )
        if mission["convoy_lateral_offset_m"]:
            trail_point = self._offset_from_heading(trail_point, trail_heading, 0.0, mission["convoy_lateral_offset_m"])
        convoy = [
            self._convoy_actor("convoy_0", lead_point, heading, distance / route_length * 100.0, mission),
            self._convoy_actor(
                "convoy_1",
                trail_point,
                trail_heading,
                max(0.0, distance - 18.0) / route_length * 100.0,
                mission,
            ),
        ]
        return convoy, lead_point, heading, distance

    def _convoy_actor(
        self,
        actor_id: str,
        point: LatLng,
        heading: float,
        progress_pct: float,
        mission: dict[str, object],
    ) -> dict[str, object]:
        pose = self._pose(point, z=0.8, heading=heading)
        return {
            "id": actor_id,
            "pose": asdict(pose),
            "geo": point.to_dict(),
            "speed_mps": mission["speed_mps"],
            "route_progress_pct": max(0.0, min(100.0, progress_pct)),
            "route_adaptation": {
                "mode": mission["mode"],
                "active_vector_id": mission["vector_id"],
                "lateral_offset_m": mission["convoy_lateral_offset_m"],
                "reason": mission["reason"],
            },
        }

    def _drones(
        self,
        lead: LatLng,
        heading: float,
        t: float,
        mission: dict[str, object],
        route_distance_m: float,
        route_length_m: float,
        edge_plan: dict[str, object],
    ) -> list[dict[str, object]]:
        drones: list[dict[str, object]] = []
        mission_sector = int(mission["sector"])
        mission_target = mission["target"]
        parent_plans = edge_plan["parents"]
        parent_points: dict[int, LatLng] = {}
        for idx in range(self.parent_count):
            parent_plan = parent_plans[idx]
            patrol_distance = float(parent_plan["route_distance_m"])
            route_point, patrol_heading = sample_route(self.route_points, self.route_distances, patrol_distance)
            lateral = float(parent_plan["lateral_m"])
            task = f"coordinate_sector_{idx}"
            assignment = "edge_supported_route_sector_search" if parent_plan["edge_anchor_id"] else "moving_route_sector_search"
            point = self._offset_from_heading(route_point, patrol_heading, 0.0, lateral)
            if mission["active"] and idx == mission_sector:
                task = f"coordinate_vector_{mission['vector_id']}"
                assignment = (
                    "edge_assisted_vector_investigation"
                    if parent_plan["edge_anchor_id"]
                    else "direct_small_drone_investigation"
                )
                if mission_target is not None:
                    target = LatLng(float(mission_target["lat"]), float(mission_target["lng"]))
                    vector_standoff = self._offset_from_heading(target, patrol_heading, -95.0, lateral * 0.18)
                    point = _blend_points(point, vector_standoff, 0.62)
            anchor_point = parent_plan.get("edge_anchor_point")
            if isinstance(anchor_point, LatLng):
                point = _limit_from_anchor(anchor_point, point, self.wifi_radius_m * 0.68)
            pose = self._pose(
                point,
                z=config.SCENE.parent_hover_altitude_m + 0.8 * math.sin(t * 0.8 + idx),
                heading=patrol_heading,
            )
            parent_points[idx] = point
            drones.append(
                {
                    "id": f"parent_{idx}",
                    "tier": "PARENT",
                    "sector_id": f"sector_{idx}",
                    "pose": asdict(pose),
                    "geo": point.to_dict(),
                    "battery_pct": round(config.COMPUTE.parent_default_battery_pct - 0.002 * t, 2),
                    "compute_load": round(0.50 + 0.18 * math.sin(t * 0.31 + idx), 3),
                    "current_task": task,
                    "assignment": assignment,
                    "search_cell": {
                        "route_distance_m": round(patrol_distance, 1),
                        "lateral_m": round(lateral, 1),
                        "pattern": parent_plan["pattern"],
                        "edge_anchor_id": parent_plan["edge_anchor_id"],
                        "edge_anchor_distance_m": parent_plan["edge_anchor_distance_m"],
                        "edge_supported": bool(parent_plan["edge_anchor_id"]),
                    },
                    "edge_anchor_id": parent_plan["edge_anchor_id"],
                    "edge_anchor_distance_m": parent_plan["edge_anchor_distance_m"],
                    "edge_supported": bool(parent_plan["edge_anchor_id"]),
                    "controls": [
                        f"small_{small_idx}"
                        for small_idx in range(self.small_count)
                        if small_idx % self.parent_count == idx
                    ],
                    "capabilities": {
                        "vision_radius_m": PARENT_CAPABILITY.vision_radius_m,
                        "compute_tops": PARENT_CAPABILITY.compute_tops,
                        "onboard_functions": list(PARENT_CAPABILITY.onboard_functions),
                        "edge_required_functions": list(PARENT_CAPABILITY.edge_required_functions),
                    },
                }
            )

        children_per_parent = max(1, math.ceil(self.small_count / max(1, self.parent_count)))
        for idx in range(self.small_count):
            sector = idx % self.parent_count
            slot = idx // self.parent_count
            parent_plan = parent_plans[sector]
            sector_center = float(parent_plan["route_distance_m"])
            slot_center = (slot - (children_per_parent - 1) / 2.0) * 115.0
            along_sweep = math.sin(t * 0.31 + idx * 0.83) * 95.0
            patrol_distance = (sector_center + slot_center + along_sweep) % max(1.0, route_length_m)
            route_point, local_heading = sample_route(self.route_points, self.route_distances, patrol_distance)
            side = -1.0 if (slot + sector) % 2 == 0 else 1.0
            lane = 78.0 + (slot % children_per_parent) * 38.0
            lateral = side * lane + float(parent_plan["lateral_m"]) * 0.22 + math.sin(t * 0.43 + idx * 0.71) * 42.0
            point = self._offset_from_heading(route_point, local_heading, 0.0, lateral)
            assignment = "moving_lawnmower_sweep"
            pattern = "edge_supported_lawnmower" if parent_plan["edge_anchor_id"] else "lawnmower_route_cell"
            controlled_by = f"parent_{sector}"
            if mission["active"] and mission_target is not None:
                target = LatLng(float(mission_target["lat"]), float(mission_target["lng"]))
                if sector == mission_sector:
                    orbit = 42.0 + (slot % children_per_parent) * 24.0
                    orbit_angle = t * (0.42 + slot * 0.025) + idx * 1.7
                    target_offset = offset_point(
                        target,
                        math.cos(orbit_angle) * orbit,
                        math.sin(orbit_angle) * orbit,
                    )
                    point = _blend_points(point, target_offset, 0.84)
                    assignment = f"investigate_{mission['vector_id']}"
                    pattern = "edge_assisted_orbit" if parent_plan["edge_anchor_id"] else "parent_directed_orbit"
                elif abs(sector - mission_sector) == 1:
                    screen_point = self._offset_from_heading(target, local_heading, -115.0, lateral * 0.34)
                    point = _blend_points(point, screen_point, 0.48)
                    assignment = f"screen_adjacent_{mission['vector_id']}"
                    pattern = "flank_screen"
            parent_point = parent_points.get(sector)
            if parent_point is not None:
                point = _limit_from_anchor(parent_point, point, config.COMMS.lora_radius_m * 0.72)
            pose = self._pose(
                point,
                z=config.SCENE.small_hover_altitude_m + 1.2 * math.sin(t * 0.9 + idx),
                heading=local_heading,
            )
            drones.append(
                {
                    "id": f"small_{idx}",
                    "tier": "SMALL",
                    "sector_id": f"sector_{sector}",
                    "pose": asdict(pose),
                    "geo": point.to_dict(),
                    "battery_pct": round(config.COMPUTE.small_default_battery_pct - 0.004 * t, 2),
                    "compute_load": round(0.05 + 0.03 * math.sin(t * 0.7 + idx), 3),
                    "current_task": assignment,
                    "assignment": assignment,
                    "controlled_by": controlled_by,
                    "search_cell": {
                        "route_distance_m": round(patrol_distance, 1),
                        "lateral_m": round(lateral, 1),
                        "pattern": pattern,
                        "edge_anchor_id": parent_plan["edge_anchor_id"],
                        "edge_anchor_distance_m": parent_plan["edge_anchor_distance_m"],
                        "edge_supported": bool(parent_plan["edge_anchor_id"]),
                    },
                    "edge_anchor_id": parent_plan["edge_anchor_id"],
                    "edge_supported": bool(parent_plan["edge_anchor_id"]),
                    "capabilities": {
                        "vision_radius_m": SMALL_CAPABILITY.vision_radius_m,
                        "compute_tops": SMALL_CAPABILITY.compute_tops,
                        "onboard_functions": list(SMALL_CAPABILITY.onboard_functions),
                        "edge_required_functions": list(SMALL_CAPABILITY.edge_required_functions),
                    },
                }
            )
        return drones

    def _edges(self, t: float, convoy: list[dict[str, object]]) -> list[dict[str, object]]:
        edges: list[dict[str, object]] = []
        for idx, vehicle in enumerate(convoy):
            pose = Pose(**vehicle["pose"])
            edge_pose = Pose(pose.x, pose.y, 2.2, yaw=pose.yaw)
            edges.append(
                {
                    "id": f"convoy_edge_{idx}",
                    "pose": asdict(edge_pose),
                    "geo": vehicle["geo"],
                    "battery_pct": 100.0,
                    "compute_load": round(0.22 + 0.08 * math.sin(t / 6.0 + idx), 3),
                    "alive": True,
                    "compute_capacity_tops": config.COMPUTE.edge_tops,
                    "wifi_radius_m": self.wifi_radius_m,
                    "lora_radius_m": config.COMMS.lora_radius_m,
                    "edge_type": "convoy_edge",
                    "status": "approved",
                    "approved": True,
                    "attached_to": vehicle["id"],
                    "reasons": ["Mobile convoy-carried edge node, active after simulation start"],
                    "coverage_m": 0.0,
                    "avg_latency_ms": config.COMMS.wifi_base_latency_ms,
                    "score": 0.0,
                }
            )

        for idx, edge in enumerate(self.analysis.edges):
            if edge.id not in self._approved_stationary_edge_ids:
                continue
            pose = self._pose(edge.point, z=max(1.2, edge.elevation_m), heading=0.0)
            status = self._edge_statuses.get(edge.id, "approved")
            edges.append(
                {
                    "id": edge.id,
                    "pose": asdict(pose),
                    "geo": edge.point.to_dict(),
                    "battery_pct": round(config.COMPUTE.edge_default_battery_pct - 0.0004 * t, 2),
                    "compute_load": round(0.18 + 0.18 * (0.5 + 0.5 * math.sin(t / 7.0 + idx)), 3),
                    "alive": True,
                    "compute_capacity_tops": config.COMPUTE.edge_tops,
                    "wifi_radius_m": self.wifi_radius_m,
                    "lora_radius_m": config.COMMS.lora_radius_m,
                    "edge_type": "manual_stationary_edge" if edge.manual else "stationary_edge",
                    "status": status,
                    "approved": True,
                    "manual": edge.manual,
                    "reasons": list(edge.reasons),
                    "coverage_m": round(edge.coverage_m, 1),
                    "avg_latency_ms": round(edge.avg_latency_ms, 1),
                    "score": round(edge.score, 1),
                }
            )
        return edges

    def _links(
        self,
        drones: list[dict[str, object]],
        edges: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        parents = [drone for drone in drones if drone["tier"] == "PARENT"]
        smalls = [drone for drone in drones if drone["tier"] == "SMALL"]
        links: list[dict[str, object]] = []
        parents_by_id = {str(parent["id"]): parent for parent in parents}

        for small in smalls:
            parent = parents_by_id.get(str(small.get("controlled_by"))) or min(parents, key=lambda p: _actor_distance(small, p))
            dist = _actor_distance(small, parent)
            if dist <= config.COMMS.lora_radius_m:
                links.append(
                    {
                        "from_id": small["id"],
                        "to_id": parent["id"],
                        "type": "LORA",
                        "quality": round(max(0.0, 1.0 - dist / config.COMMS.lora_radius_m), 3),
                        "active_payload": False,
                    }
                )

        for i, parent_a in enumerate(parents):
            for parent_b in parents[i + 1 :]:
                dist = _actor_distance(parent_a, parent_b)
                if dist <= self.wifi_radius_m:
                    links.append(
                        {
                            "from_id": parent_a["id"],
                            "to_id": parent_b["id"],
                            "type": "WIFI_MESH",
                            "quality": round(max(0.0, 1.0 - dist / self.wifi_radius_m), 3),
                            "active_payload": False,
                        }
                    )

        for parent in parents:
            for edge in edges:
                dist = _actor_distance(parent, edge)
                if dist <= self.wifi_radius_m:
                    links.append(
                        {
                            "from_id": parent["id"],
                            "to_id": edge["id"],
                            "type": "WIFI_MESH",
                            "quality": round(max(0.0, 1.0 - dist / self.wifi_radius_m), 3),
                            "active_payload": False,
                        }
                    )
        return links

    def _apply_connectivity_rules(
        self,
        drones: list[dict[str, object]],
        links: list[dict[str, object]],
        edges: list[dict[str, object]],
    ) -> None:
        edge_ids = {str(edge["id"]) for edge in edges}
        edge_connected = {
            str(link["from_id"])
            for link in links
            if link["type"] == "WIFI_MESH" and str(link["to_id"]) in edge_ids
        }
        edge_connected.update(
            str(link["to_id"])
            for link in links
            if link["type"] == "WIFI_MESH" and str(link["from_id"]) in edge_ids
        )
        edge_link_by_parent: dict[str, tuple[str, float]] = {}
        for link in links:
            if link["type"] != "WIFI_MESH":
                continue
            from_id = str(link["from_id"])
            to_id = str(link["to_id"])
            quality = float(link["quality"])
            parent_id = ""
            edge_id = ""
            if from_id.startswith("parent_") and to_id in edge_ids:
                parent_id = from_id
                edge_id = to_id
            elif to_id.startswith("parent_") and from_id in edge_ids:
                parent_id = to_id
                edge_id = from_id
            if parent_id and quality > edge_link_by_parent.get(parent_id, ("", -1.0))[1]:
                edge_link_by_parent[parent_id] = (edge_id, quality)
        small_lora = {
            str(link["from_id"]): float(link["quality"])
            for link in links
            if link["type"] == "LORA" and str(link["from_id"]).startswith("small_")
        }
        parent_by_id = {str(drone["id"]): drone for drone in drones if drone["tier"] == "PARENT"}
        for drone in drones:
            caps = drone["capabilities"]
            onboard = list(caps["onboard_functions"])
            edge_required = list(caps["edge_required_functions"])
            if drone["tier"] == "PARENT":
                connected_edge = edge_link_by_parent.get(str(drone["id"]))
                has_edge = connected_edge is not None
                connected_edge_id = None if connected_edge is None else connected_edge[0]
                connected_quality = 0.0 if connected_edge is None else connected_edge[1]
                drone["compute_mode"] = "edge_augmented" if has_edge else "onboard_parent"
                drone["available_functions"] = onboard + (edge_required if has_edge else [])
                drone["edge_connected"] = has_edge
                drone["connected_edge_id"] = connected_edge_id
                drone["edge_link_quality"] = round(connected_quality, 3)
                if has_edge and connected_edge_id == drone.get("edge_anchor_id"):
                    mode = "direct_anchor"
                elif has_edge:
                    mode = "direct_edge"
                elif drone.get("edge_anchor_id"):
                    mode = "assigned_anchor_out_of_range"
                else:
                    mode = "none"
                drone["edge_connectivity_mode"] = mode
            else:
                parent_id = str(drone.get("controlled_by") or "")
                parent = parent_by_id.get(parent_id)
                lora_quality = float(small_lora.get(str(drone["id"]), 0.0))
                edge_connected_via_parent = bool(parent and parent.get("edge_connected") and lora_quality > 0.0)
                drone["compute_mode"] = "small_onboard_report_only"
                drone["available_functions"] = onboard
                drone["parent_link_available"] = lora_quality > 0.0
                drone["parent_link_quality"] = round(lora_quality, 3)
                drone["edge_connected"] = edge_connected_via_parent
                drone["connected_edge_id"] = None if not parent else parent.get("connected_edge_id")
                drone["edge_link_quality"] = 0.0 if not edge_connected_via_parent else parent.get("edge_link_quality", 0.0)
                drone["edge_connectivity_mode"] = (
                    "via_parent_edge" if edge_connected_via_parent else ("parent_lora_only" if lora_quality > 0.0 else "none")
                )

    def _sensing_state(
        self,
        drones: list[dict[str, object]],
        links: list[dict[str, object]],
    ) -> dict[str, object]:
        link_quality = {(str(link["from_id"]), str(link["to_id"])): float(link["quality"]) for link in links}
        detections: list[dict[str, object]] = []
        reports_by_target: dict[str, list[dict[str, object]]] = {}
        parents = [drone for drone in drones if drone["tier"] == "PARENT"]
        parent_by_id = {str(parent["id"]): parent for parent in parents}

        for drone in drones:
            radius = float(drone["capabilities"]["vision_radius_m"])
            visible: list[str] = []
            for target in self._search_targets:
                distance = haversine_m(_actor_point(drone), LatLng(float(target["lat"]), float(target["lng"])))
                if distance > radius:
                    continue
                visible.append(str(target["id"]))
                confidence = max(0.15, min(0.98, 1.0 - distance / radius))
                edge_assisted = bool(drone.get("edge_connected"))
                if edge_assisted:
                    confidence = min(0.99, confidence + 0.1 + float(drone.get("edge_link_quality", 0.0)) * 0.08)
                detection = {
                    "target_id": target["id"],
                    "attack_vector_id": target.get("attack_vector_id"),
                    "observer_id": drone["id"],
                    "observer_tier": drone["tier"],
                    "distance_m": round(distance, 1),
                    "confidence": round(confidence, 3),
                    "reported_to": None,
                    "classification": "edge_augmented_contact" if edge_assisted else "coarse_contact",
                    "edge_assisted": edge_assisted,
                    "edge_anchor_id": drone.get("connected_edge_id") or drone.get("edge_anchor_id"),
                }
                if drone["tier"] == "SMALL":
                    parent_id = self._report_parent_id(drone, drones)
                    quality = max(
                        link_quality.get((str(drone["id"]), parent_id), 0.0),
                        link_quality.get((parent_id, str(drone["id"])), 0.0),
                    )
                    if quality > 0.0:
                        parent = parent_by_id.get(parent_id)
                        parent_edge_assisted = bool(parent and parent.get("edge_connected"))
                        if parent_edge_assisted:
                            confidence = min(0.99, confidence + 0.12 + quality * 0.05)
                            detection["confidence"] = round(confidence, 3)
                            detection["classification"] = "edge_relayed_coarse_contact"
                            detection["edge_assisted"] = True
                            detection["edge_anchor_id"] = parent.get("connected_edge_id") or parent.get("edge_anchor_id")
                        detection["reported_to"] = parent_id
                        detection["uplink_quality"] = round(quality, 3)
                        reports_by_target.setdefault(str(target["id"]), []).append(detection)
                    else:
                        detection["dropped_reason"] = "no_lora_to_parent"
                else:
                    reports_by_target.setdefault(str(target["id"]), []).append(detection)
                detections.append(detection)
            drone["visible_target_ids"] = visible

        fused = []
        for target in self._search_targets:
            reports = reports_by_target.get(str(target["id"]), [])
            if not reports:
                continue
            best_parent = self._fusion_parent_for_target(target, reports, parent_by_id)
            mode = best_parent.get("compute_mode", "onboard_parent")
            required = "high_resolution_classification"
            edge_assisted = bool(best_parent.get("edge_connected")) or any(bool(report.get("edge_assisted")) for report in reports)
            status = "classified" if required in best_parent.get("available_functions", []) else "tracked_pending_edge"
            avg_report_confidence = sum(float(report["confidence"]) for report in reports) / max(1, len(reports))
            confidence = min(
                0.99,
                0.34 + avg_report_confidence * 0.28 + 0.13 * len(reports) + (0.16 if edge_assisted else 0.0),
            )
            edge_anchor_id = best_parent.get("connected_edge_id") or best_parent.get("edge_anchor_id")
            classification_quality = "edge_high_resolution" if edge_assisted else "parent_local_fusion"
            reason = (
                f"{len(reports)} reports fused with edge anchor {edge_anchor_id}"
                if edge_assisted
                else f"{len(reports)} LoRa/onboard reports fused locally"
            )
            fused.append(
                {
                    "target_id": target["id"],
                    "attack_vector_id": target.get("attack_vector_id"),
                    "fusion_parent_id": best_parent["id"],
                    "report_count": len(reports),
                    "compute_mode": mode,
                    "status": status,
                    "edge_assisted": edge_assisted,
                    "edge_anchor_id": edge_anchor_id,
                    "classification_quality": classification_quality,
                    "fusion_confidence_reason": reason,
                    "confidence": round(confidence, 3),
                }
            )

        risky_tracks = [track for track in fused if float(track["confidence"]) >= 0.75]
        best_risky = max(risky_tracks, key=lambda track: float(track["confidence"]), default=None)
        if best_risky is None:
            reason = ""
            control_action = "continue_route"
        elif best_risky.get("edge_assisted"):
            reason = f"Edge-assisted fused-track confidence exceeded threshold via {best_risky.get('edge_anchor_id')}"
            control_action = "auto_reroute_with_edge_assisted_fusion"
        else:
            reason = "Synthetic fused-track confidence exceeded reroute threshold"
            control_action = "request_alternate_route_and_slow_convoy"
        return {
            "targets": self._search_targets,
            "attack_vectors": self._attack_vectors,
            "detections": detections,
            "fused_tracks": fused,
            "route_adaptation": {
                "recommended": bool(risky_tracks),
                "reason": reason,
                "trigger_target_ids": [str(track["target_id"]) for track in risky_tracks],
                "control_action": control_action,
            },
            "rules": {
                "small_drone": "circular FoV, coarse detection only, must uplink to parent over LoRa",
                "parent_drone": "larger circular FoV, local fusion/classification, edge-augmented functions only while connected to an edge",
                "edge_node": "convoy edges are always active after start; stationary edges require operator approval",
            },
        }

    def _events(
        self,
        t: float,
        drones: list[dict[str, object]],
        edges: list[dict[str, object]],
        links: list[dict[str, object]],
    ) -> list[OffloadEvent]:
        if t < self._next_task_t:
            return []
        self._next_task_t = t + 3.5
        events: list[OffloadEvent] = []
        parents = [drone for drone in drones if drone["tier"] == "PARENT"]

        for parent in parents:
            ctx = self._offload_ctx(parent, parents, edges, links)
            _, event = self._policy.decide(
                Task(id=f"rw_{int(t * 10):05d}_{parent['id']}"),
                ctx,
            )
            actual = round(max(1.0, event.expected_latency_ms * (1.0 + 0.08 * math.sin(t))), 1)
            events.append(
                OffloadEvent(
                    parent_id=event.parent_id,
                    task_id=event.task_id,
                    chosen_target=event.chosen_target,
                    expected_latency_ms=event.expected_latency_ms,
                    actual_latency_ms=actual,
                    reason=event.reason,
                )
            )

        self._event_log.extend(events)
        self._event_log = self._event_log[-24:]
        return events

    def _offload_ctx(
        self,
        parent: dict[str, object],
        parents: list[dict[str, object]],
        edges: list[dict[str, object]],
        links: list[dict[str, object]],
    ) -> OffloadCtx:
        parent_id = str(parent["id"])
        wifi_quality: dict[str, float] = {}
        for link in links:
            if link["type"] != "WIFI_MESH":
                continue
            if link["from_id"] == parent_id:
                wifi_quality[str(link["to_id"])] = float(link["quality"])
            elif link["to_id"] == parent_id:
                wifi_quality[str(link["from_id"])] = float(link["quality"])

        peers = [
            PeerInfo(
                id=str(peer["id"]),
                link_quality=wifi_quality[str(peer["id"])],
                compute_load=float(peer["compute_load"]),
                battery_pct=float(peer["battery_pct"]),
            )
            for peer in parents
            if peer["id"] != parent_id and peer["id"] in wifi_quality
        ]

        edge_states = [
            EdgeState(
                id=str(edge["id"]),
                pose=Pose(**edge["pose"]),
                battery_pct=float(edge["battery_pct"]),
                compute_load=float(edge["compute_load"]),
                alive=bool(edge["alive"]),
                compute_capacity_tops=float(edge["compute_capacity_tops"]),
                wifi_radius_m=float(edge["wifi_radius_m"]),
                lora_radius_m=float(edge["lora_radius_m"]),
            )
            for edge in edges
            if edge["id"] in wifi_quality and edge["alive"]
        ]

        return OffloadCtx(
            own_id=parent_id,
            own_load=float(parent["compute_load"]),
            own_battery_pct=float(parent["battery_pct"]),
            own_tops=config.COMPUTE.parent_tops,
            peers_in_wifi=peers,
            edges_in_wifi=edge_states,
            edge_link_qualities={edge.id: wifi_quality[edge.id] for edge in edge_states},
        )

    def _pose(self, point: LatLng, *, z: float, heading: float) -> Pose:
        x, y = local_xy(self.reference, point)
        return Pose(x=x, y=y, z=z, yaw=heading)

    def _offset_from_heading(
        self,
        origin: LatLng,
        heading: float,
        along_m: float,
        lateral_m: float,
    ) -> LatLng:
        east = math.sin(heading) * along_m + math.cos(heading) * lateral_m
        north = math.cos(heading) * along_m - math.sin(heading) * lateral_m
        return offset_point(origin, east, north)

    def _build_attack_vectors(self) -> list[dict[str, object]]:
        route_length = self.route_distances[-1]
        vectors: list[dict[str, object]] = []
        seeds = [
            (0.22, -420.0, 0.58),
            (0.52, 380.0, 0.72),
            (0.76, -360.0, 0.64),
        ]
        for idx, (frac, lateral, risk) in enumerate(seeds):
            route_point, heading = sample_route(self.route_points, self.route_distances, route_length * frac)
            start = self._offset_from_heading(route_point, heading, -80.0, lateral)
            end = self._offset_from_heading(route_point, heading, 0.0, lateral * 0.18)
            vectors.append(
                {
                    "id": f"synthetic_vector_{idx}",
                    "type": "synthetic_approach_corridor",
                    "start": start.to_dict(),
                    "end": end.to_dict(),
                    "width_m": 180.0,
                    "risk": risk,
                    "route_distance_m": round(route_length * frac, 1),
                    "explanation": "Synthetic route-risk corridor generated from route geometry; not live intelligence.",
                }
            )
        for idx, (start_gap, end_gap) in enumerate(self.analysis.coverage_gaps[:2]):
            vectors.append(
                {
                    "id": f"coverage_gap_vector_{idx}",
                    "type": "synthetic_gap_pressure",
                    "start": start_gap.to_dict(),
                    "end": end_gap.to_dict(),
                    "width_m": 120.0,
                    "risk": 0.48,
                    "route_distance_m": 0.0,
                    "explanation": "Synthetic risk marker for an uncovered route segment.",
                }
            )
        return vectors

    def _build_search_targets(self) -> list[dict[str, object]]:
        targets: list[dict[str, object]] = []
        for idx, vector in enumerate(self._attack_vectors):
            end = vector["end"]
            targets.append(
                {
                    "id": f"search_target_{idx}",
                    "attack_vector_id": vector["id"],
                    "lat": float(end["lat"]),
                    "lng": float(end["lng"]),
                    "type": "synthetic_route_contact",
                    "route_distance_m": vector.get("route_distance_m", 0.0),
                }
            )
        return targets

    def _mission_state(self, distance_m: float, route_length_m: float) -> dict[str, object]:
        if not self._attack_vectors:
            return self._nominal_mission()
        candidates = []
        for vector in self._attack_vectors:
            route_distance = float(vector.get("route_distance_m", 0.0))
            if route_distance <= 0.0:
                continue
            delta = abs(route_distance - distance_m)
            window = max(550.0, min(1_100.0, route_length_m * 0.18))
            if delta <= window:
                candidates.append((delta, -float(vector.get("risk", 0.0)), vector))
        if not candidates:
            return self._nominal_mission()
        _, _, vector = sorted(candidates)[0]
        target = next(
            (
                target
                for target in self._search_targets
                if target.get("attack_vector_id") == vector["id"]
            ),
            None,
        )
        route_distance = float(vector.get("route_distance_m", distance_m))
        sector = max(
            0,
            min(
                self.parent_count - 1,
                int((route_distance / max(1.0, route_length_m)) * self.parent_count),
            ),
        )
        lateral_sign = _relative_lateral_sign(vector)
        offset = -lateral_sign * min(55.0, 28.0 + float(vector.get("risk", 0.5)) * 28.0)
        return {
            "active": True,
            "mode": "defensive_slowdown_and_offset",
            "vector_id": vector["id"],
            "sector": sector,
            "target": target,
            "speed_mps": round(self.route_speed_mps * 0.46, 2),
            "holdback_m": 35.0,
            "convoy_lateral_offset_m": round(offset, 1),
            "reason": f"Parent sector {sector} assigned small drones to synthetic vector {vector['id']}",
        }

    def _screening_mission(self, mission: dict[str, object]) -> dict[str, object]:
        if not mission["active"]:
            return self._nominal_mission()
        next_mission = dict(mission)
        next_mission.update(
            {
                "mode": "parent_directed_search",
                "speed_mps": self.route_speed_mps,
                "holdback_m": 0.0,
                "convoy_lateral_offset_m": 0.0,
                "reason": (
                    f"Parent sector {mission['sector']} is directing small-drone search; "
                    "convoy route unchanged until fused detection crosses threshold."
                ),
            }
        )
        return next_mission

    def _route_control_from_sensing(
        self,
        mission: dict[str, object],
        sensing: dict[str, object],
    ) -> dict[str, object]:
        if not mission["active"] or not sensing["route_adaptation"]["recommended"]:
            return self._screening_mission(mission)
        next_mission = dict(mission)
        trigger_ids = sensing["route_adaptation"].get("trigger_target_ids", [])
        next_mission.update(
            {
                "mode": "auto_reroute_defensive_slowdown",
                "reason": (
                    "Parent/child fused detection crossed confidence threshold; "
                    f"auto-reroute armed for {', '.join(trigger_ids) or mission['vector_id']}."
                ),
            }
        )
        return next_mission

    def _nominal_mission(self) -> dict[str, object]:
        return {
            "active": False,
            "mode": "nominal_route_follow",
            "vector_id": None,
            "sector": 0,
            "target": None,
            "speed_mps": self.route_speed_mps,
            "holdback_m": 0.0,
            "convoy_lateral_offset_m": 0.0,
            "reason": "",
        }

    def _route_distance_at(self, t: float, route_length_m: float) -> float:
        return ((t * self.route_speed_mps) + self._route_distance_offset_m) % max(1.0, route_length_m)

    def _edge_support_plan(
        self,
        edges: list[dict[str, object]],
        route_distance_m: float,
        route_length_m: float,
        mission: dict[str, object],
    ) -> dict[str, object]:
        anchors = [self._edge_anchor(edge) for edge in edges if bool(edge.get("approved", True))]
        sector_span = max(260.0, min(950.0, route_length_m / max(1, self.parent_count) * 1.35))
        parent_plans: list[dict[str, object]] = []
        mission_sector = int(mission["sector"])
        mission_distance = self._target_route_distance(mission, route_distance_m)
        for idx in range(self.parent_count):
            sector_offset = (idx - (self.parent_count - 1) / 2.0) * sector_span * 0.62 + 175.0
            sweep = math.sin(route_distance_m * 0.003 + idx * 1.31) * sector_span * 0.2
            desired_distance = (route_distance_m + sector_offset + sweep) % max(1.0, route_length_m)
            if mission["active"] and idx == mission_sector:
                desired_distance = mission_distance
            anchor = self._best_edge_anchor(anchors, desired_distance, route_length_m)
            lateral = (-1.0 if idx % 2 == 0 else 1.0) * (
                90.0 + idx * 18.0 + 18.0 * math.sin(route_distance_m * 0.004 + idx)
            )
            pattern = "route_sector_sweep"
            edge_anchor_id = None
            edge_anchor_point = None
            edge_anchor_distance_m = None
            if anchor is not None:
                edge_anchor_id = anchor["id"]
                edge_anchor_point = anchor["point"]
                edge_anchor_distance_m = round(
                    _route_delta(float(anchor["route_distance_m"]), desired_distance, route_length_m),
                    1,
                )
                if edge_anchor_distance_m <= max(520.0, self.wifi_radius_m * 3.5):
                    desired_distance = (
                        desired_distance * 0.58 + float(anchor["route_distance_m"]) * 0.42
                    ) % max(1.0, route_length_m)
                    pattern = "edge_anchor_sector_sweep"
            parent_plans.append(
                {
                    "parent_id": f"parent_{idx}",
                    "sector_id": f"sector_{idx}",
                    "route_distance_m": desired_distance,
                    "lateral_m": lateral,
                    "pattern": pattern,
                    "edge_anchor_id": edge_anchor_id,
                    "edge_anchor_point": edge_anchor_point,
                    "edge_anchor_distance_m": edge_anchor_distance_m,
                }
            )
        return {"anchors": anchors, "parents": parent_plans}

    def _edge_anchor(self, edge: dict[str, object]) -> dict[str, object]:
        point = _actor_point(edge)
        route_distance, route_offset = self._project_to_route(point)
        return {
            "id": str(edge["id"]),
            "point": point,
            "route_distance_m": route_distance,
            "route_offset_m": route_offset,
            "edge_type": str(edge.get("edge_type", "edge")),
        }

    def _project_to_route(self, point: LatLng) -> tuple[float, float]:
        nearest_idx = min(range(len(self.route_points)), key=lambda idx: haversine_m(point, self.route_points[idx]))
        return self.route_distances[nearest_idx], haversine_m(point, self.route_points[nearest_idx])

    def _best_edge_anchor(
        self,
        anchors: list[dict[str, object]],
        desired_route_distance_m: float,
        route_length_m: float,
    ) -> dict[str, object] | None:
        if not anchors:
            return None
        return min(
            anchors,
            key=lambda anchor: (
                _route_delta(float(anchor["route_distance_m"]), desired_route_distance_m, route_length_m)
                + float(anchor["route_offset_m"]) * 0.35
                - (80.0 if "stationary_edge" in str(anchor["edge_type"]) else 0.0)
            ),
        )

    def _target_route_distance(self, mission: dict[str, object], fallback_m: float) -> float:
        if mission.get("target") is None:
            return fallback_m
        target_distance = float(mission["target"].get("route_distance_m", 0.0))
        return target_distance if target_distance > 0.0 else fallback_m

    def _nearest_parent_id(
        self,
        drone: dict[str, object],
        drones: list[dict[str, object]],
    ) -> str:
        parents = [candidate for candidate in drones if candidate["tier"] == "PARENT"]
        if not parents:
            return ""
        return str(min(parents, key=lambda parent: _actor_distance(drone, parent))["id"])

    def _report_parent_id(
        self,
        drone: dict[str, object],
        drones: list[dict[str, object]],
    ) -> str:
        assigned = str(drone.get("controlled_by") or "")
        if assigned:
            return assigned
        return self._nearest_parent_id(drone, drones)

    def _fusion_parent_for_target(
        self,
        target: dict[str, object],
        reports: list[dict[str, object]],
        parents: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        if not parents:
            raise ValueError("Fusion requires at least one parent drone")
        target_point = LatLng(float(target["lat"]), float(target["lng"]))
        scores: dict[str, float] = {}
        for report in reports:
            parent_id = str(report["observer_id"]) if report["observer_tier"] == "PARENT" else str(report.get("reported_to") or "")
            if parent_id not in parents:
                continue
            parent = parents[parent_id]
            score = float(report["confidence"])
            if parent.get("edge_connected"):
                score += 0.28 + float(parent.get("edge_link_quality", 0.0)) * 0.18
            score += max(0.0, 0.2 - haversine_m(_actor_point(parent), target_point) / 2_500.0)
            scores[parent_id] = scores.get(parent_id, 0.0) + score
        if scores:
            return parents[max(scores, key=scores.get)]
        return min(parents.values(), key=lambda parent: haversine_m(_actor_point(parent), target_point))


def _actor_distance(a: dict[str, object], b: dict[str, object]) -> float:
    return haversine_m(_actor_point(a), _actor_point(b))


def _actor_point(actor: dict[str, object]) -> LatLng:
    geo = actor["geo"]
    return LatLng(float(geo["lat"]), float(geo["lng"]))


def _blend_points(a: LatLng, b: LatLng, amount: float) -> LatLng:
    u = max(0.0, min(1.0, amount))
    return LatLng(
        lat=a.lat + (b.lat - a.lat) * u,
        lng=a.lng + (b.lng - a.lng) * u,
    )


def _limit_from_anchor(anchor: LatLng, point: LatLng, max_distance_m: float) -> LatLng:
    distance = haversine_m(anchor, point)
    if distance <= max_distance_m or distance <= 0.01:
        return point
    return _blend_points(anchor, point, max_distance_m / distance)


def _route_delta(a: float, b: float, route_length_m: float) -> float:
    direct = abs(a - b)
    return min(direct, max(0.0, route_length_m - direct))


def _serializable_edge_plan(edge_plan: dict[str, object]) -> dict[str, object]:
    anchors = []
    for anchor in edge_plan.get("anchors", []):
        anchors.append(
            {
                "id": anchor["id"],
                "point": anchor["point"].to_dict(),
                "route_distance_m": round(float(anchor["route_distance_m"]), 1),
                "route_offset_m": round(float(anchor["route_offset_m"]), 1),
                "edge_type": anchor["edge_type"],
            }
        )
    parents = []
    for parent in edge_plan.get("parents", []):
        parents.append(
            {
                "parent_id": parent["parent_id"],
                "sector_id": parent["sector_id"],
                "route_distance_m": round(float(parent["route_distance_m"]), 1),
                "lateral_m": round(float(parent["lateral_m"]), 1),
                "pattern": parent["pattern"],
                "edge_anchor_id": parent["edge_anchor_id"],
                "edge_anchor_distance_m": parent["edge_anchor_distance_m"],
            }
        )
    return {"anchors": anchors, "parents": parents}


def _relative_lateral_sign(vector: dict[str, object]) -> float:
    start = vector.get("start", {})
    end = vector.get("end", {})
    start_lng = float(start.get("lng", 0.0))
    end_lng = float(end.get("lng", 0.0))
    if start_lng == end_lng:
        return 1.0
    return 1.0 if start_lng > end_lng else -1.0
