from bridge.demo_publisher import DemoSimPublisher
from bridge.sim_publisher import SyntheticSimPublisher
from hades import config
from hades.autonomy.comms import CommsModel
from hades.autonomy.offload_policy import HeuristicOffloadPolicy, OffloadCtx, Task
from hades.state import DroneState, Pose


def test_comms_handles_no_parent_drones() -> None:
    small = DroneState(
        id="small_0",
        tier="SMALL",
        pose=Pose(0.0, 0.0, 10.0),
        battery_pct=90.0,
        compute_load=0.1,
        current_task="escort",
    )

    assert CommsModel().tick([small], []) == []


def test_local_compute_uses_compute_latency_without_wifi_transfer() -> None:
    task = Task(id="task_local", compute_cost_gflops=200.0, latency_budget_ms=120.0)
    ctx = OffloadCtx(
        own_id="parent_0",
        own_load=0.1,
        own_battery_pct=98.0,
        own_tops=config.COMPUTE.parent_tops,
    )

    chosen, event = HeuristicOffloadPolicy().decide(task, ctx)

    assert chosen == "parent_0"
    assert event.reason == "no_wifi_in_range"
    assert event.expected_latency_ms == 2.2


def test_threat_injection_dispatches_one_small_team() -> None:
    pub = DemoSimPublisher()

    frame = pub.frame_at(60.0)

    investigating = [
        drone for drone in frame.drones if drone.current_task == "investigate_threat"
    ]
    assert len(investigating) == 2
