import math

from bridge.sim_publisher import SyntheticSimPublisher, Track2SimPublisher


def _drone(frame, actor_id):
    return next(d for d in frame.drones if d.id == actor_id)


def _dist2(a, b) -> float:
    return math.hypot(a.pose.x - b.pose.x, a.pose.y - b.pose.y)


def test_synthetic_swarm_is_not_a_fixed_ring() -> None:
    frame = SyntheticSimPublisher().frame_at(0.0)
    convoy = frame.convoy[0]
    smalls = [d for d in frame.drones if d.tier == "SMALL"]
    radii = [round(_dist2(d, convoy), 1) for d in smalls]

    assert max(radii) - min(radii) > 40.0
    assert {d.current_task for d in smalls} != {f"escort_quadrant_{i}" for i in range(6)}


def test_seeded_motion_is_repeatable_and_curved() -> None:
    first = [SyntheticSimPublisher().frame_at(t) for t in (0.0, 5.0, 10.0)]
    second = [SyntheticSimPublisher().frame_at(t) for t in (0.0, 5.0, 10.0)]

    assert [_drone(f, "small_0").pose for f in first] == [_drone(f, "small_0").pose for f in second]

    p0 = _drone(first[0], "small_0").pose
    p1 = _drone(first[1], "small_0").pose
    p2 = _drone(first[2], "small_0").pose
    triangle_area = abs(
        p0.x * (p1.y - p2.y)
        + p1.x * (p2.y - p0.y)
        + p2.x * (p0.y - p1.y)
    ) / 2.0
    assert triangle_area > 100.0


def test_swarm_motion_is_smooth_between_frames() -> None:
    pub = Track2SimPublisher(stub=True)
    prev = pub.frame_at(10.0)
    curr = pub.frame_at(10.1)

    for drone in curr.drones:
        before = _drone(prev, drone.id)
        step = math.sqrt(
            (drone.pose.x - before.pose.x) ** 2
            + (drone.pose.y - before.pose.y) ** 2
            + (drone.pose.z - before.pose.z) ** 2
        )
        assert step < 5.0, f"{drone.id} jumped {step:.2f}m between 10 Hz frames"


def test_threat_response_scouts_investigate_without_rigid_recenter() -> None:
    pub = Track2SimPublisher(stub=True)
    pub.frame_at(14.9)
    frame = pub.frame_at(20.0)

    assert _drone(frame, "small_0").current_task.startswith("investigate_threat_")
    assert _drone(frame, "small_1").current_task.startswith("investigate_threat_")
    assert _drone(frame, "parent_0").current_task == "wide_area_relay"
    assert frame.convoy[0].active_route_id != "main"

    threat = frame.threats[0].pose
    scout = _drone(frame, "small_0").pose
    assert math.hypot(scout.x - threat.x, scout.y - threat.y) < 55.0
