from pathlib import Path

from bridge.sim_publisher import SyntheticSimPublisher
from hades import config


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


def test_isaac_stage_uses_real_asset_references() -> None:
    scene_text = Path("isaac/scene.usda").read_text(encoding="utf-8")

    assert "def Cube" not in scene_text
    assert "Jetracer/Tracks/track_solid_line.usd" in scene_text
    assert "Carter/carter_v1_physx_lidar.usd" in scene_text
    assert "Quadcopter/quadcopter.usd" in scene_text
    assert "Crazyflie/cf2x.usd" in scene_text
    assert "Server_1U_A_01.usd" in scene_text


def test_scene_has_correct_actor_counts() -> None:
    scene_text = Path("isaac/scene.usda").read_text(encoding="utf-8")

    parent_count = sum(1 for line in scene_text.splitlines() if line.strip().startswith('def Xform "parent_'))
    small_count = sum(1 for line in scene_text.splitlines() if line.strip().startswith('def Xform "small_'))
    edge_count = sum(1 for line in scene_text.splitlines() if line.strip().startswith('def Xform "edge_'))
    convoy_count = sum(1 for line in scene_text.splitlines() if line.strip().startswith('def Xform "convoy_'))

    assert parent_count == config.COUNTS.parent_drones
    assert small_count == config.COUNTS.small_drones
    assert edge_count == config.COUNTS.edge_nodes
    assert convoy_count == config.COUNTS.convoy_vehicles
