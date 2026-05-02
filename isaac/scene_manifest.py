"""Declarative Phase 1 scene manifest.

This file is intentionally independent of Isaac imports. Isaac-specific scripts
can consume it inside Kit, while tests and the bridge can import it anywhere.
"""

from __future__ import annotations

from dataclasses import asdict

from bridge.sim_publisher import SyntheticSimPublisher
from hades import config
from isaac.drones.edge_node import make_edge_configs
from isaac.drones.parent import make_parent_configs
from isaac.drones.small import make_small_configs


def build_scene_manifest() -> dict:
    frame = SyntheticSimPublisher().frame_at(0.0)
    return {
        "name": config.SCENE.name,
        "environment_priority": [
            config.SCENE.environment_primary,
            config.SCENE.environment_fallback,
            config.SCENE.environment_emergency,
        ],
        "route": {
            "length_m": config.SCENE.route_length_m,
            "road_width_m": config.SCENE.road_width_m,
            "waypoints": [
                {"x": -190.0, "y": 0.0, "z": 0.0},
                {"x": 190.0, "y": 0.0, "z": 0.0},
            ],
        },
        "capabilities": {
            "parents": [asdict(item) for item in make_parent_configs()],
            "smalls": [asdict(item) for item in make_small_configs()],
            "edges": [asdict(item) for item in make_edge_configs()],
        },
        "initial_frame": frame.to_dict(),
    }
