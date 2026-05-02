"""Single-frame HTTP snapshot route."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()

# Publisher injected by server.py at startup
_publisher = None


def set_publisher(pub: Any) -> None:
    global _publisher
    _publisher = pub


@router.get("/frame", tags=["sim"])
async def frame() -> dict[str, Any]:
    return _publisher.now_frame().to_dict()
