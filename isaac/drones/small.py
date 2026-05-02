"""Small drone capability profile."""

from __future__ import annotations

from dataclasses import dataclass, field

from hades import config


@dataclass(frozen=True)
class SmallDroneConfig:
    id: str
    platform_class: str = "Crazyflie 2.1 class"
    compute_capacity_tops: float = config.COMPUTE.small_tops
    default_battery_pct: float = config.COMPUTE.small_default_battery_pct
    sensors: dict = field(default_factory=lambda: config.SMALL_SENSOR_SUITE)


def make_small_configs() -> list[SmallDroneConfig]:
    return [SmallDroneConfig(id=f"small_{idx}") for idx in range(config.COUNTS.small_drones)]
