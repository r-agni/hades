# HADES Tracks 2–4: Compute Rules, Sensor-Driven Swarm, and RL Training in Isaac Lab

## Context

Phase 1 (complete) built the simulation scaffold: Isaac Sim 5.1 scene with generated Laughlin/Bullhead map terrain plus real actor assets (Carter convoy, OmniDrones Neo11 hexcopter parents, CF2X Isaac-tuned smalls, 1U server edges), a FastAPI WebSocket bridge at 10 Hz, and frozen dataclass state models. No autonomy, no control, no RL exists yet.

The goal of Tracks 2–4 is to implement the full swarm-escort-under-threat scenario entirely inside Isaac Lab — using real sensors on every actor, enforcing compute and comms constraints, training a MAPPO policy via SKRL, and running a scored demo episode. No separate visualizer layer: everything renders and trains directly in Isaac Sim 5.1.

**Demo rationale:** Drone swarm protecting a convoy through a threat landscape is the correct demo. It exercises all three compute tiers simultaneously, partial observability is natural (drones don't know edge locations), the reward signal ("convoy reaches endpoint alive") is immediately interpretable, and it showcases the edge-offload mechanic that is the commercial differentiator of the architecture.

---

## Location: Laughlin/Bullhead City Corridor, AZ/NV

**Coords:** `HADES_SCENE_LAT=35.1700`, `HADES_SCENE_LON=-114.5700`  
**AOI:** 1500 m × 1500 m (zoom 17, ~1.2 m/px via existing `fetch_terrain.py`)

Two real routes created by the US-95/AZ-95 Y-fork:

| Route ID | Waypoints (scene-local, x/y metres) | Character |
|---|---|---|
| `main` | (−580, 0) → (0, 10) → (580, 0) | Direct, crosses open bridge, exposed |
| `north_bypass` | (−580, 0) → (−200, 130) → (200, 130) → (580, 0) | Longer, partial cover |
| `south_bypass` | (−580, 0) → (−200, −130) → (200, −130) → (580, 0) | Alternative, industrial approach |

Threat spawn zones: `choke_a` at (0, 0) r=80 m (bridge centre), `flank_b` at (220, 180) r=60 m (bypass entry).

`route_length_m` changes from 420 m → **1200 m**. Edge node spacing stays ~65 m with 18 nodes.

---

## Sensor Manifest (per actor — all declared in Isaac Lab `InteractiveSceneCfg`)

All sensors use Isaac Lab's `TiledCameraCfg` / `ImuCfg` / `RayCasterCfg`. Every actor reads its own sensors each step inside `_get_observations()`.

### Parent Drone (2×, 100 TOPS)
| Sensor | Isaac Lab class | Config | Data shape |
|---|---|---|---|
| 6× RGB nav cameras (360°) | `TiledCameraCfg` | 1280×720, 10 Hz, rgb+depth | `[num_envs, 6, 720, 1280, 4]` |
| Thermal (FLIR class) | `TiledCameraCfg` | 640×512, 10 Hz, rgb | `[num_envs, 1, 512, 640, 3]` |
| RTX LiDAR | `RayCasterCfg` | 360° horizontal, 32 vertical beams, 100 m range | `[num_envs, 32*H, 3]` |
| IMU | `ImuCfg` | 100 Hz, update_period=0.01 | lin_acc `[num_envs, 3]`, ang_vel `[num_envs, 3]` |

### Small Drone (6×, 0.5 TOPS)
| Sensor | Isaac Lab class | Config | Data shape |
|---|---|---|---|
| 1× RGB camera (downward/forward) | `TiledCameraCfg` | 320×240, 10 Hz, rgb | `[num_envs, 1, 240, 320, 3]` |
| IMU | `ImuCfg` | 100 Hz | lin_acc `[num_envs, 3]`, ang_vel `[num_envs, 3]` |

### Edge Node (18×, 50 TOPS — static compute nodes, no sensors)
No sensors. Edge nodes only **receive** compute jobs offloaded from drones (via Parent relay) and **send** results back. They have no independent perception of the environment. State fields: `compute_load`, `compute_capacity_tops`, `wifi_radius_m`, `alive`.

### Convoy Vehicle (2×, carries embedded edge node — no sensors, receive-only)
No sensors. The convoy **receives** threat intel and reroute commands from the drone swarm and **sends** its position/route-progress back via the embedded edge node. It does not perceive the environment independently. State fields: `pose`, `speed_mps`, `route_progress_pct`, `active_route_id`, `threat_ahead`.

---

## Track 2: Compute Rules, Comms Topology, Sensor Pipeline

**Goal:** Wire every sensor into the Isaac Lab scene config, implement compute budget enforcement and comms graph, and drive all actors with pretrained/deterministic controllers. No RL. All existing tests stay green. Make sure to use Isaac Sim to vialize 

### 2.1 New Files

| File | Purpose |
|---|---|
| `hades/comms.py` | `CommsGraph` — range-gated topology, latency model, relay path resolution |
| `hades/compute.py` | `ComputeScheduler` — local / offload / drop waterfall per TOPS budget |
| `hades/threats.py` | `ThreatSpawner` — deterministic (Track 2) and Poisson (Track 3) modes |
| `hades/navigation.py` | `DroneNavigator`, `ConvoyRouter` — pretrained-ONNX + Dijkstra controllers |
| `hades/models.py` | `ModelRegistry` — lazy ONNX loading, zero-output stub for test mode |
| `scripts/fetch_terrain.py` | Already exists; re-run with new Laughlin coords |
| `scripts/build_terrain_usd.py` | Already exists; re-run to patch scene.usda |

### 2.2 Files to Modify

| File | Change |
|---|---|
| `hades/config.py` | Add `RouteConfig`, `ComputeBudgetConfig`, `CommsLatencyConfig`; `SceneConfig.route_length_m=1200` |
| `hades/state.py` | Add `ThreatState`, `ComputeEvent` dataclasses; extend `ConvoyState` with `active_route_id`, `threat_ahead`; extend `SimFrame` with `threats: list[ThreatState]`, `compute_events: list[ComputeEvent]` |
| `bridge/sim_publisher.py` | Add `Track2SimPublisher` subclass — integrates comms/compute/navigation/threat step |
| `isaac/scene.usda` | Patched by `build_terrain_usd.py` after re-fetching Laughlin terrain |
| `isaac/load_scene.py` | `ROUTE_START_X=-580`, `ROUTE_END_X=580`; recompute 18 edge positions over 1200 m |
| `pyproject.toml` | Add to core deps: `numpy>=1.26`, `onnxruntime>=1.17`, `ahrs>=0.3`, `filterpy>=1.4`, `networkx>=3.2`, `scikit-image>=0.22` |

### 2.3 Communication Rules (enforced in `CommsGraph.reachable()`)

```
Small  ↔ Small:         WiFi mesh ≤150 m
Small  ↔ Parent:        WiFi mesh ≤150 m  OR  LoRa ≤2000 m
Parent ↔ Parent:        WiFi mesh ≤150 m  OR  LoRa ≤2000 m
Parent ↔ Static Edge:   WiFi mesh ≤150 m ONLY
Edge   ↔ Edge:          WiFi mesh ≤150 m (backbone)
Convoy edge ↔ all:      WiFi mesh ≤150 m (moving embedded node)
Small  → Static Edge:   FORBIDDEN — must relay through Parent
```

Latency: `base_ms + congestion_factor × active_links + distance_factor × max(0, dist−200)`.  
Link quality: `clamp(1 − dist/max_radius, 0, 1)`. Links < 0.05 quality are severed.

### 2.4 Compute Budget Rules (enforced in `ComputeScheduler`)

Decision waterfall: **local → nearest reachable Parent with headroom → reachable Edge (Parent only, via WiFi) → Convoy edge → drop.**

| Actor | Task | TOPS | Runs where |
|---|---|---|---|
| Small | MobileNetV2-SSD 320×240 INT8 | 0.08 | Local (fits in 0.5) |
| Small | Madgwick IMU fusion | 0.01 | Local |
| Small | Collision avoidance PD | 0.005 | Local |
| Small | YOLOv8n 1280×720 FP16 | 8.0 | Offload → Parent |
| Parent | YOLOv8n detection | 8.0 | Local |
| Parent | EKF sensor fusion | 5.0 | Local |
| Parent | A* path planning | 2.0 | Local |
| Parent | YOLOv8m (received from small) | 12.0 | Offload → Edge |
| Edge / Convoy | YOLOv8m inference job | 12.0 | Local (fits in 50) |

### 2.5 Pretrained Model Bootstrap

| Model | Source | Used by |
|---|---|---|
| MobileNetV2-SSD COCO INT8 ONNX | `torchvision` export | Small detection |
| YOLOv8n COCO FP16 ONNX | `ultralytics` export | Parent detection |
| YOLOv8m COCO FP32 ONNX | `ultralytics` export | Edge offloaded jobs |
| Madgwick filter | `ahrs` library | IMU fusion all tiers |
| Extended Kalman Filter | `filterpy` | Parent sensor fusion |
| A* occupancy grid | `scikit-image.graph.route_through_array` | Parent path planning |
| Dijkstra + threat penalty | `networkx` | Convoy route selection |

Weights download to `~/.hades/models/` on first use. `ModelRegistry.get_*(stub=True)` returns zero tensors — used in all unit tests.

### 2.6 New Tests

- `tests/test_comms_graph.py` — range gating, relay enforcement, no-small-to-static-edge
- `tests/test_compute_scheduler.py` — local/offload/drop decisions, TOPS arithmetic
- `tests/test_track2_publisher.py` — 10 ticks: threats appear, convoy reroutes, compute events fire

---

## Track 3: Isaac Lab RL Environment and MAPPO Training

**Goal:** Implement the HADES RL env as an Isaac Lab `DirectMARLEnv`, wire all sensors into observations, train with SKRL MAPPO. No bridge layer for training — Isaac Lab drives the loop directly.

### 3.1 Isaac Lab Env Files

| File | Purpose |
|---|---|
| `hades/env/__init__.py` | Package marker |
| `hades/env/hades_env_cfg.py` | `HADESEnvCfg(DirectMARLEnvCfg)` — scene, sim, sensor, actor, agent space config |
| `hades/env/hades_env.py` | `HADESEnv(DirectMARLEnv)` — implements all required methods |
| `hades/env/obs_builder.py` | `ObsBuilder` — flattens sensor tensors into per-agent obs vectors |
| `hades/env/reward.py` | `RewardCalculator` — shared + per-agent reward terms |
| `hades/env/action_executor.py` | `ActionExecutor` — maps RL actions to velocity/route commands |
| `hades/env/scene_cfg.py` | `HADESSceneCfg(InteractiveSceneCfg)` — all actor and sensor declarations |
| `scripts/train_rl.py` | SKRL MAPPO training launcher |
| `scripts/eval_policy.py` | Load checkpoint, run N episodes, print EpisodeScore |

### 3.2 Config Structure (`hades_env_cfg.py`)

```python
from isaaclab.utils.configclass import configclass
from isaaclab.envs import DirectMARLEnvCfg
from isaaclab.sim import SimulationCfg

@configclass
class HADESEnvCfg(DirectMARLEnvCfg):
    sim: SimulationCfg = SimulationCfg(dt=0.1)          # 10 Hz physics
    scene: HADESSceneCfg = HADESSceneCfg(num_envs=64)   # parallel episodes

    possible_agents: list[str] = (
        ["parent_0", "parent_1"] +
        [f"small_{i}" for i in range(6)]
    )  # 8 agents; convoy is rule-based

    observation_spaces: dict = {
        "parent_0": 64, "parent_1": 64,
        **{f"small_{i}": 32 for i in range(6)},
    }
    action_spaces: dict = {
        "parent_0": 4, "parent_1": 4,        # Box(4): (vx, vy, vz, yaw_rate)
        **{f"small_{i}": 7 for i in range(6)}, # Discrete(7): hold/N/S/E/W/up/relay
    }
    state_space: int = 0   # no centralised state tensor needed (critic uses concat obs)
```

### 3.3 Scene Config (`scene_cfg.py`)

All sensors declared here using Isaac Lab sensor config classes:

```python
from isaaclab.scene import InteractiveSceneCfg
from isaaclab.sensors import TiledCameraCfg, ImuCfg, RayCasterCfg
from isaaclab.utils.configclass import configclass

@configclass
class HADESSceneCfg(InteractiveSceneCfg):
    # Terrain
    terrain: TerrainImporterCfg = TerrainImporterCfg(
        usd_path="assets/terrain/terrain.usda",  # built by build_terrain_usd.py
        collision_group=-1,
    )

    # Parent drone sensors (pattern: parent_0 and parent_1 via ENV_REGEX)
    parent_nav_cam: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/nav_cam",
        data_types=["rgb", "distance_to_camera"],
        height=720, width=1280, update_period=0.1,
    )
    parent_thermal: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/thermal",
        data_types=["rgb"], height=512, width=640, update_period=0.1,
    )
    parent_lidar: RayCasterCfg = RayCasterCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/lidar",
        mesh_prim_paths=["{ENV_REGEX_NS}/hades_phase_1/terrain"],
        pattern_cfg=LidarPatternCfg(channels=32, vertical_fov_range=(-20, 20), horizontal_res=1.0),
        max_distance=100.0,
    )
    parent_imu: ImuCfg = ImuCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/parent_.*/imu",
        update_period=0.01,
    )

    # Small drone sensors
    small_cam: TiledCameraCfg = TiledCameraCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/small_.*/cam",
        data_types=["rgb"], height=240, width=320, update_period=0.1,
    )
    small_imu: ImuCfg = ImuCfg(
        prim_path="{ENV_REGEX_NS}/hades_phase_1/small_.*/imu",
        update_period=0.01,
    )

    # No edge node sensors — edge nodes are passive compute targets only.
    # No convoy sensors — convoy receives data from drones, does not perceive independently.
```

### 3.4 Environment Class (`hades_env.py`)

```python
from isaaclab.envs import DirectMARLEnv
from isaaclab.sensors import TiledCamera, IMUSensor, RayCaster
from hades.comms import CommsGraph
from hades.compute import ComputeScheduler
from hades.threats import ThreatSpawner
from hades.env.obs_builder import ObsBuilder
from hades.env.reward import RewardCalculator
from hades.env.action_executor import ActionExecutor
import torch

class HADESEnv(DirectMARLEnv):
    cfg: HADESEnvCfg

    def __init__(self, cfg: HADESEnvCfg, **kwargs):
        super().__init__(cfg, **kwargs)
        # Isaac Lab creates sensor objects from scene config
        self.parent_nav_cam = TiledCamera(cfg.scene.parent_nav_cam)
        self.parent_thermal  = TiledCamera(cfg.scene.parent_thermal)
        self.parent_lidar    = RayCaster(cfg.scene.parent_lidar)
        self.parent_imu      = IMUSensor(cfg.scene.parent_imu)
        self.small_cam       = TiledCamera(cfg.scene.small_cam)
        self.small_imu       = IMUSensor(cfg.scene.small_imu)
        # Edge nodes and convoy have no sensors; they are receive-only actors.

        self._obs_builder     = ObsBuilder(cfg)
        self._reward_calc     = RewardCalculator(cfg)
        self._action_exec     = ActionExecutor(cfg)
        self._threat_spawner  = ThreatSpawner(mode="random")
        self._comms           = CommsGraph(cfg)
        self._compute         = ComputeScheduler(cfg)

    def _setup_scene(self) -> None:
        # Clone num_envs copies of the hades_phase_1 prim hierarchy
        # Filter collisions between drone prims
        ...

    def _pre_physics_step(self, actions: dict[str, torch.Tensor]) -> None:
        # Store actions; run ComputeScheduler (decides offload targets this tick)
        self._actions = actions
        self._pending_compute = self._compute.schedule_all(self._last_frame, self._comms)

    def _apply_action(self) -> None:
        # Translate RL actions to joint velocity targets / articulation commands
        self._action_exec.apply(self._actions, self.scene)

    def _get_observations(self) -> dict[str, dict[str, torch.Tensor]]:
        # Read all sensors; pass raw tensors through ObsBuilder
        sensor_data = {
            "parent_nav_rgb":   self.parent_nav_cam.data.output["rgb"],
            "parent_nav_depth": self.parent_nav_cam.data.output["distance_to_camera"],
            "parent_thermal":   self.parent_thermal.data.output["rgb"],
            "parent_lidar":     self.parent_lidar.data.ray_hits_w,
            "parent_imu_acc":   self.parent_imu.data.lin_acc_b,
            "parent_imu_gyr":   self.parent_imu.data.ang_vel_b,
            "small_rgb":        self.small_cam.data.output["rgb"],
            "small_imu_acc":    self.small_imu.data.lin_acc_b,
            "small_imu_gyr":    self.small_imu.data.ang_vel_b,
            # Edge and convoy contribute no sensor data; their state (pose, compute_load,
            # route_progress) is read from the simulation prim transforms directly.
        }
        return self._obs_builder.build(sensor_data, self._comms, self._pending_compute)
        # Returns: {"parent_0": {"obs": tensor([num_envs, 64])}, "small_0": ..., ...}

    def _get_rewards(self) -> dict[str, torch.Tensor]:
        return self._reward_calc.compute(self._prev_frame, self._curr_frame, self._actions)

    def _get_dones(self) -> tuple[torch.Tensor, torch.Tensor]:
        convoy_dead = self._curr_frame["convoy_hit_threat"]    # bool [num_envs]
        convoy_done = self._curr_frame["convoy_at_endpoint"]   # bool [num_envs]
        timeout     = self.episode_length_buf >= self.max_episode_length
        terminated  = convoy_dead | convoy_done
        return terminated, timeout

    def _reset_idx(self, env_ids):
        # Reset actor poses to start, respawn threats, reset battery/compute
        self._threat_spawner.reset(env_ids)
        super()._reset_idx(env_ids)
```

### 3.5 Observation Vectors

**Small drone obs (dim 32):**  
`own_pose(6) + battery(1) + compute_load(1) + nearest_threat_relative(3) + threat_conf(1) + nearest_parent_relative(3) + parent_link_quality(1) + 8bin_threat_histogram(8) + time_since_relay(1) + offload_queue(1) + convoy_relative(3) + convoy_progress(1) + [padding 3]`

Visual input (320×240 RGB) goes through frozen MobileNetV2-SSD encoder → 128-dim embedding appended. Total with visual: **160 dim**.

**Parent drone obs (dim 64):**  
`own_pose(6) + battery(1) + compute_load(1) + convoy_relative(3) + route_progress(1) + per_small[relative(3)+battery(1)+link_quality(1)]×6=30 + 4×4_threat_grid(16) + nearest_3_edges[tops_free+latency]×3=6`

Visual: YOLOv8n frozen backbone → 512-dim detection embedding fed to critic only (not local actor policy, keeps actor lightweight). Total actor obs: **64 dim**. Critic obs: **576 dim**.

### 3.6 Action Spaces

- **Small:** `Discrete(7)` — {HOLD, MOVE_N, MOVE_S, MOVE_E, MOVE_W, MOVE_UP, RELAY_NOW}
- **Parent:** `Box(4)` clipped [−1, 1] → physical units (vx max 15 m/s, vz max 5 m/s, yaw_rate max π/4 rad/s)

Convoy routing is rule-based in Track 3: `ConvoyRouter` (Dijkstra + threat penalty from `hades/navigation.py`) selects route each step. Convoy becomes an RL agent only if Track 4 performance plateaus.

### 3.7 Reward Structure (per step)

```
# Shared across all 8 drone agents:
R_convoy    = +5.0 × route_progress_delta
            + 50.0  if convoy at endpoint  (terminal)
            - 100.0 if convoy hit threat   (terminal)
            - 0.1 × threat_proximity_score (threats <80 m of convoy)

R_detect    = +2.0 × new_unique_threats_detected
            + 0.5 × confidence_improvement_on_tracked_threats

R_coverage  = +0.1 × fraction_of_200m_ahead_corridor_under_observation

R_comms     = +0.3 per active relay link used
            - 0.1 per dropped offload job (compute budget exceeded)

R_battery   = -0.01 × total_battery_consumed_all_drones

# Per-agent only:
R_crash_i   = -50.0 if drone_i battery=0 or collision (terminal for that drone)
```

### 3.8 Training Configuration (`scripts/train_rl.py`)

Framework: **SKRL MAPPO** (only Isaac Lab-compatible trainer with true multi-agent support).

```python
from isaaclab_rl.wrappers import SkrlVecEnvWrapper
from skrl.agents.torch.mappo import MAPPO, MAPPO_DEFAULT_CONFIG
from skrl.trainers.torch import ParallelTrainer

# Env
env = HADESEnv(cfg=HADESEnvCfg())
env = SkrlVecEnvWrapper(env)   # must be last wrapper

# Policy: shared MLP(256,256) per agent tier (parents share weights, smalls share weights)
# Critic: centralised MLP(512,256) consumes concatenated global obs

trainer_cfg = {
    "timesteps": 20_000_000,
    "headless": True,
}
trainer = ParallelTrainer(cfg=trainer_cfg, env=env, agents=mappo_agents)
trainer.train()
# Checkpoints saved every 50k steps to checkpoints/hades_mappo/
```

CLI launch (from Isaac Lab root):
```bash
./isaaclab.sh -p scripts/train_rl.py \
    --task HADES-Convoy-Escort-v0 \
    --num_envs 64 \
    --headless \
    --algorithm MAPPO
```

### 3.9 New Tests

- `tests/test_hades_env.py` — reset/step API, obs dict shape, reward sign, no crash on random actions (headless, no Isaac required via mock scene)

---

## Track 4: Scored Demo Episode

**Goal:** A single 60-second Isaac Sim episode with 3 scripted acts, running the trained MAPPO checkpoint, producing a final `EpisodeScore`. No separate visualizer — Isaac Sim's viewport is the only render.

### 4.1 New Files

| File | Purpose |
|---|---|
| `hades/scoring.py` | `EpisodeScore` dataclass + `ScoreCalculator` |
| `scripts/run_demo.py` | `DemoOrchestrator` — loads checkpoint, runs 3-act episode, prints score |

### 4.2 Demo Acts

| Act | Sim time | What happens |
|---|---|---|
| 1: Departure | 0–15 s | Convoy departs from (−580, 0). Swarm forms escort ring. Comms links active in viewport. |
| 2: Threat contact | 15–40 s | 2 threats spawn at choke_a (bridge centre). Smalls detect via camera → relay to parents → ConvoyRouter switches to `north_bypass`. Compute offload events visible in terminal log. |
| 3: Bypass and arrival | 40–60 s | Convoy navigates bypass. One drone battery hits 20% → hardcoded return-to-base. Convoy reaches (580, 0). Score printed. |

`run_demo.py` falls back to the Track 2 pretrained-only (no RL) controller if no checkpoint is found.

### 4.3 EpisodeScore fields

```python
@dataclass
class EpisodeScore:
    convoy_reached_endpoint: bool
    time_to_complete_s: float
    threats_detected: int
    successful_reroutes: int       # convoy rerouted around a confirmed threat
    drone_losses: int
    mean_compute_utilisation: float
    relay_events: int
    mean_detection_latency_ms: float
```

### 4.4 Files Modified for Track 4

- `isaac/scene.usda` — patched to Laughlin terrain (re-run `fetch_terrain.py` + `build_terrain_usd.py` with new coords)
- `isaac/load_scene.py` — `ROUTE_START_X=−580`, `ROUTE_END_X=580`, 18 edges over 1200 m
- `pyproject.toml` — optional `[demo]` group: `rich>=13.7`, `tqdm>=4.66`

> **Actor sensor summary (final):** Only parent drones and small drones carry sensors. Edge nodes and convoy vehicles are receive-only — they accept offloaded compute jobs / reroute commands and report back state, but have no independent perception.

---

## Implementation Order

```
Track 2 —Isaac required, fully unit-testable:
  1. hades/state.py          — ThreatState, ComputeEvent, extend ConvoyState + SimFrame
  2. hades/config.py         — RouteConfig, ComputeBudgetConfig, CommsLatencyConfig
  3. hades/comms.py          — CommsGraph (critical path; all downstream depends on it)
  4. hades/compute.py        — ComputeScheduler
  5. hades/threats.py        — ThreatSpawner
  6. hades/models.py         — ModelRegistry with stubs
  7. hades/navigation.py     — DroneNavigator, ConvoyRouter
  8. bridge/sim_publisher.py — Track2SimPublisher (keeps existing tests green)
  9. tests/                  — test_comms_graph, test_compute_scheduler, test_track2_publisher
  10. Terrain update         — fetch_terrain.py + build_terrain_usd.py with Laughlin coords

Track 3 — requires Isaac Lab 5.1:
  11. hades/env/scene_cfg.py     — HADESSceneCfg with all sensor declarations
  12. hades/env/hades_env_cfg.py — HADESEnvCfg (DirectMARLEnvCfg)
  13. hades/env/obs_builder.py   — sensor tensor → per-agent obs vector
  14. hades/env/reward.py        — RewardCalculator
  15. hades/env/action_executor.py
  16. hades/env/hades_env.py     — HADESEnv (DirectMARLEnv), all 7 required methods
  17. scripts/train_rl.py        — SKRL MAPPO launcher
  18. scripts/eval_policy.py
  19. tests/test_hades_env.py

Track 4 — requires Track 3 checkpoint or Track 2 fallback:
  20. hades/scoring.py
  21. scripts/run_demo.py
  22. isaac/load_scene.py update — route geometry for 1200 m
```

---

## Verification

```bash
# Track 2 — no Isaac required
pytest tests/                         # all original 4 + ~15 new tests green
python -m bridge.server &             # bridge still works with Track2SimPublisher
python scripts/check_bridge.py        # 10 Hz frames with threats and compute_events

# Track 3 — requires Isaac Sim 5.1 + Isaac Lab
./isaaclab.sh -p scripts/train_rl.py --task HADES-Convoy-Escort-v0 \
    --num_envs 64 --headless --algorithm MAPPO
# Expect: reward climbing from ~−30 (random) to >+40 (escort learned) within 5M steps

# Track 4
./isaaclab.sh -p scripts/run_demo.py  # prints EpisodeScore; Isaac viewport renders live
```
