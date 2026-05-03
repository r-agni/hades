HADES: Hierarchical Autonomous Drone Edge System

HADES is a simulation scaffold for hierarchical drone escort, edge compute
offload, and communications experiments. The Isaac Sim/OpenUSD pieces remain
the primary integration target; the bundled bridge and temporary tactical
visualizer exist so routing and autonomy logic can be exercised while the Isaac
environment matures.

## Quick Start

```powershell
python -m pip install -e ".[dev]"
python -m bridge.server
```

Then open:

- `http://127.0.0.1:8000/viz` for the temporary tactical visualizer
- `http://127.0.0.1:8000/frame` for one JSON frame
- `ws://127.0.0.1:8000/stream` for the 10 Hz frame stream

You can smoke-check the stream from another terminal:

```powershell
python .\scripts\check_bridge.py
```

By default the bridge uses `HADES_PUBLISHER_MODE=demo`, which powers the
temporary `/viz` presentation with scripted contacts, jamming, and callouts. For
track development or non-visual consumers, run with `HADES_PUBLISHER_MODE=synthetic`
to use the reusable synthetic publisher without demo choreography.

OpenAI API use is disabled by default. If optional explanation features are
enabled later, configure `HADES_OPENAI_ENABLED=1` and keep `OPENAI_MODEL` on a
lightweight model such as `gpt-4.1-mini` unless a larger model is explicitly
needed.

## Layout

- `hades/config.py` and `hades/state.py` define shared constants and the stable
  frame/state contract.
- `hades/autonomy/` contains reusable Track 2 logic: comms links, compute
  offload routing, small-drone role allocation, and parent re-election state.
- `bridge/` exposes FastAPI routes, the reusable synthetic publisher, and a
  separate demo publisher used only for the temporary visualizer.
- `isaac/` contains Isaac/OpenUSD stage assets, environment resolution, and
  drone capability definitions.
- `viz/` contains the temporary static dashboard served at `/viz`.
- `protocol/messages.proto` defines the protobuf-facing sim contract.
- `infra/aws/` contains optional AWS scaffolding for an Isaac Sim GPU host.

## Environment Priority

1. Cesium for Omniverse real-world road/open-terrain location.
2. NVIDIA free OpenUSD City Demo Assets Pack.
3. Generated flat-road fallback in `isaac/scene.usda`.

The synthetic bridge publishes the same `SimFrame` shape expected from the
future Isaac adapter, so consumers should depend on the shared `hades` state and
autonomy modules rather than the temporary visualizer.
