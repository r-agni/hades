"""Contextual planning signals for the real-world visualizer.

The data in this module is deliberately environmental and civic-infrastructure
oriented. It avoids operational threat intelligence and treats public data
sources as optional enrichments over the Google route/elevation baseline.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx

from hades.realworld.geo import LatLng, haversine_m, route_bounds
from hades.realworld.google import ElevationSample, GoogleRoute
from hades.realworld.optimizer import EdgeAnalysis


SourceState = Literal["available", "partial", "unavailable", "derived"]


@dataclass(frozen=True)
class DataSource:
    key: str
    label: str
    state: SourceState
    summary: str
    details: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "state": self.state,
            "summary": self.summary,
            "details": self.details,
        }


@dataclass(frozen=True)
class TerrainSegment:
    start: LatLng
    end: LatLng
    slope_pct: float
    severity: str

    def to_dict(self) -> dict[str, object]:
        return {
            "start": self.start.to_dict(),
            "end": self.end.to_dict(),
            "slope_pct": round(self.slope_pct, 2),
            "severity": self.severity,
        }


@dataclass(frozen=True)
class TerrainSummary:
    avg_slope_pct: float
    max_slope_pct: float
    elevation_gain_m: float
    elevation_loss_m: float
    segments: tuple[TerrainSegment, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "avg_slope_pct": round(self.avg_slope_pct, 2),
            "max_slope_pct": round(self.max_slope_pct, 2),
            "elevation_gain_m": round(self.elevation_gain_m, 1),
            "elevation_loss_m": round(self.elevation_loss_m, 1),
            "segments": [segment.to_dict() for segment in self.segments],
        }


@dataclass(frozen=True)
class WeatherSummary:
    available: bool
    temperature_c: float | None = None
    precipitation_mm: float | None = None
    wind_speed_kmh: float | None = None
    wind_gusts_kmh: float | None = None
    cloud_cover_pct: float | None = None
    weather_code: int | None = None
    observation_time: str | None = None
    summary: str = "Weather source unavailable"

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "temperature_c": None if self.temperature_c is None else round(self.temperature_c, 1),
            "precipitation_mm": None if self.precipitation_mm is None else round(self.precipitation_mm, 2),
            "wind_speed_kmh": None if self.wind_speed_kmh is None else round(self.wind_speed_kmh, 1),
            "wind_gusts_kmh": None if self.wind_gusts_kmh is None else round(self.wind_gusts_kmh, 1),
            "cloud_cover_pct": None if self.cloud_cover_pct is None else round(self.cloud_cover_pct, 1),
            "weather_code": self.weather_code,
            "observation_time": self.observation_time,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class RoadContextSummary:
    available: bool
    dominant_classes: dict[str, int] = field(default_factory=dict)
    intersection_count: int = 0
    intersections_per_km: float = 0.0
    deployable_hint_count: int = 0
    access_notes: tuple[str, ...] = ()
    summary: str = "Open map context unavailable"

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "dominant_classes": self.dominant_classes,
            "intersection_count": self.intersection_count,
            "intersections_per_km": round(self.intersections_per_km, 2),
            "deployable_hint_count": self.deployable_hint_count,
            "access_notes": list(self.access_notes),
            "summary": self.summary,
        }


@dataclass(frozen=True)
class TrafficSummary:
    available: bool
    static_duration_s: float | None
    traffic_duration_s: float | None
    delay_ratio: float | None
    speed_interval_count: int
    summary: str

    def to_dict(self) -> dict[str, object]:
        return {
            "available": self.available,
            "static_duration_s": None if self.static_duration_s is None else round(self.static_duration_s, 1),
            "traffic_duration_s": None if self.traffic_duration_s is None else round(self.traffic_duration_s, 1),
            "delay_ratio": None if self.delay_ratio is None else round(self.delay_ratio, 3),
            "speed_interval_count": self.speed_interval_count,
            "summary": self.summary,
        }


@dataclass(frozen=True)
class RouteContext:
    data_sources: tuple[DataSource, ...]
    terrain: TerrainSummary
    weather: WeatherSummary
    road_context: RoadContextSummary
    traffic: TrafficSummary

    def to_live_conditions_dict(self) -> dict[str, object]:
        return {
            "terrain": self.terrain.to_dict(),
            "weather": self.weather.to_dict(),
            "road_context": self.road_context.to_dict(),
            "traffic": self.traffic.to_dict(),
        }

    def data_sources_dict(self) -> list[dict[str, object]]:
        return [source.to_dict() for source in self.data_sources]


@dataclass(frozen=True)
class ScoreFactor:
    key: str
    label: str
    score: float
    weight: float
    status: SourceState
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "label": self.label,
            "score": round(max(0.0, min(1.0, self.score)), 3),
            "weight": round(self.weight, 3),
            "status": self.status,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class RouteScore:
    overall: float
    grade: str
    summary: str
    factors: tuple[ScoreFactor, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "overall": round(self.overall, 1),
            "grade": self.grade,
            "summary": self.summary,
            "factors": [factor.to_dict() for factor in self.factors],
            "factor_scores": {
                factor.key: round(max(0.0, min(1.0, factor.score)), 3)
                for factor in self.factors
            },
        }


class RealWorldContextProvider(Protocol):
    async def analyze(
        self,
        *,
        route: GoogleRoute,
        route_sample_points: list[LatLng],
        route_elevations: list[ElevationSample],
    ) -> RouteContext:
        ...


class RealWorldContextClient:
    def __init__(
        self,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_s: float = 5.0,
        enable_public_sources: bool | None = None,
    ) -> None:
        if enable_public_sources is None:
            enable_public_sources = os.getenv("HADES_REALWORLD_PUBLIC_CONTEXT", "1") != "0"
        self._client = http_client
        self._timeout_s = timeout_s
        self._enable_public_sources = enable_public_sources

    async def analyze(
        self,
        *,
        route: GoogleRoute,
        route_sample_points: list[LatLng],
        route_elevations: list[ElevationSample],
    ) -> RouteContext:
        terrain = summarize_terrain(route_sample_points, route_elevations)
        traffic = summarize_traffic(route)
        weather = WeatherSummary(available=False)
        road_context = RoadContextSummary(available=False)
        weather_source = DataSource(
            key="open_meteo",
            label="Open-Meteo Weather",
            state="unavailable",
            summary="Public weather source disabled or unavailable",
        )
        osm_source = DataSource(
            key="openstreetmap_overpass",
            label="OpenStreetMap / Overpass",
            state="unavailable",
            summary="Public map context disabled or unavailable",
        )

        if self._enable_public_sources:
            weather, weather_source = await self._fetch_weather(route_sample_points)
            road_context, osm_source = await self._fetch_osm_context(route_sample_points)

        sources = (
            DataSource(
                key="google_routes",
                label="Google Routes",
                state="available",
                summary="Driving route geometry and travel time returned by Google Routes",
                details={
                    "distance_m": round(route.distance_m, 1),
                    "duration_s": round(route.duration_s, 1),
                },
            ),
            DataSource(
                key="google_elevation",
                label="Google Elevation",
                state="derived",
                summary="Terrain and slope derived from sampled route elevations",
                details={
                    "sample_count": len(route_elevations),
                    "max_slope_pct": round(terrain.max_slope_pct, 2),
                },
            ),
            DataSource(
                key="google_traffic",
                label="Google Traffic",
                state="available" if traffic.available else "unavailable",
                summary=traffic.summary,
                details=traffic.to_dict(),
            ),
            weather_source,
            osm_source,
        )
        return RouteContext(
            data_sources=sources,
            terrain=terrain,
            weather=weather,
            road_context=road_context,
            traffic=traffic,
        )

    async def _fetch_weather(self, route_points: list[LatLng]) -> tuple[WeatherSummary, DataSource]:
        if not route_points:
            weather = WeatherSummary(available=False, summary="No route center available for weather lookup")
            return weather, _source_unavailable("open_meteo", "Open-Meteo Weather", weather.summary)
        center = _route_center(route_points)
        params = {
            "latitude": f"{center.lat:.6f}",
            "longitude": f"{center.lng:.6f}",
            "current": ",".join(
                [
                    "temperature_2m",
                    "relative_humidity_2m",
                    "precipitation",
                    "rain",
                    "showers",
                    "snowfall",
                    "weather_code",
                    "cloud_cover",
                    "wind_speed_10m",
                    "wind_direction_10m",
                    "wind_gusts_10m",
                ]
            ),
            "wind_speed_unit": "kmh",
            "timezone": "auto",
        }
        try:
            data = await self._get_json("https://api.open-meteo.com/v1/forecast", params=params)
            current = data.get("current") if isinstance(data, dict) else None
            if not isinstance(current, dict):
                raise ValueError("missing current weather block")
            precipitation = _float_or_none(current.get("precipitation"))
            wind = _float_or_none(current.get("wind_speed_10m"))
            gusts = _float_or_none(current.get("wind_gusts_10m"))
            clouds = _float_or_none(current.get("cloud_cover"))
            summary = _weather_summary(precipitation, wind, gusts, clouds)
            weather = WeatherSummary(
                available=True,
                temperature_c=_float_or_none(current.get("temperature_2m")),
                precipitation_mm=precipitation,
                wind_speed_kmh=wind,
                wind_gusts_kmh=gusts,
                cloud_cover_pct=clouds,
                weather_code=int(current["weather_code"]) if current.get("weather_code") is not None else None,
                observation_time=str(current.get("time")) if current.get("time") else None,
                summary=summary,
            )
            return weather, DataSource(
                key="open_meteo",
                label="Open-Meteo Weather",
                state="available",
                summary=summary,
                details=weather.to_dict(),
            )
        except Exception as exc:  # pragma: no cover - exercised with injected failing providers
            summary = f"Open-Meteo unavailable: {exc}"
            weather = WeatherSummary(available=False, summary=summary)
            return weather, _source_unavailable("open_meteo", "Open-Meteo Weather", summary)

    async def _fetch_osm_context(
        self,
        route_points: list[LatLng],
    ) -> tuple[RoadContextSummary, DataSource]:
        if not route_points:
            road = RoadContextSummary(available=False, summary="No route bounds available for map context")
            return road, _source_unavailable("openstreetmap_overpass", "OpenStreetMap / Overpass", road.summary)
        bounds = _bounded_route_box(route_points)
        query = f"""
[out:json][timeout:6];
(
  way["highway"]({bounds['south']:.6f},{bounds['west']:.6f},{bounds['north']:.6f},{bounds['east']:.6f});
  node["highway"="traffic_signals"]({bounds['south']:.6f},{bounds['west']:.6f},{bounds['north']:.6f},{bounds['east']:.6f});
  node["amenity"~"^(parking|fuel|charging_station|bus_station)$"]({bounds['south']:.6f},{bounds['west']:.6f},{bounds['north']:.6f},{bounds['east']:.6f});
  way["amenity"~"^(parking|fuel|charging_station|bus_station)$"]({bounds['south']:.6f},{bounds['west']:.6f},{bounds['north']:.6f},{bounds['east']:.6f});
);
out tags center geom 80;
"""
        try:
            data = await self._get_json("https://overpass-api.de/api/interpreter", params={"data": query})
            elements = data.get("elements") if isinstance(data, dict) else None
            if not isinstance(elements, list):
                raise ValueError("missing Overpass elements")
            road = _summarize_osm_elements(elements, route_points)
            return road, DataSource(
                key="openstreetmap_overpass",
                label="OpenStreetMap / Overpass",
                state="available" if road.available else "partial",
                summary=road.summary,
                details=road.to_dict(),
            )
        except Exception as exc:  # pragma: no cover - exercised with injected failing providers
            summary = f"OpenStreetMap context unavailable: {exc}"
            road = RoadContextSummary(available=False, summary=summary)
            return road, _source_unavailable("openstreetmap_overpass", "OpenStreetMap / Overpass", summary)

    async def _get_json(self, url: str, *, params: dict[str, str]) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.get(url, params=params, timeout=self._timeout_s)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {}


class DerivedOnlyContextProvider:
    async def analyze(
        self,
        *,
        route: GoogleRoute,
        route_sample_points: list[LatLng],
        route_elevations: list[ElevationSample],
    ) -> RouteContext:
        terrain = summarize_terrain(route_sample_points, route_elevations)
        traffic = summarize_traffic(route)
        return RouteContext(
            data_sources=(
                DataSource(
                    key="google_routes",
                    label="Google Routes",
                    state="available",
                    summary="Driving route geometry and travel time returned by Google Routes",
                    details={"distance_m": round(route.distance_m, 1), "duration_s": round(route.duration_s, 1)},
                ),
                DataSource(
                    key="google_elevation",
                    label="Google Elevation",
                    state="derived",
                    summary="Terrain and slope derived from sampled route elevations",
                    details={"sample_count": len(route_elevations), "max_slope_pct": round(terrain.max_slope_pct, 2)},
                ),
                DataSource(
                    key="google_traffic",
                    label="Google Traffic",
                    state="available" if traffic.available else "unavailable",
                    summary=traffic.summary,
                    details=traffic.to_dict(),
                ),
                _source_unavailable("open_meteo", "Open-Meteo Weather", "Public weather source not used in this context"),
                _source_unavailable(
                    "openstreetmap_overpass",
                    "OpenStreetMap / Overpass",
                    "Public map context not used in this context",
                ),
            ),
            terrain=terrain,
            weather=WeatherSummary(available=False, summary="Public weather source not used in this context"),
            road_context=RoadContextSummary(
                available=False,
                summary="Public map context not used in this context",
            ),
            traffic=traffic,
        )


def summarize_terrain(
    route_points: list[LatLng],
    route_elevations: list[ElevationSample],
) -> TerrainSummary:
    if len(route_points) < 2 or len(route_elevations) < 2:
        return TerrainSummary(0.0, 0.0, 0.0, 0.0, tuple())

    segments: list[TerrainSegment] = []
    total_weighted_slope = 0.0
    total_distance = 0.0
    max_slope = 0.0
    gain = 0.0
    loss = 0.0
    for idx in range(1, min(len(route_points), len(route_elevations))):
        a = route_points[idx - 1]
        b = route_points[idx]
        dist = max(1.0, haversine_m(a, b))
        elev_delta = route_elevations[idx].elevation_m - route_elevations[idx - 1].elevation_m
        slope = abs(elev_delta) / dist * 100.0
        severity = "steep" if slope >= 8.0 else ("moderate" if slope >= 4.0 else "low")
        segments.append(TerrainSegment(start=a, end=b, slope_pct=slope, severity=severity))
        total_weighted_slope += slope * dist
        total_distance += dist
        max_slope = max(max_slope, slope)
        if elev_delta >= 0:
            gain += elev_delta
        else:
            loss += abs(elev_delta)

    return TerrainSummary(
        avg_slope_pct=total_weighted_slope / max(1.0, total_distance),
        max_slope_pct=max_slope,
        elevation_gain_m=gain,
        elevation_loss_m=loss,
        segments=tuple(_thin_segments(segments, limit=80)),
    )


def summarize_traffic(route: GoogleRoute) -> TrafficSummary:
    static_duration = route.static_duration_s
    intervals = tuple(route.speed_reading_intervals or ())
    if static_duration and route.duration_s:
        delay_ratio = max(0.0, route.duration_s / max(1.0, static_duration) - 1.0)
        return TrafficSummary(
            available=True,
            static_duration_s=static_duration,
            traffic_duration_s=route.duration_s,
            delay_ratio=delay_ratio,
            speed_interval_count=len(intervals),
            summary=f"Traffic-aware duration adds {delay_ratio * 100.0:.0f}% over static travel time",
        )
    if intervals:
        return TrafficSummary(
            available=True,
            static_duration_s=static_duration,
            traffic_duration_s=route.duration_s or None,
            delay_ratio=None,
            speed_interval_count=len(intervals),
            summary=f"Traffic speed intervals returned for {len(intervals)} route sections",
        )
    return TrafficSummary(
        available=False,
        static_duration_s=static_duration,
        traffic_duration_s=route.duration_s or None,
        delay_ratio=None,
        speed_interval_count=0,
        summary="Traffic details not returned for this route",
    )


def score_route(
    *,
    route: GoogleRoute,
    context: RouteContext,
    analysis: EdgeAnalysis,
    active_edge_support: dict[str, float],
    synthetic_risk_score: float,
    baseline_distance_m: float | None = None,
    baseline_duration_s: float | None = None,
) -> RouteScore:
    factors: list[ScoreFactor] = []
    distance_ratio = route.distance_m / max(1.0, baseline_distance_m or route.distance_m or 1.0)
    duration_ratio = route.duration_s / max(1.0, baseline_duration_s or route.duration_s or 1.0)
    distance_time_score = max(0.0, min(1.0, 1.18 - (distance_ratio * 0.55 + duration_ratio * 0.45 - 1.0)))
    factors.append(
        ScoreFactor(
            "distance_time",
            "Distance / Time",
            distance_time_score,
            1.25,
            "available",
            f"{route.distance_m:.0f} m, {route.duration_s / 60.0:.1f} min",
        )
    )

    terrain_score = max(0.0, min(1.0, 1.0 - context.terrain.max_slope_pct / 14.0))
    factors.append(
        ScoreFactor(
            "terrain_slope",
            "Terrain / Slope",
            terrain_score,
            1.0,
            "derived",
            f"Max slope {context.terrain.max_slope_pct:.1f}%, gain {context.terrain.elevation_gain_m:.0f} m",
        )
    )

    if context.traffic.available:
        delay = context.traffic.delay_ratio if context.traffic.delay_ratio is not None else 0.08
        factors.append(
            ScoreFactor(
                "traffic",
                "Traffic",
                max(0.0, min(1.0, 1.0 - delay * 2.4)),
                0.75,
                "available",
                context.traffic.summary,
            )
        )

    if context.weather.available:
        factors.append(
            ScoreFactor(
                "weather_visibility",
                "Weather / Visibility",
                _weather_score(context.weather),
                0.8,
                "available",
                context.weather.summary,
            )
        )

    if context.road_context.available:
        factors.append(
            ScoreFactor(
                "road_accessibility",
                "Road Accessibility",
                _road_accessibility_score(context.road_context),
                0.85,
                "available",
                context.road_context.summary,
            )
        )
        factors.append(
            ScoreFactor(
                "route_complexity",
                "Route Complexity",
                max(0.0, min(1.0, 1.0 - context.road_context.intersections_per_km / 22.0)),
                0.55,
                "available",
                f"{context.road_context.intersections_per_km:.1f} intersections/km from open map context",
            )
        )

    edge_coverage = float(active_edge_support.get("edge_coverage_score", 0.0))
    connectivity = float(active_edge_support.get("connectivity_score", 0.0))
    factors.append(
        ScoreFactor(
            "edge_connectivity",
            "Approved Edge Support",
            max(0.0, min(1.0, edge_coverage * 0.7 + connectivity * 0.3)),
            1.1,
            "derived",
            f"Approved edge coverage {edge_coverage * 100.0:.0f}%, connectivity {connectivity * 100.0:.0f}%",
        )
    )

    feasible_zones = [zone for zone in analysis.candidate_zones if zone.deployability_class != "low"]
    deployability_score = sum(zone.feasibility_score for zone in feasible_zones[:8]) / max(1, min(8, len(feasible_zones)))
    factors.append(
        ScoreFactor(
            "stationary_deployability",
            "Stationary Deployability",
            deployability_score,
            0.75,
            "derived",
            f"{len(feasible_zones)} feasible sparse candidate zones",
        )
    )

    factors.append(
        ScoreFactor(
            "coverage_gaps",
            "Coverage Gaps",
            edge_coverage,
            0.65,
            "derived",
            "Pending/rejected edge sites are excluded from active coverage scoring",
        )
    )

    factors.append(
        ScoreFactor(
            "synthetic_scenario_exposure",
            "Synthetic Scenario Exposure",
            max(0.0, min(1.0, 1.0 - synthetic_risk_score)),
            0.45,
            "derived",
            "Synthetic demo vector exposure only; not live threat intelligence",
        )
    )

    total_weight = sum(factor.weight for factor in factors)
    overall = 100.0 * sum(max(0.0, min(1.0, factor.score)) * factor.weight for factor in factors) / max(1.0, total_weight)
    grade = "strong" if overall >= 78.0 else ("watch" if overall >= 58.0 else "constrained")
    weak = sorted(factors, key=lambda factor: factor.score)[:2]
    summary = "Plan constrained by " + ", ".join(factor.label.lower() for factor in weak)
    if grade == "strong":
        summary = "Route plan has strong environmental and edge-support posture"
    return RouteScore(overall=overall, grade=grade, summary=summary, factors=tuple(factors))


def _source_unavailable(key: str, label: str, summary: str) -> DataSource:
    return DataSource(key=key, label=label, state="unavailable", summary=summary)


def _route_center(points: list[LatLng]) -> LatLng:
    return LatLng(
        sum(point.lat for point in points) / len(points),
        sum(point.lng for point in points) / len(points),
    )


def _bounded_route_box(points: list[LatLng]) -> dict[str, float]:
    bounds = route_bounds(points)
    lat_pad = 0.006
    lng_pad = 0.008
    return {
        "south": max(-90.0, bounds["south"] - lat_pad),
        "west": max(-180.0, bounds["west"] - lng_pad),
        "north": min(90.0, bounds["north"] + lat_pad),
        "east": min(180.0, bounds["east"] + lng_pad),
    }


def _weather_summary(
    precipitation_mm: float | None,
    wind_speed_kmh: float | None,
    wind_gusts_kmh: float | None,
    cloud_cover_pct: float | None,
) -> str:
    parts = []
    if precipitation_mm is not None:
        parts.append(f"{precipitation_mm:.1f} mm precipitation")
    if wind_speed_kmh is not None:
        parts.append(f"{wind_speed_kmh:.0f} km/h wind")
    if wind_gusts_kmh is not None and wind_gusts_kmh >= 35.0:
        parts.append(f"{wind_gusts_kmh:.0f} km/h gusts")
    if cloud_cover_pct is not None:
        parts.append(f"{cloud_cover_pct:.0f}% cloud")
    return ", ".join(parts) if parts else "Current weather conditions returned"


def _summarize_osm_elements(elements: list[object], route_points: list[LatLng]) -> RoadContextSummary:
    road_classes: dict[str, int] = {}
    node_refs: dict[tuple[float, float], int] = {}
    deployable_hint_count = 0
    access_notes: set[str] = set()
    route_km = max(0.1, _route_length(route_points) / 1000.0)

    for raw in elements:
        if not isinstance(raw, dict):
            continue
        tags = raw.get("tags")
        if not isinstance(tags, dict):
            tags = {}
        if "military" in tags or tags.get("landuse") == "military":
            continue
        highway = str(tags.get("highway") or "")
        if highway:
            road_classes[highway] = road_classes.get(highway, 0) + 1
            if tags.get("access") in {"private", "no", "permissive"}:
                access_notes.add(f"access={tags.get('access')}")
            if tags.get("surface"):
                access_notes.add(f"surface={tags.get('surface')}")
            geometry = raw.get("geometry")
            if isinstance(geometry, list):
                for point in geometry:
                    if isinstance(point, dict) and "lat" in point and "lon" in point:
                        key = (round(float(point["lat"]), 5), round(float(point["lon"]), 5))
                        node_refs[key] = node_refs.get(key, 0) + 1
        amenity = str(tags.get("amenity") or "")
        if amenity in {"parking", "fuel", "charging_station", "bus_station"}:
            deployable_hint_count += 1

    intersection_count = sum(1 for count in node_refs.values() if count >= 2)
    if not road_classes and not deployable_hint_count:
        return RoadContextSummary(available=False, summary="No open map context returned inside the route bounds")
    top = ", ".join(f"{key}:{value}" for key, value in sorted(road_classes.items(), key=lambda item: item[1], reverse=True)[:3])
    summary = (
        f"OSM classes {top or 'none'}, "
        f"{intersection_count} inferred intersections, {deployable_hint_count} public deployable hints"
    )
    return RoadContextSummary(
        available=True,
        dominant_classes=road_classes,
        intersection_count=intersection_count,
        intersections_per_km=intersection_count / route_km,
        deployable_hint_count=deployable_hint_count,
        access_notes=tuple(sorted(access_notes)[:6]),
        summary=summary,
    )


def _road_accessibility_score(road: RoadContextSummary) -> float:
    classes = road.dominant_classes
    total = max(1, sum(classes.values()))
    weights = {
        "motorway": 0.98,
        "trunk": 0.95,
        "primary": 0.9,
        "secondary": 0.82,
        "tertiary": 0.72,
        "residential": 0.6,
        "service": 0.45,
        "track": 0.32,
        "path": 0.2,
    }
    score = sum(weights.get(key, 0.55) * count for key, count in classes.items()) / total
    if any("access=private" in note or "access=no" in note for note in road.access_notes):
        score -= 0.15
    if road.deployable_hint_count > 0:
        score += min(0.12, road.deployable_hint_count * 0.025)
    return max(0.0, min(1.0, score))


def _weather_score(weather: WeatherSummary) -> float:
    score = 1.0
    if weather.precipitation_mm is not None:
        score -= min(0.35, weather.precipitation_mm * 0.07)
    if weather.wind_speed_kmh is not None:
        score -= min(0.24, max(0.0, weather.wind_speed_kmh - 22.0) / 80.0)
    if weather.wind_gusts_kmh is not None:
        score -= min(0.2, max(0.0, weather.wind_gusts_kmh - 35.0) / 90.0)
    if weather.cloud_cover_pct is not None:
        score -= min(0.12, max(0.0, weather.cloud_cover_pct - 65.0) / 300.0)
    return max(0.0, min(1.0, score))


def _thin_segments(segments: list[TerrainSegment], *, limit: int) -> list[TerrainSegment]:
    if len(segments) <= limit:
        return segments
    step = max(1, math.ceil(len(segments) / limit))
    return segments[::step][:limit]


def _route_length(points: list[LatLng]) -> float:
    if len(points) < 2:
        return 0.0
    return sum(haversine_m(points[idx - 1], points[idx]) for idx in range(1, len(points)))


def _float_or_none(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
