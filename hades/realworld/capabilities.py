"""Capability rules for real-world drone/edge simulation decisions."""

from __future__ import annotations

from dataclasses import dataclass

from hades import config


@dataclass(frozen=True)
class DroneCapability:
    tier: str
    vision_radius_m: float
    compute_tops: float
    onboard_functions: tuple[str, ...]
    edge_required_functions: tuple[str, ...]


PARENT_CAPABILITY = DroneCapability(
    tier="PARENT",
    vision_radius_m=260.0,
    compute_tops=config.COMPUTE.parent_tops,
    onboard_functions=(
        "route_following",
        "small_drone_coordination",
        "coarse_object_detection",
        "local_track_fusion",
        "fallback_classification",
    ),
    edge_required_functions=(
        "high_resolution_classification",
        "multi_sensor_fusion",
        "coverage_replanning",
        "terrain_cost_update",
    ),
)

SMALL_CAPABILITY = DroneCapability(
    tier="SMALL",
    vision_radius_m=95.0,
    compute_tops=config.COMPUTE.small_tops,
    onboard_functions=(
        "route_following",
        "coarse_object_detection",
        "parent_report_uplink",
    ),
    edge_required_functions=(),
)

