from hades.scoring import EpisodeScore, ScoreCalculator
from hades.state import CommsLink, ComputeEvent, ConvoyState, Pose, SimFrame, ThreatState


def _frame(
    *,
    progress: float = 25.0,
    links: list[CommsLink] | None = None,
    compute_events: list[ComputeEvent] | None = None,
    threats: list[ThreatState] | None = None,
) -> SimFrame:
    return SimFrame(
        t=1.0,
        convoy=[
            ConvoyState(
                id="convoy_0",
                pose=Pose(x=-580.0 + 11.6 * progress, y=0.0, z=0.8),
                speed_mps=20.0,
                route_progress_pct=progress,
            )
        ],
        links=links or [],
        compute_events=compute_events or [],
        threats=threats or [],
        environment="test",
    )


def _event(task: str, *, dropped: bool) -> ComputeEvent:
    return ComputeEvent(
        tick=1,
        actor_id="parent_0",
        task_name=task,
        tops_required=8.0,
        scheduled_on="edge_0",
        latency_ms=5.0,
        dropped=dropped,
    )


def test_episode_score_fields_populated_correctly() -> None:
    calc = ScoreCalculator()
    calc.record_step(
        _frame(
            progress=50.0,
            links=[CommsLink("parent_0", "edge_0", "WIFI_MESH", 0.8)],
            compute_events=[_event("yolov8m_offload", dropped=False)],
            threats=[
                ThreatState(
                    id="threat_0",
                    pose=Pose(x=0.0, y=80.0, z=0.0),
                    spawn_zone="choke_a",
                    confidence=1.0,
                )
            ],
        ),
        rewards={"parent_0": 1.5, "small_0": 2.5},
    )

    score = calc.finalize()

    assert isinstance(score, EpisodeScore)
    assert score.route_completion_pct == 50.0
    assert score.threats_neutralized == 1
    assert score.compute_drop_rate == 0.0
    assert score.mean_link_quality == 0.8
    assert score.total_return == 4.0
    assert score.steps == 1


def test_drop_rate_calculation() -> None:
    calc = ScoreCalculator()
    calc.record_step(
        _frame(
            compute_events=[
                _event("a", dropped=False),
                _event("b", dropped=True),
                _event("c", dropped=True),
                _event("d", dropped=False),
            ]
        )
    )

    assert calc.finalize().compute_drop_rate == 0.5


def test_zero_step_edge_case() -> None:
    score = ScoreCalculator().finalize()

    assert score == EpisodeScore(
        convoy_survived=False,
        route_completion_pct=0.0,
        threats_neutralized=0,
        compute_drop_rate=0.0,
        mean_link_quality=0.0,
        total_return=0.0,
        steps=0,
    )


def test_full_route_completion_flag() -> None:
    calc = ScoreCalculator()
    calc.record_step(_frame(progress=100.0))

    score = calc.finalize()

    assert score.convoy_survived is True
    assert score.route_completion_pct == 100.0
