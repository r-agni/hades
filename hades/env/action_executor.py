"""Map RL action tensors to physical commands for each agent tier."""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import torch

if TYPE_CHECKING:
    from hades.state import DroneState, SimFrame

# Small drone discrete action indices (must match obs_builder.py)
HOLD, MOVE_N, MOVE_S, MOVE_E, MOVE_W, MOVE_UP, RELAY = range(7)

# Physical limits
VX_MAX = 15.0       # m/s horizontal
VZ_MAX = 5.0        # m/s vertical
YAW_MAX = math.pi / 4  # rad/s

# Small drone step size (1 action = 1 s at low speed)
SMALL_STEP = 5.0    # m per discrete move


class ActionExecutor:
    """Converts per-agent RL output to velocity/waypoint commands.

    Returns a dict {agent_id: command_dict} where command_dict has:
      parent agents: {"vx", "vy", "vz", "yaw_rate"}  (physical m/s, rad/s)
      small agents:  {"dx", "dy", "dz", "relay"}       (displacement m, relay flag)

    All math is done on env-0 only (index 0) since the sim publisher is
    single-env; the remaining [num_envs-1] envs are training copies.
    """

    def __init__(self, cfg) -> None:
        self._cfg = cfg

    def execute(
        self,
        actions: dict[str, torch.Tensor],
        curr_frame: "SimFrame",
    ) -> dict[str, dict]:
        commands: dict[str, dict] = {}
        for agent_id, action in actions.items():
            if agent_id.startswith("parent_"):
                commands[agent_id] = self._parent_cmd(action)
            else:
                commands[agent_id] = self._small_cmd(action)
        return commands

    # ------------------------------------------------------------------
    # Parent: continuous Box(4) → physical velocities
    # ------------------------------------------------------------------
    def _parent_cmd(self, action: torch.Tensor) -> dict:
        # action shape: [num_envs, 4] or [4] — use env-0
        a = action[0] if action.dim() > 1 else action
        a = a.clamp(-1.0, 1.0)
        return {
            "vx":       float(a[0]) * VX_MAX,
            "vy":       float(a[1]) * VX_MAX,
            "vz":       float(a[2]) * VZ_MAX,
            "yaw_rate": float(a[3]) * YAW_MAX,
        }

    # ------------------------------------------------------------------
    # Small: Discrete(7) → displacement + relay flag
    # ------------------------------------------------------------------
    def _small_cmd(self, action: torch.Tensor) -> dict:
        # action shape: [num_envs] or scalar — use env-0
        idx = int(action[0].item()) if action.dim() > 0 else int(action.item())
        dx = dy = dz = 0.0
        relay = False
        if idx == MOVE_N:
            dy = SMALL_STEP
        elif idx == MOVE_S:
            dy = -SMALL_STEP
        elif idx == MOVE_E:
            dx = SMALL_STEP
        elif idx == MOVE_W:
            dx = -SMALL_STEP
        elif idx == MOVE_UP:
            dz = SMALL_STEP
        elif idx == RELAY:
            relay = True
        return {"dx": dx, "dy": dy, "dz": dz, "relay": relay}
