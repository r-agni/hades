"""Isaac Lab InteractiveSceneCfg — actors and sensors for the HADES scene."""

from __future__ import annotations

import isaaclab.sim as sim_utils
from isaaclab.assets import ArticulationCfg, AssetBaseCfg
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import ImuCfg, RayCasterCfg, TiledCameraCfg
from isaaclab.sensors.ray_caster import patterns
from isaaclab.terrains import TerrainImporterCfg
from isaaclab.utils import configclass


@configclass
class HADESSceneCfg(InteractiveSceneCfg):
    """Scene config: Laughlin/Bullhead terrain + all drone sensors.

    Edge nodes and convoy have no sensors — they are receive-only actors.
    """

    # ------------------------------------------------------------------
    # Terrain
    # ------------------------------------------------------------------
    terrain: TerrainImporterCfg = TerrainImporterCfg(
        prim_path="/World/ground",
        terrain_type="usd",
        usd_path="assets/terrain/terrain.usda",
        collision_group=-1,
        debug_vis=False,
    )

    # ------------------------------------------------------------------
    # Parent drone sensors  (pattern matches parent_0, parent_1)
    # ------------------------------------------------------------------
    parent_nav_cam: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/nav_cam",
        offset=TiledCameraCfg.OffsetCfg(pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0)),
        data_types=["rgb", "distance_to_camera"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=12.0, focus_distance=400.0,
            horizontal_aperture=20.955, clipping_range=(0.1, 500.0),
        ),
        width=1280, height=720, update_period=0.1,
    )

    parent_thermal: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/thermal",
        offset=TiledCameraCfg.OffsetCfg(pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0)),
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=12.0, focus_distance=400.0,
            horizontal_aperture=20.955, clipping_range=(0.1, 1000.0),
        ),
        width=640, height=512, update_period=0.1,
    )

    parent_lidar: RayCasterCfg = RayCasterCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/lidar",
        offset=RayCasterCfg.OffsetCfg(pos=(0.0, 0.0, 0.0)),
        attach_yaw_only=True,
        pattern_cfg=patterns.LidarPatternCfg(
            channels=32,
            vertical_fov_range=(-20.0, 20.0),
            horizontal_res=1.0,
        ),
        max_distance=100.0,
        mesh_prim_paths=["{ENV_REGEX_NS}/hades_phase_1/terrain"],
    )

    parent_imu: ImuCfg = ImuCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/imu",
        update_period=0.01,
    )

    # ------------------------------------------------------------------
    # Small drone sensors  (pattern matches small_0 … small_5)
    # ------------------------------------------------------------------
    small_cam: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/small_.*/cam",
        offset=TiledCameraCfg.OffsetCfg(pos=(0.0, 0.0, 0.0), rot=(1.0, 0.0, 0.0, 0.0)),
        data_types=["rgb"],
        spawn=sim_utils.PinholeCameraCfg(
            focal_length=6.0, focus_distance=100.0,
            horizontal_aperture=20.955, clipping_range=(0.1, 200.0),
        ),
        width=320, height=240, update_period=0.1,
    )

    small_imu: ImuCfg = ImuCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/small_.*/imu",
        update_period=0.01,
    )

    # Edge nodes and convoy: no sensors — receive-only actors.
