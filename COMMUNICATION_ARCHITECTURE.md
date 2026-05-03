# HADES Drone Communication And Sensor Fusion Architecture

This document explains how HADES connects child drones, parent drones, edge nodes, and convoy vehicles into a hierarchical tactical autonomy network. It focuses on communication paths, directive flow, compute offload, sensor fusion, and how the swarm turns raw sensor data into route and mission decisions.

HADES uses the term **child drone** for the small scout UAV tier implemented as `small_0` through `small_5`. Parent drones are implemented as `parent_0` and `parent_1`. Static edge nodes are implemented as `edge_*`. Convoy vehicles are receive-only ground assets with embedded edge capability.

## Architecture Summary

- **Child drones:** Low-power scouts that carry lightweight cameras and IMU/kinematic state. They perform local lightweight detection, report sightings, relay when needed, and execute parent directives.
- **Parent drones:** Higher-compute aerial coordinators. They maintain wider situational awareness, fuse reports from child drones, relay traffic, run heavier local perception, and decide where to send compute jobs.
- **Static edge nodes:** Passive compute servers placed along the route. They have no sensors. They only process jobs they receive through valid communication paths.
- **Convoy edge:** Receive-only embedded compute and command interface on the convoy. It receives threat intelligence and route directives, reports convoy position/progress, and can serve as a fallback compute endpoint.
- **Bridge and sim frame:** The simulation publishes a 10 Hz `SimFrame` containing actors, links, threats, compute events, and convoy state for visualization, scoring, and training.

```text
flowchart LR
    subgraph Children["Child Drone Layer - small_0..small_5"]
        C0["Child Drone\nRGB + IMU\n0.5 TOPS"]
        C1["Child Drone\nRGB + IMU\n0.5 TOPS"]
        C2["Child Drone\nRGB + IMU\n0.5 TOPS"]
    end

    subgraph Parents["Parent Drone Layer - parent_0..parent_1"]
        P0["Parent Drone\nRGB/Depth/Thermal/LiDAR/IMU\n100 TOPS"]
        P1["Parent Drone\nCoordinator + Relay\n100 TOPS"]
    end

    subgraph Edge["Edge Compute Layer"]
        E0["Static Edge Node\nNo sensors\n50 TOPS"]
        E1["Static Edge Node\nNo sensors\n50 TOPS"]
        CV["Convoy Edge\nReceive-only\nFallback compute"]
    end

    subgraph Ground["Convoy Layer"]
        V["Convoy Vehicle\nRoute state\nNo independent perception"]
    end

    C0 <-- "WiFi mesh <=150 m\nor LoRa <=2000 m" --> P0
    C1 <-- "WiFi mesh <=150 m\nor LoRa <=2000 m" --> P0
    C2 <-- "WiFi mesh <=150 m\nor LoRa <=2000 m" --> P1
    C0 <-- "WiFi mesh <=150 m" --> C1
    P0 <-- "WiFi or LoRa" --> P1
    P0 <-- "WiFi only <=150 m" --> E0
    P1 <-- "WiFi only <=150 m" --> E1
    E0 <-- "WiFi backbone" --> E1
    P0 <-- "WiFi only <=150 m" --> CV
    CV --> V
```

## Actor Roles

| Tier | Code IDs | Sensors | Compute | Primary job |
|---|---|---:|---:|---|
| **Child drone** | `small_0`..`small_5` | RGB, IMU/kinematics | 0.5 TOPS | Scout, detect, relay, preserve coverage |
| **Parent drone** | `parent_0`, `parent_1` | RGB/depth, thermal, LiDAR, IMU target plan | 100 TOPS | Coordinate children, fuse tracks, relay, schedule compute |
| **Static edge node** | `edge_*` | None | 50 TOPS | Process offloaded perception jobs |
| **Convoy edge** | `convoy_*` | None | Edge-class fallback | Receive intel, route state, fallback compute |
| **Convoy vehicle** | `convoy_*` | None | Embedded receiver | Move along selected route |

Important invariant: **edge nodes and convoy vehicles do not perceive independently**. They only know what the drone network reports. This prevents the simulation from cheating and forces the communication architecture to matter.

## Communication Rules

`CommsGraph` rebuilds the active topology every simulation step from actor positions. A link exists only if the pair is allowed, within range, and above the minimum link-quality threshold.

| Link pair | Allowed path | Rule |
|---|---|---|
| **Child <-> Child** | WiFi mesh | `<=150 m` |
| **Child <-> Parent** | WiFi mesh or LoRa | WiFi `<=150 m`, LoRa `<=2000 m` |
| **Parent <-> Parent** | WiFi mesh or LoRa | WiFi `<=150 m`, LoRa `<=2000 m` |
| **Parent <-> Static edge** | WiFi mesh only | `<=150 m` |
| **Edge <-> Edge** | WiFi mesh backbone | `<=150 m` |
| **Convoy edge <-> any actor** | WiFi mesh only | `<=150 m` |
| **Child -> Static edge** | Forbidden direct path | Must relay through a parent |

```text
flowchart TD
    A["Actor positions at tick t"] --> B["Classify actor pair\nCHILD, PARENT, EDGE, CONVOY"]
    B --> C{"Is pair allowed?"}
    C -- "No" --> X["No link"]
    C -- "Yes" --> D{"Within radio range?"}
    D -- "No" --> X
    D -- "Yes" --> E["Compute quality\n1 - distance / max_radius"]
    E --> F{"Quality >= 0.05?"}
    F -- "No" --> X
    F -- "Yes" --> G["Add graph edge\nwith type, distance, quality"]
    G --> H["Expose links in SimFrame"]
```

Link quality:

```text
quality = clamp(1 - distance / max_radius, 0, 1)
```

Latency:

```text
latency_ms = base_ms
           + congestion_factor * active_links
           + distance_factor * max(0, distance_m - 200)
```

This means a technically reachable actor can still be a bad relay choice when the network is congested, far away, or close to the quality cutoff.

## Message Types

HADES can be understood as a small set of recurring messages passed across the graph.

| Message | Producer | Consumer | Payload |
|---|---|---|---|
| **HealthBeacon** | Child, parent, edge, convoy | Parent, bridge, policy | Pose, battery, compute load, alive state |
| **SensorSummary** | Child, parent | Parent, obs builder, critic | Compact RGB/depth/thermal/LiDAR/IMU features |
| **ThreatReport** | Child, parent, edge result | Parent fusion, convoy router | Threat ID/candidate, pose, confidence, timestamp, detected_by |
| **ComputeJob** | Child or parent | Parent, static edge, convoy edge | Task name, required TOPS, source actor, priority |
| **ComputeResult** | Parent, edge, convoy edge | Parent fusion, child/convoy | Detection output, latency, confidence, dropped flag |
| **Directive** | Parent policy/controller | Child drones, convoy | Move, hold, relay, track, return, reroute, slow/hold |
| **RouteIntent** | Convoy router | Convoy vehicle, bridge | Active route, progress, threat_ahead |

```text
sequenceDiagram
    participant C as Child Drone
    participant P as Parent Drone
    participant E as Static Edge Node
    participant V as Convoy Edge
    participant R as Convoy Router

    C->>C: RGB + IMU local preprocessing
    C->>P: ThreatReport + SensorSummary
    P->>P: Fuse child report with parent sensors
    P->>E: ComputeJob if heavy inference is needed
    E-->>P: ComputeResult with latency and confidence
    P->>R: Confirmed threat + confidence
    R->>V: RouteIntent: switch to safer route
    P->>C: Directive: relay/track/cover sector
    V-->>P: Convoy position and route progress
```

## Directive Flow

Directives are top-down mission commands generated from fused state, policy actions, and rule-based convoy routing. They are not raw joystick inputs; they are compact behaviors that child drones and convoy logic can execute.

Parent-to-child directives:

- **Scout sector:** Move to a sector ahead or beside the convoy.
- **Track threat:** Keep observing a candidate object or zone.
- **Relay now:** Prioritize communications link maintenance over exploration.
- **Hold:** Maintain current pose or coverage.
- **Move N/S/E/W/up:** Discrete child movement actions used by the RL policy.
- **Return or conserve:** Move closer to parent/convoy or reduce activity when battery is low.
- **Upload summary:** Send compact detection state instead of raw video when bandwidth is constrained.

Parent-to-convoy or router directives:

- **Threat ahead:** Mark current route as unsafe or high-cost.
- **Reroute:** Switch from `main` to `north_bypass` or `south_bypass`.
- **Slow or hold:** Reduce route progress when detection confidence is uncertain.
- **Resume:** Continue once the ahead corridor is observed and threat cost is acceptable.

```text
flowchart LR
    S["Fused swarm state"] --> P["Parent policy/controller"]
    P --> C1["Child directive\nmove/relay/track/hold"]
    P --> C2["Compute directive\noffload/drop/local"]
    P --> R["Threat intelligence"]
    R --> V["Convoy directive\nreroute/slow/resume"]
    V --> F["Updated SimFrame\nroute_progress + active_route"]
```

## Compute Offload Architecture

Compute is scheduled by a waterfall. The scheduler tries to run local work first when appropriate, then offloads only through valid communication paths.

Waterfall:

1. **Local:** Run on the actor if it is a local task and the actor has TOPS headroom.
2. **Child -> parent:** Child heavy jobs offload to nearest reachable parent with headroom.
3. **Parent -> static edge:** Parent heavy jobs offload to nearest reachable edge node over WiFi.
4. **Parent -> convoy edge:** If static edge is not available, use the convoy edge fallback.
5. **Drop:** If no legal target has compute headroom, the job is dropped and recorded.

```text
flowchart TD
    J["Compute task generated"] --> L{"Local task and local headroom?"}
    L -- "Yes" --> A["Run locally\nlatency=0"]
    L -- "No" --> T{"Source actor tier"}
    T -- "Child heavy job" --> P{"Reachable parent\nwith headroom?"}
    P -- "Yes" --> PR["Schedule on parent\nrecord latency"]
    P -- "No" --> D["Drop job"]
    T -- "Parent heavy job" --> E{"Reachable static edge\nwith headroom?"}
    E -- "Yes" --> ER["Schedule on edge\nrecord latency"]
    E -- "No" --> C{"Reachable convoy edge\nwith headroom?"}
    C -- "Yes" --> CR["Schedule on convoy edge\nrecord latency"]
    C -- "No" --> D
```

Compute examples:

| Source | Task | TOPS | Normal execution |
|---|---:|---:|---|
| **Child** | MobileNetV2-SSD 320x240 INT8 | 0.08 | Local |
| **Child** | Madgwick IMU fusion | 0.01 | Local |
| **Child** | Collision avoidance PD | 0.005 | Local |
| **Child** | YOLOv8n-style heavier detection | 8.0 | Offload to parent |
| **Parent** | YOLOv8n detection | 8.0 | Local |
| **Parent** | EKF sensor fusion | 5.0 | Local |
| **Parent** | A* path planning | 2.0 | Local |
| **Parent** | YOLOv8m heavy inference | 12.0 | Offload to edge |
| **Edge/convoy edge** | YOLOv8m inference result | 12.0 | Local on edge target |

## Sensor Fusion Pipeline

Sensor fusion turns many local observations into one useful mission picture.

Child drone sensing:

- **RGB camera:** Local object candidates, terrain/route context, visual threat cues.
- **IMU/kinematics:** Motion state, stabilization, pose-relative interpretation, battery-aware movement.
- **Local lightweight model:** Produces compact detections that fit the child compute budget.

Parent drone sensing:

- **RGB/depth camera:** Visual detection plus range/depth context.
- **Thermal camera:** Heat signatures and low-light/obscured contrast in the target plan.
- **LiDAR/ray casting:** 3D obstacle and terrain structure in the target plan.
- **IMU/kinematics:** Stabilized pose, velocity, angular motion, and fusion correction.
- **Heavy local models:** More capable detection and track refinement.

Edge-node processing:

- **No direct sensors:** Edge nodes only process received jobs.
- **Heavy inference:** Edge nodes run jobs that exceed parent or child capacity.
- **Result return:** Edge results return as confidence, location, latency, and dropped/completed status.

```text
flowchart TD
    subgraph Child["Child Drone"]
        CRGB["RGB frame"] --> CM["MobileNet / compact visual feature"]
        CIMU["IMU + kinematics"] --> CP["Pose-normalized detection"]
        CM --> CTR["Child ThreatReport"]
        CP --> CTR
    end

    subgraph Parent["Parent Drone"]
        PRGB["RGB/depth"] --> PF["Parent local detection"]
        PTH["Thermal"] --> PF
        PLD["LiDAR / ray hits"] --> PF
        PIMU["IMU + kinematics"] --> PF
        CTR --> FUSE["Track fusion\nassociation + confidence update"]
        PF --> FUSE
    end

    subgraph EdgeNode["Edge Node"]
        JOB["Offloaded heavy job"] --> INF["YOLOv8m / heavy inference"]
        INF --> RES["ComputeResult"]
    end

    FUSE --> NEED{"Need heavier inference?"}
    NEED -- "Yes" --> JOB
    RES --> FUSE
    NEED -- "No" --> PIC["Fused threat picture"]
    FUSE --> PIC
    PIC --> ROUTE["Convoy route decision"]
    PIC --> OBS["RL observation vector"]
```

Fusion logic, step by step:

1. **Timestamp and pose-align:** Convert each detection from local drone coordinates into scene/world coordinates using actor pose.
2. **Associate detections:** Match new detections to existing candidate tracks by spatial distance, time, confidence, and sensor source.
3. **Deduplicate:** Merge multiple child reports that likely describe the same threat.
4. **Update confidence:** Raise confidence when independent sensors agree; decay confidence when a track is not reacquired.
5. **Estimate threat geometry:** Track relative position to convoy, route segment, and chokepoint.
6. **Request compute if needed:** Send ambiguous or high-value detections to parent or edge compute.
7. **Publish fused state:** Add confirmed or candidate threats to the frame and observation vectors.
8. **Drive decisions:** Feed route planning, policy observations, rewards, and demo scoring.

## Decision Pipeline

The system makes decisions once per simulation tick.

```text
flowchart TD
    A["Tick t"] --> B["Read actor poses, battery, compute load"]
    B --> C["Read drone sensors\nRGB/depth/thermal/LiDAR/IMU"]
    C --> D["Build CommsGraph\nlinks + quality + latency"]
    D --> E["Run local detection and fusion"]
    E --> F["Schedule compute jobs\nlocal/offload/drop"]
    F --> G["Build observations\nper parent + per child"]
    G --> H["RL policy actions\nparent continuous + child discrete"]
    H --> I["ActionExecutor\nmovement + relay directives"]
    E --> J["ConvoyRouter\nDijkstra + threat penalty"]
    J --> K["RouteIntent\nmain/north/south bypass"]
    I --> L["Update SimFrame"]
    K --> L
    L --> M["Reward + score\nconvoy, threat, comms, battery, compute"]
```

The parent drone is the main tactical coordinator, but it is not omniscient. It only receives:

- Its own sensor outputs.
- Child reports that arrive across valid links.
- Edge compute results from jobs that were legally scheduled.
- Convoy route/progress state from the convoy edge.
- Current link and compute state from the simulation frame.

That limitation is intentional. HADES tests whether the architecture works when information is partial and delayed.

## RL Observation Fusion

For training, raw world state is converted into compact per-agent observation vectors.

Child observation includes:

- **Own pose, battery, compute load.**
- **Nearest threat relative position and confidence.**
- **Nearest/best parent relative position and link quality.**
- **Offload queue pressure.**
- **Convoy relative position and route progress.**
- **Compact camera features.**

Parent observation includes:

- **Own pose, battery, compute load.**
- **Convoy relative position and progress.**
- **Per-child relative position, battery, and link quality.**
- **Threat grid around the convoy.**
- **Nearest edge free capacity and latency.**
- **Compact camera feature.**

```text
flowchart LR
    SD["Sensor data"] --> OB["ObsBuilder"]
    CG["CommsGraph\nlink quality + latency"] --> OB
    CE["ComputeEvents\ndropped + scheduled jobs"] --> OB
    TH["ThreatState\nconfidence + pose"] --> OB
    CV["ConvoyState\nroute + progress"] --> OB
    DS["DroneState\nbattery + compute"] --> OB
    OB --> PO["Parent obs\n64 dim"]
    OB --> CO["Child obs\n32 dim"]
    PO --> MAPPO["MAPPO policy"]
    CO --> MAPPO
```

## Threat-To-Reroute Example

This is the core HADES scenario: a child drone detects a threat near the direct route, the parent fuses the report, edge compute strengthens confidence, and the convoy switches to a safer bypass.

```text
sequenceDiagram
    participant S as small_2
    participant P as parent_0
    participant E as edge_7
    participant R as ConvoyRouter
    participant C as convoy_0
    participant F as SimFrame

    S->>S: Detect candidate threat near choke_a
    S->>P: ThreatReport(conf=0.48, pose, timestamp)
    P->>P: Associate with parent RGB/depth/thermal/LiDAR cue
    P->>E: Offload YOLOv8m job if WiFi edge reachable
    E-->>P: ComputeResult(conf=0.82, latency_ms)
    P->>R: Confirmed threat on main route
    R->>C: Directive: active_route_id = north_bypass
    P->>S: Directive: track threat + maintain relay
    C-->>F: route_progress_pct + active_route_id
    F-->>F: Score reroute, latency, relay, compute utilization
```

## Failure And Attack Vectors Modeled

HADES treats the communication system as part of the mission, not plumbing that always works.

- **Range loss:** Actors drift outside WiFi or LoRa ranges and links disappear.
- **Low-quality links:** Links near the range edge can fall below the quality threshold.
- **Congestion:** More active links increase latency.
- **Compute overload:** Jobs are dropped when no valid actor has TOPS headroom.
- **Forbidden paths:** Child drones cannot bypass parent control and talk directly to static edge nodes.
- **Edge unavailability:** Static nodes can be out of range, overloaded, or dead.
- **Battery pressure:** Drones that chase every objective can damage mission endurance.
- **Delayed threat custody:** A detection can become stale if the swarm fails to reacquire it.
- **Route denial:** A threat near a chokepoint raises route cost and can force a bypass.
- **Partial observability:** No actor has a perfect global picture.

## Implementation Map

Primary implementation references in `C:\Users\agni_\Documents\HADES-rl-training`:

| File | Responsibility |
|---|---|
| `hades/comms.py` | Range-gated graph, link quality, latency, relay paths |
| `hades/compute.py` | TOPS-budget local/offload/drop scheduling |
| `hades/state.py` | `DroneState`, `EdgeState`, `ThreatState`, `ComputeEvent`, `ConvoyState`, `CommsLink`, `SimFrame` |
| `hades/env/obs_builder.py` | Sensor, comms, compute, threat, and convoy state into policy observations |
| `hades/env/action_executor.py` | Converts policy actions into movement/relay behavior |
| `hades/env/reward.py` | Rewards convoy progress, detections, relay quality, dropped compute, battery, and crashes |
| `hades/navigation.py` | Convoy route selection and threat-aware navigation logic |
| `bridge/sim_publisher.py` | 10 Hz frame production for bridge, demo, and tests |

Primary planning reference in `C:\Users\agni_\Documents\HADES-main`:

| File | Responsibility |
|---|---|
| `plan.md` | Track 2-4 architecture target, route geometry, sensors, compute rules, training plan |

## Technical Takeaway

HADES is a hierarchical swarm architecture where sensing, communication, compute, and routing are coupled:

- **Child drones** generate local observations and relay compact intelligence.
- **Parent drones** fuse information, coordinate movement, and decide compute placement.
- **Edge nodes** provide heavy processing only when legal, reachable, and under capacity.
- **The convoy** acts on received intelligence but does not magically sense threats.
- **The RL policy** learns to protect the convoy by balancing coverage, latency, battery, link quality, and compute load.

The result is a testbed for whether a drone-edge architecture can preserve decision quality under the same constraints that break many real-world systems: degraded communications, scarce compute, partial observability, energy limits, and time pressure.

