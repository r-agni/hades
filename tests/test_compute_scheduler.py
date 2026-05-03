from hades import config
from hades.comms import CommsGraph
from hades.compute import ComputeScheduler
from hades.state import ConvoyState, DroneState, EdgeState, Pose, SimFrame


def _drone(id: str, x: float, y: float, tier: str = "SMALL") -> DroneState:
    return DroneState(
        id=id, tier=tier, pose=Pose(x=x, y=y, z=18.0 if tier == "SMALL" else 34.0),
        battery_pct=90.0, compute_load=0.0, current_task="test",
    )


def _edge(id: str, x: float, y: float, load: float = 0.0) -> EdgeState:
    return EdgeState(
        id=id, pose=Pose(x=x, y=y, z=1.2),
        battery_pct=100.0, compute_load=load, alive=True,
        compute_capacity_tops=config.COMPUTE.edge_tops,  # 50 TOPS
        wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
        lora_radius_m=config.COMMS.lora_radius_m,
    )


def _frame(drones, edges, convoy=None, t: float = 1.0) -> SimFrame:
    return SimFrame(
        t=t, drones=drones, edges=edges,
        convoy=convoy or [], links=[], events=[],
        environment="test",
    )


def _comms_stepped(drones, edges, convoy=None) -> CommsGraph:
    comms = CommsGraph()
    comms.step(drones, edges, convoy or [])
    return comms


def test_small_yolov8n_offloads_to_parent() -> None:
    s0 = _drone("small_0", 0.0, 0.0)
    p0 = _drone("parent_0", 100.0, 0.0, tier="PARENT")
    drones = [s0, p0]

    comms = _comms_stepped(drones, [])
    frame = _frame(drones, [])
    events = ComputeScheduler().schedule_all(frame, comms)

    yolo_offload = next(
        (e for e in events if e.actor_id == "small_0" and e.task_name == "yolov8n_offload"),
        None,
    )
    assert yolo_offload is not None, "yolov8n_offload event for small_0 not found"
    assert yolo_offload.scheduled_on == "parent_0", (
        f"Expected scheduled_on=parent_0, got {yolo_offload.scheduled_on}"
    )
    assert not yolo_offload.dropped, "yolov8n_offload should not be dropped"


def test_parent_yolov8m_offloads_to_edge() -> None:
    p0 = _drone("parent_0", 0.0, 0.0, tier="PARENT")
    e0 = _edge("edge_0", 100.0, 0.0)

    comms = _comms_stepped([p0], [e0])
    frame = _frame([p0], [e0])
    events = ComputeScheduler().schedule_all(frame, comms)

    yolov8m = next(
        (e for e in events if e.actor_id == "parent_0" and e.task_name == "yolov8m_offload"),
        None,
    )
    assert yolov8m is not None, "yolov8m_offload event for parent_0 not found"
    assert yolov8m.scheduled_on == "edge_0", (
        f"Expected scheduled_on=edge_0, got {yolov8m.scheduled_on}"
    )
    assert not yolov8m.dropped, "yolov8m_offload should not be dropped"


def test_yolov8m_drops_when_all_edges_full() -> None:
    p0 = _drone("parent_0", 0.0, 0.0, tier="PARENT")
    # Edge has only 0 TOPS capacity (use an edge with compute_capacity=0)
    e0 = EdgeState(
        id="edge_0", pose=Pose(x=100.0, y=0.0, z=1.2),
        battery_pct=100.0, compute_load=1.0, alive=True,
        compute_capacity_tops=0.0,  # no headroom
        wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
        lora_radius_m=config.COMMS.lora_radius_m,
    )

    comms = _comms_stepped([p0], [e0])
    frame = _frame([p0], [e0])
    events = ComputeScheduler().schedule_all(frame, comms)

    yolov8m = next(
        (e for e in events if e.actor_id == "parent_0" and e.task_name == "yolov8m_offload"),
        None,
    )
    assert yolov8m is not None
    assert yolov8m.dropped, "yolov8m_offload should be dropped when no edge has headroom"


def test_tops_arithmetic_two_smalls_both_fit() -> None:
    s0 = _drone("small_0", 0.0, 0.0)
    s1 = _drone("small_1", 0.0, 10.0)
    p0 = _drone("parent_0", 100.0, 5.0, tier="PARENT")  # 100 TOPS
    drones = [s0, s1, p0]

    comms = _comms_stepped(drones, [])
    frame = _frame(drones, [])
    events = ComputeScheduler().schedule_all(frame, comms)

    yolo_events = [
        e for e in events
        if e.task_name == "yolov8n_offload" and e.actor_id in ("small_0", "small_1")
    ]
    assert len(yolo_events) == 2, "Both smalls should produce a yolov8n_offload event"
    # Both offload to parent_0 (8 + 8 = 16 TOPS, fits in 100)
    assert all(not e.dropped for e in yolo_events), "Both yolov8n tasks should fit in parent_0"
    assert all(e.scheduled_on == "parent_0" for e in yolo_events), (
        "Both yolov8n tasks should be scheduled on parent_0"
    )
