"""Phase 1 constants for the HADES simulation scaffold."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BridgeConfig:
    host: str = "127.0.0.1"
    port: int = 8000
    tick_hz: float = 10.0
    websocket_path: str = "/stream"


@dataclass(frozen=True)
class CommsConfig:
    wifi_mesh_radius_m: float = 150.0
    lora_radius_m: float = 2_000.0
    wifi_base_latency_ms: float = 5.0
    lora_control_latency_ms: float = 50.0


@dataclass(frozen=True)
class ActorCounts:
    parent_drones: int = 2
    small_drones: int = 6
    edge_nodes: int = 18
    convoy_vehicles: int = 2


@dataclass(frozen=True)
class ComputeConfig:
    parent_tops: float = 100.0
    small_tops: float = 0.5
    edge_tops: float = 50.0
    parent_default_battery_pct: float = 98.0
    small_default_battery_pct: float = 92.0
    edge_default_battery_pct: float = 100.0


@dataclass(frozen=True)
class SceneConfig:
    name: str = "hades_phase_1"
    environment_primary: str = "cesium_for_omniverse"
    environment_fallback: str = "nvidia_openusd_city_demo"
    environment_emergency: str = "generated_flat_road"
    route_length_m: float = 420.0
    road_width_m: float = 10.0
    parent_hover_altitude_m: float = 34.0
    small_hover_altitude_m: float = 18.0


BRIDGE = BridgeConfig()
COMMS = CommsConfig()
COUNTS = ActorCounts()
COMPUTE = ComputeConfig()
SCENE = SceneConfig()


PARENT_SENSOR_SUITE = {
    "rgb_nav_cameras": {
        "count": 6,
        "resolution": "1280x720",
        "hz": 10,
        "coverage": "360deg",
    },
    "thermal": {
        "model": "FLIR Boson+ class",
        "resolution": "640x512",
        "hz": 10,
    },
    "lidar": {
        "type": "Isaac RtxLidar class",
    },
    "imu": {
        "hz": 100,
    },
}


SMALL_SENSOR_SUITE = {
    "rgb_camera": {
        "count": 1,
        "resolution": "320x240",
        "hz": 10,
        "orientation": "downward_or_forward",
    },
    "imu": {
        "hz": 100,
    },
}
