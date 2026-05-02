import math

from fastapi.testclient import TestClient

from bridge.routes import realworld
from bridge.server import app
from hades.realworld.geo import LatLng, cumulative_distances, decode_polyline, densify_route
from hades.realworld.google import ElevationSample, GoogleRoute
from hades.realworld.optimizer import EdgeRecommendation, EdgeAnalysis, optimize_edges
from hades.realworld.publisher import RealWorldSimPublisher
from hades.realworld.scenario import RealWorldScenarioService


def test_decode_google_polyline_example() -> None:
    points = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@")

    assert points == [
        LatLng(38.5, -120.2),
        LatLng(40.7, -120.95),
        LatLng(43.252, -126.453),
    ]


def test_route_densification_preserves_distance_order() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.01, -118.0)]
    dense = densify_route(route, spacing_m=100.0, max_points=20)
    distances = cumulative_distances(dense)

    assert len(dense) > 2
    assert all(a <= b for a, b in zip(distances, distances[1:]))
    assert math.isclose(distances[-1], cumulative_distances(route)[-1], rel_tol=0.02)


def test_optimizer_selects_edges_and_reports_coverage() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.001, -118.0), LatLng(34.002, -118.0)]
    distances = cumulative_distances(route)
    route_samples = [
        type("RouteSample", (), {"point": point, "distance_m": distances[idx], "elevation_m": 10.0})()
        for idx, point in enumerate(route)
    ]
    candidates = [LatLng(34.0, -118.0), LatLng(34.001, -118.0002), LatLng(34.002, -118.0)]
    elevations = [ElevationSample(point=candidate, elevation_m=14.0) for candidate in candidates]

    analysis = optimize_edges(
        route_samples,
        candidates,
        elevations,
        [None, None, None],
        edge_count=2,
        wifi_radius_m=140.0,
    )

    assert len(analysis.edges) == 2
    assert analysis.coverage_percent > 50.0
    assert analysis.edges[0].reasons


def test_publisher_applies_capability_and_sensing_rules() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.0, -117.995)]
    edge = EdgeRecommendation(
        id="edge_0",
        point=LatLng(34.0, -118.0),
        elevation_m=20.0,
        nearest_road_distance_m=0.0,
        coverage_m=100.0,
        avg_latency_ms=12.0,
        elevation_advantage_m=5.0,
        score=100.0,
        manual=False,
        reasons=("covers route",),
    )
    analysis = EdgeAnalysis(
        edges=(edge,),
        coverage_percent=100.0,
        uncovered_m=0.0,
        coverage_gaps=(),
        route_length_m=cumulative_distances(route)[-1],
    )

    frame = RealWorldSimPublisher(
        scenario_id="rw_test",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
    ).frame_at(3.0)

    parent = next(drone for drone in frame["drones"] if drone["tier"] == "PARENT")
    small = next(drone for drone in frame["drones"] if drone["tier"] == "SMALL")
    assert parent["capabilities"]["vision_radius_m"] > small["capabilities"]["vision_radius_m"]
    assert "fallback_classification" in parent["available_functions"]
    assert "high_resolution_classification" in parent["capabilities"]["edge_required_functions"]
    assert "high_resolution_classification" not in small["available_functions"]
    assert "targets" in frame["sensing"]


class FakeGoogle:
    async def geocode(self, query: str) -> LatLng:
        return LatLng(34.0, -118.0) if "Origin" in query else LatLng(34.004, -118.0)

    async def compute_route(self, origin: LatLng, destination: LatLng) -> GoogleRoute:
        points = [origin, LatLng(34.002, -118.0), destination]
        return GoogleRoute(points=points, distance_m=cumulative_distances(points)[-1], duration_s=60.0, encoded_polyline="fake")

    async def elevations(self, points: list[LatLng]) -> list[ElevationSample]:
        return [ElevationSample(point=point, elevation_m=25.0 + idx) for idx, point in enumerate(points)]

    async def nearest_roads(self, points: list[LatLng]):
        return [None for _ in points]


def test_realworld_scenario_service_uses_google_client() -> None:
    service = RealWorldScenarioService(FakeGoogle())

    import asyncio

    scenario = asyncio.run(
        service.create(
            origin="Origin Test",
            destination="Destination Test",
            edge_count=3,
            wifi_radius_m=160.0,
            search_buffer_m=180.0,
        )
    )

    payload = scenario.to_dict()
    assert payload["scenario_id"].startswith("rw_")
    assert len(payload["analysis"]["edges"]) == 3
    assert payload["route"]["distance_m"] > 0


def test_realworld_routes_and_existing_viz(monkeypatch) -> None:
    monkeypatch.setenv("VITE_GOOGLE_API_KEY", "browser-test-key")
    client = TestClient(app)

    config_resp = client.get("/api/realworld/config")
    assert config_resp.status_code == 200
    assert config_resp.json()["default_edge_count"] == 18

    viz_resp = client.get("/viz")
    assert viz_resp.status_code == 200
    assert "HADES Tactical Dashboard" in viz_resp.text

    realworld_resp = client.get("/viz/realworld-tempVisualizer")
    assert realworld_resp.status_code == 200
    assert "HADES Real-World Visualizer" in realworld_resp.text


def test_realworld_create_route_uses_injected_service(monkeypatch) -> None:
    class FakeScenario:
        def to_dict(self):
            return {"scenario_id": "rw_fake", "analysis": {"edges": []}}

    class FakeService:
        async def create(self, **kwargs):
            self.kwargs = kwargs
            return FakeScenario()

    fake = FakeService()
    monkeypatch.setattr(realworld, "_service", fake)
    try:
        client = TestClient(app)
        resp = client.post(
            "/api/realworld/scenarios",
            json={
                "origin": "Origin Test",
                "destination": "Destination Test",
                "edge_count": 2,
                "wifi_radius_m": 150,
                "search_buffer_m": 200,
            },
        )
    finally:
        monkeypatch.setattr(realworld, "_service", None)

    assert resp.status_code == 200
    assert resp.json()["scenario_id"] == "rw_fake"
