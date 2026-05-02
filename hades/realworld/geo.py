"""Small geospatial helpers used by the real-world visualizer.

The simulator only needs short-range accuracy around a chosen route, so the
lat/lng <-> local meter helpers use an equirectangular approximation while
distance and heading calculations use spherical formulas.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class LatLng:
    lat: float
    lng: float

    def to_dict(self) -> dict[str, float]:
        return {"lat": self.lat, "lng": self.lng}


def decode_polyline(encoded: str) -> list[LatLng]:
    """Decode a Google encoded polyline into WGS84 coordinates."""

    points: list[LatLng] = []
    index = 0
    lat = 0
    lng = 0

    while index < len(encoded):
        delta_lat, index = _decode_polyline_value(encoded, index)
        delta_lng, index = _decode_polyline_value(encoded, index)
        lat += delta_lat
        lng += delta_lng
        points.append(LatLng(lat / 1e5, lng / 1e5))

    return points


def _decode_polyline_value(encoded: str, index: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if index >= len(encoded):
            raise ValueError("Invalid encoded polyline")
        byte = ord(encoded[index]) - 63
        index += 1
        result |= (byte & 0x1F) << shift
        shift += 5
        if byte < 0x20:
            break
    value = ~(result >> 1) if result & 1 else result >> 1
    return value, index


def haversine_m(a: LatLng, b: LatLng) -> float:
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = lat2 - lat1
    dlng = math.radians(b.lng - a.lng)
    sin_dlat = math.sin(dlat / 2.0)
    sin_dlng = math.sin(dlng / 2.0)
    h = sin_dlat**2 + math.cos(lat1) * math.cos(lat2) * sin_dlng**2
    return 2.0 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(h)))


def cumulative_distances(points: list[LatLng]) -> list[float]:
    if not points:
        return []
    distances = [0.0]
    for idx in range(1, len(points)):
        distances.append(distances[-1] + haversine_m(points[idx - 1], points[idx]))
    return distances


def bearing_rad(a: LatLng, b: LatLng) -> float:
    """Return bearing from north, clockwise, in radians."""

    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlng = math.radians(b.lng - a.lng)
    y = math.sin(dlng) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlng)
    return math.atan2(y, x)


def destination_point(origin: LatLng, distance_m: float, bearing: float) -> LatLng:
    angular = distance_m / EARTH_RADIUS_M
    lat1 = math.radians(origin.lat)
    lng1 = math.radians(origin.lng)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(angular)
        + math.cos(lat1) * math.sin(angular) * math.cos(bearing)
    )
    lng2 = lng1 + math.atan2(
        math.sin(bearing) * math.sin(angular) * math.cos(lat1),
        math.cos(angular) - math.sin(lat1) * math.sin(lat2),
    )
    return LatLng(math.degrees(lat2), ((math.degrees(lng2) + 540.0) % 360.0) - 180.0)


def offset_point(origin: LatLng, east_m: float, north_m: float) -> LatLng:
    distance = math.hypot(east_m, north_m)
    if distance == 0.0:
        return origin
    bearing = math.atan2(east_m, north_m)
    return destination_point(origin, distance, bearing)


def local_xy(reference: LatLng, point: LatLng) -> tuple[float, float]:
    ref_lat = math.radians(reference.lat)
    x = math.radians(point.lng - reference.lng) * EARTH_RADIUS_M * math.cos(ref_lat)
    y = math.radians(point.lat - reference.lat) * EARTH_RADIUS_M
    return x, y


def latlng_from_xy(reference: LatLng, x_m: float, y_m: float) -> LatLng:
    ref_lat = math.radians(reference.lat)
    lat = reference.lat + math.degrees(y_m / EARTH_RADIUS_M)
    lng = reference.lng + math.degrees(x_m / (EARTH_RADIUS_M * max(0.01, math.cos(ref_lat))))
    return LatLng(lat, lng)


def densify_route(points: list[LatLng], spacing_m: float = 75.0, max_points: int = 400) -> list[LatLng]:
    """Sample a route at roughly even spacing while preserving endpoints."""

    if len(points) < 2:
        return list(points)

    distances = cumulative_distances(points)
    total = distances[-1]
    if total <= 0:
        return [points[0]]

    requested = int(total / max(1.0, spacing_m)) + 1
    count = max(2, min(max_points, requested))
    step = total / (count - 1)
    return [sample_route(points, distances, min(total, idx * step))[0] for idx in range(count)]


def sample_route(
    points: list[LatLng],
    distances: list[float],
    distance_m: float,
) -> tuple[LatLng, float]:
    """Return point and heading at cumulative distance along a route."""

    if not points:
        raise ValueError("Cannot sample an empty route")
    if len(points) == 1:
        return points[0], 0.0

    total = distances[-1]
    d = min(max(distance_m, 0.0), total)
    for idx in range(1, len(distances)):
        if d <= distances[idx]:
            seg_start = distances[idx - 1]
            seg_len = max(0.001, distances[idx] - seg_start)
            u = (d - seg_start) / seg_len
            a = points[idx - 1]
            b = points[idx]
            ax, ay = local_xy(a, a)
            bx, by = local_xy(a, b)
            point = latlng_from_xy(a, ax + (bx - ax) * u, ay + (by - ay) * u)
            return point, bearing_rad(a, b)

    return points[-1], bearing_rad(points[-2], points[-1])


def route_bounds(points: list[LatLng]) -> dict[str, float]:
    if not points:
        return {"north": 0.0, "south": 0.0, "east": 0.0, "west": 0.0}
    return {
        "north": max(p.lat for p in points),
        "south": min(p.lat for p in points),
        "east": max(p.lng for p in points),
        "west": min(p.lng for p in points),
    }


def distance_point_to_route_m(point: LatLng, route_points: list[LatLng], reference: LatLng) -> float:
    px, py = local_xy(reference, point)
    route_xy = [local_xy(reference, p) for p in route_points]
    if len(route_xy) < 2:
        return min((math.hypot(px - x, py - y) for x, y in route_xy), default=0.0)

    best = float("inf")
    for idx in range(1, len(route_xy)):
        ax, ay = route_xy[idx - 1]
        bx, by = route_xy[idx]
        vx = bx - ax
        vy = by - ay
        denom = vx * vx + vy * vy
        u = 0.0 if denom == 0.0 else max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / denom))
        cx = ax + vx * u
        cy = ay + vy * u
        best = min(best, math.hypot(px - cx, py - cy))
    return best
