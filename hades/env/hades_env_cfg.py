"""HADESEnvCfg — DirectMARLEnvCfg for the convoy-escort task."""

from __future__ import annotations

try:
    from isaaclab.envs import DirectMARLEnvCfg
    from isaaclab.sim import SimulationCfg
    from isaaclab.utils import configclass
    from hades.env.scene_cfg import HADESSceneCfg

    @configclass
    class HADESEnvCfg(DirectMARLEnvCfg):
        """Configuration for the HADES convoy-escort MARL environment.

        8 RL agents: 2 parent drones + 6 small drones.
        Convoy is rule-based (ConvoyRouter Dijkstra) — not an RL agent.
        """

        # Simulation: 10 Hz physics
        sim: SimulationCfg = SimulationCfg(dt=0.1, render_interval=1)

        # Scene: 64 parallel episodes on a single GPU
        scene: HADESSceneCfg = HADESSceneCfg(num_envs=64, env_spacing=200.0)

        # Episode length: 600 steps = 60 seconds at 10 Hz
        episode_length_s: float = 60.0

        # ------------------------------------------------------------------
        # Agent spaces
        # ------------------------------------------------------------------
        possible_agents: list[str] = (
            ["parent_0", "parent_1"] + [f"small_{i}" for i in range(6)]
        )

        # Observation dimensions per agent tier (visual embeddings added in ObsBuilder)
        observation_spaces: dict = {
            "parent_0": 64,
            "parent_1": 64,
            **{f"small_{i}": 32 for i in range(6)},
        }

        # Action spaces:
        #   parents → Box(4): [vx, vy, vz, yaw_rate] clipped [-1, 1]
        #   smalls  → Discrete(7): HOLD/N/S/E/W/UP/RELAY
        action_spaces: dict = {
            "parent_0": 4,
            "parent_1": 4,
            **{f"small_{i}": 7 for i in range(6)},
        }

        # No centralised state tensor needed — critic uses concatenated obs
        state_space: int = 0

        # ------------------------------------------------------------------
        # Reward coefficients
        # ------------------------------------------------------------------
        r_convoy_progress: float = 5.0
        r_convoy_reached: float = 50.0
        r_convoy_hit: float = -100.0
        r_threat_proximity: float = -0.1   # per threat within 80 m of convoy
        r_detect_new: float = 2.0
        r_coverage: float = 0.1
        r_relay_link: float = 0.3
        r_drop_penalty: float = -0.1
        r_battery: float = -0.01
        r_crash: float = -50.0

except ImportError:
    # Headless / test mode — provide a plain dataclass substitute
    from dataclasses import dataclass, field

    @dataclass
    class _SimCfg:
        dt: float = 0.1
        render_interval: int = 1

    @dataclass
    class _SceneCfg:
        num_envs: int = 64
        env_spacing: float = 200.0

    @dataclass
    class HADESEnvCfg:  # type: ignore[no-redef]
        sim: _SimCfg = field(default_factory=_SimCfg)
        scene: _SceneCfg = field(default_factory=_SceneCfg)
        episode_length_s: float = 60.0

        possible_agents: list = field(default_factory=lambda: (
            ["parent_0", "parent_1"] + [f"small_{i}" for i in range(6)]
        ))
        observation_spaces: dict = field(default_factory=lambda: {
            "parent_0": 64, "parent_1": 64,
            **{f"small_{i}": 32 for i in range(6)},
        })
        action_spaces: dict = field(default_factory=lambda: {
            "parent_0": 4, "parent_1": 4,
            **{f"small_{i}": 7 for i in range(6)},
        })
        state_space: int = 0

        r_convoy_progress: float = 5.0
        r_convoy_reached: float = 50.0
        r_convoy_hit: float = -100.0
        r_threat_proximity: float = -0.1
        r_detect_new: float = 2.0
        r_coverage: float = 0.1
        r_relay_link: float = 0.3
        r_drop_penalty: float = -0.1
        r_battery: float = -0.01
        r_crash: float = -50.0
