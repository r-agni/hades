# HADES

Hierarchical drone escort and edge compute for environments where communications are degraded and compute is scarce.

One drone with one camera is useful. A hierarchy of small scouts, parent relay drones, edge compute nodes, and convoy-side command logic keeps working when a single operator feed, cloud server, or cellular link fails.

[Demo video](https://www.youtube.com/watch?v=cuLlt9UxrS0)

## How it works

- **Four actor tiers** with asymmetric compute: 6 small drones (0.5 TOPS), 2 parent drones (100 TOPS), 18 static edge nodes (50 TOPS), 2 convoy vehicles — modelling the real constraint that the things which can move cheaply cannot think, and vice versa.
- **Only drones sense.** Edge nodes and convoy vehicles are receive-only. This invariant stops the simulation cheating by letting static infrastructure know what it could not know without the drone network.
- **Range-gated comms model** with explicit relay constraints, so link loss is a first-class condition rather than an error path.
- **Offload scheduler** decides local / offload / drop per job against live compute and link budgets.
- **Multi-agent RL** in an Isaac Lab-style environment, PPO via SKRL, with headless training that runs without Isaac Sim installed.
- **Isaac Sim + OpenUSD** for the physics-accurate target environment; a Cesium tactical visualizer and a 10 Hz state-frame bridge let routing and autonomy logic be exercised while the Isaac environment matures.

Framed for defensive protection, emergency response, and human-supervised decision support. Not a weaponization project.

## Run it

```bash
python -m pip install -e ".[dev]"
python -m bridge.server
```

- `http://127.0.0.1:8000/viz` — tactical visualizer
- `ws://127.0.0.1:8000/stream` — 10 Hz frame stream

Full design notes, use cases, and research sources: [docs/README-full.md](docs/README-full.md).
