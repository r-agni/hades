"""Viz route serving the tactical dashboard HTML."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

_VIZ_PATH = Path(__file__).parent.parent.parent / "viz" / "index.html"


@router.get("/viz", response_class=HTMLResponse, tags=["ui"])
async def viz() -> str:
    return _VIZ_PATH.read_text(encoding="utf-8")
