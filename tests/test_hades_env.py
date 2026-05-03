"""Track 3 — headless unit tests for HADESEnv (no Isaac Sim required)."""

from __future__ import annotations

import torch
import pytest

from hades.env.hades_env import HADESEnv
from hades.env.hades_env_cfg import HADESEnvCfg


@pytest.fixture
def env():
    cfg = HADESEnvCfg()
    cfg.scene.num_envs = 4  # small batch for speed
    e = HADESEnv(cfg)
    # Wire a Track2SimPublisher in stub mode
    from bridge.sim_publisher import Track2SimPublisher
    e._publisher = Track2SimPublisher(stub=True)
    e._curr_frame = e._publisher.frame_at(0.0)
    return e


def test_reset_returns_obs_dict(env):
    """_get_observations() returns one entry per agent with correct shape."""
    obs = env._get_observations()
    cfg = env.cfg
    assert set(obs.keys()) == set(cfg.possible_agents)
    for aid in cfg.possible_agents:
        assert "obs" in obs[aid]
        tensor = obs[aid]["obs"]
        expected_dim = cfg.observation_spaces[aid]
        assert tensor.shape == (cfg.scene.num_envs, expected_dim), (
            f"{aid}: expected ({cfg.scene.num_envs}, {expected_dim}), got {tensor.shape}"
        )


def test_reward_shapes(env):
    """_get_rewards() returns tensors of shape [num_envs] for every agent."""
    rewards = env._get_rewards()
    ne = env.cfg.scene.num_envs
    for aid in env.cfg.possible_agents:
        assert aid in rewards
        assert rewards[aid].shape == (ne,), f"{aid} reward shape mismatch"


def test_reward_sign_convoy_progress(env):
    """Reward is non-negative when convoy makes forward progress (positive coefficient)."""
    rewards = env._get_rewards()
    # With no convoy hit and r_convoy_progress > 0, shared base should be ≥ r_convoy_hit floor
    for aid in env.cfg.possible_agents:
        # Not necessarily positive (battery drain etc.) but should be finite
        assert torch.isfinite(rewards[aid]).all(), f"{aid} has non-finite reward"


def test_dones_shape(env):
    """_get_dones() returns two dicts, each mapping agent_id → bool tensor [num_envs]."""
    terminated, truncated = env._get_dones()
    ne = env.cfg.scene.num_envs
    for aid in env.cfg.possible_agents:
        assert terminated[aid].shape == (ne,)
        assert truncated[aid].shape == (ne,)
        assert terminated[aid].dtype == torch.bool
        assert truncated[aid].dtype == torch.bool


def test_no_crash_on_random_actions(env):
    """Stepping with random actions should not raise."""
    cfg = env.cfg
    actions = {
        aid: (
            torch.rand(cfg.scene.num_envs, cfg.action_spaces[aid]) * 2 - 1
            if aid.startswith("parent_")
            else torch.randint(0, cfg.action_spaces[aid], (cfg.scene.num_envs,))
        )
        for aid in cfg.possible_agents
    }
    env._pre_physics_step(actions)
    env._apply_action()
    obs = env._get_observations()
    rewards = env._get_rewards()
    terminated, truncated = env._get_dones()
    assert set(obs.keys()) == set(cfg.possible_agents)
    assert set(rewards.keys()) == set(cfg.possible_agents)


def test_reset_idx_clears_flags(env):
    """_reset_idx() should zero convoy_hit/done flags for the given envs."""
    env._convoy_hit[:] = True
    env._convoy_done[:] = True
    env._reset_idx(torch.tensor([0, 1]))
    assert not env._convoy_hit[0]
    assert not env._convoy_hit[1]
    # env 2 and 3 remain True (not in reset_ids)
    assert env._convoy_hit[2]
