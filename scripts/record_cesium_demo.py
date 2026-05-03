"""Record the HADES demo from Isaac Sim with Cesium for Omniverse terrain.

Run inside an Isaac Sim 6.0 / Kit 109 process or container after installing
Cesium for Omniverse v0.28.0:

  export CESIUM_ION_TOKEN=...
  python scripts/record_cesium_demo.py --duration-s 30 --fps 10
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hades.cesium import assert_isaac_runtime_compatible, runtime_config  # noqa: E402
from scripts.cesium_presentation import apply_actor_presentation, configure_cesium_map, update_visual_markers  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=ROOT / "isaac" / "scene.usda")
    parser.add_argument("--out-dir", type=Path, default=Path("/opt/hades/recordings"))
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--settle-frames", type=int, default=8)
    parser.add_argument("--initial-settle-frames", type=int, default=90)
    parser.add_argument("--extension-dir", type=Path, default=Path.home() / "Documents" / "Kit" / "Shared" / "exts")
    parser.add_argument("--camera", default="/hades_phase_1/RecordCamera")
    parser.add_argument("--map-mode", choices=("world-terrain", "photorealistic"), default="photorealistic")
    return parser.parse_args()


def _setting(settings, *keys: str) -> str | None:
    for key in keys:
        try:
            value = settings.get(key)
        except Exception:
            continue
        if value:
            return str(value)
    return None


def _runtime_versions() -> tuple[str | None, str | None]:
    import carb
    import omni.kit.app

    settings = carb.settings.get_settings()
    app_version = _setting(settings, "/app/version", "/app/appVersion")
    build_version = _setting(settings, "/app/buildVersion", "/app/kitVersion")

    app = omni.kit.app.get_app()
    for attr_name in ("get_app_version", "get_version"):
        attr = getattr(app, attr_name, None)
        if attr is not None and app_version is None:
            try:
                app_version = str(attr())
            except Exception:
                pass
    attr = getattr(app, "get_build_version", None)
    if attr is not None and build_version is None:
        try:
            build_version = str(attr())
        except Exception:
            pass
    return app_version, build_version


def _add_extension_path(extension_dir: Path) -> None:
    import carb
    import omni.kit.app

    if not extension_dir.exists():
        return
    manager = omni.kit.app.get_app().get_extension_manager()
    add_path = getattr(manager, "add_path", None)
    if add_path is not None:
        add_path(str(extension_dir))
        return

    settings = carb.settings.get_settings()
    current = settings.get("/app/exts/folders") or []
    if isinstance(current, str):
        current = [current]
    paths = [str(p) for p in current]
    if str(extension_dir) not in paths:
        paths.append(str(extension_dir))
        settings.set("/app/exts/folders", paths)


def _enable_cesium_extensions(extension_dir: Path) -> None:
    import carb
    import omni.kit.app

    _add_extension_path(extension_dir)
    settings = carb.settings.get_settings()
    settings.set('exts."cesium.omniverse".showOnStartup', False)
    settings.set("/app/fabric/enabled", True)

    app = omni.kit.app.get_app()
    manager = app.get_extension_manager()
    errors: list[str] = []
    for ext_id in ("cesium.usd.plugins", "cesium.omniverse"):
        try:
            manager.set_extension_enabled_immediate(ext_id, True)
            for _ in range(15):
                app.update()
        except Exception as exc:
            errors.append(f"{ext_id}: {exc}")

    if errors:
        raise RuntimeError(
            "Failed to enable Cesium for Omniverse extensions. "
            f"Install v0.28.0 first with scripts/install_cesium_omniverse.py. Details: {'; '.join(errors)}"
        )


async def _open_stage(stage_path: Path) -> None:
    import omni.kit.app
    import omni.usd

    ctx = omni.usd.get_context()
    ok, err = await ctx.open_stage_async(str(stage_path))
    if not ok:
        raise RuntimeError(f"Failed to open stage {stage_path}: {err}")
    app = omni.kit.app.get_app()
    for _ in range(30):
        await app.next_update_async()


def _set_attr(stage, prim_path: str, attr_name: str, value) -> None:
    prim = stage.GetPrimAtPath(prim_path)
    if not prim or not prim.IsValid():
        raise RuntimeError(f"Cesium prim not found: {prim_path}")
    attr = prim.GetAttribute(attr_name)
    if not attr or not attr.IsValid():
        raise RuntimeError(f"Cesium attribute not found: {prim_path}.{attr_name}")
    attr.Set(value)


def _apply_cesium_config(cfg) -> None:
    import omni.usd

    stage = omni.usd.get_context().get_stage()
    _set_attr(stage, "/CesiumGeoreference", "cesium:georeferenceOrigin:latitude", cfg.latitude_deg)
    _set_attr(stage, "/CesiumGeoreference", "cesium:georeferenceOrigin:longitude", cfg.longitude_deg)
    _set_attr(stage, "/CesiumGeoreference", "cesium:georeferenceOrigin:height", cfg.height_m)
    _set_attr(stage, "/Cesium_World_Terrain", "cesium:ionAccessToken", cfg.ion_token)
    _set_attr(stage, "/Cesium_World_Terrain/Bing_Maps_Aerial_imagery", "cesium:ionAccessToken", cfg.ion_token)
    _set_attr(stage, "/CesiumServers/IonOfficial", "cesium:projectDefaultIonAccessToken", cfg.ion_token)


def _set_camera(camera_path: str) -> object:
    from omni.kit.viewport.utility import get_active_viewport

    viewport = get_active_viewport()
    if viewport is None:
        raise RuntimeError("No active Omniverse viewport is available for capture.")
    if hasattr(viewport, "camera_path"):
        viewport.camera_path = camera_path
    elif hasattr(viewport, "set_active_camera"):
        viewport.set_active_camera(camera_path)
    return viewport


def _capture_viewport(viewport: object, out_path: Path) -> None:
    from omni.kit.viewport.utility import capture_viewport_to_file

    try:
        capture = capture_viewport_to_file(viewport, file_path=str(out_path))
    except TypeError:
        try:
            capture = capture_viewport_to_file(viewport, str(out_path))
        except TypeError:
            capture = capture_viewport_to_file(str(out_path))

    for method_name in ("wait_for_result", "wait_for_completed", "wait"):
        method = getattr(capture, method_name, None)
        if method is not None:
            method()
            return


def _summarize_frame(frame: dict) -> str:
    convoy = frame.get("convoy", [])
    route = convoy[0].get("active_route_id", "main") if convoy else "main"
    compute_events = frame.get("compute_events", [])
    dropped = sum(1 for event in compute_events if event.get("dropped"))
    scheduled = len(compute_events) - dropped
    return (
        f"t={float(frame.get('t', 0.0)):06.3f} "
        f"drones={len(frame.get('drones', []))} "
        f"edges={len(frame.get('edges', []))} "
        f"convoy={len(convoy)} links={len(frame.get('links', []))} "
        f"threats={len(frame.get('threats', []))} route={route} "
        f"compute_events={len(compute_events)} scheduled={scheduled} dropped={dropped}"
    )


async def _record(args: argparse.Namespace) -> None:
    import omni.kit.app

    from bridge.sim_publisher import IsaacSimDriver, Track2SimPublisher

    cfg = runtime_config(require_token=True)
    _enable_cesium_extensions(args.extension_dir.expanduser().resolve())
    app_version, build_version = _runtime_versions()
    assert_isaac_runtime_compatible(app_version=app_version, build_version=build_version)

    await _open_stage(args.stage.resolve())
    _apply_cesium_config(cfg)
    configure_cesium_map(args.map_mode, cfg.ion_token)
    apply_actor_presentation()
    viewport = _set_camera(args.camera)

    app = omni.kit.app.get_app()
    for _ in range(args.initial_settle_frames):
        app.update()

    out_dir: Path = args.out_dir
    frames_dir = out_dir / "cesium_frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    mp4_path = out_dir / "phase2_demo_cesium.mp4"
    log_path = out_dir / "phase2_demo_cesium.log"

    publisher = Track2SimPublisher(stub=True)
    driver = IsaacSimDriver()
    total_ticks = int(args.duration_s * args.fps)
    log_lines: list[str] = []

    for tick in range(total_ticks):
        t = tick / args.fps
        frame = publisher.frame_at(t)
        driver.apply(frame)
        update_visual_markers(frame, follow_camera=True)
        for _ in range(args.settle_frames):
            app.update()

        frame_dict = frame.to_full_dict()
        line = _summarize_frame(frame_dict)
        log_lines.append(line)
        print(line, flush=True)
        _capture_viewport(viewport, frames_dir / f"frame_{tick:04d}.png")

    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(args.fps),
        "-i", str(frames_dir / "frame_%04d.png"),
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-crf", "18",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True)
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"[HADES] Cesium video -> {mp4_path}", flush=True)
    print(f"[HADES] Cesium log   -> {log_path}", flush=True)


def main() -> None:
    args = parse_args()

    from isaacsim import SimulationApp

    sim_app = SimulationApp(
        {
            "headless": True,
            "width": args.width,
            "height": args.height,
            "renderer": "RayTracedLighting",
            "anti_aliasing": 0,
        }
    )
    try:
        asyncio.get_event_loop().run_until_complete(_record(args))
    finally:
        sim_app.close()


if __name__ == "__main__":
    main()
