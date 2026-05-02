"""Scenario orchestration for the live real-world visualizer."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from hades.realworld.geo import LatLng, cumulative_distances, densify_route, route_bounds
from hades.realworld.google import GoogleMapsClient, GoogleMapsError
from hades.realworld.optimizer import (
    EdgeAnalysis,
    ManualEdge,
    build_route_samples,
    generate_candidate_points,
    optimize_edges,
)
from hades.realworld.publisher import RealWorldSimPublisher


DEFAULT_ORIGIN = "Griffith Observatory, Los Angeles, CA"
DEFAULT_DESTINATION = "Travel Town Museum, Los Angeles, CA"
DEFAULT_EDGE_COUNT = 18
DEFAULT_WIFI_RADIUS_M = 150.0
DEFAULT_SEARCH_BUFFER_M = 600.0


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
    publisher: RealWorldSimPublisher
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.id,
            "origin": {"label": self.origin_label, **self.origin.to_dict()},
            "destination": {"label": self.destination_label, **self.destination.to_dict()},
            "settings": {
                "edge_count": self.edge_count,
                "wifi_radius_m": self.wifi_radius_m,
                "search_buffer_m": self.search_buffer_m,
            },
            "route": {
                "points": [point.to_dict() for point in self.route_points],
                "samples": [point.to_dict() for point in self.route_sample_points],
                "distance_m": round(self.route_distance_m, 1),
                "duration_s": round(self.route_duration_s, 1),
                "encoded_polyline": self.encoded_polyline,
                "bounds": route_bounds(self.route_points),
            },
            "analysis": self.analysis.to_dict(),
        }


class RealWorldScenarioService:
    def __init__(self, google_client: GoogleMapsClient) -> None:
        self._google = google_client
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
        )

        scenario_id = f"rw_{uuid.uuid4().hex[:10]}"
        publisher = RealWorldSimPublisher(
            scenario_id=scenario_id,
            route_points=route_sample_points,
            analysis=analysis,
            wifi_radius_m=wifi_radius_m,
        )
        scenario = RealWorldScenario(
            id=scenario_id,
            origin_label=origin_label,
            destination_label=dest_label,
            origin=origin_point,
            destination=dest_point,
            route_points=route.points,
            route_sample_points=route_sample_points,
            route_sample_distances=route_sample_distances,
            route_distance_m=route.distance_m or route_sample_distances[-1],
            route_duration_s=route.duration_s,
            encoded_polyline=route.encoded_polyline,
            edge_count=edge_count,
            wifi_radius_m=wifi_radius_m,
            search_buffer_m=search_buffer_m,
            candidate_points=candidate_points,
            candidate_elevations=candidate_elevations,
            candidate_roads=candidate_roads,
            route_samples=route_samples,
            analysis=analysis,
            publisher=publisher,
        )
        self._scenarios[scenario_id] = scenario
        return scenario

    async def update_edges(
        self,
        scenario_id: str,
        manual_edges: list[ManualEdge],
    ) -> RealWorldScenario:
        scenario = self.get(scenario_id)
        analysis = optimize_edges(
            scenario.route_samples,
            scenario.candidate_points,
            scenario.candidate_elevations,
            scenario.candidate_roads,
            edge_count=scenario.edge_count,
            wifi_radius_m=scenario.wifi_radius_m,
            manual_edges=manual_edges,
        )
        scenario.analysis = analysis
        scenario.publisher.set_analysis(analysis)
        return scenario

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

