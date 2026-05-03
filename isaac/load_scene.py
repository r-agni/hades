"""Load the HADES Phase 1 scene inside Isaac Sim.

Usage (pip-installed Isaac Sim 5.1):

    python load_scene.py [path/to/scene.usda] [--headless]

SimulationApp must be created before any omni/carb imports so that the Kit
kernel is bootstrapped first.
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

# Bootstrap Kit kernel before any omni/carb imports
from isaacsim import SimulationApp

_headless = "--headless" in sys.argv or True   # always headless on the remote H100
_sim_app = SimulationApp({"headless": _headless, "anti_aliasing": 0})

import carb  # noqa: E402 — must be after SimulationApp
import omni.kit.app  # noqa: E402
import omni.usd  # noqa: E402
from omni.isaac.core import World  # noqa: E402
from omni.isaac.core.prims import RigidPrim, XFormPrim  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402


# ---------------------------------------------------------------------------
# Actor layout — must match scene.usda and hades/config.py
# ---------------------------------------------------------------------------

ROUTE_START_X = -580.0
ROUTE_END_X = 580.0
ROUTE_LENGTH = ROUTE_END_X - ROUTE_START_X
EDGE_COUNT = 18

PARENT_HOVER_Z = 34.0
SMALL_HOVER_Z = 18.0
SMALL_RING_R = 24.0
PARENT_Y_OFF = 32.0
EDGE_Y_OFF = 42.0


def _edge_positions() -> list[tuple[float, float, float]]:
    step = ROUTE_LENGTH / (EDGE_COUNT - 1)
    positions = []
    for i in range(EDGE_COUNT):
        x = ROUTE_START_X + i * step
        y = EDGE_Y_OFF * (-1.0 if i % 2 else 1.0)
        positions.append((x, y, 1.2))
    return positions


def _small_positions() -> list[tuple[float, float, float]]:
    convoy_x = ROUTE_START_X
    positions = []
    for i in range(6):
        angle = 2.0 * math.pi * i / 6
        x = convoy_x + SMALL_RING_R * math.cos(angle)
        y = SMALL_RING_R * math.sin(angle)
        positions.append((x, y, SMALL_HOVER_Z))
    return positions


ACTOR_PRIMS: dict[str, list[tuple[str, tuple[float, float, float]]]] = {
    "parents": [
        ("parent_0", (ROUTE_START_X - 18.0, PARENT_Y_OFF, PARENT_HOVER_Z)),
        ("parent_1", (ROUTE_START_X + 18.0, -PARENT_Y_OFF, PARENT_HOVER_Z)),
    ],
    "smalls": [(f"small_{i}", pos) for i, pos in enumerate(_small_positions())],
    "edges": [(f"edge_{i}", pos) for i, pos in enumerate(_edge_positions())],
    "convoy": [
        ("convoy_0", (ROUTE_START_X, -3.0, 0.8)),
        ("convoy_1", (ROUTE_START_X - 14.0, 3.0, 0.8)),
    ],
}


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------

def _log(msg: str) -> None:
    carb.log_info(f"[HADES load_scene] {msg}")
    print(f"[HADES load_scene] {msg}", flush=True)


async def _open_stage(path: str) -> None:
    ctx = omni.usd.get_context()
    ok, err = await ctx.open_stage_async(path)
    if not ok:
        raise RuntimeError(f"Failed to open stage: {err}")
    app = omni.kit.app.get_app()
    for _ in range(10):
        await app.next_update_async()
    _log(f"Stage opened: {path}")


def _register_actors(world: World) -> None:
    """Set world-frame positions on every actor prim and register with the world."""
    stage = omni.usd.get_context().get_stage()
    root = "/hades_phase_1"

    for group, entries in ACTOR_PRIMS.items():
        for prim_name, (x, y, z) in entries:
            prim_path = f"{root}/{prim_name}"
            prim = stage.GetPrimAtPath(prim_path)
            if not prim.IsValid():
                _log(f"WARNING: prim not found in stage: {prim_path}")
                continue

            xformable = UsdGeom.Xformable(prim)
            xformable.ClearXformOpOrder()
            translate_op = xformable.AddTranslateOp()
            translate_op.Set(Gf.Vec3d(x, y, z))

            if group in ("parents", "smalls", "convoy"):
                world.scene.add(RigidPrim(prim_path=prim_path, name=prim_name))
            else:
                world.scene.add(XFormPrim(prim_path=prim_path, name=prim_name))

            _log(f"Registered {prim_name} at ({x:.1f}, {y:.1f}, {z:.1f})")


async def _run(stage_path: str) -> None:
    await _open_stage(stage_path)

    world = World(stage_units_in_meters=1.0)
    await world.initialize_simulation_context_async()

    _register_actors(world)
    await world.reset_async()

    _log("Simulation running — press Ctrl+C to stop")
    app = omni.kit.app.get_app()
    while True:
        world.step(render=True)
        await app.next_update_async()


def main() -> None:
    # Skip --headless flag when parsing positional stage path
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    stage_path = positional[0] if positional else str(Path(__file__).with_name("scene.usda"))

    try:
        asyncio.ensure_future(_run(stage_path))
    finally:
        _sim_app.close()


main()
