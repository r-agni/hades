"""Scenario orchestration for the live real-world visualizer."""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from hades.realworld.geo import (
    LatLng,
    cumulative_distances,
    densify_route,
    haversine_m,
    route_bounds,
)
from hades.realworld.google import GoogleMapsClient, GoogleMapsError, GoogleRoute
from hades.realworld.capabilities import PARENT_CAPABILITY
from hades.realworld.context import (
    DerivedOnlyContextProvider,
    RealWorldContextClient,
    RealWorldContextProvider,
    RouteContext,
    RouteScore,
    score_route,
)
from hades.realworld.optimizer import (
    EdgeAnalysis,
    EdgeRecommendation,
    ManualEdge,
    build_route_samples,
    generate_candidate_points,
    optimize_edges,
)
from hades.realworld.publisher import RealWorldSimPublisher


DEFAULT_ORIGIN = "Maidan Nezalezhnosti, Kyiv, Ukraine"
DEFAULT_DESTINATION = "National Botanical Garden, Kyiv, Ukraine"
DEFAULT_EDGE_COUNT = 6
DEFAULT_WIFI_RADIUS_M = 150.0
DEFAULT_SEARCH_BUFFER_M = 600.0
REALWORLD_PARENT_DRONES = 4
REALWORLD_SMALL_DRONES = 16

EdgeStatus = Literal["pending", "approved", "moved", "rejected"]


@dataclass(frozen=True)
class RerouteProposal:
    id: str
    route_points: list[LatLng]
    distance_m: float
    duration_s: float
    encoded_polyline: str
    risk_score: float
    edge_coverage_score: float
    connectivity_score: float
    sensor_coverage_score: float
    score: float
    route_score: RouteScore
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "points": [point.to_dict() for point in self.route_points],
            "distance_m": round(self.distance_m, 1),
            "duration_s": round(self.duration_s, 1),
            "risk_score": round(self.risk_score, 3),
            "edge_coverage_score": round(self.edge_coverage_score, 3),
            "connectivity_score": round(self.connectivity_score, 3),
            "sensor_coverage_score": round(self.sensor_coverage_score, 3),
            "score": round(self.score, 1),
            "route_score": self.route_score.to_dict(),
            "reasons": list(self.reasons),
        }


@dataclass
class RouteAnalysisBundle:
    route_points: list[LatLng]
    route_sample_points: list[LatLng]
    route_sample_distances: list[float]
    route_distance_m: float
    route_duration_s: float
    encoded_polyline: str
    candidate_points: list[LatLng]
    candidate_elevations: list[Any]
    candidate_roads: list[Any]
    route_samples: list[Any]
    analysis: EdgeAnalysis
    route_context: RouteContext


@dataclass
class RealWorldScenario:
    id: str
    origin_label: str
    destination_label: str
    origin: LatLng
    destination: LatLng
    route_points: list[LatLng]
    route_sample_points: list[LatLng]
    route_sample_distances: list[float]
    route_distance_m: float
    route_duration_s: float
    encoded_polyline: str
    edge_count: int
    wifi_radius_m: float
    search_buffer_m: float
    candidate_points: list[LatLng]
    candidate_elevations: list[Any]
    candidate_roads: list[Any]
    route_samples: list[Any]
    analysis: EdgeAnalysis
    route_context: RouteContext
    publisher: RealWorldSimPublisher
    edge_statuses: dict[str, EdgeStatus] = field(default_factory=dict)
    rejected_zone_ids: set[str] = field(default_factory=set)
    started: bool = False
    reroute_proposals: list[RerouteProposal] = field(default_factory=list)
    applied_reroute_id: str | None = None
    created_at: float = field(default_factory=time.time)

    @property
    def min_required_stationary_edges(self) -> int:
        return max(1, min(3, self.edge_count))

    @property
    def approved_stationary_edge_ids(self) -> set[str]:
        return {
            edge_id
            for edge_id, status in self.edge_statuses.items()
            if status in {"approved", "moved"}
        }

    @property
    def can_start(self) -> bool:
        return len(self.approved_stationary_edge_ids) >= self.min_required_stationary_edges

    def to_dict(self) -> dict[str, object]:
        active_support = _route_edge_support_scores(
            self.route_points,
            _active_stationary_edges(self),
            self.wifi_radius_m,
        )
        route_score = self._route_score(active_support)
        return {
            "scenario_id": self.id,
            "origin": {"label": self.origin_label, **self.origin.to_dict()},
            "destination": {"label": self.destination_label, **self.destination.to_dict()},
            "settings": {
                "edge_count": self.edge_count,
                "wifi_radius_m": self.wifi_radius_m,
                "search_buffer_m": self.search_buffer_m,
                "parent_drones": REALWORLD_PARENT_DRONES,
                "small_drones": REALWORLD_SMALL_DRONES,
                "traffic_layer_available": self.route_context.traffic.available,
            },
            "preflight": {
                "started": self.started,
                "can_start": self.can_start,
                "approved_stationary_edges": len(self.approved_stationary_edge_ids),
                "min_required_stationary_edges": self.min_required_stationary_edges,
                "instructions": "Approve or move recommended stationary edge nodes before starting.",
            },
            "route": {
                "points": [point.to_dict() for point in self.route_points],
                "samples": [point.to_dict() for point in self.route_sample_points],
                "distance_m": round(self.route_distance_m, 1),
                "duration_s": round(self.route_duration_s, 1),
                "encoded_polyline": self.encoded_polyline,
                "bounds": route_bounds(self.route_points),
            },
            "analysis": {
                **self.analysis.to_dict(),
                "edges": self._edge_dicts(),
                "candidate_zones": self._candidate_zone_dicts(),
                "data_sources": self.route_context.data_sources_dict(),
                "live_conditions": self.route_context.to_live_conditions_dict(),
                "route_score": route_score.to_dict(),
                "attack_vectors": self.publisher.attack_vectors,
                "reroute_proposals": [proposal.to_dict() for proposal in self.reroute_proposals],
            },
        }

    def _edge_dicts(self) -> list[dict[str, object]]:
        result: list[dict[str, object]] = []
        total_route = max(1.0, self.analysis.route_length_m)
        for edge in self.analysis.edges:
            status = self.edge_statuses.get(edge.id, "pending")
            payload = edge.to_dict()
            payload.update(
                {
                    "edge_type": "manual_stationary_edge" if edge.manual else "stationary_edge",
                    "status": status,
                    "approved": status in {"approved", "moved"},
                    "covered_route_percent": round(100.0 * edge.coverage_m / total_route, 1),
                    "redundancy_contribution": _redundancy_contribution(edge.id, self.analysis),
                }
            )
            result.append(payload)
        return result

    def _candidate_zone_dicts(self) -> list[dict[str, object]]:
        selected_statuses = dict(self.edge_statuses)
        zones: list[dict[str, object]] = []
        for zone in self.analysis.candidate_zones:
            status = "candidate"
            if zone.id in self.rejected_zone_ids or selected_statuses.get(zone.id) == "rejected":
                status = "rejected"
            elif selected_statuses.get(zone.id) in {"approved", "moved", "pending"}:
                status = selected_statuses[zone.id]
            elif zone.selected:
                status = "pending"
            payload = zone.to_dict()
            payload.update({"status": status, "approved": status in {"approved", "moved"}})
            zones.append(payload)
        return zones

    def _route_score(self, active_support: dict[str, float]) -> RouteScore:
        return score_route(
            route=GoogleRoute(
                points=self.route_points,
                distance_m=self.route_distance_m,
                duration_s=self.route_duration_s,
                encoded_polyline=self.encoded_polyline,
            ),
            context=self.route_context,
            analysis=self.analysis,
            active_edge_support=active_support,
            synthetic_risk_score=_route_risk_score(self.route_points, self.publisher.attack_vectors),
        )


class RealWorldScenarioService:
    def __init__(
        self,
        google_client: GoogleMapsClient,
        context_provider: RealWorldContextProvider | None = None,
    ) -> None:
        self._google = google_client
        if context_provider is None:
            context_provider = (
                RealWorldContextClient()
                if isinstance(google_client, GoogleMapsClient)
                else DerivedOnlyContextProvider()
            )
        self._context = context_provider
        self._scenarios: dict[str, RealWorldScenario] = {}

    def get(self, scenario_id: str) -> RealWorldScenario:
        try:
            return self._scenarios[scenario_id]
        except KeyError as exc:
            raise KeyError(f"Unknown real-world scenario {scenario_id}") from exc

    async def create(
        self,
        *,
        origin: Any = None,
        destination: Any = None,
        edge_count: int = DEFAULT_EDGE_COUNT,
        wifi_radius_m: float = DEFAULT_WIFI_RADIUS_M,
        search_buffer_m: float = DEFAULT_SEARCH_BUFFER_M,
    ) -> RealWorldScenario:
        origin_label, origin_point = await self._resolve_location(origin or DEFAULT_ORIGIN)
        dest_label, dest_point = await self._resolve_location(destination or DEFAULT_DESTINATION)
        route = await self._google.compute_route(origin_point, dest_point)
        bundle = await self._analyze_route(
            route,
            edge_count=edge_count,
            wifi_radius_m=wifi_radius_m,
            search_buffer_m=search_buffer_m,
        )

        scenario_id = f"rw_{uuid.uuid4().hex[:10]}"
        edge_statuses = {edge.id: "pending" for edge in bundle.analysis.edges}
        publisher = RealWorldSimPublisher(
            scenario_id=scenario_id,
            route_points=bundle.route_sample_points,
            analysis=bundle.analysis,
            wifi_radius_m=wifi_radius_m,
            approved_stationary_edge_ids=set(),
            parent_count=REALWORLD_PARENT_DRONES,
            small_count=REALWORLD_SMALL_DRONES,
        )
        scenario = RealWorldScenario(
            id=scenario_id,
            origin_label=origin_label,
            destination_label=dest_label,
            origin=origin_point,
            destination=dest_point,
            edge_count=edge_count,
            wifi_radius_m=wifi_radius_m,
            search_buffer_m=search_buffer_m,
            publisher=publisher,
            edge_statuses=edge_statuses,
            **bundle.__dict__,
        )
        self._scenarios[scenario_id] = scenario
        return scenario

    async def update_edges(
        self,
        scenario_id: str,
        manual_edges: list[ManualEdge],
        *,
        approved_edge_ids: list[str] | None = None,
        rejected_edge_ids: list[str] | None = None,
    ) -> RealWorldScenario:
        scenario = self.get(scenario_id)
        rejected_ids = set(scenario.rejected_zone_ids)
        rejected_ids.update(rejected_edge_ids or [])
        for edge_id in approved_edge_ids or []:
            rejected_ids.discard(edge_id)
        for manual in manual_edges:
            rejected_ids.discard(manual.id)
        analysis = optimize_edges(
            scenario.route_samples,
            scenario.candidate_points,
            scenario.candidate_elevations,
            scenario.candidate_roads,
            edge_count=scenario.edge_count,
            wifi_radius_m=scenario.wifi_radius_m,
            manual_edges=manual_edges,
            rejected_zone_ids=rejected_ids,
        )
        scenario.analysis = analysis
        next_statuses: dict[str, EdgeStatus] = {
            edge.id: scenario.edge_statuses.get(edge.id, "pending")
            for edge in analysis.edges
            if edge.id not in rejected_ids
        }
        for manual in manual_edges:
            if manual.id in next_statuses:
                next_statuses[manual.id] = "moved"
        for edge_id in approved_edge_ids or []:
            if edge_id in next_statuses:
                next_statuses[edge_id] = "approved"
        scenario.edge_statuses = next_statuses
        scenario.rejected_zone_ids = rejected_ids
        self._sync_publisher(scenario)
        return scenario

    def start(self, scenario_id: str) -> RealWorldScenario:
        scenario = self.get(scenario_id)
        if not scenario.can_start:
            raise GoogleMapsError(
                f"Approve at least {scenario.min_required_stationary_edges} stationary edge nodes before starting"
            )
        scenario.started = True
        scenario.publisher.start()
        self._sync_publisher(scenario)
        return scenario

    async def propose_reroutes(self, scenario_id: str) -> RealWorldScenario:
        scenario = self.get(scenario_id)
        live_anchor = scenario.publisher.current_route_anchor() if scenario.started else None
        route_origin = live_anchor["point"] if live_anchor is not None else scenario.origin
        routes = await self._google.compute_routes(route_origin, scenario.destination, alternatives=True)
        proposals: list[RerouteProposal] = []
        current_encoded = None if scenario.started else scenario.encoded_polyline
        active_stationary_edges = _active_stationary_edges(scenario)
        baseline_distance_m = max(1.0, routes[0].distance_m if routes else scenario.route_distance_m)
        baseline_duration_s = max(1.0, routes[0].duration_s if routes else scenario.route_duration_s)
        for idx, route in enumerate(routes):
            if route.encoded_polyline == current_encoded:
                continue
            risk = _route_risk_score(route.points, scenario.publisher.attack_vectors)
            support = _route_edge_support_scores(route.points, active_stationary_edges, scenario.wifi_radius_m)
            route_context = await self._context_for_route(route)
            route_score = score_route(
                route=route,
                context=route_context,
                analysis=scenario.analysis,
                active_edge_support=support,
                synthetic_risk_score=risk,
                baseline_distance_m=baseline_distance_m,
                baseline_duration_s=baseline_duration_s,
            )
            proposals.append(
                RerouteProposal(
                    id=f"reroute_{idx}",
                    route_points=route.points,
                    distance_m=route.distance_m,
                    duration_s=route.duration_s,
                    encoded_polyline=route.encoded_polyline,
                    risk_score=risk,
                    edge_coverage_score=support["edge_coverage_score"],
                    connectivity_score=support["connectivity_score"],
                    sensor_coverage_score=support["sensor_coverage_score"],
                    score=route_score.overall,
                    route_score=route_score,
                    reasons=(
                        route_score.summary,
                        (
                            f"Live reroute starts {live_anchor['route_progress_pct']:.1f}% along the active route"
                            if live_anchor is not None
                            else "Preflight reroute starts at scenario origin"
                        ),
                        f"Distance {route.distance_m:.0f} m",
                        f"Approved edge coverage {support['edge_coverage_score'] * 100.0:.0f}%",
                        f"Parent-edge connectivity {support['connectivity_score'] * 100.0:.0f}%",
                        f"Synthetic scenario exposure {risk:.2f} (demo object only)",
                        "Auto-applies after warning while keeping the live stream running",
                    ),
                )
            )
        scenario.reroute_proposals = sorted(proposals, key=lambda p: p.score, reverse=True)[:3]
        return scenario

    async def apply_reroute(self, scenario_id: str, proposal_id: str) -> RealWorldScenario:
        scenario = self.get(scenario_id)
        proposal = next((p for p in scenario.reroute_proposals if p.id == proposal_id), None)
        if proposal is None:
            raise KeyError(f"Unknown reroute proposal {proposal_id}")
        preserved_edges = _active_stationary_edges(scenario) if scenario.started else []
        bundle = await self._analyze_route(
            GoogleRoute(
                points=proposal.route_points,
                distance_m=proposal.distance_m,
                duration_s=proposal.duration_s,
                encoded_polyline=proposal.encoded_polyline,
            ),
            edge_count=scenario.edge_count,
            wifi_radius_m=scenario.wifi_radius_m,
            search_buffer_m=scenario.search_buffer_m,
            manual_edges=[ManualEdge(id=edge.id, point=edge.point) for edge in preserved_edges],
        )
        for key, value in bundle.__dict__.items():
            setattr(scenario, key, value)
        preserved_ids = {edge.id for edge in preserved_edges}
        scenario.edge_statuses = {
            edge.id: "moved" if edge.id in preserved_ids else "pending"
            for edge in scenario.analysis.edges
        }
        scenario.rejected_zone_ids = set()
        scenario.applied_reroute_id = proposal.id
        scenario.reroute_proposals = []
        scenario.publisher.update_route(
            scenario.route_sample_points,
            scenario.analysis,
            applied_reroute_id=proposal.id if scenario.started else None,
            start_at_route_beginning=scenario.started,
        )
        self._sync_publisher(scenario)
        return scenario

    async def _analyze_route(
        self,
        route: GoogleRoute,
        *,
        edge_count: int,
        wifi_radius_m: float,
        search_buffer_m: float,
        manual_edges: list[ManualEdge] | None = None,
    ) -> RouteAnalysisBundle:
        route_sample_points = densify_route(route.points, spacing_m=75.0, max_points=400)
        route_sample_distances = cumulative_distances(route_sample_points)
        route_elevations = await self._google.elevations(route_sample_points)
        route_samples = build_route_samples(route_sample_points, route_sample_distances, route_elevations)
        candidate_points = generate_candidate_points(
            route_sample_points,
            search_buffer_m=search_buffer_m,
        )
        if not candidate_points:
            raise GoogleMapsError("No edge-placement candidates were generated for this route")
        candidate_elevations = await self._google.elevations(candidate_points)
        candidate_roads = await self._google.nearest_roads(candidate_points)
        analysis = optimize_edges(
            route_samples,
            candidate_points,
            candidate_elevations,
            candidate_roads,
            edge_count=edge_count,
            wifi_radius_m=wifi_radius_m,
            manual_edges=manual_edges,
        )
        route_context = await self._context.analyze(
            route=route,
            route_sample_points=route_sample_points,
            route_elevations=route_elevations,
        )
        return RouteAnalysisBundle(
            route_points=route.points,
            route_sample_points=route_sample_points,
            route_sample_distances=route_sample_distances,
            route_distance_m=route.distance_m or route_sample_distances[-1],
            route_duration_s=route.duration_s,
            encoded_polyline=route.encoded_polyline,
            candidate_points=candidate_points,
            candidate_elevations=candidate_elevations,
            candidate_roads=candidate_roads,
            route_samples=route_samples,
            analysis=analysis,
            route_context=route_context,
        )

    async def _context_for_route(self, route: GoogleRoute) -> RouteContext:
        route_sample_points = densify_route(route.points, spacing_m=95.0, max_points=180)
        route_elevations = await self._google.elevations(route_sample_points)
        return await self._context.analyze(
            route=route,
            route_sample_points=route_sample_points,
            route_elevations=route_elevations,
        )

    async def _resolve_location(self, raw: Any) -> tuple[str, LatLng]:
        if isinstance(raw, str):
            return raw, await self._google.geocode(raw)
        if isinstance(raw, dict):
            if "lat" in raw and "lng" in raw:
                point = LatLng(float(raw["lat"]), float(raw["lng"]))
                return str(raw.get("label") or f"{point.lat:.6f},{point.lng:.6f}"), point
            if "latitude" in raw and "longitude" in raw:
                point = LatLng(float(raw["latitude"]), float(raw["longitude"]))
                return str(raw.get("label") or f"{point.lat:.6f},{point.lng:.6f}"), point
            if "text" in raw:
                label = str(raw["text"])
                return label, await self._google.geocode(label)
        raise GoogleMapsError("Location must be a text query or lat/lng object")

    def _sync_publisher(self, scenario: RealWorldScenario) -> None:
        scenario.publisher.set_analysis(
            scenario.analysis,
            approved_stationary_edge_ids=scenario.approved_stationary_edge_ids,
            edge_statuses=scenario.edge_statuses,
        )


def _redundancy_contribution(edge_id: str, analysis: EdgeAnalysis) -> float:
    edge = next((candidate for candidate in analysis.edges if candidate.id == edge_id), None)
    if edge is None:
        return 0.0
    peers = [candidate for candidate in analysis.edges if candidate.id != edge_id]
    overlap = sum(min(edge.coverage_m, peer.coverage_m) for peer in peers[:4])
    return round(max(0.0, min(1.0, overlap / max(edge.coverage_m * 4.0, 1.0))), 3)


def _active_stationary_edges(scenario: RealWorldScenario) -> list[EdgeRecommendation]:
    approved_ids = scenario.approved_stationary_edge_ids
    return [
        edge
        for edge in scenario.analysis.edges
        if edge.id in approved_ids
    ]


def _route_edge_support_scores(
    route_points: list[LatLng],
    active_edges: list[EdgeRecommendation],
    wifi_radius_m: float,
) -> dict[str, float]:
    if not route_points or not active_edges:
        return {
            "edge_coverage_score": 0.0,
            "connectivity_score": 0.0,
            "sensor_coverage_score": 0.0,
        }
    samples = densify_route(route_points, spacing_m=90.0, max_points=160)
    edge_points = [edge.point for edge in active_edges]
    covered = 0
    sensor_covered = 0
    qualities: list[float] = []
    sensor_radius = PARENT_CAPABILITY.vision_radius_m + wifi_radius_m
    connectivity_radius = max(wifi_radius_m * 3.5, PARENT_CAPABILITY.vision_radius_m)
    for sample in samples:
        nearest = min(haversine_m(sample, edge_point) for edge_point in edge_points)
        if nearest <= wifi_radius_m:
            covered += 1
        if nearest <= sensor_radius:
            sensor_covered += 1
        qualities.append(max(0.0, 1.0 - nearest / connectivity_radius))
    total = max(1, len(samples))
    return {
        "edge_coverage_score": covered / total,
        "connectivity_score": sum(qualities) / total,
        "sensor_coverage_score": sensor_covered / total,
    }


def _route_risk_score(route_points: list[LatLng], attack_vectors: list[dict[str, object]]) -> float:
    if not route_points or not attack_vectors:
        return 0.0
    route_samples = route_points[:: max(1, len(route_points) // 32)] or route_points
    exposure = 0.0
    for vector in attack_vectors:
        end = LatLng(float(vector["end"]["lat"]), float(vector["end"]["lng"]))
        closest = min(haversine_m(point, end) for point in route_samples)
        exposure += max(0.0, 1.0 - closest / 650.0) * float(vector.get("risk", 0.4))
    return max(0.0, min(1.0, exposure / max(1.0, math.sqrt(len(attack_vectors)))))
