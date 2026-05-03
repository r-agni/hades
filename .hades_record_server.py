"""Temporary recording server for accelerated real-world visualizer capture."""

from __future__ import annotations

import os

import uvicorn
from dotenv import load_dotenv

load_dotenv()

os.environ["HADES_BRIDGE_HOST"] = "127.0.0.1"
os.environ["HADES_BRIDGE_PORT"] = "8030"
os.environ["HADES_OPENAI_ENABLED"] = "0"
os.environ.setdefault("HADES_RECORD_ROUTE_SPEED", "120")

import hades.realworld.scenario as scenario_mod  # noqa: E402
from bridge.server import app  # noqa: E402
from hades.realworld.publisher import RealWorldSimPublisher as BasePublisher  # noqa: E402


class RecordingPublisher(BasePublisher):
    def __init__(self, *args: object, **kwargs: object) -> None:
        kwargs["route_speed_mps"] = float(os.getenv("HADES_RECORD_ROUTE_SPEED", "120"))
        super().__init__(*args, **kwargs)


scenario_mod.RealWorldSimPublisher = RecordingPublisher


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8030, log_level="info")
