from bridge.demo_publisher import DemoSimPublisher
from bridge.sim_publisher import SyntheticSimPublisher
from hades import config
from isaac.environment import GENERATED_FLAT_ROAD, resolve_environment


def test_synthetic_frame_has_phase_1_actors() -> None:
    frame = SyntheticSimPublisher().frame_at(0.0)

    assert len([d for d in frame.drones if d.tier == "PARENT"]) == config.COUNTS.parent_drones
    assert len([d for d in frame.drones if d.tier == "SMALL"]) == config.COUNTS.small_drones
    assert len(frame.edges) == config.COUNTS.edge_nodes
    assert len(frame.convoy) == config.COUNTS.convoy_vehicles
    assert frame.links


def test_synthetic_frame_serializes_to_protocol_shape() -> None:
    payload = SyntheticSimPublisher().frame_at(1.25).to_dict()

    assert set(payload) == {
        "t",
        "drones",
        "edges",
        "convoy",
        "links",
        "events",
        "scenario_phase",
        "alerts",
        "threats",
        "environment",
    }
    assert {"id", "tier", "pose", "battery_pct", "compute_load", "current_task"} <= set(
        payload["drones"][0]
    )
    assert {"id", "pose", "battery_pct", "compute_load", "alive"} <= set(payload["edges"][0])


def test_curved_route_progress_and_yaw_are_bounded() -> None:
    pub = SyntheticSimPublisher()
    samples = [pub.frame_at(t).convoy[0] for t in (0.0, 25.0, 50.0, 75.0)]

    assert all(0.0 <= sample.route_progress_pct <= 100.0 for sample in samples)
    assert len({round(sample.pose.y, 1) for sample in samples}) > 2
    assert all(-3.2 <= sample.pose.yaw <= 3.2 for sample in samples)


def test_scenario_phases_activate_expected_metadata() -> None:
    pub = DemoSimPublisher()

    weak = pub.frame_at(40.0)
    threat = pub.frame_at(60.0)
    jam = pub.frame_at(84.0)
    recovery = pub.frame_at(100.0)

    assert weak.scenario_phase == "weak_link_zone"
    assert "LINK DEGRADED" in weak.alerts
    assert threat.scenario_phase == "threat_contact"
    assert len(threat.threats) == 1
    assert len([d for d in threat.drones if d.current_task == "investigate_threat"]) == 2
    assert jam.scenario_phase == "rf_jamming"
    assert "JAMMING" in jam.alerts
    assert recovery.scenario_phase == "recovery"
    assert not recovery.threats


def test_environment_resolver_falls_back_to_local_usd(monkeypatch) -> None:
    monkeypatch.delenv("HADES_CESIUM_STAGE_USD", raising=False)
    monkeypatch.delenv("HADES_CITY_DEMO_STAGE_USD", raising=False)

    candidate, path = resolve_environment()

    assert candidate == GENERATED_FLAT_ROAD
    assert path.name == "scene.usda"
    assert path.exists()
