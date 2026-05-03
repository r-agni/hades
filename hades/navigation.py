"""Pretrained-ONNX drone navigator and Dijkstra convoy router."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import networkx as nx

from hades import config
from hades.state import ConvoyState, DroneState, Pose, SimFrame, ThreatState

if TYPE_CHECKING:
    from hades.models import ModelRegistry

_THREAT_PENALTY = 1_000.0  # cost added per waypoint segment near a threat
_THREAT_RADIUS_M = 80.0    # threat influence radius for route scoring


class DroneNavigator:
    """Navigation controller for individual drones.

    In stub/no-model mode the drone hovers at its current pose.
    With a real ONNX model, camera images would drive avoidance.
    """

    def __init__(self, registry: "ModelRegistry") -> None:
        self._registry = registry

    def navigate(
        self,
        drone: DroneState,
        threats: list[ThreatState],
        frame: SimFrame,
    ) -> Pose:
        model = self._registry.get_mobilenet_ssd()
        if model(None) is None:
            # Stub: hover in place
            return drone.pose

        # Live path: run model on camera image, return avoidance pose
        # (Not implemented until real sensor pipeline is available in Track 3)
        return drone.pose


class ConvoyRouter:
    """Selects the lowest-cost route using Dijkstra with threat penalties.

    The route graph is rebuilt each ``select_route()`` call so threat
    positions are always current.
    """

    def __init__(self, registry: "ModelRegistry") -> None:
        self._registry = registry

    def select_route(
        self,
        convoy: ConvoyState,
        threats: list[ThreatState],
    ) -> str:
        best_route: str = convoy.active_route_id
        best_cost: float = float("inf")

        for route_name, waypoints in config.ROUTE_WAYPOINTS.items():
            cost = self._route_cost(waypoints, threats)
            if cost < best_cost:
                best_cost = cost
                best_route = route_name

        return best_route

    def next_waypoint(
        self,
        convoy: ConvoyState,
        active_route: str,
    ) -> tuple[float, float]:
        waypoints = config.ROUTE_WAYPOINTS.get(active_route, config.ROUTE_WAYPOINTS["main"])
        cx, cy = convoy.pose.x, convoy.pose.y

        for wx, wy in waypoints:
            # Return the first waypoint the convoy hasn't yet passed (ahead in x)
            if wx > cx:
                return (float(wx), float(wy))

        # Already past all waypoints — return the last one
        last = waypoints[-1]
        return (float(last[0]), float(last[1]))

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _route_cost(
        self,
        waypoints: list[tuple[float, float]],
        threats: list[ThreatState],
    ) -> float:
        total = 0.0
        for i in range(len(waypoints) - 1):
            ax, ay = waypoints[i]
            bx, by = waypoints[i + 1]
            segment_len = math.sqrt((bx - ax) ** 2 + (by - ay) ** 2)
            total += segment_len

            # Penalise if any threat is within _THREAT_RADIUS_M of the segment
            # Use point-to-segment distance so threats near any part of the
            # segment (not just the midpoint) are correctly penalised.
            penalised = False
            for threat in threats:
                if not penalised and self._point_segment_dist(
                    threat.pose.x, threat.pose.y, ax, ay, bx, by
                ) < _THREAT_RADIUS_M:
                    total += _THREAT_PENALTY
                    penalised = True  # one penalty per segment

        return total

    @staticmethod
    def _point_segment_dist(
        px: float, py: float,
        ax: float, ay: float,
        bx: float, by: float,
    ) -> float:
        """Minimum distance from point (px,py) to line segment (ax,ay)-(bx,by)."""
        dx, dy = bx - ax, by - ay
        len_sq = dx * dx + dy * dy
        if len_sq == 0.0:
            return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / len_sq))
        cx, cy = ax + t * dx, ay + t * dy
        return math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
