"""Async Google Maps Platform client for the real-world visualizer."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx

from hades.realworld.geo import LatLng, decode_polyline, haversine_m


class GoogleMapsError(RuntimeError):
    """Raised when a required live Google call fails."""


@dataclass(frozen=True)
class GoogleRoute:
    points: list[LatLng]
    distance_m: float
    duration_s: float
    encoded_polyline: str


@dataclass(frozen=True)
class ElevationSample:
    point: LatLng
    elevation_m: float
    resolution_m: float | None = None


@dataclass(frozen=True)
class NearestRoad:
    point: LatLng
    snapped: LatLng
    distance_m: float
    place_id: str | None = None


class GoogleMapsClient:
    def __init__(
        self,
        api_key: str,
        *,
        http_client: httpx.AsyncClient | None = None,
        timeout_s: float = 20.0,
    ) -> None:
        if not api_key:
            raise GoogleMapsError("GOOGLE_MAPS_API_KEY is required")
        self.api_key = api_key
        self._client = http_client
        self._timeout_s = timeout_s

    async def geocode(self, query: str) -> LatLng:
        data = await self._get(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={"address": query, "key": self.api_key},
        )
        status = data.get("status")
        if status != "OK" or not data.get("results"):
            raise GoogleMapsError(f"Geocoding failed for {query!r}: {status or 'empty response'}")
        loc = data["results"][0]["geometry"]["location"]
        return LatLng(float(loc["lat"]), float(loc["lng"]))

    async def compute_route(self, origin: LatLng, destination: LatLng) -> GoogleRoute:
        body = {
            "origin": {"location": {"latLng": {"latitude": origin.lat, "longitude": origin.lng}}},
            "destination": {
                "location": {"latLng": {"latitude": destination.lat, "longitude": destination.lng}}
            },
            "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE",
            "computeAlternativeRoutes": False,
            "languageCode": "en-US",
            "units": "METRIC",
        }
        data = await self._post(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            json=body,
            headers={
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": "routes.duration,routes.distanceMeters,routes.polyline.encodedPolyline",
            },
        )
        routes = data.get("routes") or []
        if not routes:
            raise GoogleMapsError("Routes API returned no route")
        route = routes[0]
        encoded = route.get("polyline", {}).get("encodedPolyline")
        if not encoded:
            raise GoogleMapsError("Routes API returned no polyline")
        duration_raw = str(route.get("duration", "0s")).rstrip("s")
        return GoogleRoute(
            points=decode_polyline(encoded),
            distance_m=float(route.get("distanceMeters", 0.0)),
            duration_s=float(duration_raw or 0.0),
            encoded_polyline=encoded,
        )

    async def elevations(self, points: list[LatLng]) -> list[ElevationSample]:
        if not points:
            return []
        chunks = [points[idx : idx + 512] for idx in range(0, len(points), 512)]
        results: list[ElevationSample] = []
        for chunk in chunks:
            locations = "|".join(f"{p.lat:.7f},{p.lng:.7f}" for p in chunk)
            data = await self._get(
                "https://maps.googleapis.com/maps/api/elevation/json",
                params={"locations": locations, "key": self.api_key},
            )
            status = data.get("status")
            if status != "OK":
                raise GoogleMapsError(f"Elevation API failed: {status or 'unknown error'}")
            for original, item in zip(chunk, data.get("results", [])):
                loc = item.get("location") or {}
                point = LatLng(float(loc.get("lat", original.lat)), float(loc.get("lng", original.lng)))
                results.append(
                    ElevationSample(
                        point=point,
                        elevation_m=float(item.get("elevation", 0.0)),
                        resolution_m=float(item["resolution"]) if "resolution" in item else None,
                    )
                )
        if len(results) != len(points):
            raise GoogleMapsError("Elevation API returned an unexpected number of samples")
        return results

    async def nearest_roads(self, points: list[LatLng]) -> list[NearestRoad | None]:
        if not points:
            return []
        results: list[NearestRoad | None] = [None] * len(points)
        for start in range(0, len(points), 100):
            chunk = points[start : start + 100]
            encoded_points = "|".join(f"{p.lat:.7f},{p.lng:.7f}" for p in chunk)
            data = await self._get(
                "https://roads.googleapis.com/v1/nearestRoads",
                params={"points": encoded_points, "key": self.api_key},
            )
            if "error" in data:
                message = data["error"].get("message", "unknown error")
                raise GoogleMapsError(f"Roads API failed: {message}")
            for item in data.get("snappedPoints", []):
                local_idx = int(item.get("originalIndex", 0))
                if not 0 <= local_idx < len(chunk):
                    continue
                original = chunk[local_idx]
                loc = item.get("location") or {}
                snapped = LatLng(float(loc["latitude"]), float(loc["longitude"]))
                results[start + local_idx] = NearestRoad(
                    point=original,
                    snapped=snapped,
                    distance_m=haversine_m(original, snapped),
                    place_id=item.get("placeId"),
                )
        return results

    async def _get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.get(url, params=params, timeout=self._timeout_s)
            return self._parse_response(response)
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.get(url, params=params)
            return self._parse_response(response)

    async def _post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
    ) -> dict[str, Any]:
        if self._client is not None:
            response = await self._client.post(
                url,
                json=json,
                headers=headers,
                timeout=self._timeout_s,
            )
            return self._parse_response(response)
        async with httpx.AsyncClient(timeout=self._timeout_s) as client:
            response = await client.post(url, json=json, headers=headers)
            return self._parse_response(response)

    def _parse_response(self, response: httpx.Response) -> dict[str, Any]:
        try:
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GoogleMapsError(f"Google request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise GoogleMapsError("Google request returned non-object JSON")
        return data


async def gather_limited(*coros: Any) -> list[Any]:
    """Tiny wrapper to keep call sites readable and future throttling centralized."""

    return list(await asyncio.gather(*coros))

