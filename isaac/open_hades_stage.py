"""Open the HADES Phase 1 USD stage inside Isaac Sim.

Usage from an Isaac Sim container:

    ./runheadless.sh --exec /hades/isaac/open_hades_stage.py /hades/isaac/scene.usda
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import carb
import omni.kit.app
import omni.usd


async def _open_stage(stage_path: str) -> None:
    context = omni.usd.get_context()
    success, error = await context.open_stage_async(stage_path)
    if not success:
        raise RuntimeError(f"Failed to open HADES stage: {error}")

    # Let the app render a few frames so the stage and viewport settle before
    # the WebRTC client connects.
    app = omni.kit.app.get_app()
    for _ in range(20):
        await app.next_update_async()


def main() -> None:
    if len(sys.argv) > 1:
        stage_path = sys.argv[1]
    else:
        stage_path = str(Path(__file__).with_name("scene.usda"))

    carb.log_info(f"Opening HADES stage: {stage_path}")
    asyncio.ensure_future(_open_stage(stage_path))


main()
