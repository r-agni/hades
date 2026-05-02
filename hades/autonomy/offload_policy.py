"""Parent-side compute offload policy.

HeuristicOffloadPolicy implements the Policy interface. Track 5 swaps it for
RLOffloadPolicy(onnx_path) without touching any call sites.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from hades import config
from hades.state import EdgeState, OffloadEvent, OffloadReason

# Cost-model weights (hand-tuned; Track 5 learns these instead)
_ALPHA = 0.30   # battery drain weight
_BETA  = 1.00   # deadline-miss penalty multiplier
_GAMMA = 0.20   # load-imbalance weight

_PARENT_WATT  = 30.0


@dataclass
class Task:
    id: str = field(default_factory=lambda: f"task_{uuid.uuid4().hex[:6]}")
    name: str = "classify_target"
    compute_cost_gflops: float = 200.0
    latency_budget_ms: float = 120.0
    priority: int = 1


@dataclass
class PeerInfo:
    id: str
    link_quality: float
    compute_load: float
    battery_pct: float


@dataclass
class OffloadCtx:
    own_id: str
    own_load: float
    own_battery_pct: float
    own_tops: float
    peers_in_wifi: list[PeerInfo] = field(default_factory=list)
    edges_in_wifi: list[EdgeState] = field(default_factory=list)
    edge_link_qualities: dict[str, float] = field(default_factory=dict)


def _compute_latency_ms(gflops: float, tops: float, load: float = 0.0) -> float:
    # tops = tera-ops/s = 1e12 ops/s; gflops = 1e9 ops
    # compute_ms = (gflops * 1e9) / (tops * 1e12) * 1000 = gflops / tops
    effective_tops = tops * max(0.1, 1.0 - load)
    return gflops / effective_tops


def _remote_latency_ms(
    gflops: float,
    tops: float,
    wifi_quality: float = 1.0,
    load: float = 0.0,
) -> float:
    transfer_ms = config.COMMS.wifi_base_latency_ms + (1.0 / max(wifi_quality, 0.01)) * 2.0
    return _compute_latency_ms(gflops, tops, load) + transfer_ms


def _drain(task: Task, tops: float) -> float:
    # seconds = compute milliseconds / 1000
    seconds  = (task.compute_cost_gflops / tops) / 1_000.0
    energy_j = _PARENT_WATT * seconds
    return energy_j / 3_600.0  # fraction of a 1 Wh battery


class HeuristicOffloadPolicy:
    """Min-cost heuristic offload router.

    cost = expected_latency_ms
         + alpha * battery_drain * 1000
         + beta * 1e6  (if latency > budget)
         + gamma * load_imbalance * 100
    """

    def decide(self, task: Task, ctx: OffloadCtx) -> tuple[str, OffloadEvent]:
        candidates: list[tuple[str, float, OffloadReason]] = []

        # Self
        lat_self = _compute_latency_ms(task.compute_cost_gflops, ctx.own_tops, ctx.own_load)
        cost_self = (
            lat_self
            + _ALPHA * _drain(task, ctx.own_tops) * 1000.0
            + (_BETA * 1e6 if lat_self > task.latency_budget_ms else 0.0)
            + _GAMMA * ctx.own_load * 100.0
        )
        candidates.append((ctx.own_id, cost_self, "local_compute"))

        # Peer parents
        for peer in ctx.peers_in_wifi:
            lat = _remote_latency_ms(
                task.compute_cost_gflops,
                config.COMPUTE.parent_tops,
                peer.link_quality,
                peer.compute_load,
            )
            cost = (
                lat
                + (_BETA * 1e6 if lat > task.latency_budget_ms else 0.0)
                + _GAMMA * peer.compute_load * 100.0
            )
            candidates.append((peer.id, cost, "min_cost"))

        # Edge nodes
        for edge in ctx.edges_in_wifi:
            q = ctx.edge_link_qualities.get(edge.id, 1.0)
            lat = _remote_latency_ms(
                task.compute_cost_gflops,
                edge.compute_capacity_tops,
                q,
                edge.compute_load,
            )
            overloaded = edge.compute_load > 0.85
            cost = (
                lat
                + (_BETA * 1e6 if lat > task.latency_budget_ms else 0.0)
                + _GAMMA * edge.compute_load * 100.0
                + (500.0 if overloaded else 0.0)
            )
            reason = "edge_overloaded" if overloaded else "min_cost"
            candidates.append((edge.id, cost, reason))

        if not ctx.edges_in_wifi and len(candidates) == 1:
            return ctx.own_id, OffloadEvent(
                parent_id=ctx.own_id, task_id=task.id,
                chosen_target=ctx.own_id,
                expected_latency_ms=round(lat_self, 1),
                actual_latency_ms=0.0,
                reason="no_wifi_in_range",
            )

        chosen_id, _, reason = min(candidates, key=lambda c: c[1])

        # Recompute expected latency for winner
        if chosen_id == ctx.own_id:
            exp_lat = lat_self
        elif any(p.id == chosen_id for p in ctx.peers_in_wifi):
            peer = next(p for p in ctx.peers_in_wifi if p.id == chosen_id)
            exp_lat = _remote_latency_ms(
                task.compute_cost_gflops,
                config.COMPUTE.parent_tops,
                peer.link_quality,
                peer.compute_load,
            )
        else:
            edge = next(e for e in ctx.edges_in_wifi if e.id == chosen_id)
            q = ctx.edge_link_qualities.get(edge.id, 1.0)
            exp_lat = _remote_latency_ms(
                task.compute_cost_gflops,
                edge.compute_capacity_tops,
                q,
                edge.compute_load,
            )

        return chosen_id, OffloadEvent(
            parent_id=ctx.own_id, task_id=task.id,
            chosen_target=chosen_id,
            expected_latency_ms=round(exp_lat, 1),
            actual_latency_ms=0.0,
            reason=reason,
        )
