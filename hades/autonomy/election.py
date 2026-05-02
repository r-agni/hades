"""Minimal parent re-election state machine.

Parents heartbeat each other over LoRa at 1 Hz.  If a parent misses
3 consecutive heartbeats the surviving parent absorbs all orphaned smalls.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

_HEARTBEAT_INTERVAL_S = 1.0
_MISSED_THRESHOLD = 3


@dataclass
class ParentHeartbeat:
    parent_id: str
    timestamp: float = field(default_factory=time.monotonic)
    small_ids: list[str] = field(default_factory=list)


class ElectionState:
    """Tracks liveness of peer parents and fires a callback on failure."""

    def __init__(self, own_id: str, on_absorb_smalls=None) -> None:
        self._own_id = own_id
        self._last_seen: dict[str, float] = {}
        self._peer_smalls: dict[str, list[str]] = {}
        self._on_absorb = on_absorb_smalls  # callable(list[str]) | None

    def receive_heartbeat(self, hb: ParentHeartbeat) -> None:
        if hb.parent_id == self._own_id:
            return
        self._last_seen[hb.parent_id] = hb.timestamp
        self._peer_smalls[hb.parent_id] = list(hb.small_ids)

    def tick(self, now: float | None = None) -> list[str]:
        """Call once per second. Returns small_ids absorbed this tick."""
        now = now if now is not None else time.monotonic()
        absorbed: list[str] = []
        for peer_id, last in list(self._last_seen.items()):
            if (now - last) / _HEARTBEAT_INTERVAL_S >= _MISSED_THRESHOLD:
                orphans = self._peer_smalls.pop(peer_id, [])
                del self._last_seen[peer_id]
                absorbed.extend(orphans)
                if self._on_absorb and orphans:
                    self._on_absorb(orphans)
        return absorbed

    def peer_alive(self, peer_id: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        last = self._last_seen.get(peer_id)
        return last is not None and (now - last) / _HEARTBEAT_INTERVAL_S < _MISSED_THRESHOLD
