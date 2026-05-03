"""TOPS-budget compute scheduler for the HADES swarm."""

from __future__ import annotations

from hades import config
from hades.comms import CommsGraph, _actor_type
from hades.state import ComputeEvent, ConvoyState, DroneState, EdgeState, SimFrame


# Tasks assigned to each actor tier, in execution order.
_SMALL_TASKS: list[tuple[str, float]] = [
    ("mobilenet_ssd", config.COMPUTE_BUDGET.mobilenet_ssd_tops),
    ("madgwick_imu",  config.COMPUTE_BUDGET.madgwick_imu_tops),
    ("collision_pd",  config.COMPUTE_BUDGET.collision_pd_tops),
    ("yolov8n_offload", config.COMPUTE_BUDGET.yolov8n_offload_tops),
]

_PARENT_TASKS: list[tuple[str, float]] = [
    ("yolov8n_local", config.COMPUTE_BUDGET.yolov8n_local_tops),
    ("ekf_fusion",    config.COMPUTE_BUDGET.ekf_fusion_tops),
    ("astar_plan",    config.COMPUTE_BUDGET.astar_plan_tops),
    ("yolov8m_offload", config.COMPUTE_BUDGET.yolov8m_offload_tops),
]

_ACTOR_TOPS: dict[str, float] = {
    "PARENT": config.COMPUTE.parent_tops,
    "SMALL":  config.COMPUTE.small_tops,
    "EDGE":   config.COMPUTE.edge_tops,
    "CONVOY": config.COMPUTE.edge_tops,  # convoy carries an embedded edge node
}


def _dist2d(
    positions: dict[str, tuple[float, float, float]],
    a: str,
    b: str,
) -> float:
    ax, ay, _ = positions[a]
    bx, by, _ = positions[b]
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


class ComputeScheduler:
    """Assigns compute tasks to actors following the TOPS waterfall.

    Waterfall per task: local → nearest reachable PARENT (with headroom)
    → nearest reachable EDGE via PARENT relay → convoy edge → drop.
    """

    def schedule_all(self, frame: SimFrame, comms: CommsGraph) -> list[ComputeEvent]:
        tick = int(round(frame.t * 10))
        compute_used: dict[str, float] = {}
        events: list[ComputeEvent] = []

        # Build actor capacity map
        actor_tops: dict[str, float] = {}
        for d in frame.drones:
            actor_tops[d.id] = _ACTOR_TOPS[d.tier]
        for e in frame.edges:
            actor_tops[e.id] = e.compute_capacity_tops
        for c in frame.convoy:
            actor_tops[c.id] = _ACTOR_TOPS["CONVOY"]

        positions = {aid: comms.actor_position(aid) or (0.0, 0.0, 0.0) for aid in actor_tops}

        parent_ids = [d.id for d in frame.drones if d.tier == "PARENT"]
        edge_ids = [e.id for e in frame.edges]
        convoy_ids = [c.id for c in frame.convoy]

        def _headroom(actor_id: str) -> float:
            return actor_tops.get(actor_id, 0.0) - compute_used.get(actor_id, 0.0)

        def _schedule_event(actor_id: str, task_name: str, tops: float) -> ComputeEvent:
            """Try waterfall; return a ComputeEvent (possibly dropped).

            Tasks ending in ``_offload`` are designed to run on a remote actor
            and skip the local step entirely — they go straight to the relay
            waterfall. All other tasks run locally if budget permits.
            """
            a_type = _actor_type(actor_id)
            is_offload_task = task_name.endswith("_offload")

            # Step 1: local (only for non-offload tasks)
            if not is_offload_task and tops <= _headroom(actor_id):
                compute_used[actor_id] = compute_used.get(actor_id, 0.0) + tops
                return ComputeEvent(tick=tick, actor_id=actor_id, task_name=task_name,
                                    tops_required=tops, scheduled_on=actor_id,
                                    latency_ms=0.0, dropped=False)

            # Step 2: SMALL yolov8n_offload → nearest reachable PARENT with headroom
            if a_type == "SMALL" and task_name == "yolov8n_offload":
                candidates = [
                    p for p in parent_ids
                    if comms.reachable(actor_id, p) and tops <= _headroom(p)
                ]
                if candidates:
                    target = min(candidates, key=lambda p: _dist2d(positions, actor_id, p))
                    compute_used[target] = compute_used.get(target, 0.0) + tops
                    lat = comms.latency_ms(actor_id, target)
                    return ComputeEvent(tick=tick, actor_id=actor_id, task_name=task_name,
                                        tops_required=tops, scheduled_on=target,
                                        latency_ms=lat, dropped=False)

            # Step 3: PARENT yolov8m_offload → nearest reachable EDGE
            if a_type == "PARENT" and task_name == "yolov8m_offload":
                candidates = [
                    e for e in edge_ids
                    if comms.reachable(actor_id, e) and tops <= _headroom(e)
                ]
                if candidates:
                    target = min(candidates, key=lambda e: _dist2d(positions, actor_id, e))
                    compute_used[target] = compute_used.get(target, 0.0) + tops
                    lat = comms.latency_ms(actor_id, target)
                    return ComputeEvent(tick=tick, actor_id=actor_id, task_name=task_name,
                                        tops_required=tops, scheduled_on=target,
                                        latency_ms=lat, dropped=False)

                # Step 4: convoy edge fallback
                convoy_candidates = [
                    c for c in convoy_ids
                    if comms.reachable(actor_id, c) and tops <= _headroom(c)
                ]
                if convoy_candidates:
                    target = min(convoy_candidates, key=lambda c: _dist2d(positions, actor_id, c))
                    compute_used[target] = compute_used.get(target, 0.0) + tops
                    lat = comms.latency_ms(actor_id, target)
                    return ComputeEvent(tick=tick, actor_id=actor_id, task_name=task_name,
                                        tops_required=tops, scheduled_on=target,
                                        latency_ms=lat, dropped=False)

            # Step 5: drop
            return ComputeEvent(tick=tick, actor_id=actor_id, task_name=task_name,
                                tops_required=tops, scheduled_on=actor_id,
                                latency_ms=0.0, dropped=True)

        for drone in frame.drones:
            tasks = _SMALL_TASKS if drone.tier == "SMALL" else _PARENT_TASKS
            for task_name, tops in tasks:
                events.append(_schedule_event(drone.id, task_name, tops))

        return events
