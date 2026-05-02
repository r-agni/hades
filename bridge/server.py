"""HADES bridge server wiring routes and static viz assets."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from bridge.demo_publisher import DemoSimPublisher
from bridge.sim_publisher import SyntheticSimPublisher
from bridge.routes import health, frame as frame_route, realworld, stream as stream_route, viz_route
from hades import config

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dependency declared, defensive for partial envs
    load_dotenv = None

if load_dotenv is not None:
    load_dotenv()

app = FastAPI(title="HADES Bridge", version="0.2.0")


def _make_publisher() -> object:
    mode = os.getenv("HADES_PUBLISHER_MODE", "demo").strip().lower()
    environment = os.getenv("HADES_ENVIRONMENT", config.SCENE.environment_emergency)
    if mode == "synthetic":
        return SyntheticSimPublisher(environment=environment)
    return DemoSimPublisher(environment=environment)


# Publisher singleton shared across routes.
publisher = _make_publisher()
frame_route.set_publisher(publisher)
stream_route.set_publisher(publisher)

# Static files: viz/ folder served at /static.
_VIZ_DIR = Path(__file__).parent.parent / "viz"
app.mount("/static", StaticFiles(directory=str(_VIZ_DIR)), name="static")

# Routes.
app.include_router(health.router)
app.include_router(frame_route.router)
app.include_router(stream_route.router)
app.include_router(viz_route.router)
app.include_router(realworld.router)


# Entry point.
def main() -> None:
    uvicorn.run(
        "bridge.server:app",
        host=os.getenv("HADES_BRIDGE_HOST", config.BRIDGE.host),
        port=int(os.getenv("HADES_BRIDGE_PORT", str(config.BRIDGE.port))),
        reload=os.getenv("HADES_RELOAD", "0") == "1",
    )


if __name__ == "__main__":
    main()
