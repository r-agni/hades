"""FastAPI WebSocket bridge for HADES Phase 1."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from bridge.sim_publisher import SyntheticSimPublisher
from hades import config


app = FastAPI(title="HADES Bridge", version="0.1.0")

if os.getenv("HADES_PUBLISHER") == "track2":
    from bridge.sim_publisher import Track2SimPublisher
    publisher: SyntheticSimPublisher | Track2SimPublisher = Track2SimPublisher(
        environment=os.getenv("HADES_ENVIRONMENT", config.SCENE.environment),
        stub=os.getenv("HADES_STUB", "0") != "0",
    )
else:
    publisher = SyntheticSimPublisher(
        environment=os.getenv("HADES_ENVIRONMENT", config.SCENE.environment)
    )


@app.get("/healthz")
async def healthz() -> JSONResponse:
    return JSONResponse({"ok": True, "tick_hz": config.BRIDGE.tick_hz})


@app.get("/frame")
async def frame() -> dict[str, Any]:
    return publisher.now_frame().to_dict()


@app.websocket(config.BRIDGE.websocket_path)
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    delay_s = 1.0 / config.BRIDGE.tick_hz
    try:
        while True:
            payload = publisher.now_frame().to_dict()
            await websocket.send_text(json.dumps(payload, separators=(",", ":")))
            await asyncio.sleep(delay_s)
    except WebSocketDisconnect:
        return


def main() -> None:
    uvicorn.run(
        "bridge.server:app",
        host=os.getenv("HADES_BRIDGE_HOST", config.BRIDGE.host),
        port=int(os.getenv("HADES_BRIDGE_PORT", str(config.BRIDGE.port))),
        reload=os.getenv("HADES_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    main()
