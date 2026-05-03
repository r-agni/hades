"""Shared deterministic actor layout for bridge frames and Isaac stage setup."""

from __future__ import annotations

from dataclasses import dataclass


ROUTE_START_X = -580.0
ROUTE_END_X = 580.0
ROUTE_DURATION_S = 60.0
PARENT_HOVER_Z = 34.0
SMALL_HOVER_Z = 18.0
SMALL_RING_R = 24.0
PARENT_Y_OFF = 32.0


@dataclass(frozen=True)
class Placement:
    id: str
    x: float
    y: float
    z: float
    yaw_deg: float = 0.0


# Sparse relay deployment: eight non-uniform field sites around route
# chokepoints, service pullouts, and likely improvised relay locations.
EDGE_DEPLOYMENTS: tuple[Placement, ...] = (
    Placement("edge_0", -560.0, 84.0, 1.2, 78.0),
    Placement("edge_1", -430.0, -132.0, 1.2, -104.0),
    Placement("edge_2", -252.0, 104.0, 1.2, 52.0),
    Placement("edge_3", -68.0, -146.0, 1.2, -138.0),
    Placement("edge_4", 96.0, 118.0, 1.2, 37.0),
    Placement("edge_5", 286.0, -92.0, 1.2, -83.0),
    Placement("edge_6", 420.0, -126.0, 1.2, -116.0),
    Placement("edge_7", 566.0, 54.0, 1.2, 66.0),
)


def parent_deployments(convoy_x: float = ROUTE_START_X) -> tuple[Placement, ...]:
    return (
        Placement("parent_0", convoy_x + 32.0, 54.0, PARENT_HOVER_Z),
        Placement("parent_1", convoy_x + 8.0, -54.0, PARENT_HOVER_Z),
    )


def small_deployments(convoy_x: float = ROUTE_START_X) -> tuple[Placement, ...]:
    return (
        Placement("small_0", convoy_x + 76.0, 44.0, SMALL_HOVER_Z + 4.0, 8.0),
        Placement("small_1", convoy_x + 68.0, -40.0, SMALL_HOVER_Z + 3.5, -12.0),
        Placement("small_2", convoy_x + 24.0, 80.0, SMALL_HOVER_Z + 2.0, 18.0),
        Placement("small_3", convoy_x + 12.0, -76.0, SMALL_HOVER_Z + 1.5, -22.0),
        Placement("small_4", convoy_x - 42.0, 38.0, SMALL_HOVER_Z + 0.5, 170.0),
        Placement("small_5", convoy_x - 56.0, -32.0, SMALL_HOVER_Z, -168.0),
    )


def convoy_deployments(convoy_x: float = ROUTE_START_X) -> tuple[Placement, ...]:
    return (
        Placement("convoy_0", convoy_x, -3.0, 0.8),
        Placement("convoy_1", convoy_x - 14.0, 3.0, 0.8),
    )
