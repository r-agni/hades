"""Routes for the live real-world temporary visualizer."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency declared, defensive for partial envs
    load_dotenv = None

from hades.realworld.geo import LatLng
from hades.realworld.google import GoogleMapsClient, GoogleMapsError
from hades.realworld.optimizer import ManualEdge
from hades.realworld.openai_settings import load_openai_settings
from hades.realworld.scenario import (
    DEFAULT_DESTINATION,
    DEFAULT_EDGE_COUNT,
    DEFAULT_ORIGIN,
    DEFAULT_SEARCH_BUFFER_M,
    DEFAULT_WIFI_RADIUS_M,
    RealWorldScenarioService,
)


if load_dotenv is not None:
    load_dotenv()


router = APIRouter()

_VIZ_PATH = Path(__file__).parent.parent.parent / "viz" / "realworld-tempVisualizer" / "index.html"
_service: RealWorldScenarioService | None = None


class ScenarioCreateRequest(BaseModel):
    origin: Any = None
    destination: Any = None
    edge_count: int = Field(DEFAULT_EDGE_COUNT, ge=1, le=64)
    wifi_radius_m: float = Field(DEFAULT_WIFI_RADIUS_M, ge=25.0, le=1_500.0)
    search_buffer_m: float = Field(DEFAULT_SEARCH_BUFFER_M, ge=100.0, le=5_000.0)


class ManualEdgeRequest(BaseModel):
    id: str
    lat: float
    lng: float


class EdgePatchRequest(BaseModel):
    manual_edges: list[ManualEdgeRequest] = Field(default_factory=list)
    approved_edge_ids: list[str] = Field(default_factory=list)
    rejected_edge_ids: list[str] = Field(default_factory=list)


class RerouteApplyRequest(BaseModel):
    proposal_id: str


@router.get("/viz/realworld-tempVisualizer", response_class=HTMLResponse, tags=["ui"])
async def realworld_viz() -> str:
    return _VIZ_PATH.read_text(encoding="utf-8")


@router.get("/api/realworld/config", tags=["realworld"])
async def realworld_config() -> dict[str, object]:
    browser_key = os.getenv("VITE_GOOGLE_API_KEY") or os.getenv("GOOGLE_MAPS_API_KEY")
    if not browser_key:
        raise HTTPException(status_code=503, detail="VITE_GOOGLE_API_KEY is required")
    openai = load_openai_settings()
    return {
        "google_maps_key": browser_key,
        "default_origin": DEFAULT_ORIGIN,
        "default_destination": DEFAULT_DESTINATION,
        "default_edge_count": DEFAULT_EDGE_COUNT,
        "default_wifi_radius_m": DEFAULT_WIFI_RADIUS_M,
        "default_search_buffer_m": DEFAULT_SEARCH_BUFFER_M,
        "openai_enabled": openai.enabled,
        "openai_model": openai.model,
        "public_context_enabled": os.getenv("HADES_REALWORLD_PUBLIC_CONTEXT", "1") != "0",
    }


@router.post("/api/realworld/scenarios", tags=["realworld"])
async def create_realworld_scenario(request: ScenarioCreateRequest) -> dict[str, object]:
    service = _get_service()
    try:
        scenario = await service.create(
            origin=request.origin,
            destination=request.destination,
            edge_count=request.edge_count,
            wifi_radius_m=request.wifi_radius_m,
            search_buffer_m=request.search_buffer_m,
        )
    except GoogleMapsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return scenario.to_dict()


@router.patch("/api/realworld/scenarios/{scenario_id}/edges", tags=["realworld"])
async def update_realworld_edges(
    scenario_id: str,
    request: EdgePatchRequest,
) -> dict[str, object]:
    service = _get_service()
    manual_edges = [
        ManualEdge(id=edge.id, point=LatLng(edge.lat, edge.lng))
        for edge in request.manual_edges
    ]
    try:
        scenario = await service.update_edges(
            scenario_id,
            manual_edges,
            approved_edge_ids=request.approved_edge_ids,
            rejected_edge_ids=request.rejected_edge_ids,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return scenario.to_dict()


@router.post("/api/realworld/scenarios/{scenario_id}/start", tags=["realworld"])
async def start_realworld_scenario(scenario_id: str) -> dict[str, object]:
    service = _get_service()
    try:
        scenario = service.start(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GoogleMapsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return scenario.to_dict()


@router.post("/api/realworld/scenarios/{scenario_id}/reroutes", tags=["realworld"])
async def propose_realworld_reroutes(scenario_id: str) -> dict[str, object]:
    service = _get_service()
    try:
        scenario = await service.propose_reroutes(scenario_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GoogleMapsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return scenario.to_dict()


@router.post("/api/realworld/scenarios/{scenario_id}/reroutes/apply", tags=["realworld"])
async def apply_realworld_reroute(
    scenario_id: str,
    request: RerouteApplyRequest,
) -> dict[str, object]:
    service = _get_service()
    try:
        scenario = await service.apply_reroute(scenario_id, request.proposal_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GoogleMapsError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return scenario.to_dict()


@router.websocket("/api/realworld/scenarios/{scenario_id}/stream")
async def realworld_stream(websocket: WebSocket, scenario_id: str) -> None:
    await websocket.accept()
    try:
        scenario = _get_service().get(scenario_id)
    except (HTTPException, KeyError) as exc:
        await websocket.send_text(json.dumps({"error": str(exc)}))
        await websocket.close(code=1008)
        return
    if not scenario.started:
        await websocket.send_text(json.dumps({"error": "Scenario must be started after edge approval"}))
        await websocket.close(code=1008)
        return

    try:
        while True:
            payload = scenario.publisher.now_frame()
            await websocket.send_text(json.dumps(payload, separators=(",", ":")))
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        return


def _get_service() -> RealWorldScenarioService:
    global _service
    if _service is not None:
        return _service
    api_key = os.getenv("GOOGLE_MAPS_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="GOOGLE_MAPS_API_KEY is required")
    _service = RealWorldScenarioService(GoogleMapsClient(api_key))
    return _service
