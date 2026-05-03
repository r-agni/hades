"""Threat spawner for the HADES simulation."""

from __future__ import annotations

import random

from hades.state import Pose, ThreatState


SPAWN_ZONES: dict[str, dict] = {
    "choke_a": {"center": (0.0, 0.0),    "radius_m": 80.0},
    "flank_b": {"center": (220.0, 180.0), "radius_m": 60.0},
}


class ThreatSpawner:
    """Spawns and manages threats in the scene.

    Modes:
    - ``deterministic``: 2 threats appear at choke_a at t=15s (Track 2).
    - ``poisson``: random Poisson-rate arrivals per zone (Track 3).
    """

    def __init__(self, mode: str = "deterministic", seed: int = 42) -> None:
        self._mode = mode
        self._seed = seed
        self._threats: list[ThreatState] = []
        self._next_threat_idx: int = 0
        self._rng = random.Random(seed)
        self._poisson_next_t: dict[str, float] = {}

    def step(self, t: float) -> list[ThreatState]:
        """Advance simulation by one step and return the current threat list."""
        if self._mode == "deterministic":
            self._step_deterministic(t)
        else:
            self._step_poisson(t)
        return list(self._threats)

    def reset(self, env_ids=None) -> None:
        self._threats = []
        self._next_threat_idx = 0
        self._rng = random.Random(self._seed)
        self._poisson_next_t = {}

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _step_deterministic(self, t: float) -> None:
        if t >= 15.0 and not self._threats:
            cx, cy = SPAWN_ZONES["choke_a"]["center"]
            self._threats = [
                ThreatState(
                    id=f"threat_{i}",
                    pose=Pose(x=cx + 10.0 * (i - 0.5), y=cy, z=0.0),
                    spawn_zone="choke_a",
                    confidence=1.0,
                    detected_by=[],
                )
                for i in range(2)
            ]

    def _step_poisson(self, t: float) -> None:
        for zone_name, zone in SPAWN_ZONES.items():
            if zone_name not in self._poisson_next_t:
                # Mean inter-arrival: 20 seconds
                self._poisson_next_t[zone_name] = t + self._rng.expovariate(1 / 20.0)

            if t >= self._poisson_next_t[zone_name]:
                cx, cy = zone["center"]
                r = zone["radius_m"]
                # Random point within radius
                angle = self._rng.uniform(0, 6.283185)
                dist = self._rng.uniform(0, r)
                px = cx + dist * (dist ** 0.5 / r) * (1 if self._rng.random() > 0.5 else -1)
                py = cy + dist * (dist ** 0.5 / r) * (1 if self._rng.random() > 0.5 else -1)
                tid = f"threat_{self._next_threat_idx}"
                self._next_threat_idx += 1
                self._threats.append(
                    ThreatState(
                        id=tid,
                        pose=Pose(x=px, y=py, z=0.0),
                        spawn_zone=zone_name,
                        confidence=0.5,
                        detected_by=[],
                    )
                )
                self._poisson_next_t[zone_name] = t + self._rng.expovariate(1 / 20.0)
