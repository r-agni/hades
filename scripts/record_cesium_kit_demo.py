"""Record the HADES Cesium demo with a Kit 109 app runtime.

This entrypoint is for Cesium for Omniverse v0.28.0, whose package target is
Kit 109. It is useful on Windows when the installed Isaac Sim package uses a
newer Kit build that cannot load the Cesium v0.28 native DLLs.
"""

from __future__ import annotations

import argparse
import faulthandler
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if os.environ.get("HADES_DEBUG_FAULTHANDLER", "").strip():
    faulthandler.enable()
    faulthandler.dump_traceback_later(float(os.environ.get("HADES_DEBUG_FAULTHANDLER", "60")), repeat=True)

print("[HADES] loading Kit capture entrypoint", flush=True)

from hades.cesium import parse_version, runtime_config  # noqa: E402
from scripts.cesium_presentation import apply_actor_presentation, configure_cesium_map, update_visual_markers  # noqa: E402
from scripts.record_cesium_demo import (  # noqa: E402
    _apply_cesium_config,
    _set_camera,
    _summarize_frame,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", type=Path, default=ROOT / "isaac" / "scene.usda")
    parser.add_argument("--out-dir", type=Path, default=ROOT / "recordings" / "cesium_show")
    parser.add_argument("--duration-s", type=float, default=30.0)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--settle-frames", type=int, default=8)
    parser.add_argument("--initial-settle-frames", type=int, default=120)
    parser.add_argument("--extension-dir", type=Path, default=Path.home() / "Documents" / "Kit" / "Shared" / "exts")
    parser.add_argument("--camera", default="/hades_phase_1/RecordCamera")
    parser.add_argument("--map-mode", choices=("world-terrain", "photorealistic"), default="photorealistic")
    return parser.parse_args()


def _kit_startup_args(args: argparse.Namespace) -> list[str]:
    extension_dir = str(args.extension_dir.expanduser().resolve())
    return [
        "--no-window",
        "--/app/window/hideUi=1",
        "--/app/vulkan=true",
        "--/app/fabric/enabled=true",
        "--/renderer/enabled=rtx",
        "--/renderer/active=rtx",
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
    """Patch Kit 109 pipapi's Windows venv executable path when needed."""
    if not sys.platform.startswith("win"):
        return

    cache_root = Path.home() / "AppData" / "Local" / "ov" / "data" / "Kit" / "kit" / "109.0" / "exts" / "3"
    for path in cache_root.glob("omni.kit.pipapi-*/omni/kit/pipapi/pipapi.py"):
        text = path.read_text(encoding="utf-8")
        old = (
            'python_exe = "python.exe" if sys.platform == "win32" else "bin/python3"\n'
            '            cmd = [sys.prefix + "/" + python_exe, "-m", "pip"] + args'
        )
        new = 'cmd = [sys.executable, "-m", "pip"] + args'
        if old in text:
            path.write_text(text.replace(old, new), encoding="utf-8")
            print(f"[HADES] patched Kit pipapi venv path: {path}", flush=True)


def _kit_build_version() -> str | None:
    import carb
    import omni.kit.app

    settings = carb.settings.get_settings()
    build_version = settings.get("/app/buildVersion") or settings.get("/app/kitVersion")
    if build_version:
        return str(build_version)
    get_build_version = getattr(omni.kit.app.get_app(), "get_build_version", None)
    if get_build_version is None:
        return None
    return str(get_build_version())


def _assert_kit_109() -> None:
    build_version = _kit_build_version()
    parsed = parse_version(build_version)
    if parsed is None or parsed[0] != 109:
        raise RuntimeError(
            "Cesium for Omniverse v0.28.0 is targeted at Kit 109. "
            f"Detected Kit build {build_version!r}."
        )


def _open_stage_blocking(stage_path: Path, kit_app) -> None:
    import omni.usd

    ctx = omni.usd.get_context()
    result = ctx.open_stage(str(stage_path))
    if isinstance(result, tuple):
        ok = bool(result[0])
        err = result[1] if len(result) > 1 else ""
    else:
        ok = bool(result)
        err = ""
    if not ok:
        raise RuntimeError(f"Failed to open stage {stage_path}: {err}")

    for _ in range(90):
        kit_app.update()
    if omni.usd.get_context().get_stage() is None:
        raise RuntimeError(f"Stage did not become available after open_stage: {stage_path}")


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


def _capture_viewport_blocking(viewport: object, out_path: Path, kit_app, *, completion_frames: int = 30) -> None:
    import asyncio

    from omni.kit.viewport.utility import capture_viewport_to_file

    out_path.parent.mkdir(parents=True, exist_ok=True)
    capture = capture_viewport_to_file(viewport, file_path=str(out_path))
    wait = getattr(capture, "wait_for_result", None)
    if wait is None:
        for _ in range(completion_frames):
            kit_app.update()
        if not out_path.exists():
            raise RuntimeError(f"Viewport capture did not create {out_path}")
        return

    task = asyncio.ensure_future(wait(completion_frames=completion_frames))
    for _ in range(completion_frames + 240):
        kit_app.update()
        if task.done():
            task.result()
            break
    else:
        raise RuntimeError(f"Timed out waiting for viewport capture: {out_path}")

    if not out_path.exists():
        raise RuntimeError(f"Viewport capture completed but file is missing: {out_path}")


def _record(args: argparse.Namespace, kit_app) -> None:
    from bridge.sim_publisher import IsaacSimDriver, Track2SimPublisher

    cfg = runtime_config(require_token=True)
    _assert_kit_109()

    stage_path = _tokenized_stage_copy(args.stage.resolve(), args.out_dir, cfg.ion_token)
    print(f"[HADES] opening tokenized stage copy: {stage_path}", flush=True)
    _open_stage_blocking(stage_path, kit_app)
    _apply_cesium_config(cfg)
    configure_cesium_map(args.map_mode, cfg.ion_token)
    apply_actor_presentation()
    viewport = _set_camera(args.camera)

    print(f"[HADES] initial Cesium settle frames: {args.initial_settle_frames}", flush=True)
    for _ in range(args.initial_settle_frames):
        kit_app.update()

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
            kit_app.update()

        frame_dict = frame.to_full_dict()
        line = _summarize_frame(frame_dict)
        log_lines.append(line)
        print(line, flush=True)
        _capture_viewport_blocking(viewport, frames_dir / f"frame_{tick:04d}.png", kit_app)

    cmd = [
        "ffmpeg",
        "-y",
        "-framerate",
        str(args.fps),
        "-i",
        str(frames_dir / "frame_%04d.png"),
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-crf",
        "18",
        str(mp4_path),
    ]
    subprocess.run(cmd, check=True)
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"[HADES] Cesium video -> {mp4_path}", flush=True)
    print(f"[HADES] Cesium log   -> {log_path}", flush=True)
    try:
        stage_path.unlink()
    except OSError:
        pass


def main() -> None:
    args = parse_args()
    _patch_venv_pipapi()
    print("[HADES] importing KitApp", flush=True)
    from omni.kit_app import KitApp

    print("[HADES] starting Kit 109 app", flush=True)
    kit_app = KitApp()
    started = time.time()
    kit_app.startup(_kit_startup_args(args))
    print(f"[HADES] Kit app started in {time.time() - started:.1f}s", flush=True)
    exit_code = 0
    try:
        _record(args, kit_app)
    except BaseException:
        exit_code = 1
        traceback.print_exc()
    finally:
        print("[HADES] shutting down Kit app", flush=True)
        shutdown_code = kit_app.shutdown()
        raise SystemExit(exit_code or shutdown_code)


if __name__ == "__main__":
    main()
