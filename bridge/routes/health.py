"""Health check route."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from hades import config

router = APIRouter()


@router.get("/healthz", tags=["ops"])
async def healthz() -> JSONResponse:
    from bridge.routes.frame import _publisher

    return JSONResponse({
        "ok": True,
        "tick_hz": config.BRIDGE.tick_hz,
        "publisher": type(_publisher).__name__ if _publisher is not None else None,
    })
