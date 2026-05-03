"""WebSocket smoke-check and recorder for the HADES bridge."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from hades import config


def summarize_frame(frame: dict[str, Any]) -> str:
    convoy = frame.get("convoy", [])
    threats = frame.get("threats", [])
    compute_events = frame.get("compute_events", [])
    route = convoy[0].get("active_route_id", "unknown") if convoy else "none"
    dropped = sum(1 for event in compute_events if event.get("dropped"))
    scheduled = len(compute_events) - dropped
    return (
        f"t={float(frame.get('t', 0.0)):06.3f} "
        f"drones={len(frame.get('drones', []))} "
        f"edges={len(frame.get('edges', []))} "
        f"convoy={len(convoy)} "
        f"links={len(frame.get('links', []))} "
        f"threats={len(threats)} "
        f"route={route} "
        f"compute_events={len(compute_events)} "
        f"scheduled={scheduled} "
        f"dropped={dropped}"
    )


async def _record(url: str, duration_s: float, out_path: Path | None) -> int:
    import websockets

    lines: list[str] = []
    start = time.monotonic()
    frames = 0
    saw_pre_threat_main = False
    saw_post_threat_reroute = False
    saw_compute = False

    async with websockets.connect(url) as websocket:
        while True:
            raw = await websocket.recv()
            frame = json.loads(raw)
            line = summarize_frame(frame)
            print(line, flush=True)
            lines.append(line)
            frames += 1

            t = float(frame.get("t", 0.0))
            convoy = frame.get("convoy", [])
            route = convoy[0].get("active_route_id", "") if convoy else ""
            threats = frame.get("threats", [])
            compute_events = frame.get("compute_events", [])
            saw_compute = saw_compute or bool(compute_events)
            saw_pre_threat_main = saw_pre_threat_main or (t < 15.0 and not threats and route == "main")
            saw_post_threat_reroute = saw_post_threat_reroute or (
                t >= 15.0 and len(threats) >= 2 and route != "main"
            )

            if duration_s <= 0 or time.monotonic() - start >= duration_s:
                break

    summary = (
        f"summary frames={frames} "
        f"saw_pre_threat_main={saw_pre_threat_main} "
        f"saw_post_threat_reroute={saw_post_threat_reroute} "
        f"saw_compute={saw_compute}"
    )
    print(summary, flush=True)
    lines.append(summary)

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if duration_s < 15.0:
        return 0 if frames > 0 else 1
    return 0 if saw_pre_threat_main and saw_post_threat_reroute and saw_compute else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default="ws://127.0.0.1:8000/stream")
    parser.add_argument("--duration-s", type=float, default=0.0)
    parser.add_argument("--out", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(_record(args.url, args.duration_s, args.out)))


if __name__ == "__main__":
    main()
