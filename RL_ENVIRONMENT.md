# HADES Reinforcement Learning Environment

This document explains the HADES RL environment: what the agents observe, what actions they can take, how rewards are calculated, how the simulator steps, and why MAPPO-style multi-agent training is appropriate for the convoy escort problem.

HADES is not training a single drone to fly around a map. It is training a cooperative, role-specialized drone team to protect a convoy while dealing with partial observability, limited communication, finite compute, battery pressure, and route threats.

## RL Objective

The RL objective is:

> Train parent and child drones to maintain useful coverage, detect threats, preserve relay paths, use edge compute intelligently, and help the convoy reach its endpoint alive.

This is a multi-agent, partially observable, cooperative task.

- **Multi-agent:** Two parent drones and six child drones act simultaneously.
- **Partially observable:** No drone sees the entire mission state.
- **Cooperative:** Rewards are mostly shared because convoy survival depends on team behavior.
- **Constrained:** Comms, compute, battery, and sensor limits affect every decision.
- **Mission-based:** The policy is scored by convoy outcome, not isolated drone behavior.

```text
flowchart TD
    A["Scenario state\nterrain, actors, threats, route"] --> B["Per-agent observations"]
    B --> C["MAPPO policies\nparents + children"]
    C --> D["Actions\nvelocity, movement, relay"]
    D --> E["Physics / publisher step"]
    E --> F["CommsGraph\nlinks, quality, latency"]
    E --> G["ComputeScheduler\nlocal, offload, drop"]
    E --> H["Threat + convoy route update"]
    F --> I["RewardCalculator"]
    G --> I
    H --> I
    I --> J["Policy update\ntrain over many episodes"]
    J --> C
```

## Environment Type

The target environment is an Isaac Lab style `DirectMARLEnv`.

| Property | Value |
|---|---|
| Environment class | `HADESEnv` |
| Config class | `HADESEnvCfg` |
| Physics timestep | `0.1 s` |
| Sim rate | `10 Hz` |
| Default vectorization | `64` parallel environments |
| Episode length | `60 s` |
| Agents | 2 parent drones + 6 child drones |
| Convoy | Rule-based, not currently an RL agent |
| Algorithm target | MAPPO-style multi-agent training through SKRL |

There are two execution modes:

- **Live Isaac mode:** Uses Isaac Sim/Isaac Lab, drone physics, procedural cameras, and controller calls.
- **Headless training mode:** Uses the Track 2 publisher and stubs where needed so training/testing can run without full Isaac Sim installed.

```text
flowchart LR
    subgraph Live["Live Isaac Mode"]
        L1["Isaac Sim SimulationApp"]
        L2["HADESEnv"]
        L3["Drone physics + cameras"]
    end

    subgraph Headless["Headless Mode"]
        H1["Track2SimPublisher"]
        H2["HADESEnv components"]
        H3["No physics/camera dependency"]
    end

    L3 --> O["Same obs/reward/action APIs"]
    H3 --> O
    O --> T["Training, eval, demo scoring"]
```

## Agents

The current RL agent set is:

| Agent | Tier | Role |
|---|---|---|
| `parent_0` | Parent | Coordinator, relay, heavy local compute |
| `parent_1` | Parent | Coordinator, relay, heavy local compute |
| `small_0` | Child | Scout, detect, relay |
| `small_1` | Child | Scout, detect, relay |
| `small_2` | Child | Scout, detect, relay |
| `small_3` | Child | Scout, detect, relay |
| `small_4` | Child | Scout, detect, relay |
| `small_5` | Child | Scout, detect, relay |

The convoy is deliberately not an RL agent in the current design.

- **Why:** It keeps the learning problem focused on drone teamwork.
- **Convoy behavior:** The convoy follows route logic using Dijkstra-style routing with threat penalties.
- **Future option:** The convoy can become an RL agent later if route behavior becomes the bottleneck.

## Action Spaces

Parent drones use continuous control:

```text
parent action = [vx, vy, vz, yaw_rate]
```

Physical scaling:

| Control | Range after scaling |
|---|---:|
| `vx` | `[-15, 15] m/s` |
| `vy` | `[-15, 15] m/s` |
| `vz` | `[-5, 5] m/s` |
| `yaw_rate` | `[-pi/4, pi/4] rad/s` |

Child drones use discrete control:

```text
0 = HOLD
1 = MOVE_N
2 = MOVE_S
3 = MOVE_E
4 = MOVE_W
5 = MOVE_UP
6 = RELAY_NOW
```

```text
flowchart TD
    A["MAPPO action"] --> B{"Agent tier"}
    B -- "Parent" --> C["Box(4)\nvx, vy, vz, yaw_rate"]
    C --> D["Lee controller\nrotor command in Isaac"]
    B -- "Child" --> E["Discrete(7)\nhold/move/relay"]
    E --> F["Target delta or relay flag"]
    D --> G["Updated actor state"]
    F --> G
```

## Observation Spaces

The policy receives compact state vectors, not raw full-resolution video. This makes training tractable while preserving the mission variables that matter.

Parent observation target:

| Component | Purpose |
|---|---|
| Own pose and motion | Where the parent is and how it is moving |
| Battery and compute load | Whether it can keep working |
| Convoy relative position and progress | Mission context |
| Per-child relative state | Where scouts are, their battery, link quality |
| Threat grid | Coarse threat map around convoy |
| Edge capacity and latency | Whether offload is useful |
| Compact camera feature | Lightweight visual cue |

Child observation target:

| Component | Purpose |
|---|---|
| Own pose and motion | Local navigation |
| Battery and compute load | Energy and processing budget |
| Nearest threat relative state | Local detection and tracking |
| Parent relative position and link quality | Relay and offload decisions |
| Offload queue pressure | Compute congestion awareness |
| Convoy relative position and progress | Escort geometry |
| Compact camera features | Local visual context |

```text
flowchart LR
    A["Drone sensors\nRGB/depth/thermal/LiDAR/IMU"] --> F["Feature extraction"]
    B["CommsGraph\nquality + latency"] --> O["ObsBuilder"]
    C["ComputeEvents\ndropped/scheduled"] --> O
    D["ThreatState\npose + confidence"] --> O
    E["ConvoyState\nroute + progress"] --> O
    F --> O
    O --> P["Parent obs\n64 dim"]
    O --> S["Child obs\n32 dim"]
    P --> M["MAPPO"]
    S --> M
```

## Sensor Fusion In The RL Loop

Sensor fusion happens before and during observation construction.

1. **Child drones** create lightweight visual/IMU summaries.
2. **Parent drones** combine child reports with parent sensor features.
3. **ComputeScheduler** decides whether heavier inference can run locally or on edge nodes.
4. **ThreatState** stores fused confidence, pose, spawn zone, and `detected_by`.
5. **ObsBuilder** converts fused state into agent-specific vectors.
6. **RewardCalculator** rewards new detections and confidence improvement.

```text
sequenceDiagram
    participant S as Child Drone
    participant P as Parent Drone
    participant E as Edge Node
    participant O as ObsBuilder
    participant M as MAPPO Policy

    S->>P: SensorSummary + candidate ThreatReport
    P->>P: Fuse child report with parent sensors
    P->>E: Offload heavy inference if reachable
    E-->>P: ComputeResult
    P->>O: Fused threat state + comms + compute events
    O->>M: Per-agent observations
    M-->>S: Move/relay action
    M-->>P: Velocity/coordinator action
```

## Reward Function

The reward is mostly shared across agents because the mission succeeds or fails as a team.

Shared reward components:

| Term | Effect |
|---|---|
| **Convoy progress** | Reward route progress |
| **Endpoint reached** | Large terminal reward |
| **Convoy hit** | Large terminal penalty |
| **Threat proximity** | Penalty for threats close to convoy |
| **New threat detection** | Reward new unique threat IDs |
| **Confidence improvement** | Reward better certainty on tracked threats |
| **Coverage** | Reward observing the corridor ahead |
| **Relay links** | Reward useful small-drone relay connectivity |
| **Dropped compute** | Penalize jobs that could not be scheduled |
| **Battery drain** | Penalize wasteful energy use |
| **Drone loss** | Per-agent penalty if battery reaches zero or crash/loss state occurs |

Simplified reward sketch:

```text
R_total =
    R_progress
  + R_terminal
  + R_detection
  + R_coverage
  + R_relay
  - R_threat_proximity
  - R_compute_drops
  - R_battery
  - R_crash
```

```text
flowchart TD
    A["Current SimFrame"] --> B["Route progress delta"]
    A --> C["Convoy hit / endpoint"]
    A --> D["Threats and confidence"]
    A --> E["Comms links"]
    A --> F["Compute events"]
    A --> G["Battery state"]
    B --> R["RewardCalculator"]
    C --> R
    D --> R
    E --> R
    F --> R
    G --> R
    R --> H["Reward per agent\nshape: num_envs"]
```

## Episode Lifecycle

One episode represents a convoy escort attempt through the scenario.

```text
flowchart TD
    A["reset"] --> B["Spawn/reset convoy, drones, threats, compute"]
    B --> C["Initial observation"]
    C --> D["policy actions"]
    D --> E["pre_physics_step\nstore actions"]
    E --> F["apply_action\nmove actors / step publisher"]
    F --> G["get_observations\nsensor + comms + compute fusion"]
    G --> H["get_rewards"]
    H --> I["get_dones"]
    I --> J{"done?"}
    J -- "No" --> D
    J -- "Yes" --> K["EpisodeScore / training update"]
```

Termination conditions:

- **Convoy reaches endpoint.**
- **Convoy is hit by a threat.**
- **Episode reaches time limit.**
- **Optional future:** catastrophic swarm loss, excessive route delay, or unrecoverable comms partition.

## Training Architecture

HADES uses MAPPO-style training because the task needs centralized learning of team outcomes with decentralized drone actions.

- **Centralized critic:** Learns convoy-level outcomes, coverage, relay value, and compute consequences.
- **Decentralized actors:** Each drone acts through its own observation and action space.
- **Tier-specialized policies:** Parent drones and child drones use different action semantics.
- **Parallel rollouts:** Many environment copies collect experience to stabilize training.
- **Checkpointing:** Policies are saved for evaluation and demo runs.

```text
flowchart LR
    E1["Env 1"] --> R["Rollout memory"]
    E2["Env 2"] --> R
    E3["... Env 64"] --> R
    R --> A["MAPPO update"]
    A --> P["Parent policy"]
    A --> S["Child policy"]
    P --> E1
    S --> E1
    P --> E2
    S --> E2
```

Target training command from the RL branch:

```powershell
python .\scripts\train_rl.py --num-envs 64 --timesteps 500000 --checkpoint-dir checkpoints/hades_mappo
```

Headless training command:

```powershell
$env:HADES_STUB="0"
python .\scripts\train_headless.py --num-envs 64 --timesteps 500000 --wandb --wandb-project hades-rl
```

Evaluation command:

```powershell
python .\scripts\eval_policy.py --checkpoint-dir checkpoints/hades_mappo --episodes 10
```

Demo command:

```powershell
python .\scripts\run_demo.py --stub --checkpoint-dir checkpoints/hades_mappo
```

## What The Policy Should Learn

A good HADES policy should learn behaviors that are hard to hand-code robustly.

- **Parent positioning:** Stay close enough to child drones for relay while remaining useful for route coverage.
- **Child scouting:** Spread out ahead of the convoy without breaking the network.
- **Relay timing:** Use `RELAY_NOW` when information flow matters more than exploration.
- **Compute discipline:** Avoid producing more heavy jobs than the network and edge layer can process.
- **Threat custody:** Keep observing important candidates until confidence is high enough for routing.
- **Battery discipline:** Preserve drones for the late episode instead of burning energy early.
- **Bypass support:** Gather enough evidence for the convoy to choose `north_bypass` or `south_bypass` when `main` is unsafe.
- **Failure recovery:** Keep the mission moving after a dropped job, weak link, or low-battery scout.

## Why RL Is Useful Here

Rules can solve the first scripted run. RL is useful because HADES needs behavior that remains effective across many variations.

- **Timing variation:** Threats can appear at different steps.
- **Spatial variation:** Drones and edge nodes can be in slightly different positions.
- **Network variation:** Link quality changes as actors move.
- **Compute variation:** Edge capacity can be free, congested, or unavailable.
- **Battery variation:** Some choices are good early but bad later.
- **Route variation:** The best route depends on current evidence, not a fixed plan.

RL lets HADES train on these variations and evaluate whether the learned policy generalizes.

## Metrics And Acceptance

A trained policy should be judged by mission metrics:

| Metric | What it proves |
|---|---|
| `convoy_reached_endpoint` | Mission success |
| `time_to_complete_s` | Speed and route efficiency |
| `threats_detected` | Perception effectiveness |
| `successful_reroutes` | Useful decision support |
| `drone_losses` | Swarm survivability |
| `mean_compute_utilisation` | Edge/parent compute efficiency |
| `relay_events` | Communication behavior |
| `mean_detection_latency_ms` | Timeliness of fused perception |
| `compute_drop_rate` | Whether architecture is overloaded |
| `mean_link_quality` | Network health |
| `total_return` | RL training signal |

```text
flowchart LR
    P["Trained policy"] --> E["Evaluation episodes"]
    E --> S["EpisodeScore"]
    S --> C{"Acceptable?"}
    C -- "No" --> T["Tune rewards, layout,\npolicy, or scenario"]
    C -- "Yes" --> D["Demo / compare / deploy to next test stage"]
```

## Implementation Map

Primary RL files in `<rl-training branch>`:

| Path | Role |
|---|---|
| `hades/env/hades_env.py` | Main environment lifecycle |
| `hades/env/hades_env_cfg.py` | Agent spaces, episode length, reward coefficients |
| `hades/env/obs_builder.py` | Builds parent and child observations |
| `hades/env/action_executor.py` | Converts actions into movement/relay commands |
| `hades/env/reward.py` | Computes shared and per-agent rewards |
| `hades/env/scene_cfg.py` | Isaac scene and actor declarations |
| `hades/comms.py` | Communication graph used by observations and offload |
| `hades/compute.py` | Compute scheduling and dropped-job events |
| `hades/scoring.py` | Evaluation and demo metrics |
| `scripts/train_rl.py` | Isaac-backed training launcher |
| `scripts/train_headless.py` | Headless training launcher |
| `scripts/eval_policy.py` | Checkpoint evaluation |
| `scripts/run_demo.py` | Scored demo episode |

## Summary

The HADES RL environment trains a cooperative drone team under field-like constraints. Parent drones learn coordination and placement. Child drones learn scouting and relay behavior. The convoy acts on fused intelligence. Edge compute is useful only when reachable and under capacity. Rewards tie every decision back to mission success.

That makes the RL environment a practical test of whether the HADES swarm can protect a convoy in degraded, compute-limited, time-sensitive conditions.

