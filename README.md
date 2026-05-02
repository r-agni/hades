HADES: Hierarchical Autonomous Drone Edge System

Phase 1 creates the simulation foundation: actor capability definitions, a
minimal Isaac/OpenUSD fallback scene, and a FastAPI WebSocket bridge that streams
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
- `GET /viz`
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
- `isaac/scene.usda` is an emergency fallback scene with road, convoy, drones,
  and edge nodes.
- `infra/aws/` contains optional AWS CLI scaffolding for an Isaac Sim GPU host.

## Environment Priority

1. Cesium for Omniverse real-world road/open-terrain location.
2. NVIDIA free OpenUSD City Demo Assets Pack.
3. Generated flat-road fallback in `isaac/scene.usda`.

Phase 1 does not implement autonomy or threat response. Those begin in later
tracks.
