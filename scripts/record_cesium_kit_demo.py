"""Record the HADES Cesium demo with a Kit 109 app runtime.

This entrypoint is for Cesium for Omniverse v0.28.0, whose package target is
Kit 109. It is useful on Windows when the installed Isaac Sim package uses a
newer Kit build that cannot load the Cesium v0.28 native DLLs.
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hades.cesium import parse_version, runtime_config  # noqa: E402
from scripts.record_cesium_demo import (  # noqa: E402
    _apply_cesium_config,
    _capture_viewport,
    _open_stage,
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
    return parser.parse_args()


def _kit_startup_args(args: argparse.Namespace) -> list[str]:
    extension_dir = str(args.extension_dir.expanduser().resolve())
    return [
        "--no-window",
        "--/app/window/hideUi=1",
        "--/app/fabric/enabled=true",
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
        "cesium.usd.plugins",
        "--enable",
        "cesium.omniverse",
    ]


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


async def _record(args: argparse.Namespace, kit_app) -> None:
    from bridge.sim_publisher import IsaacSimDriver, Track2SimPublisher

    cfg = runtime_config(require_token=True)
    _assert_kit_109()

    print(f"[HADES] opening stage: {args.stage.resolve()}", flush=True)
    await _open_stage(args.stage.resolve())
    _apply_cesium_config(cfg)
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
        for _ in range(args.settle_frames):
            kit_app.update()

        frame_dict = frame.to_full_dict()
        line = _summarize_frame(frame_dict)
        log_lines.append(line)
        print(line, flush=True)
        _capture_viewport(viewport, frames_dir / f"frame_{tick:04d}.png")

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


def main() -> None:
    args = parse_args()
    print("[HADES] importing KitApp", flush=True)
    from omni.kit_app import KitApp

    print("[HADES] starting Kit 109 app", flush=True)
    kit_app = KitApp()
    started = time.time()
    kit_app.startup(_kit_startup_args(args))
    print(f"[HADES] Kit app started in {time.time() - started:.1f}s", flush=True)
    try:
        asyncio.get_event_loop().run_until_complete(_record(args, kit_app))
    finally:
        print("[HADES] shutting down Kit app", flush=True)
        raise SystemExit(kit_app.shutdown())


if __name__ == "__main__":
    main()
