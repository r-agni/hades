"""Range-gated communications topology for the HADES swarm."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import networkx as nx

from hades import config
from hades.state import CommsLink, ConvoyState, DroneState, EdgeState

if TYPE_CHECKING:
    pass


def _distance(ax: float, ay: float, bx: float, by: float, bz: float = 0.0, az: float = 0.0) -> float:
    return math.sqrt((ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2)


def _actor_type(actor_id: str) -> str:
    if actor_id.startswith("parent_"):
        return "PARENT"
    if actor_id.startswith("small_"):
        return "SMALL"
    if actor_id.startswith("edge_"):
        return "EDGE"
    if actor_id.startswith("convoy_"):
        return "CONVOY"
    raise ValueError(f"Unknown actor id prefix: {actor_id!r}")


def _allowed_link(
    a_type: str,
    b_type: str,
    dist: float,
    wifi: float,
    lora: float,
) -> tuple[bool, str]:
    """Return (allowed, link_type). SMALL↔EDGE is always FORBIDDEN."""
    pair = frozenset({a_type, b_type})

    if pair == frozenset({"SMALL"}):
        return dist <= wifi, "WIFI_MESH"

    if pair == frozenset({"SMALL", "PARENT"}):
        if dist <= wifi:
            return True, "WIFI_MESH"
        if dist <= lora:
            return True, "LORA"
        return False, ""

    if pair == frozenset({"PARENT"}):
        if dist <= wifi:
            return True, "WIFI_MESH"
        if dist <= lora:
            return True, "LORA"
        return False, ""

    if pair == frozenset({"PARENT", "EDGE"}):
        return dist <= wifi, "WIFI_MESH"

    if pair == frozenset({"EDGE"}):
        return dist <= wifi, "WIFI_MESH"

    if "CONVOY" in pair:
        return dist <= wifi, "WIFI_MESH"

    # SMALL ↔ EDGE and any other unrecognised pair: FORBIDDEN
    return False, ""


class CommsGraph:
    """Range-gated, latency-aware comms topology updated every sim step."""

    def __init__(self, cfg: config.CommsConfig | None = None) -> None:
        self._cfg = cfg or config.COMMS
        self._lat_cfg = config.COMMS_LATENCY
        self._graph: nx.Graph = nx.Graph()
        self._links: list[CommsLink] = []
        self._positions: dict[str, tuple[float, float, float]] = {}
        self._link_types: dict[frozenset[str], str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def step(
        self,
        drones: list[DroneState],
        edges: list[EdgeState],
        convoy: list[ConvoyState],
    ) -> None:
        """Rebuild the graph from current actor positions."""
        self._graph = nx.Graph()
        self._links = []
        self._positions = {}
        self._link_types = {}

        actors: list[tuple[str, float, float, float]] = []
        for d in drones:
            actors.append((d.id, d.pose.x, d.pose.y, d.pose.z))
        for e in edges:
            actors.append((e.id, e.pose.x, e.pose.y, e.pose.z))
        for c in convoy:
            actors.append((c.id, c.pose.x, c.pose.y, c.pose.z))

        for actor_id, x, y, z in actors:
            self._graph.add_node(actor_id)
            self._positions[actor_id] = (x, y, z)

        wifi = self._cfg.wifi_mesh_radius_m
        lora = self._cfg.lora_radius_m

        for i in range(len(actors)):
            for j in range(i + 1, len(actors)):
                a_id, ax, ay, az = actors[i]
                b_id, bx, by, bz = actors[j]
                a_type = _actor_type(a_id)
                b_type = _actor_type(b_id)

                dist = _distance(ax, ay, bx, by, bz, az)
                allowed, link_type = _allowed_link(a_type, b_type, dist, wifi, lora)
                if not allowed:
                    continue

                max_radius = wifi if link_type == "WIFI_MESH" else lora
                quality = max(0.0, min(1.0, 1.0 - dist / max_radius))
                if quality < 0.05:
                    continue

                self._graph.add_edge(a_id, b_id, link_type=link_type, dist=dist, quality=quality)
                key = frozenset({a_id, b_id})
                self._link_types[key] = link_type
                self._links.append(
                    CommsLink(
                        from_id=a_id,
                        to_id=b_id,
                        type=link_type,  # type: ignore[arg-type]
                        quality=round(quality, 3),
                    )
                )

    def reachable(self, from_id: str, to_id: str) -> bool:
        """True if there is a direct active link between the two actors."""
        return self._graph.has_edge(from_id, to_id)

    def link_quality(self, from_id: str, to_id: str) -> float:
        if not self._graph.has_edge(from_id, to_id):
            return 0.0
        return float(self._graph[from_id][to_id]["quality"])

    def latency_ms(self, from_id: str, to_id: str) -> float:
        if not self._graph.has_edge(from_id, to_id):
            return float("inf")
        dist = float(self._graph[from_id][to_id]["dist"])
        active_links = self._graph.number_of_edges()
        return (
            self._lat_cfg.base_ms
            + self._lat_cfg.congestion_factor * active_links
            + self._lat_cfg.distance_factor * max(0.0, dist - 200.0)
        )

    def relay_path(self, from_id: str, to_id: str) -> list[str]:
        """BFS shortest relay path. Returns [] if no path exists."""
        try:
            return list(nx.shortest_path(self._graph, from_id, to_id))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def links(self) -> list[CommsLink]:
        return list(self._links)

    def actor_position(self, actor_id: str) -> tuple[float, float, float] | None:
        return self._positions.get(actor_id)
