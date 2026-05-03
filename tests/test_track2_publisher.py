from bridge.sim_publisher import Track2SimPublisher


def _pub() -> Track2SimPublisher:
    return Track2SimPublisher(stub=True)


def test_threats_appear_at_t15() -> None:
    frame = _pub().frame_at(15.1)
    assert len(frame.threats) == 2, f"Expected 2 threats at t=15.1, got {len(frame.threats)}"
    assert all(th.spawn_zone == "choke_a" for th in frame.threats), (
        "All threats should be in choke_a zone"
    )


def test_no_threats_before_t15() -> None:
    frame = _pub().frame_at(14.9)
    assert len(frame.threats) == 0, f"Expected 0 threats at t=14.9, got {len(frame.threats)}"


def test_convoy_reroutes_after_threat() -> None:
    pub = _pub()
    frame_before = pub.frame_at(14.9)
    assert frame_before.convoy[0].active_route_id == "main"

    # Same publisher instance — threats appear at t=15.1, route should switch
    frame_after = pub.frame_at(15.1)
    assert frame_after.convoy[0].active_route_id != "main", (
        f"Convoy should reroute away from 'main' after choke_a threat; "
        f"got {frame_after.convoy[0].active_route_id!r}"
    )


def test_compute_events_present() -> None:
    frame = _pub().frame_at(5.0)
    assert len(frame.compute_events) > 0, "compute_events should be non-empty at t=5.0"
    non_dropped = [e for e in frame.compute_events if not e.dropped]
    assert non_dropped, "At least one compute event should not be dropped"


def test_to_dict_preserves_phase1_shape() -> None:
    frame = _pub().frame_at(15.1)
    payload = frame.to_dict()
    assert set(payload) == {"t", "drones", "edges", "convoy", "links", "events", "environment"}, (
        f"to_dict() must emit exactly the Phase 1 keys; got {set(payload)}"
    )


def test_to_full_dict_includes_track2_fields() -> None:
    frame = _pub().frame_at(15.1)
    full = frame.to_full_dict()
    assert "threats" in full, "to_full_dict() must include 'threats'"
    assert "compute_events" in full, "to_full_dict() must include 'compute_events'"
    assert len(full["threats"]) == 2
