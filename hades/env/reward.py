"""Reward calculator for the HADES convoy-escort task."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from hades.env.hades_env_cfg import HADESEnvCfg
    from hades.state import ComputeEvent, SimFrame, ThreatState


class RewardCalculator:
    """Computes per-agent and shared rewards each step.

    All rewards are returned as tensors of shape [num_envs] so SKRL MAPPO
    can broadcast them correctly.
    """

    def __init__(self, cfg: "HADESEnvCfg") -> None:
        self._cfg = cfg
        self._ne = cfg.scene.num_envs

    def compute(
        self,
        prev_frame: "SimFrame | None",
        curr_frame: "SimFrame",
        actions: dict[str, torch.Tensor],
        convoy_hit: torch.Tensor,    # bool [num_envs]
        convoy_done: torch.Tensor,   # bool [num_envs]
    ) -> dict[str, torch.Tensor]:
        """Return {agent_id: reward tensor [num_envs]}."""
        cfg = self._cfg
        ne = self._ne
        rewards: dict[str, torch.Tensor] = {}

        # ------------------------------------------------------------------
        # Shared components
        # ------------------------------------------------------------------
        # Route progress delta
        curr_progress = torch.tensor(
            [c.route_progress_pct for c in curr_frame.convoy[:1]] * ne,
            dtype=torch.float32,
        )
        if prev_frame is not None:
            prev_progress = torch.tensor(
                [c.route_progress_pct for c in prev_frame.convoy[:1]] * ne,
                dtype=torch.float32,
            )
        else:
            prev_progress = curr_progress.clone()

        progress_delta = (curr_progress - prev_progress).clamp(min=0.0)
        r_progress = cfg.r_convoy_progress * progress_delta / 100.0

        # Terminal convoy reward/penalty
        r_terminal = torch.zeros(ne)
        r_terminal += cfg.r_convoy_reached * convoy_done.float()
        r_terminal += cfg.r_convoy_hit * convoy_hit.float()

        # Threat proximity to convoy
        cx = curr_frame.convoy[0].pose.x if curr_frame.convoy else 0.0
        cy = curr_frame.convoy[0].pose.y if curr_frame.convoy else 0.0
        prox_count = sum(
            1 for th in curr_frame.threats
            if math.sqrt((th.pose.x - cx) ** 2 + (th.pose.y - cy) ** 2) < 80.0
        )
        r_threat = torch.full((ne,), cfg.r_threat_proximity * prox_count)

        # Compute drop penalty
        drops = sum(1 for ev in curr_frame.compute_events if ev.dropped)
        r_drops = torch.full((ne,), cfg.r_drop_penalty * drops)

        # Battery consumption (placeholder — all drones drain ~0.002% per step)
        r_battery = torch.full((ne,), cfg.r_battery * 8)  # 8 drones

        shared = r_progress + r_terminal + r_threat + r_drops + r_battery

        # ------------------------------------------------------------------
        # Per-agent rewards (shared + crash penalty)
        # ------------------------------------------------------------------
        for agent_id in self._cfg.possible_agents:
            drone_state = next(
                (d for d in curr_frame.drones if d.id == agent_id), None
            )
            r_crash = torch.zeros(ne)
            if drone_state is not None and drone_state.battery_pct <= 0.0:
                r_crash = torch.full((ne,), cfg.r_crash)

            rewards[agent_id] = shared + r_crash

        return rewards
