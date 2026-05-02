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

    assert set(payload) == {"t", "drones", "edges", "convoy", "links", "events", "environment"}
    assert {"id", "tier", "pose", "battery_pct", "compute_load", "current_task"} <= set(
        payload["drones"][0]
    )
    assert {"id", "pose", "battery_pct", "compute_load", "alive"} <= set(payload["edges"][0])


def test_environment_resolver_falls_back_to_local_usd(monkeypatch) -> None:
    monkeypatch.delenv("HADES_CESIUM_STAGE_USD", raising=False)
    monkeypatch.delenv("HADES_CITY_DEMO_STAGE_USD", raising=False)

    candidate, path = resolve_environment()

    assert candidate == GENERATED_FLAT_ROAD
    assert path.name == "scene.usda"
    assert path.exists()
