"""Small WebSocket smoke-check for the HADES bridge."""

from __future__ import annotations

import asyncio
import json
import sys


async def _main(url: str) -> None:
    import websockets

    async with websockets.connect(url) as websocket:
        raw = await websocket.recv()
        frame = json.loads(raw)
        print(
            "received frame:",
            f"drones={len(frame['drones'])}",
            f"edges={len(frame['edges'])}",
            f"convoy={len(frame['convoy'])}",
            f"links={len(frame['links'])}",
        )


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:8000/stream"
    asyncio.run(_main(target))
