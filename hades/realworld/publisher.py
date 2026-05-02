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
        self.route_speed_mps = route_speed_mps
        self.started_at = time.monotonic()
        self._policy = HeuristicOffloadPolicy()
        self._next_task_t = 2.0
        self._event_log: list[OffloadEvent] = []
        self._search_targets = self._build_search_targets()

    def set_analysis(self, analysis: EdgeAnalysis) -> None:
        self.analysis = analysis

    def now_frame(self) -> dict[str, object]:
        return self.frame_at(time.monotonic() - self.started_at)

    def frame_at(self, t: float) -> dict[str, object]:
        route_length = self.route_distances[-1]
        distance = (t * self.route_speed_mps) % max(1.0, route_length)
        lead_point, heading = sample_route(self.route_points, self.route_distances, distance)
        trail_point, trail_heading = sample_route(
            self.route_points,
            self.route_distances,
            max(0.0, distance - 18.0),
        )
        convoy = [
            self._convoy_actor("convoy_0", lead_point, heading, distance / route_length * 100.0),
            self._convoy_actor("convoy_1", trail_point, trail_heading, max(0.0, distance - 18.0) / route_length * 100.0),
        ]
        drones = self._drones(lead_point, heading, t)
        edges = self._edges(t)
        links = self._links(drones, edges)
        self._apply_connectivity_rules(drones, links)
        sensing = self._sensing_state(drones, links)
        new_events = self._events(t, drones, edges, links)

        active_pairs = {(event.parent_id, event.chosen_target) for event in new_events}
        for link in links:
            if (link["from_id"], link["to_id"]) in active_pairs or (link["to_id"], link["from_id"]) in active_pairs:
                link["active_payload"] = True

        alerts = []
        if self.analysis.coverage_percent < 95.0:
            alerts.append(f"COVERAGE {self.analysis.coverage_percent:.1f}%")

        return {
            "t": round(t, 3),
            "drones": drones,
            "edges": edges,
            "convoy": convoy,
            "links": links,
            "events": [asdict(event) for event in self._event_log],
            "scenario_phase": "realworld_route_analysis",
            "alerts": alerts,
            "threats": [],
            "environment": "google_maps_realworld",
            "sensing": sensing,
            "geo": {
                "scenario_id": self.scenario_id,
                "route_distance_m": round(route_length, 1),
                "coverage_percent": round(self.analysis.coverage_percent, 1),
                "coverage_gaps": [
                    {"start": start.to_dict(), "end": end.to_dict()}
                    for start, end in self.analysis.coverage_gaps
                ],
                "search_targets": self._search_targets,
            },
        }

    def _convoy_actor(
        self,
        actor_id: str,
        point: LatLng,
        heading: float,
        progress_pct: float,
    ) -> dict[str, object]:
        pose = self._pose(point, z=0.8, heading=heading)
        return {
            "id": actor_id,
            "pose": asdict(pose),
            "geo": point.to_dict(),
            "speed_mps": self.route_speed_mps,
            "route_progress_pct": max(0.0, min(100.0, progress_pct)),
        }

    def _drones(self, lead: LatLng, heading: float, t: float) -> list[dict[str, object]]:
        parent_specs = [
            ("parent_0", 48.0, -34.0, "forward_scout"),
            ("parent_1", -38.0, 36.0, "rear_overwatch"),
        ]
        drones: list[dict[str, object]] = []
        for idx, (drone_id, along, lateral, task) in enumerate(parent_specs):
            point = self._offset_from_heading(lead, heading, along, lateral)
            pose = self._pose(
                point,
                z=config.SCENE.parent_hover_altitude_m + 0.8 * math.sin(t * 0.8 + idx),
                heading=heading,
            )
            drones.append(
                {
                    "id": drone_id,
                    "tier": "PARENT",
                    "pose": asdict(pose),
                    "geo": point.to_dict(),
                    "battery_pct": round(config.COMPUTE.parent_default_battery_pct - 0.002 * t, 2),
                    "compute_load": round(0.55 + 0.16 * math.sin(t * 0.35 + idx), 3),
                    "current_task": task,
                    "capabilities": {
                        "vision_radius_m": PARENT_CAPABILITY.vision_radius_m,
                        "compute_tops": PARENT_CAPABILITY.compute_tops,
                        "onboard_functions": list(PARENT_CAPABILITY.onboard_functions),
                        "edge_required_functions": list(PARENT_CAPABILITY.edge_required_functions),
                    },
                }
            )

        small_specs = [
            ("left_flank", 10.0, 46.0),
            ("right_flank", 12.0, -46.0),
            ("forward_scout", 68.0, 8.0),
            ("rear_guard", -55.0, -8.0),
            ("high_scan", 34.0, 31.0),
            ("reserve", -18.0, 31.0),
        ]
        for idx in range(config.COUNTS.small_drones):
            task, along, lateral = small_specs[idx % len(small_specs)]
            along += 5.0 * math.sin(t / 4.0 + idx)
            lateral += 7.0 * math.sin(t / 6.0 + idx * 0.7)
            point = self._offset_from_heading(lead, heading, along, lateral)
            pose = self._pose(
                point,
                z=config.SCENE.small_hover_altitude_m + 1.2 * math.sin(t * 0.9 + idx),
                heading=heading,
            )
            drones.append(
                {
                    "id": f"small_{idx}",
                    "tier": "SMALL",
                    "pose": asdict(pose),
                    "geo": point.to_dict(),
                    "battery_pct": round(config.COMPUTE.small_default_battery_pct - 0.004 * t, 2),
                    "compute_load": round(0.05 + 0.03 * math.sin(t * 0.7 + idx), 3),
                    "current_task": task,
                    "capabilities": {
                        "vision_radius_m": SMALL_CAPABILITY.vision_radius_m,
                        "compute_tops": SMALL_CAPABILITY.compute_tops,
                        "onboard_functions": list(SMALL_CAPABILITY.onboard_functions),
                        "edge_required_functions": list(SMALL_CAPABILITY.edge_required_functions),
                    },
                }
            )
        return drones

    def _edges(self, t: float) -> list[dict[str, object]]:
        edges: list[dict[str, object]] = []
        for idx, edge in enumerate(self.analysis.edges):
            pose = self._pose(edge.point, z=max(1.2, edge.elevation_m), heading=0.0)
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

        for small in smalls:
            parent = min(parents, key=lambda p: _actor_distance(small, p))
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
    ) -> None:
        edge_connected = {
            str(link["from_id"])
            for link in links
            if link["type"] == "WIFI_MESH" and str(link["to_id"]).startswith("edge_")
        }
        edge_connected.update(
            str(link["to_id"])
            for link in links
            if link["type"] == "WIFI_MESH" and str(link["from_id"]).startswith("edge_")
        )
        small_lora = {
            str(link["from_id"]): True
            for link in links
            if link["type"] == "LORA" and str(link["from_id"]).startswith("small_")
        }
        for drone in drones:
            caps = drone["capabilities"]
            onboard = list(caps["onboard_functions"])
            edge_required = list(caps["edge_required_functions"])
            if drone["tier"] == "PARENT":
                has_edge = drone["id"] in edge_connected
                drone["compute_mode"] = "edge_augmented" if has_edge else "onboard_parent"
                drone["available_functions"] = onboard + (edge_required if has_edge else [])
            else:
                drone["compute_mode"] = "small_onboard_report_only"
                drone["available_functions"] = onboard
                drone["parent_link_available"] = bool(small_lora.get(str(drone["id"]), False))

    def _sensing_state(
        self,
        drones: list[dict[str, object]],
        links: list[dict[str, object]],
    ) -> dict[str, object]:
        link_quality = {(str(link["from_id"]), str(link["to_id"])): float(link["quality"]) for link in links}
        detections: list[dict[str, object]] = []
        reports_by_target: dict[str, list[dict[str, object]]] = {}

        for drone in drones:
            radius = float(drone["capabilities"]["vision_radius_m"])
            visible: list[str] = []
            for target in self._search_targets:
                distance = haversine_m(_actor_point(drone), LatLng(float(target["lat"]), float(target["lng"])))
                if distance > radius:
                    continue
                visible.append(str(target["id"]))
                confidence = max(0.15, min(0.98, 1.0 - distance / radius))
                detection = {
                    "target_id": target["id"],
                    "observer_id": drone["id"],
                    "observer_tier": drone["tier"],
                    "distance_m": round(distance, 1),
                    "confidence": round(confidence, 3),
                    "reported_to": None,
                    "classification": "coarse_contact",
                }
                if drone["tier"] == "SMALL":
                    parent_id = self._nearest_parent_id(drone, drones)
                    quality = max(
                        link_quality.get((str(drone["id"]), parent_id), 0.0),
                        link_quality.get((parent_id, str(drone["id"])), 0.0),
                    )
                    if quality > 0.0:
                        detection["reported_to"] = parent_id
                        detection["uplink_quality"] = round(quality, 3)
                        reports_by_target.setdefault(str(target["id"]), []).append(detection)
                else:
                    reports_by_target.setdefault(str(target["id"]), []).append(detection)
                detections.append(detection)
            drone["visible_target_ids"] = visible

        fused = []
        parents = [drone for drone in drones if drone["tier"] == "PARENT"]
        for target in self._search_targets:
            reports = reports_by_target.get(str(target["id"]), [])
            if not reports:
                continue
            best_parent = min(parents, key=lambda parent: haversine_m(_actor_point(parent), LatLng(float(target["lat"]), float(target["lng"]))))
            mode = best_parent.get("compute_mode", "onboard_parent")
            required = "high_resolution_classification"
            status = "classified" if required in best_parent.get("available_functions", []) else "tracked_pending_edge"
            fused.append(
                {
                    "target_id": target["id"],
                    "fusion_parent_id": best_parent["id"],
                    "report_count": len(reports),
                    "compute_mode": mode,
                    "status": status,
                    "confidence": round(min(0.99, 0.45 + 0.18 * len(reports)), 3),
                }
            )

        return {
            "targets": self._search_targets,
            "detections": detections,
            "fused_tracks": fused,
            "rules": {
                "small_drone": "circular FoV, coarse detection only, must uplink to parent over LoRa",
                "parent_drone": "larger circular FoV, local fusion/classification, edge-augmented functions only while connected to an edge",
                "edge_node": "adds high-resolution classification, multi-sensor fusion, coverage replanning, and terrain cost updates over Wi-Fi mesh",
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

    def _build_search_targets(self) -> list[dict[str, object]]:
        route_length = self.route_distances[-1]
        fractions = (0.26, 0.52, 0.78)
        lateral_offsets = (70.0, -85.0, 60.0)
        targets: list[dict[str, object]] = []
        for idx, (frac, lateral) in enumerate(zip(fractions, lateral_offsets)):
            route_point, heading = sample_route(self.route_points, self.route_distances, route_length * frac)
            point = self._offset_from_heading(route_point, heading, 0.0, lateral)
            targets.append(
                {
                    "id": f"search_target_{idx}",
                    "lat": point.lat,
                    "lng": point.lng,
                    "type": "route_search_contact",
                    "route_distance_m": round(route_length * frac, 1),
                }
            )
        return targets

    def _nearest_parent_id(
        self,
        drone: dict[str, object],
        drones: list[dict[str, object]],
    ) -> str:
        parents = [candidate for candidate in drones if candidate["tier"] == "PARENT"]
        if not parents:
            return ""
        return str(min(parents, key=lambda parent: _actor_distance(drone, parent))["id"])


def _actor_distance(a: dict[str, object], b: dict[str, object]) -> float:
    return haversine_m(_actor_point(a), _actor_point(b))


def _actor_point(actor: dict[str, object]) -> LatLng:
    geo = actor["geo"]
    return LatLng(float(geo["lat"]), float(geo["lng"]))
