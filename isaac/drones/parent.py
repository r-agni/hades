"""Parent drone capability profile."""

from __future__ import annotations

from dataclasses import dataclass, field

from hades import config


@dataclass(frozen=True)
class ParentDroneConfig:
    id: str
    platform_class: str = "Skydio X10D class"
    compute_capacity_tops: float = config.COMPUTE.parent_tops
    default_battery_pct: float = config.COMPUTE.parent_default_battery_pct
    sensors: dict = field(default_factory=lambda: config.PARENT_SENSOR_SUITE)


def make_parent_configs() -> list[ParentDroneConfig]:
    return [ParentDroneConfig(id=f"parent_{idx}") for idx in range(config.COUNTS.parent_drones)]
