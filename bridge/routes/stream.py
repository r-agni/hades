"""WebSocket streaming route emitting SimFrame JSON at tick_hz."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from hades import config

router = APIRouter()

_publisher = None


def set_publisher(pub: Any) -> None:
    global _publisher
    _publisher = pub


@router.websocket(config.BRIDGE.websocket_path)
async def stream(websocket: WebSocket) -> None:
    await websocket.accept()
    delay_s = 1.0 / config.BRIDGE.tick_hz
    try:
        while True:
            payload = _publisher.now_frame().to_dict()
            await websocket.send_text(json.dumps(payload, separators=(",", ":")))
            await asyncio.sleep(delay_s)
    except WebSocketDisconnect:
        return
