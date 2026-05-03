from pathlib import Path

from bridge.sim_publisher import SyntheticSimPublisher
from hades import config
from hades.layout import EDGE_DEPLOYMENTS


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
    assert "Jetracer" not in scene_text
    assert "track_solid_line.usd" not in scene_text
    assert "../assets/terrain/terrain.usda" not in scene_text
    assert "CesiumGeoreferencePrim" in scene_text
    assert "cesium:georeferenceOrigin:height = 165" in scene_text
    assert "Cesium_World_Terrain" in scene_text
    assert "Bing_Maps_Aerial_imagery" in scene_text
    assert "cesium:maximumScreenSpaceError = 4" in scene_text
    assert "cesium_laughlin_bullhead_world_terrain" in scene_text
    assert "Carter/carter_v1_physx_lidar.usd" in scene_text
    assert "../assets/drones/omnidrones/usd/neo11.usd" in scene_text
    assert "../assets/drones/omnidrones/usd/iris.usd" not in scene_text
    assert "Quadcopter/quadcopter.usd" not in scene_text
    assert "../assets/drones/omnidrones/usd/cf2x_isaac.usd" in scene_text
    assert "Crazyflie/cf2x.usd" not in scene_text
    assert "Server_1U_A_01.usd" in scene_text
    assert "xformOp:scale = (8.0, 8.0, 8.0)" in scene_text
    assert "xformOp:scale = (32.0, 32.0, 32.0)" in scene_text
    assert "xformOp:scale = (0.16, 0.16, 0.16)" in scene_text
    assert Path("assets/drones/omnidrones/usd/neo11.usd").exists()
    assert Path("assets/drones/omnidrones/usd/neo11.yaml").exists()
    assert Path("assets/drones/omnidrones/usd/Props/neo11_instanceable_meshes.usd").exists()
    assert Path("assets/drones/omnidrones/usd/cf2x_isaac.usd").exists()
    assert Path("assets/drones/omnidrones/usd/crazyflie.yaml").exists()
    assert Path("assets/drones/omnidrones/usd/Props/cf2x_isaac_instanceable_meshes.usd").exists()

    neo11_yaml = Path("assets/drones/omnidrones/usd/neo11.yaml").read_text(encoding="utf-8")
    crazyflie_yaml = Path("assets/drones/omnidrones/usd/crazyflie.yaml").read_text(encoding="utf-8")
    assert "mass: 3.42" in neo11_yaml
    assert "num_rotors: 6" in neo11_yaml
    assert "mass: 0.028" in crazyflie_yaml
    assert "num_rotors: 4" in crazyflie_yaml


def test_generated_terrain_remains_available_as_fallback_only() -> None:
    terrain_path = Path("assets/terrain/terrain.usda")
    assert terrain_path.exists()

    terrain_text = terrain_path.read_text(encoding="utf-8")
    assert 'hades:environment = "laughlin_bullhead_map_terrain"' in terrain_text
    assert "satellite.png" in terrain_text
    assert "Jetracer" not in terrain_text


def test_edge_layout_is_sparse_and_irregular() -> None:
    assert config.COUNTS.edge_nodes == 8
    assert len(EDGE_DEPLOYMENTS) == config.COUNTS.edge_nodes

    xs = [p.x for p in EDGE_DEPLOYMENTS]
    ys = [p.y for p in EDGE_DEPLOYMENTS]
    gaps = [round(xs[i + 1] - xs[i], 1) for i in range(len(xs) - 1)]
    signs = [y > 0 for y in ys]

    assert len(set(gaps)) >= 5
    assert max(ys) - min(ys) > 240.0
    assert signs != [i % 2 == 0 for i in range(len(signs))]
    assert signs != [i % 2 == 1 for i in range(len(signs))]


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
