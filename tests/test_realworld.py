import math

from fastapi.testclient import TestClient

from bridge.routes import realworld
from bridge.server import app
from hades.realworld.geo import LatLng, cumulative_distances, decode_polyline, densify_route, haversine_m
from hades.realworld.google import ElevationSample, GoogleMapsError, GoogleRoute
from hades.realworld.context import (
    DataSource,
    RoadContextSummary,
    RouteContext,
    TrafficSummary,
    WeatherSummary,
    score_route,
    summarize_terrain,
    summarize_traffic,
)
from hades.realworld.optimizer import EdgeRecommendation, EdgeAnalysis, optimize_edges
from hades.realworld.openai_settings import DEFAULT_OPENAI_MODEL, load_openai_settings
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


def test_openai_settings_default_to_lightweight_disabled_model() -> None:
    settings = load_openai_settings({})

    assert not settings.enabled
    assert settings.model == DEFAULT_OPENAI_MODEL
    assert not settings.has_api_key


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


def test_optimizer_uses_sparse_stable_realistic_candidate_zones() -> None:
    route = [LatLng(34.0 + idx * 0.001, -118.0) for idx in range(10)]
    distances = cumulative_distances(route)
    route_samples = [
        type("RouteSample", (), {"point": point, "distance_m": distances[idx], "elevation_m": 10.0 + idx})()
        for idx, point in enumerate(route)
    ]
    candidates = [LatLng(point.lat, point.lng + 0.0008) for point in route]
    elevations = [ElevationSample(point=candidate, elevation_m=18.0) for candidate in candidates]

    analysis = optimize_edges(
        route_samples,
        candidates,
        elevations,
        [None for _ in candidates],
        edge_count=6,
        wifi_radius_m=130.0,
    )

    assert len(analysis.edges) == 6
    assert all(edge.id.startswith("zone_") for edge in analysis.edges)
    assert analysis.candidate_zones
    route_distances = sorted(edge.zone_id for edge in analysis.edges)
    assert len(route_distances) == len(set(route_distances))
    assert all(edge.deployability_class in {"high", "medium", "low"} for edge in analysis.edges)


def test_rejected_edge_zone_is_excluded_and_replenished() -> None:
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
    rejected_id = scenario.analysis.edges[0].id
    scenario = asyncio.run(service.update_edges(scenario.id, [], rejected_edge_ids=[rejected_id]))
    payload = scenario.to_dict()

    assert rejected_id not in {edge.id for edge in scenario.analysis.edges}
    assert len(scenario.analysis.edges) == 3
    assert any(zone["id"] == rejected_id and zone["status"] == "rejected" for zone in payload["analysis"]["candidate_zones"])


def test_route_scoring_uses_environmental_context_factors() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.0, -117.99)]
    elevations = [ElevationSample(point=route[0], elevation_m=10.0), ElevationSample(point=route[1], elevation_m=80.0)]
    analysis = EdgeAnalysis(
        edges=(),
        coverage_percent=0.0,
        uncovered_m=100.0,
        coverage_gaps=(),
        route_length_m=cumulative_distances(route)[-1],
    )
    context = RouteContext(
        data_sources=(DataSource("test", "Test", "available", "test"),),
        terrain=summarize_terrain(route, elevations),
        weather=WeatherSummary(
            available=True,
            precipitation_mm=3.0,
            wind_speed_kmh=42.0,
            wind_gusts_kmh=58.0,
            cloud_cover_pct=88.0,
            summary="wet and windy",
        ),
        road_context=RoadContextSummary(
            available=True,
            dominant_classes={"service": 4},
            intersection_count=8,
            intersections_per_km=12.0,
            summary="complex service roads",
        ),
        traffic=TrafficSummary(
            available=True,
            static_duration_s=80.0,
            traffic_duration_s=120.0,
            delay_ratio=0.5,
            speed_interval_count=2,
            summary="traffic delay",
        ),
    )

    score = score_route(
        route=GoogleRoute(route, cumulative_distances(route)[-1], 120.0, "route"),
        context=context,
        analysis=analysis,
        active_edge_support={"edge_coverage_score": 0.0, "connectivity_score": 0.0},
        synthetic_risk_score=0.25,
    )

    assert score.overall < 70.0
    assert {"traffic", "weather_visibility", "road_accessibility", "terrain_slope"}.issubset(
        {factor.key for factor in score.factors}
    )


def test_google_traffic_summary_reports_available_and_unavailable_states() -> None:
    route_with_traffic = GoogleRoute(
        points=[LatLng(34.0, -118.0), LatLng(34.0, -117.99)],
        distance_m=1000.0,
        duration_s=120.0,
        encoded_polyline="traffic",
        static_duration_s=100.0,
        speed_reading_intervals=({"speed": "SLOW"},),
    )
    route_without_traffic = GoogleRoute(
        points=route_with_traffic.points,
        distance_m=1000.0,
        duration_s=120.0,
        encoded_polyline="plain",
    )

    assert summarize_traffic(route_with_traffic).available
    assert summarize_traffic(route_without_traffic).available is False


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

    publisher = RealWorldSimPublisher(
        scenario_id="rw_test",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
    )
    frame = publisher.frame_at(3.0)

    assert len([drone for drone in frame["drones"] if drone["tier"] == "PARENT"]) == 4
    assert len([drone for drone in frame["drones"] if drone["tier"] == "SMALL"]) == 16
    assert len([edge for edge in frame["edges"] if edge["edge_type"] == "convoy_edge"]) == 2
    assert frame["reroute"]["recommended"]
    assert frame["convoy"][0]["route_adaptation"]["mode"] == "auto_reroute_defensive_slowdown"
    assert frame["convoy"][0]["speed_mps"] < 11.0
    parent = next(drone for drone in frame["drones"] if drone["tier"] == "PARENT")
    small = next(
        drone
        for drone in frame["drones"]
        if drone["tier"] == "SMALL" and drone["assignment"].startswith("investigate_")
    )
    assert parent["capabilities"]["vision_radius_m"] == 380.0
    assert small["capabilities"]["vision_radius_m"] == 135.0
    assert small["controlled_by"].startswith("parent_")
    assert small["search_cell"]["pattern"] == "edge_assisted_orbit"
    assert parent["edge_connected"]
    assert parent["edge_connectivity_mode"] == "direct_anchor"
    assert parent["connected_edge_id"].startswith("convoy_edge_")
    assert small["edge_connected"]
    assert small["edge_connectivity_mode"] == "via_parent_edge"
    assert frame["sensing"]["fused_tracks"][0]["edge_assisted"]
    assert frame["sensing"]["fused_tracks"][0]["classification_quality"] == "edge_high_resolution"
    assert "edge anchor" in frame["sensing"]["fused_tracks"][0]["fusion_confidence_reason"]
    small_reports = [
        detection
        for detection in frame["sensing"]["detections"]
        if detection["observer_tier"] == "SMALL" and detection.get("reported_to")
    ]
    assert small_reports
    assert all("uplink_quality" in detection for detection in small_reports)
    search_distances = {
        round(float(drone["search_cell"]["route_distance_m"]), -1)
        for drone in frame["drones"]
        if drone["tier"] == "SMALL"
    }
    assert len(search_distances) > 4
    later_frame = publisher.frame_at(9.0)
    later_small = next(drone for drone in later_frame["drones"] if drone["id"] == small["id"])
    assert haversine_m(
        LatLng(float(small["geo"]["lat"]), float(small["geo"]["lng"])),
        LatLng(float(later_small["geo"]["lat"]), float(later_small["geo"]["lng"])),
    ) > 5.0
    assert "fallback_classification" in parent["available_functions"]
    assert "high_resolution_classification" in parent["capabilities"]["edge_required_functions"]
    assert "high_resolution_classification" not in small["available_functions"]
    assert "targets" in frame["sensing"]
    assert frame["sensing"]["attack_vectors"]


def test_approved_stationary_edges_affect_search_assignments_but_pending_do_not() -> None:
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

    pending_frame = RealWorldSimPublisher(
        scenario_id="rw_pending",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
        edge_statuses={"edge_0": "pending"},
    ).frame_at(3.0)
    approved_frame = RealWorldSimPublisher(
        scenario_id="rw_approved",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
        approved_stationary_edge_ids={"edge_0"},
        edge_statuses={"edge_0": "approved"},
    ).frame_at(3.0)

    assert all(
        drone["edge_anchor_id"] != "edge_0"
        for drone in pending_frame["drones"]
        if drone["tier"] == "PARENT"
    )
    assert any(
        drone["edge_anchor_id"] == "edge_0"
        for drone in approved_frame["drones"]
        if drone["tier"] == "PARENT"
    )
    assert any(
        anchor["id"] == "edge_0"
        for anchor in approved_frame["geo"]["edge_support_plan"]["anchors"]
    )


def test_publisher_live_route_update_preserves_route_progress() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.0, -117.89)]
    longer_route = [LatLng(34.0, -118.0), LatLng(34.0, -117.78)]
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
    longer_analysis = EdgeAnalysis(
        edges=(edge,),
        coverage_percent=100.0,
        uncovered_m=0.0,
        coverage_gaps=(),
        route_length_m=cumulative_distances(longer_route)[-1],
    )
    publisher = RealWorldSimPublisher(
        scenario_id="rw_live",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
    )
    publisher.start()
    before = publisher.frame_at(50.0)["convoy"][0]["route_progress_pct"]

    publisher.update_route(longer_route, longer_analysis, applied_reroute_id="reroute_live", current_t=50.0)
    after_frame = publisher.frame_at(50.0)

    assert math.isclose(after_frame["convoy"][0]["route_progress_pct"], before, abs_tol=0.05)
    assert after_frame["reroute"]["applied"]["proposal_id"] == "reroute_live"
    assert after_frame["geo"]["route_revision"] == 1


def test_publisher_route_progress_clamps_instead_of_wrapping() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.0, -117.999)]
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
    publisher = RealWorldSimPublisher(
        scenario_id="rw_no_wrap",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
        route_speed_mps=80.0,
    )
    publisher.start()
    frame = publisher.frame_at(20.0)

    assert publisher._route_distance_at(20.0, publisher.route_distances[-1]) == publisher.route_distances[-1]
    assert all(
        0.0 <= float(drone["search_cell"]["route_distance_m"]) <= frame["geo"]["route_distance_m"]
        for drone in frame["drones"]
    )


def test_publisher_live_reroute_can_start_at_new_route_beginning() -> None:
    route = [LatLng(34.0, -118.0), LatLng(34.0, -117.89)]
    reroute = [LatLng(34.0, -117.95), LatLng(34.01, -117.92)]
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
    reroute_analysis = EdgeAnalysis(
        edges=(edge,),
        coverage_percent=100.0,
        uncovered_m=0.0,
        coverage_gaps=(),
        route_length_m=cumulative_distances(reroute)[-1],
    )
    publisher = RealWorldSimPublisher(
        scenario_id="rw_live_beginning",
        route_points=route,
        analysis=analysis,
        wifi_radius_m=150.0,
    )
    publisher.start()
    publisher.update_route(
        reroute,
        reroute_analysis,
        applied_reroute_id="reroute_from_current",
        current_t=30.0,
        start_at_route_beginning=True,
    )
    anchor = publisher.current_route_anchor(30.0)

    assert haversine_m(anchor["point"], reroute[0]) < 1.0
    assert anchor["route_progress_pct"] == 0.0
    assert publisher.frame_at(30.0)["reroute"]["applied"]["mode"] == "live_route_from_current_position"


class FakeGoogle:
    async def geocode(self, query: str) -> LatLng:
        return LatLng(34.0, -118.0) if "Origin" in query else LatLng(34.004, -118.0)

    async def compute_route(self, origin: LatLng, destination: LatLng) -> GoogleRoute:
        points = [origin, LatLng(34.002, -118.0), destination]
        return GoogleRoute(points=points, distance_m=cumulative_distances(points)[-1], duration_s=60.0, encoded_polyline="fake")

    async def compute_routes(self, origin: LatLng, destination: LatLng, *, alternatives: bool = False):
        self.last_routes_origin = origin
        route_a = await self.compute_route(origin, destination)
        alt_points = [origin, LatLng(34.002, -117.998), destination]
        return [
            route_a,
            GoogleRoute(
                points=alt_points,
                distance_m=cumulative_distances(alt_points)[-1],
                duration_s=75.0,
                encoded_polyline="fake_alt",
            ),
        ]

    async def elevations(self, points: list[LatLng]) -> list[ElevationSample]:
        return [ElevationSample(point=point, elevation_m=25.0 + idx) for idx, point in enumerate(points)]

    async def nearest_roads(self, points: list[LatLng]):
        return [None for _ in points]


class EdgeAwareFakeGoogle(FakeGoogle):
    async def compute_routes(self, origin: LatLng, destination: LatLng, *, alternatives: bool = False):
        self.last_routes_origin = origin
        route_a = await self.compute_route(origin, destination)
        far_points = [origin, LatLng(34.002, -117.97), destination]
        near_points = [origin, LatLng(34.002, -118.0001), destination]
        return [
            route_a,
            GoogleRoute(
                points=far_points,
                distance_m=cumulative_distances(far_points)[-1],
                duration_s=90.0,
                encoded_polyline="far_alt",
            ),
            GoogleRoute(
                points=near_points,
                distance_m=cumulative_distances(near_points)[-1],
                duration_s=70.0,
                encoded_polyline="edge_supported_alt",
            ),
        ]


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
    assert payload["analysis"]["candidate_zones"]
    assert payload["analysis"]["route_score"]["factors"]
    assert any(source["key"] == "open_meteo" and source["state"] == "unavailable" for source in payload["analysis"]["data_sources"])
    assert payload["route"]["distance_m"] > 0
    assert not payload["preflight"]["can_start"]
    assert all(edge["status"] == "pending" for edge in payload["analysis"]["edges"])


def test_realworld_requires_stationary_edge_approval_before_start() -> None:
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

    try:
        service.start(scenario.id)
    except GoogleMapsError:
        pass
    else:
        raise AssertionError("start should require approved stationary edges")

    approved_ids = [edge.id for edge in scenario.analysis.edges]
    scenario = asyncio.run(service.update_edges(scenario.id, [], approved_edge_ids=approved_ids))
    assert scenario.can_start
    scenario = service.start(scenario.id)
    frame = scenario.publisher.frame_at(3.0)

    assert scenario.started
    assert len([edge for edge in frame["edges"] if edge["edge_type"] == "convoy_edge"]) == 2
    assert len([edge for edge in frame["edges"] if edge["edge_type"] == "stationary_edge"]) >= 1


def test_pending_and_rejected_edges_do_not_contribute_to_route_score() -> None:
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
    pending_score = scenario.to_dict()["analysis"]["route_score"]["factor_scores"]["edge_connectivity"]
    rejected_id = scenario.analysis.edges[0].id
    scenario = asyncio.run(service.update_edges(scenario.id, [], rejected_edge_ids=[rejected_id]))
    rejected_score = scenario.to_dict()["analysis"]["route_score"]["factor_scores"]["edge_connectivity"]
    scenario = asyncio.run(
        service.update_edges(
            scenario.id,
            [],
            approved_edge_ids=[edge.id for edge in scenario.analysis.edges],
        )
    )
    approved_score = scenario.to_dict()["analysis"]["route_score"]["factor_scores"]["edge_connectivity"]

    assert pending_score == 0.0
    assert rejected_score == 0.0
    assert approved_score > 0.0


def test_realworld_reroute_proposal_and_apply_with_mocked_routes() -> None:
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
    scenario = asyncio.run(service.propose_reroutes(scenario.id))
    assert scenario.reroute_proposals

    proposal_id = scenario.reroute_proposals[0].id
    scenario = asyncio.run(service.apply_reroute(scenario.id, proposal_id))

    assert scenario.encoded_polyline == "fake_alt"
    assert scenario.applied_reroute_id == proposal_id
    assert not scenario.can_start


def test_realworld_reroute_scoring_prefers_approved_edge_support() -> None:
    service = RealWorldScenarioService(EdgeAwareFakeGoogle())

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
    scenario = asyncio.run(
        service.update_edges(
            scenario.id,
            [],
            approved_edge_ids=[edge.id for edge in scenario.analysis.edges],
        )
    )
    scenario = asyncio.run(service.propose_reroutes(scenario.id))

    assert scenario.reroute_proposals[0].encoded_polyline == "edge_supported_alt"
    assert scenario.reroute_proposals[0].edge_coverage_score > scenario.reroute_proposals[-1].edge_coverage_score
    assert any("Approved edge coverage" in reason for reason in scenario.reroute_proposals[0].reasons)


def test_realworld_live_reroute_apply_keeps_simulation_running() -> None:
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
    scenario = asyncio.run(
        service.update_edges(
            scenario.id,
            [],
            approved_edge_ids=[edge.id for edge in scenario.analysis.edges],
        )
    )
    scenario = service.start(scenario.id)
    scenario.publisher.started_at -= 25.0
    live_anchor = scenario.publisher.current_route_anchor()["point"]
    scenario = asyncio.run(service.propose_reroutes(scenario.id))
    assert haversine_m(service._google.last_routes_origin, live_anchor) < 1.0
    proposal_id = scenario.reroute_proposals[0].id

    scenario = asyncio.run(service.apply_reroute(scenario.id, proposal_id))
    frame = scenario.publisher.frame_at(scenario.publisher.elapsed_s())

    assert scenario.started
    assert frame["scenario_phase"] == "realworld_running"
    assert frame["reroute"]["applied"]["proposal_id"] == proposal_id
    assert frame["geo"]["route_revision"] == 1
    assert frame["reroute"]["applied"]["mode"] == "live_route_from_current_position"
    assert haversine_m(scenario.route_sample_points[0], live_anchor) < 1.0
    assert any(status == "moved" for status in scenario.edge_statuses.values())
    assert any("stationary_edge" in edge["edge_type"] for edge in frame["edges"])


def test_realworld_routes_and_existing_viz(monkeypatch) -> None:
    monkeypatch.setenv("VITE_GOOGLE_API_KEY", "browser-test-key")
    client = TestClient(app)

    config_resp = client.get("/api/realworld/config")
    assert config_resp.status_code == 200
    assert config_resp.json()["default_edge_count"] == 6
    assert "Kyiv" in config_resp.json()["default_origin"]
    assert config_resp.json()["openai_enabled"] is False
    assert config_resp.json()["openai_model"] == DEFAULT_OPENAI_MODEL

    viz_resp = client.get("/viz")
    assert viz_resp.status_code == 200
    assert "HADES Tactical Dashboard" in viz_resp.text

    realworld_resp = client.get("/viz/realworld-tempVisualizer")
    assert realworld_resp.status_code == 200
    assert "HADES Real-World Visualizer" in realworld_resp.text
    assert "Start Simulation" in realworld_resp.text
    assert "Auto reroute pending" in realworld_resp.text
    assert "Defense Presentation" in realworld_resp.text
    assert "missionRoute" in realworld_resp.text
    assert "routeScore" in realworld_resp.text
    assert "map-legend" in realworld_resp.text
    assert "Parent drone" in realworld_resp.text
    assert "Synthetic vector" in realworld_resp.text
    assert "Planner Intelligence" in realworld_resp.text
    assert "Live And Context Data" in realworld_resp.text
    assert "data-layer=\"routeScore\"" in realworld_resp.text
    assert "data-layer=\"feasibility\"" in realworld_resp.text
    assert "data-layer=\"candidates\"" in realworld_resp.text
    assert "data-layer=\"vectors\"" in realworld_resp.text
    assert "timelineStrip" in realworld_resp.text

    realworld_js_resp = client.get("/static/realworld-tempVisualizer/app.js")
    assert realworld_js_resp.status_code == 200
    assert "AUTO_REROUTE_DELAY_MS" in realworld_js_resp.text
    assert "FOLLOW_LOCK_ZOOM = 15" in realworld_js_resp.text
    assert "MOTION_SMOOTH_MS" in realworld_js_resp.text
    assert "smoothOverlayPosition" in realworld_js_resp.text
    assert "resetLiveMotionOnRouteRevision" in realworld_js_resp.text
    assert "FOLLOW_MAX_ZOOM" in realworld_js_resp.text
    assert "routeAheadPoint" in realworld_js_resp.text
    assert "edgeAnchorLabel" in realworld_js_resp.text
    assert "edge_assisted" in realworld_js_resp.text
    assert "renderEdgeSupport" in realworld_js_resp.text
    assert "renderPlanning" in realworld_js_resp.text
    assert "renderCandidateZones" in realworld_js_resp.text
    assert "renderTerrainLayer" in realworld_js_resp.text
    assert "vectorMarkers" in realworld_js_resp.text
    assert "showVectorInfo" in realworld_js_resp.text
    assert "Synthetic scenario object; not live intelligence." in realworld_js_resp.text
    assert "data_sources" in realworld_js_resp.text
    assert "route_score" in realworld_js_resp.text
    assert "decisionNarrative" in realworld_js_resp.text
    assert "setPresentationMode" in realworld_js_resp.text
    assert "toggleLayer" in realworld_js_resp.text
    assert "corridorPath" in realworld_js_resp.text
    assert "renderTimeline" in realworld_js_resp.text


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
