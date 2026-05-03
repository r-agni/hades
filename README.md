HADES: Hierarchical Autonomous Drone Edge System

Phase 1 creates the simulation foundation: actor capability definitions, a
real-asset Isaac/OpenUSD scene, and a FastAPI WebSocket bridge that streams
synthetic `SimFrame` state at 10 Hz.

## Quick Start

```powershell
python -m pip install -e ".[dev]"
python -m bridge.server
```

Then, in another terminal:

```powershell
python .\scripts\check_bridge.py
```

The bridge also exposes:

- `GET /healthz`
- `GET /frame`
- `WS /stream`

## Phase 1 Contents

- `hades/config.py` holds shared limits, counts, ranges, update rates, compute
  capacity, and sensor specs.
- `protocol/messages.proto` defines the stable sim-to-consumer message contract.
- `bridge/server.py` streams live frames for web, ATGS-style adapters, or debug
  clients.
- `bridge/sim_publisher.py` provides a synthetic publisher and the future Isaac
  adapter boundary.
- `isaac/drones/` defines parent drone, small drone, and passive edge-node
  capabilities.
- `isaac/scene.usda` is the active Isaac stage. It references the NVIDIA
  Jetracer track environment, Carter convoy vehicles, Isaac quadcopters,
  Crazyflies, and NVIDIA 1U server assets for edge compute nodes.
- `isaac/capture_hades_preview.py` opens the active stage in Isaac Sim and
  captures proof frames into an external artifact directory.
- `infra/aws/` contains optional AWS CLI scaffolding for an Isaac Sim GPU host.

## Visual Environment

The checked-in visual scene is `isaac/scene.usda`. The old generated block
fallback has been removed from the active workflow so preview captures fail
instead of silently rendering placeholder cubes.

Phase 1 does not implement autonomy or threat response. Those begin in later
tracks.
