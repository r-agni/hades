"""Edge-device placement optimizer for real-world routes."""

from __future__ import annotations

import math
from dataclasses import dataclass

from hades import config
from hades.realworld.geo import (
    LatLng,
    distance_point_to_route_m,
    haversine_m,
    latlng_from_xy,
    local_xy,
)
from hades.realworld.google import ElevationSample, NearestRoad


@dataclass(frozen=True)
class RouteSample:
    point: LatLng
    distance_m: float
    elevation_m: float


@dataclass(frozen=True)
class ManualEdge:
    id: str
    point: LatLng


@dataclass(frozen=True)
class CandidateMetrics:
    point: LatLng
    elevation_m: float
    nearest_road_distance_m: float | None
    nearest_road: LatLng | None
    covered_indices: frozenset[int]
    covered_m: float
    avg_latency_ms: float
    elevation_advantage_m: float
    base_score: float


@dataclass(frozen=True)
class EdgeRecommendation:
    id: str
    point: LatLng
    elevation_m: float
    nearest_road_distance_m: float | None
    coverage_m: float
    avg_latency_ms: float
    elevation_advantage_m: float
    score: float
    manual: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "lat": self.point.lat,
            "lng": self.point.lng,
            "elevation_m": round(self.elevation_m, 1),
            "nearest_road_distance_m": (
                None if self.nearest_road_distance_m is None else round(self.nearest_road_distance_m, 1)
            ),
            "coverage_m": round(self.coverage_m, 1),
            "avg_latency_ms": round(self.avg_latency_ms, 1),
            "elevation_advantage_m": round(self.elevation_advantage_m, 1),
            "score": round(self.score, 1),
            "manual": self.manual,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class EdgeAnalysis:
    edges: tuple[EdgeRecommendation, ...]
    coverage_percent: float
    uncovered_m: float
    coverage_gaps: tuple[tuple[LatLng, LatLng], ...]
    route_length_m: float

    def to_dict(self) -> dict[str, object]:
        return {
            "edges": [edge.to_dict() for edge in self.edges],
            "coverage_percent": round(self.coverage_percent, 1),
            "uncovered_m": round(self.uncovered_m, 1),
            "coverage_gaps": [
                {"start": start.to_dict(), "end": end.to_dict()} for start, end in self.coverage_gaps
            ],
            "route_length_m": round(self.route_length_m, 1),
        }


def generate_candidate_points(
    route_points: list[LatLng],
    *,
    search_buffer_m: float,
    target_spacing_m: float | None = None,
) -> list[LatLng]:
    if not route_points:
        return []

    reference = route_points[0]
    route_xy = [local_xy(reference, point) for point in route_points]
    min_x = min(x for x, _ in route_xy) - search_buffer_m
    max_x = max(x for x, _ in route_xy) + search_buffer_m
    min_y = min(y for _, y in route_xy) - search_buffer_m
    max_y = max(y for _, y in route_xy) + search_buffer_m

    spacing = target_spacing_m or max(120.0, min(260.0, search_buffer_m / 2.5))
    cols = max(1, int((max_x - min_x) / spacing) + 1)
    rows = max(1, int((max_y - min_y) / spacing) + 1)
    points: list[LatLng] = []

    for row in range(rows + 1):
        y = min_y + row * spacing
        for col in range(cols + 1):
            stagger = 0.5 * spacing if row % 2 else 0.0
            x = min_x + col * spacing + stagger
            point = latlng_from_xy(reference, x, y)
            if distance_point_to_route_m(point, route_points, reference) <= search_buffer_m:
                points.append(point)

    return points


def build_route_samples(
    route_points: list[LatLng],
    route_distances_m: list[float],
    elevations: list[ElevationSample],
) -> list[RouteSample]:
    elevation_by_idx = {idx: sample.elevation_m for idx, sample in enumerate(elevations)}
    return [
        RouteSample(
            point=point,
            distance_m=route_distances_m[idx],
            elevation_m=elevation_by_idx.get(idx, 0.0),
        )
        for idx, point in enumerate(route_points)
    ]


def optimize_edges(
    route_samples: list[RouteSample],
    candidate_points: list[LatLng],
    candidate_elevations: list[ElevationSample],
    nearest_roads: list[NearestRoad | None],
    *,
    edge_count: int,
    wifi_radius_m: float,
    manual_edges: list[ManualEdge] | None = None,
) -> EdgeAnalysis:
    if not route_samples:
        return EdgeAnalysis(tuple(), 0.0, 0.0, tuple(), 0.0)

    manual_edges = manual_edges or []
    route_length = route_samples[-1].distance_m
    sample_weight = _sample_weight(route_samples, route_length)
    metrics = _candidate_metrics(
        route_samples,
        candidate_points,
        candidate_elevations,
        nearest_roads,
        wifi_radius_m=wifi_radius_m,
        sample_weight=sample_weight,
    )

    selected: list[tuple[CandidateMetrics, bool, str | None]] = []
    covered: set[int] = set()

    for manual in manual_edges[:edge_count]:
        metric = _metric_for_manual(route_samples, manual, wifi_radius_m, sample_weight)
        selected.append((metric, True, manual.id))
        covered.update(metric.covered_indices)

    remaining = max(0, edge_count - len(selected))
    available = metrics[:]
    for _ in range(remaining):
        best_idx = None
        best_score = -float("inf")
        for idx, metric in enumerate(available):
            if any(haversine_m(metric.point, chosen.point) < wifi_radius_m * 0.55 for chosen, _, _ in selected):
                spacing_penalty = 35.0
            else:
                spacing_penalty = 0.0
            new_coverage = sum(sample_weight[i] for i in metric.covered_indices if i not in covered)
            score = metric.base_score + new_coverage * 2.8 - spacing_penalty
            if score > best_score:
                best_idx = idx
                best_score = score
        if best_idx is None:
            break
        chosen = available.pop(best_idx)
        selected.append((chosen, False, None))
        covered.update(chosen.covered_indices)

    selected = _swap_improve(selected, metrics, covered, sample_weight, wifi_radius_m)
    covered = set()
    for metric, _, _ in selected:
        covered.update(metric.covered_indices)

    edges = tuple(
        _recommendation(idx, metric, manual, manual_id, wifi_radius_m)
        for idx, (metric, manual, manual_id) in enumerate(selected)
    )
    covered_m = sum(sample_weight[i] for i in covered)
    coverage_percent = 100.0 * covered_m / max(route_length, 1.0)
    gaps = _coverage_gaps(route_samples, covered)
    return EdgeAnalysis(
        edges=edges,
        coverage_percent=max(0.0, min(100.0, coverage_percent)),
        uncovered_m=max(0.0, route_length - covered_m),
        coverage_gaps=tuple(gaps),
        route_length_m=route_length,
    )


def _candidate_metrics(
    route_samples: list[RouteSample],
    candidate_points: list[LatLng],
    candidate_elevations: list[ElevationSample],
    nearest_roads: list[NearestRoad | None],
    *,
    wifi_radius_m: float,
    sample_weight: list[float],
) -> list[CandidateMetrics]:
    elevation_by_idx = {idx: sample.elevation_m for idx, sample in enumerate(candidate_elevations)}
    metrics: list[CandidateMetrics] = []
    for idx, point in enumerate(candidate_points):
        road = nearest_roads[idx] if idx < len(nearest_roads) else None
        metrics.append(
            _metric_for_point(
                route_samples,
                point,
                elevation_by_idx.get(idx, 0.0),
                road,
                wifi_radius_m,
                sample_weight,
            )
        )
    return sorted(metrics, key=lambda metric: metric.base_score, reverse=True)


def _metric_for_manual(
    route_samples: list[RouteSample],
    manual: ManualEdge,
    wifi_radius_m: float,
    sample_weight: list[float],
) -> CandidateMetrics:
    nearest = min(route_samples, key=lambda sample: haversine_m(sample.point, manual.point))
    return _metric_for_point(
        route_samples,
        manual.point,
        nearest.elevation_m,
        None,
        wifi_radius_m,
        sample_weight,
    )


def _metric_for_point(
    route_samples: list[RouteSample],
    point: LatLng,
    elevation_m: float,
    road: NearestRoad | None,
    wifi_radius_m: float,
    sample_weight: list[float],
) -> CandidateMetrics:
    covered: set[int] = set()
    latencies: list[float] = []
    covered_elevations: list[float] = []
    for idx, sample in enumerate(route_samples):
        dist = haversine_m(point, sample.point)
        if dist <= wifi_radius_m:
            covered.add(idx)
            covered_elevations.append(sample.elevation_m)
            quality = max(0.05, 1.0 - dist / max(wifi_radius_m, 1.0))
            latencies.append(config.COMMS.wifi_base_latency_ms + (1.0 / quality) * 2.0 + 4.0)

    coverage_m = sum(sample_weight[idx] for idx in covered)
    avg_latency = sum(latencies) / len(latencies) if latencies else 999.0
    route_elev = sum(covered_elevations) / len(covered_elevations) if covered_elevations else 0.0
    elevation_advantage = elevation_m - route_elev
    road_distance = None if road is None else road.distance_m
    road_bonus = 0.0 if road_distance is None else max(-35.0, 25.0 - road_distance * 0.08)
    elevation_bonus = max(-20.0, min(35.0, elevation_advantage * 0.7))
    latency_penalty = min(60.0, avg_latency * 0.35)
    base_score = coverage_m + road_bonus + elevation_bonus - latency_penalty

    return CandidateMetrics(
        point=point,
        elevation_m=elevation_m,
        nearest_road_distance_m=road_distance,
        nearest_road=None if road is None else road.snapped,
        covered_indices=frozenset(covered),
        covered_m=coverage_m,
        avg_latency_ms=avg_latency,
        elevation_advantage_m=elevation_advantage,
        base_score=base_score,
    )


def _recommendation(
    idx: int,
    metric: CandidateMetrics,
    manual: bool,
    manual_id: str | None,
    wifi_radius_m: float,
) -> EdgeRecommendation:
    edge_id = manual_id or f"edge_{idx}"
    road_text = (
        "Road access unverified"
        if metric.nearest_road_distance_m is None
        else f"Nearest road is {metric.nearest_road_distance_m:.0f} m away"
    )
    reasons = (
        f"Covers {metric.covered_m:.0f} m of route inside {wifi_radius_m:.0f} m Wi-Fi radius",
        f"Average estimated offload latency {metric.avg_latency_ms:.1f} ms",
        f"Elevation advantage {metric.elevation_advantage_m:+.1f} m vs covered route",
        road_text,
        "Manual placement pinned by operator" if manual else "Selected by coverage/latency optimizer",
    )
    return EdgeRecommendation(
        id=edge_id,
        point=metric.point,
        elevation_m=metric.elevation_m,
        nearest_road_distance_m=metric.nearest_road_distance_m,
        coverage_m=metric.covered_m,
        avg_latency_ms=metric.avg_latency_ms,
        elevation_advantage_m=metric.elevation_advantage_m,
        score=metric.base_score,
        manual=manual,
        reasons=reasons,
    )


def _sample_weight(route_samples: list[RouteSample], route_length: float) -> list[float]:
    if len(route_samples) <= 1:
        return [route_length]
    weights: list[float] = []
    for idx, sample in enumerate(route_samples):
        if idx == 0:
            weights.append((route_samples[1].distance_m - sample.distance_m) / 2.0)
        elif idx == len(route_samples) - 1:
            weights.append((sample.distance_m - route_samples[idx - 1].distance_m) / 2.0)
        else:
            weights.append((route_samples[idx + 1].distance_m - route_samples[idx - 1].distance_m) / 2.0)
    return [max(0.0, weight) for weight in weights]


def _coverage_gaps(
    route_samples: list[RouteSample],
    covered: set[int],
) -> list[tuple[LatLng, LatLng]]:
    gaps: list[tuple[LatLng, LatLng]] = []
    start_idx: int | None = None
    for idx, sample in enumerate(route_samples):
        if idx not in covered and start_idx is None:
            start_idx = idx
        elif idx in covered and start_idx is not None:
            gaps.append((route_samples[start_idx].point, route_samples[max(start_idx, idx - 1)].point))
            start_idx = None
    if start_idx is not None:
        gaps.append((route_samples[start_idx].point, route_samples[-1].point))
    return gaps


def _swap_improve(
    selected: list[tuple[CandidateMetrics, bool, str | None]],
    metrics: list[CandidateMetrics],
    covered: set[int],
    sample_weight: list[float],
    wifi_radius_m: float,
) -> list[tuple[CandidateMetrics, bool, str | None]]:
    if not selected:
        return selected

    def coverage_score(items: list[tuple[CandidateMetrics, bool, str | None]]) -> float:
        item_covered: set[int] = set()
        for metric, _, _ in items:
            item_covered.update(metric.covered_indices)
        return sum(sample_weight[idx] for idx in item_covered)

    best = selected[:]
    best_score = coverage_score(best)
    for selected_idx, (_, is_manual, _) in enumerate(selected):
        if is_manual:
            continue
        for metric in metrics[:24]:
            if any(metric is item[0] for item in selected):
                continue
            if any(
                idx != selected_idx and haversine_m(metric.point, item[0].point) < wifi_radius_m * 0.4
                for idx, item in enumerate(selected)
            ):
                continue
            candidate = selected[:]
            candidate[selected_idx] = (metric, False, None)
            score = coverage_score(candidate)
            if score > best_score:
                best = candidate
                best_score = score
    return best

