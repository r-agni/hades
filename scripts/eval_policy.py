"""Load a MAPPO checkpoint and evaluate over N episodes, printing EpisodeScore."""

from __future__ import annotations

import argparse
import statistics

from isaacsim import SimulationApp
_app = SimulationApp({"headless": True, "anti_aliasing": 0})

import torch

from hades.env.hades_env import HADESEnv
from hades.env.hades_env_cfg import HADESEnvCfg


def parse_args():
    p = argparse.ArgumentParser(description="Evaluate HADES MAPPO checkpoint")
    p.add_argument("--checkpoint-dir", required=True, help="Directory with saved SKRL agents")
    p.add_argument("--episodes", type=int, default=10)
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    return p.parse_args()


def main():
    args = parse_args()

    cfg = HADESEnvCfg()
    cfg.scene.num_envs = 1
    env = HADESEnv(cfg)

    episode_returns: list[float] = []

    for ep in range(args.episodes):
        obs = env.reset()
        done = False
        ep_return = 0.0
        steps = 0

        while not done:
            # Random policy for eval scaffold — replace with loaded agents
            actions = {
                aid: (
                    torch.rand(1, cfg.action_spaces[aid]) * 2 - 1
                    if aid.startswith("parent_")
                    else torch.randint(0, cfg.action_spaces[aid], (1,))
                )
                for aid in cfg.possible_agents
            }

            obs, rewards, terminated, truncated, _ = env.step(actions)
            ep_return += sum(float(r[0]) for r in rewards.values())
            done = any(terminated[aid][0] or truncated[aid][0]
                       for aid in cfg.possible_agents)
            steps += 1

        episode_returns.append(ep_return)
        print(f"Episode {ep+1:3d} | steps={steps:4d} | return={ep_return:8.2f}")

    mean = statistics.mean(episode_returns)
    std  = statistics.stdev(episode_returns) if len(episode_returns) > 1 else 0.0
    print(f"\nEpisodeScore  mean={mean:.2f}  std={std:.2f}  n={args.episodes}")
    _app.close()


if __name__ == "__main__":
    main()
