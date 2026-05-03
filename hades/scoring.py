"""Episode scoring for HADES demo and policy evaluation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from hades.state import SimFrame


@dataclass(frozen=True)
class EpisodeScore:
    convoy_survived: bool
    route_completion_pct: float
    threats_neutralized: int
    compute_drop_rate: float
    mean_link_quality: float
    total_return: float
    steps: int


class ScoreCalculator:
    """Accumulates per-step telemetry and returns an EpisodeScore.

    The current state model has threat detection confidence but no explicit
    "destroyed" or "cleared" threat field. For Track 4 scoring, a neutralized
    threat is a confirmed threat that did not kill the convoy by episode end.
    """

    def __init__(
        self,
        *,
        completion_threshold_pct: float = 100.0,
        convoy_hit_radius_m: float = 20.0,
        confirmed_threat_confidence: float = 0.5,
    ) -> None:
        self._completion_threshold_pct = completion_threshold_pct
        self._convoy_hit_radius_m = convoy_hit_radius_m
        self._confirmed_threat_confidence = confirmed_threat_confidence
        self.reset()

    def reset(self) -> None:
        self._steps = 0
        self._max_route_completion_pct = 0.0
        self._total_compute_events = 0
        self._dropped_compute_events = 0
        self._link_quality_sum = 0.0
        self._link_quality_count = 0
        self._total_return = 0.0
        self._convoy_hit = False
        self._confirmed_threat_ids: set[str] = set()

    def record_step(
        self,
        frame: SimFrame,
        rewards: Any = None,
        *,
        convoy_hit: bool | None = None,
    ) -> None:
        self._steps += 1

        if frame.convoy:
            completion = max(c.route_progress_pct for c in frame.convoy)
            self._max_route_completion_pct = max(
                self._max_route_completion_pct,
                float(completion),
            )

        for event in frame.compute_events:
            self._total_compute_events += 1
            if event.dropped:
                self._dropped_compute_events += 1

        for link in frame.links:
            self._link_quality_sum += float(link.quality)
            self._link_quality_count += 1

        self._total_return += self._reward_sum(rewards)

        for threat in frame.threats:
            if threat.confidence >= self._confirmed_threat_confidence or threat.detected_by:
                self._confirmed_threat_ids.add(threat.id)

        if convoy_hit is None:
            convoy_hit = self._infer_convoy_hit(frame)
        self._convoy_hit = self._convoy_hit or bool(convoy_hit)

    def finalize(self) -> EpisodeScore:
        drop_rate = (
            self._dropped_compute_events / self._total_compute_events
            if self._total_compute_events
            else 0.0
        )
        mean_link_quality = (
            self._link_quality_sum / self._link_quality_count
            if self._link_quality_count
            else 0.0
        )
        convoy_survived = (
            self._max_route_completion_pct >= self._completion_threshold_pct
            and not self._convoy_hit
        )
        threats_neutralized = len(self._confirmed_threat_ids) if not self._convoy_hit else 0
        return EpisodeScore(
            convoy_survived=convoy_survived,
            route_completion_pct=round(self._max_route_completion_pct, 3),
            threats_neutralized=threats_neutralized,
            compute_drop_rate=round(drop_rate, 6),
            mean_link_quality=round(mean_link_quality, 6),
            total_return=round(self._total_return, 6),
            steps=self._steps,
        )

    def _infer_convoy_hit(self, frame: SimFrame) -> bool:
        if not frame.convoy or not frame.threats:
            return False
        for convoy in frame.convoy:
            for threat in frame.threats:
                dist = math.hypot(
                    threat.pose.x - convoy.pose.x,
                    threat.pose.y - convoy.pose.y,
                )
                if dist < self._convoy_hit_radius_m:
                    return True
        return False

    @staticmethod
    def _reward_sum(rewards: Any) -> float:
        if rewards is None:
            return 0.0
        if isinstance(rewards, (int, float)):
            return float(rewards)
        if isinstance(rewards, dict):
            return sum(ScoreCalculator._reward_sum(value) for value in rewards.values())
        if hasattr(rewards, "detach") and callable(rewards.detach):
            rewards = rewards.detach()
        if hasattr(rewards, "sum") and callable(rewards.sum):
            summed = rewards.sum()
            if hasattr(summed, "item") and callable(summed.item):
                return float(summed.item())
            return float(summed)
        if isinstance(rewards, (list, tuple)):
            return sum(ScoreCalculator._reward_sum(value) for value in rewards)
        return 0.0
