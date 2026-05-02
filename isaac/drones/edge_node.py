"""Passive edge compute node profile."""

from __future__ import annotations

from dataclasses import dataclass

from hades import config


@dataclass(frozen=True)
class EdgeNodeConfig:
    id: str
    compute_capacity_tops: float = config.COMPUTE.edge_tops
    default_battery_pct: float = config.COMPUTE.edge_default_battery_pct
    wifi_radius_m: float = config.COMMS.wifi_mesh_radius_m
    lora_radius_m: float = config.COMMS.lora_radius_m
    passive_compute_only: bool = True


def make_edge_configs() -> list[EdgeNodeConfig]:
    return [EdgeNodeConfig(id=f"edge_{idx}") for idx in range(config.COUNTS.edge_nodes)]
