from hades.comms import CommsGraph
from hades.state import DroneState, EdgeState, Pose


def _drone(id: str, x: float, y: float, z: float = 18.0, tier: str = "SMALL") -> DroneState:
    return DroneState(
        id=id, tier=tier, pose=Pose(x=x, y=y, z=z),
        battery_pct=90.0, compute_load=0.1, current_task="test",
    )


def _edge(id: str, x: float, y: float) -> EdgeState:
    from hades import config
    return EdgeState(
        id=id, pose=Pose(x=x, y=y, z=1.2),
        battery_pct=100.0, compute_load=0.1, alive=True,
        compute_capacity_tops=config.COMPUTE.edge_tops,
        wifi_radius_m=config.COMMS.wifi_mesh_radius_m,
        lora_radius_m=config.COMMS.lora_radius_m,
    )


def test_small_to_small_wifi_range_gating() -> None:
    comms = CommsGraph()
    s0 = _drone("small_0", 0.0, 0.0)
    s1_near = _drone("small_1", 100.0, 0.0)   # 100m — within WiFi 150m
    s1_far  = _drone("small_1", 200.0, 0.0)   # 200m — beyond WiFi 150m

    comms.step([s0, s1_near], [], [])
    assert comms.reachable("small_0", "small_1"), "small↔small within 150m should be reachable"

    comms.step([s0, s1_far], [], [])
    assert not comms.reachable("small_0", "small_1"), "small↔small beyond 150m should be blocked"


def test_small_to_static_edge_direct_forbidden() -> None:
    comms = CommsGraph()
    s0 = _drone("small_0", 0.0, 0.0)
    e0 = _edge("edge_0", 50.0, 0.0)  # only 50m away — well within WiFi

    comms.step([s0], [e0], [])
    assert not comms.reachable("small_0", "edge_0"), "small→static edge direct link must be FORBIDDEN"


def test_small_reaches_edge_via_parent_relay() -> None:
    comms = CommsGraph()
    # small_0 → parent_0 (100m WiFi) → edge_0 (100m WiFi from parent)
    # small_0 is 300m from edge_0 — no direct link possible (forbidden anyway)
    s0 = _drone("small_0", 0.0, 0.0)
    p0 = _drone("parent_0", 100.0, 0.0, tier="PARENT")
    e0 = _edge("edge_0", 200.0, 0.0)

    comms.step([s0, p0], [e0], [])

    assert comms.reachable("small_0", "parent_0"), "small→parent direct link should exist"
    assert comms.reachable("parent_0", "edge_0"), "parent→edge direct link should exist"
    assert not comms.reachable("small_0", "edge_0"), "small→edge direct still FORBIDDEN"

    path = comms.relay_path("small_0", "edge_0")
    assert path == ["small_0", "parent_0", "edge_0"], f"Expected 3-hop relay path, got {path}"


def test_small_parent_lora_fallback() -> None:
    comms = CommsGraph()
    # 300m — beyond WiFi (150m) but within LoRa (2000m)
    s0 = _drone("small_0", 0.0, 0.0)
    p0 = _drone("parent_0", 300.0, 0.0, tier="PARENT")

    comms.step([s0, p0], [], [])

    assert comms.reachable("small_0", "parent_0"), "small↔parent at 300m should use LoRa fallback"

    lk = next(
        lk for lk in comms.links()
        if {lk.from_id, lk.to_id} == {"small_0", "parent_0"}
    )
    assert lk.type == "LORA", f"Link type should be LORA, got {lk.type}"
