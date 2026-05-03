"""Load the HADES scene inside Isaac Sim and keep it running."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from isaacsim import SimulationApp


_headless = "--headless" in sys.argv or True
_sim_app = SimulationApp({"headless": _headless, "anti_aliasing": 0})

import carb  # noqa: E402
import omni.kit.app  # noqa: E402
import omni.usd  # noqa: E402
from omni.isaac.core import World  # noqa: E402
from omni.isaac.core.prims import RigidPrim, XFormPrim  # noqa: E402
from pxr import Gf, UsdGeom  # noqa: E402

from hades.layout import EDGE_DEPLOYMENTS, convoy_deployments, parent_deployments, small_deployments  # noqa: E402
from hades.cesium import runtime_config  # noqa: E402


ACTOR_PRIMS: dict[str, list[tuple[str, tuple[float, float, float], float]]] = {
    "parents": [(p.id, (p.x, p.y, p.z), p.yaw_deg) for p in parent_deployments()],
    "smalls": [(p.id, (p.x, p.y, p.z), p.yaw_deg) for p in small_deployments()],
    "edges": [(p.id, (p.x, p.y, p.z), p.yaw_deg) for p in EDGE_DEPLOYMENTS],
    "convoy": [(p.id, (p.x, p.y, p.z), p.yaw_deg) for p in convoy_deployments()],
}


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


def _apply_cesium_env() -> None:
    """Inject Cesium token/georeference settings when available."""
    if not os.environ.get("CESIUM_ION_TOKEN"):
        _log("CESIUM_ION_TOKEN not set; Cesium terrain may not stream.")
        return

    cfg = runtime_config(require_token=True)
    stage = omni.usd.get_context().get_stage()
    updates = {
        "/CesiumGeoreference": {
            "cesium:georeferenceOrigin:latitude": cfg.latitude_deg,
            "cesium:georeferenceOrigin:longitude": cfg.longitude_deg,
            "cesium:georeferenceOrigin:height": cfg.height_m,
        },
        "/Cesium_World_Terrain": {"cesium:ionAccessToken": cfg.ion_token},
        "/Cesium_World_Terrain/Bing_Maps_Aerial_imagery": {"cesium:ionAccessToken": cfg.ion_token},
        "/CesiumServers/IonOfficial": {"cesium:projectDefaultIonAccessToken": cfg.ion_token},
    }
    for prim_path, attrs in updates.items():
        prim = stage.GetPrimAtPath(prim_path)
        if not prim.IsValid():
            _log(f"WARNING: Cesium prim not found: {prim_path}")
            continue
        for attr_name, value in attrs.items():
            attr = prim.GetAttribute(attr_name)
            if attr.IsValid():
                attr.Set(value)
    _log("Applied Cesium ion token and georeference settings from environment.")


def _register_actors(world: World) -> None:
    stage = omni.usd.get_context().get_stage()
    root = "/hades_phase_1"

    for group, entries in ACTOR_PRIMS.items():
        for prim_name, (x, y, z), yaw_deg in entries:
            prim_path = f"{root}/{prim_name}"
            prim = stage.GetPrimAtPath(prim_path)
            if not prim.IsValid():
                _log(f"WARNING: prim not found in stage: {prim_path}")
                continue

            xformable = UsdGeom.Xformable(prim)
            translate_op = None
            rotate_op = None
            for op in xformable.GetOrderedXformOps():
                if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                    translate_op = op
                elif op.GetOpType() == UsdGeom.XformOp.TypeRotateXYZ:
                    rotate_op = op

            if translate_op is None:
                translate_op = xformable.AddTranslateOp()
            translate_op.Set(Gf.Vec3d(x, y, z))
            if rotate_op is None:
                rotate_op = xformable.AddRotateXYZOp()
            rotate_op.Set(Gf.Vec3f(0.0, 0.0, yaw_deg))

            if group in ("parents", "smalls", "convoy"):
                world.scene.add(RigidPrim(prim_path=prim_path, name=prim_name))
            else:
                world.scene.add(XFormPrim(prim_path=prim_path, name=prim_name))

            _log(f"Registered {prim_name} at ({x:.1f}, {y:.1f}, {z:.1f}), yaw={yaw_deg:.1f}")


async def _run(stage_path: str) -> None:
    await _open_stage(stage_path)
    _apply_cesium_env()

    world = World(stage_units_in_meters=1.0)
    await world.initialize_simulation_context_async()

    _register_actors(world)
    await world.reset_async()

    _log("Simulation running - press Ctrl+C to stop")
    app = omni.kit.app.get_app()
    while True:
        world.step(render=True)
        await app.next_update_async()


def main() -> None:
    positional = [a for a in sys.argv[1:] if not a.startswith("--")]
    stage_path = positional[0] if positional else str(Path(__file__).with_name("scene.usda"))

    try:
        asyncio.get_event_loop().run_until_complete(_run(stage_path))
    finally:
        _sim_app.close()


main()
