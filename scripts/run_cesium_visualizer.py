"""Run the HADES Cesium scene in a visible Kit 109 viewport."""

from __future__ import annotations

import argparse
import faulthandler
import os
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if os.environ.get("HADES_DEBUG_FAULTHANDLER", "").strip():
    faulthandler.enable()
    faulthandler.dump_traceback_later(float(os.environ.get("HADES_DEBUG_FAULTHANDLER", "600")), repeat=True)

from bridge.sim_publisher import IsaacSimDriver, SyntheticWorldLayout, Track2SimPublisher  # noqa: E402
from hades.cesium import parse_version, runtime_config  # noqa: E402
from scripts.cesium_presentation import apply_actor_presentation, configure_cesium_map, update_visual_markers  # noqa: E402
from scripts.record_cesium_demo import _apply_cesium_config, _set_camera, _summarize_frame  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=ROOT / "isaac" / "scene.usda")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "recordings" / "cesium_visualizer")
    parser.add_argument("--width", type=int, default=1600)
    parser.add_argument("--height", type=int, default=900)
    parser.add_argument("--fps", type=float, default=10.0)
    parser.add_argument("--duration-s", type=float, default=0.0, help="0 means run until the window is closed.")
    parser.add_argument("--initial-settle-frames", type=int, default=300)
    parser.add_argument("--extension-dir", type=Path, default=Path.home() / "Documents" / "Kit" / "Shared" / "exts")
    parser.add_argument("--camera", default="/hades_phase_1/RecordCamera")
    parser.add_argument("--map-mode", choices=("world-terrain", "photorealistic"), default="photorealistic")
    parser.add_argument("--scenario-period-s", type=float, default=150.0)
    parser.add_argument("--single-pass", action="store_true", help="Do not loop the visible demo scenario.")
    return parser.parse_args()


def _kit_startup_args(args: argparse.Namespace) -> list[str]:
    extension_dir = str(args.extension_dir.expanduser().resolve())
    return [
        "--/app/vulkan=true",
        "--/app/fabric/enabled=true",
        "--/renderer/enabled=rtx",
        "--/renderer/active=rtx",
        "--/app/file/ignoreUnsavedOnExit=true",
        f"--/app/window/width={args.width}",
        f"--/app/window/height={args.height}",
        f"--/app/renderer/resolution/width={args.width}",
        f"--/app/renderer/resolution/height={args.height}",
        "--ext-folder",
        extension_dir,
        "--enable",
        "omni.kit.loop-default",
        "--enable",
        "omni.kit.mainwindow",
        "--enable",
        "omni.usd",
        "--enable",
        "omni.kit.window.file",
        "--enable",
        "omni.kit.context_menu",
        "--enable",
        "omni.kit.viewport.window",
        "--enable",
        "omni.kit.viewport.utility",
        "--enable",
        "omni.hydra.rtx",
        "--enable",
        "usdrt.scenegraph",
        "--enable",
        "cesium.usd.plugins",
        "--enable",
        "cesium.omniverse",
    ]


def _patch_venv_pipapi() -> None:
    if not sys.platform.startswith("win"):
        return
    cache_root = Path.home() / "AppData" / "Local" / "ov" / "data" / "Kit" / "kit" / "109.0" / "exts" / "3"
    for path in cache_root.glob("omni.kit.pipapi-*/omni/kit/pipapi/pipapi.py"):
        text = path.read_text(encoding="utf-8")
        old = (
            'python_exe = "python.exe" if sys.platform == "win32" else "bin/python3"\n'
            '            cmd = [sys.prefix + "/" + python_exe, "-m", "pip"] + args'
        )
        if old in text:
            path.write_text(text.replace(old, 'cmd = [sys.executable, "-m", "pip"] + args'), encoding="utf-8")
            print(f"[HADES] patched Kit pipapi venv path: {path}", flush=True)


def _assert_kit_109() -> None:
    import carb
    import omni.kit.app

    settings = carb.settings.get_settings()
    build_version = settings.get("/app/buildVersion") or settings.get("/app/kitVersion")
    if not build_version:
        get_build_version = getattr(omni.kit.app.get_app(), "get_build_version", None)
        build_version = get_build_version() if get_build_version else None
    parsed = parse_version(str(build_version) if build_version else None)
    if parsed is None or parsed[0] != 109:
        raise RuntimeError(f"Cesium for Omniverse v0.28.0 is targeted at Kit 109. Detected {build_version!r}.")


def _tokenized_stage_copy(stage_path: Path, out_dir: Path, token: str) -> Path:
    text = stage_path.read_text(encoding="utf-8")
    text = text.replace('string cesium:ionAccessToken = ""', f'string cesium:ionAccessToken = "{token}"')
    text = text.replace(
        'string cesium:projectDefaultIonAccessToken = ""',
        f'string cesium:projectDefaultIonAccessToken = "{token}"',
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_stage = stage_path.parent / f".{stage_path.stem}.cesium_tokenized.{os.getpid()}.usda"
    temp_stage.write_text(text, encoding="utf-8")
    return temp_stage


def _open_stage(stage_path: Path, kit_app) -> None:
    import omni.usd

    ctx = omni.usd.get_context()
    result = ctx.open_stage(str(stage_path))
    ok = bool(result[0]) if isinstance(result, tuple) else bool(result)
    if not ok:
        raise RuntimeError(f"Failed to open stage {stage_path}")
    for _ in range(120):
        kit_app.update()


def _run(args: argparse.Namespace, kit_app) -> None:
    cfg = runtime_config(require_token=True)
    _assert_kit_109()

    stage_path = _tokenized_stage_copy(args.stage.resolve(), args.out_dir, cfg.ion_token)
    print(f"[HADES] opening tokenized stage copy: {stage_path}", flush=True)
    _open_stage(stage_path, kit_app)
    _apply_cesium_config(cfg)
    configure_cesium_map(args.map_mode, cfg.ion_token)
    apply_actor_presentation()
    _set_camera(args.camera)

    print(f"[HADES] settling Cesium/RTX for {args.initial_settle_frames} frames", flush=True)
    for i in range(args.initial_settle_frames):
        kit_app.update()
        if i and i % 60 == 0:
            print(f"[HADES] settle frame {i}/{args.initial_settle_frames}", flush=True)

    layout = SyntheticWorldLayout(route_duration_s=args.scenario_period_s, loop=False)
    publisher = Track2SimPublisher(layout=layout, stub=True)
    driver = IsaacSimDriver()
    start = time.monotonic()
    last_scenario_t = 0.0
    tick = 0
    print("[HADES] visualizer running. Close the Omniverse window to stop.", flush=True)

    try:
        while kit_app.is_running():
            now = time.monotonic()
            wall_t = now - start
            if args.duration_s > 0 and wall_t >= args.duration_s:
                break
            if args.single_pass:
                scenario_t = wall_t
            else:
                scenario_t = wall_t % args.scenario_period_s
                if scenario_t < last_scenario_t:
                    publisher = Track2SimPublisher(layout=layout, stub=True)
                    print("[HADES] scenario loop reset to convoy departure", flush=True)
            last_scenario_t = scenario_t

            frame = publisher.frame_at(scenario_t)
            driver.apply(frame)
            update_visual_markers(frame, follow_camera=True)
            kit_app.update()
            if tick % max(1, int(args.fps * 5)) == 0:
                print(_summarize_frame(frame.to_full_dict()), flush=True)
            tick += 1
            time.sleep(max(0.0, (1.0 / args.fps) - (time.monotonic() - now)))
    finally:
        try:
            stage_path.unlink()
        except OSError:
            pass


def main() -> None:
    args = parse_args()
    _patch_venv_pipapi()

    from omni.kit_app import KitApp

    print("[HADES] starting visible Kit 109 Cesium visualizer", flush=True)
    kit_app = KitApp()
    started = time.time()
    kit_app.startup(_kit_startup_args(args))
    print(f"[HADES] Kit app started in {time.time() - started:.1f}s", flush=True)

    exit_code = 0
    try:
        _run(args, kit_app)
    except BaseException:
        exit_code = 1
        traceback.print_exc()
    finally:
        print("[HADES] shutting down visualizer", flush=True)
        shutdown_code = kit_app.shutdown()
        raise SystemExit(exit_code or shutdown_code)


if __name__ == "__main__":
    main()
