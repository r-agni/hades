# HADES: Hierarchical Autonomous Drone Edge System

[Demo video](https://www.youtube.com/watch?v=cuLlt9UxrS0)

HADES is a simulation and training project for defensive autonomous drone swarms operating around a convoy, route, or protected area when communications are degraded and compute is scarce. The core idea is simple: one drone with one camera is useful, but a hierarchy of small scouts, parent relay drones, edge compute nodes, and convoy-side command logic can keep working when a single operator feed, cloud server, or cellular link fails.

The project is security-first, but not security-only. The same technical problem appears in humanitarian response, public safety, disaster logistics, search and rescue, wildfire response, and infrastructure inspection: people need fast aerial perception and safe route decisions before the ground picture is complete.

HADES is framed for defensive protection, emergency response, resilience, and human-supervised decision support. It is not a weaponization project and should not be used to automate harmful targeting or unsupervised force decisions.

## Temporary Media

These videos are temporary simulations and early visual references. They are not the final Isaac Sim 6.0 environment. Final simulation videos will be added later.

| Preview | Link | Notes |
|---|---|---|
| [![HADES simV1 temporary simulation](https://img.youtube.com/vi/UTx-ue-XfFI/hqdefault.jpg)](https://youtu.be/UTx-ue-XfFI) | [HADES simV1](https://youtu.be/UTx-ue-XfFI) | Temporary simulation reference for the current convoy/swarm concept. |
| [![HADES simv3 temporary simulation](https://img.youtube.com/vi/gaawL6yjg1o/hqdefault.jpg)](https://youtu.be/gaawL6yjg1o) | [HADES simv3](https://youtu.be/gaawL6yjg1o) | Temporary simulation reference that will be replaced by final Isaac captures. |
| [![HADES temporary simulation reference](https://img.youtube.com/vi/2omBTuV8wPA/hqdefault.jpg)](https://youtu.be/2omBTuV8wPA) | [HADES sim reference](https://youtu.be/2omBTuV8wPA) | Temporary simulation/media reference for the evolving HADES concept. |
| [![HADES temporary environment reference](https://img.youtube.com/vi/kKx2W4P_vSQ/hqdefault.jpg)](https://youtu.be/kKx2W4P_vSQ) | [HADES environment reference](https://youtu.be/kKx2W4P_vSQ) | Temporary environment/media reference that will be replaced by final Isaac/Cesium captures. |

![Public-domain drone swarm field experiment from DVIDS](https://d1ldvf68ux039x.cloudfront.net/thumbs/photos/2112/6968384/850w_q95.jpg)

Public-domain U.S. Army/DVIDS photo from a DARPA OFFSET field experiment, included as contextual imagery for swarm-scale autonomy. This is not a HADES render.

![WFP drone field work](https://drones.wfp.org/sites/default/files/node/activity/field_cover/2021-01/i-mvcCS95-XL.jpg)

World Food Programme drone field image, included as contextual imagery for humanitarian drone operations. This is not a HADES render.

## Why HADES Exists

Modern security and emergency-response teams face a timing problem. Convoys, responders, and aid teams often move through areas where the map is stale, communications are congested, roads are blocked, threats are mobile, and cloud access is unreliable. The first few minutes matter. A route that looked safe can become unsafe. A damaged bridge, fire front, flood cut, drone incursion, road ambush, or collapsed communications tower can turn a planned movement into an emergency.

The broader world is already moving toward autonomous and semi-autonomous systems. The U.S. Defense Innovation Unit describes Replicator as a Department of Defense effort to accelerate autonomous capabilities at speed and scale, with Replicator 1 focused on fielding multiple thousands of all-domain attritable autonomous systems and Replicator 2 focused on countering small uncrewed aerial systems around critical installations and force concentrations ([DIU Replicator](https://www.diu.mil/replicator)). In August 2025, DoD also announced a Joint Interagency Task Force for affordable counter-UAS capabilities, explicitly citing the growing threat of hostile drones to personnel, equipment, and facilities ([DoD C-sUAS task force](https://www.defense.gov/News/Releases/Release/Article/4289621/dod-establishes-joint-interagency-task-force-to-deliver-affordable-c-suas-capab/)).

The humanitarian and public-safety side is just as urgent. The World Meteorological Organization reports nearly 12,000 weather, climate, and water-related disasters from 1970 to 2021, with reported losses of US$4.3 trillion and about 2 million deaths, 90 percent in developing countries ([WMO Atlas](https://wmo.int/publication-series/atlas-of-mortality-and-economic-losses-from-weather-climate-and-water-related-hazards-1970-2021)). UN Geneva reported that the Global Humanitarian Overview 2026 seeks US$33 billion to reach 135 million people in 50 countries, with an immediate US$23 billion priority for 87 million people affected by war, climate disasters, earthquakes, epidemics, and crop failures ([UN Geneva GHO 2026](https://www.ungeneva.org/en/news-media/news/2025/12/113710/humanitarians-launch-33-billion-appeal-2026)). UNDRR's GAR 2025 argues that disaster costs exceed US$2.3 trillion annually when cascading and ecosystem costs are included ([UNDRR GAR 2025](https://www.undrr.org/gar2025)).

HADES exists because both domains need the same capability: resilient aerial perception and route decision support that does not collapse when the network, cloud, or a single vehicle fails.

## What The Field Uses Today

Current drone use is real and growing, but most deployments still depend on isolated aircraft, direct operator feeds, or post-flight processing.

In humanitarian work, WFP reports drone activity across 15 countries, capacity building for more than 400 participants, drones prepositioned in 5 regions, and more than 50 activities from mapping to emergency response since 2017 ([WFP drones](https://www.wfp.org/wfp-drones)). WFP describes drones as useful for assessing disaster damage, monitoring food security, supporting search and rescue, restoring communications, and helping responders coordinate. WFP's training package covers coordination, mapping, and flight operations, which is a strong signal that the hard part is not only flying drones but integrating them into safe response workflows.

In Mozambique after cyclones Idai and Kenneth, WFP combined drones and AI for humanitarian emergency assessment. Thousands of drone images were stitched into maps for response decisions, and WFP's DEEP system reduced analysis time from weeks to hours ([WFP AI and drones in emergencies](https://www.wfp.org/stories/joining-dots-how-ai-and-drones-are-transforming-emergencies)). That is exactly the kind of gap HADES is designed around: the data is valuable, but delay reduces its value.

Connectivity is another active area. WFP's R2C2 project uses a tethered drone and communications payload as a portable 90-metre tower, providing 24/7 coverage over 72 square kilometers and reducing per-user connectivity costs from US$40 to US$4 in its model ([WFP R2C2](https://innovation.wfp.org/project/r2c2)). This shows why aerial systems matter beyond imagery: a drone can also be a communication node.

In public safety, NIST notes that responders need networks and applications to continue functioning when cellular coverage is absent, backhaul is limited, or interference and congestion degrade communications ([NIST resilient systems](https://www.nist.gov/ctl/pscr/resilient-systems)). NIST's connected drones report says public-safety UAS are predominantly used for visual information, increasingly including thermal imagery and 3D mapping, especially where it is difficult, dangerous, or impossible to gather information otherwise ([NIST connected drones PDF](https://www.nist.gov/system/files/documents/2024/05/13/AUTONOMOUSAERIALDRONESCONNECTINGPUBLICSAFETYOPPORTUNITIESANDCHALLENGESFORTHEFUTURE.pdf)). FAA guidance also supports public agencies through Part 107 or public-aircraft COA pathways and emergency authorizations for natural disasters and other emergency response ([FAA public-safety drone operations](https://www.faa.gov/uas/public_safety_gov/drone_program)).

The field is not starting from zero. The problem is that most systems are not trained as a constrained, cooperative, compute-aware swarm before they are expected to operate in the real world.

## Where Current Systems Break

Single-drone operations are useful, but fragile. They often depend on one pilot, one control unit, one video feed, one radio link, and one battery. When the link drops or the operator loses line of sight, the aircraft can stop being useful at the moment it is most needed.

Cloud-centric workflows are also fragile. NIST describes a common pattern where a UAV sends video to the operator control unit, the control unit relays it through a cellular network to an internet streaming server, and responders then pull the stream back down over cellular devices. That path can work in a normal city. It is a poor default for a disaster, convoy, wildfire, or contested infrastructure scenario where cellular service is congested, partial, or unavailable. NIST also highlights latency as a major disadvantage of cellular/cloud routing for UAV control because image and command delays can vary rapidly under congestion.

Humanitarian mapping has a different version of the same bottleneck. Aerial imagery can be collected quickly, but converting thousands of images into useful damage assessment can take too long. WFP's Mozambique work is important because it shows the value of AI-assisted analysis, but it also shows why the system needs to move closer to the sensors.

Security operations add another constraint: adversarial or hostile drone activity can appear faster than traditional procurement, fixed infrastructure, and manual command workflows can adapt. DoD's Replicator and C-sUAS announcements show that autonomy, counter-drone sensing, and scalable unmanned systems are no longer distant research topics. They are operational priorities.

HADES directly models these failure modes:

- Bandwidth is limited.
- Links have range and quality.
- Compute capacity is finite.
- Heavy perception jobs can be offloaded, delayed, or dropped.
- Edge nodes do not magically perceive the world.
- The convoy cannot see threats by itself.
- Route safety depends on what the swarm can detect and relay in time.
- The learned policy is rewarded for mission outcomes, not just pretty flight paths.

## The HADES Advantage

HADES is not just a drone demo. It is a testbed for hierarchical autonomy under realistic constraints.

The hierarchy matters:

- Small scout drones explore, observe, and relay.
- Parent drones carry heavier compute and act as aerial coordinators.
- Static edge nodes provide local compute where they are reachable.
- The convoy carries an embedded edge receiver and follows reroute decisions.
- The bridge and simulation state expose the whole system as a 10 Hz `SimFrame` stream for visualization, testing, and later integration.

The compute model matters:

- Small drones can run lightweight local inference and IMU fusion.
- Heavy detections can be offloaded to parent drones.
- Parent drones can offload larger jobs to static edge nodes when WiFi range and capacity allow.
- Convoy edge compute is a last-resort receiver.
- Jobs that cannot fit the compute and link constraints are dropped, and the policy pays a cost.

The communications model matters:

- Small-to-small, small-to-parent, parent-to-parent, parent-to-edge, edge-to-edge, and convoy-edge links have different rules.
- Small drones are not allowed to offload directly to static edge nodes; they must relay through a parent.
- Link quality declines with distance, and low-quality links are severed.
- Latency rises with congestion and distance.

The training model matters:

- HADES uses multi-agent reinforcement learning so agents learn cooperation rather than isolated behavior.
- Parent drones and small drones have different action spaces.
- The convoy remains rule-based in the current training plan, keeping the learning problem focused on aerial protection and relay behavior.
- Rewards combine convoy progress, endpoint arrival, threat detection, coverage, relay behavior, dropped compute penalties, battery cost, and crash/loss penalties.

This gives HADES a large practical advantage over a simple visual demo: it can measure whether the swarm detects threats, keeps the convoy alive, uses compute efficiently, maintains relay coverage, and arrives on time.

## Why HADES Is Better Than Common Current Approaches

HADES is designed to be stronger than the usual choices of one-off drone flights, manual pilots, cloud-only analytics, static CCTV, or disconnected simulation demos.

- **Better than a single drone:** HADES trains a coordinated swarm, so one battery, link, or sensor failure does not collapse the whole mission picture.
- **Better than manual-only piloting:** HADES can evaluate policies over repeated episodes, giving measurable evidence of route safety, detection latency, relay quality, and compute load before people enter the field.
- **Better than cloud-only AI:** HADES models edge inference, parent-drone offload, and dropped jobs, so the system is tested under realistic bandwidth and latency limits instead of assuming perfect internet.
- **Better than static cameras:** HADES moves the sensors with the convoy and can reallocate drones around bridges, chokepoints, blind spots, and route changes.
- **Better than basic mapping drones:** HADES does not stop at imagery collection; it connects perception to routing, communications, compute scheduling, and mission scoring.
- **Better than scripted demos:** HADES turns the scenario into a trainable multi-agent environment where success is measured by convoy survival, arrival, detections, reroutes, compute efficiency, and relay behavior.
- **Better than unconstrained autonomy tests:** HADES explicitly simulates battery drain, link degradation, compute capacity, threat proximity, latency, congestion, offload failures, and drone losses.
- **Better for decision-makers:** HADES produces repeatable metrics, not just video. Leaders can compare policies, routes, sensor mixes, edge-node layouts, and failure conditions.

## Security Use Cases

HADES is built for defensive security missions where the goal is to protect people, vehicles, routes, and infrastructure.

- **Convoy escort:** Small drones scout ahead and around a moving convoy, parent drones hold relay and compute positions, edge nodes process heavier jobs, and the convoy reroutes when threat intelligence makes the direct path unsafe.
- **Route reconnaissance:** The system can compare route choices before committing vehicles, using recent drone observations rather than trusting a stale map or a single preplanned road.
- **Critical-infrastructure monitoring:** Bases, airfields, ports, power facilities, hospitals, data centers, and logistics hubs can be modeled as protected zones with low-altitude aerial awareness.
- **Defensive C-UAS sensing:** HADES can train detection, tracking, relay, and alerting behavior for suspicious aerial activity while keeping decisions human-supervised.
- **Mobile perimeter security:** The swarm can shift coverage as a convoy, field team, or command post moves, instead of depending on fixed cameras or fixed towers.
- **Chokepoint awareness:** Bridges, tunnels, intersections, industrial approaches, and narrow roads can be simulated as high-risk zones where drones must maintain coverage.
- **Disaster-zone security:** After hurricanes, earthquakes, floods, fires, or conflict-related infrastructure damage, HADES can model aid convoy overwatch, route denial, degraded communications, and local compute.
- **Training and rehearsal:** Teams can test tactics, edge-node placement, sensor mixes, and route plans in a high-risk scenario without exposing real personnel or aircraft.

## Humanitarian And Public-Safety Use Cases

The humanitarian value comes from the same constraints that make the security problem hard: uncertainty, degraded networks, limited time, and dangerous terrain.

- **Search and rescue:** Scout drones can cover hazardous or hard-to-reach terrain while parent drones maintain relay coverage and local compute for detection and mapping.
- **Flood and earthquake mapping:** HADES can simulate blocked roads, damaged bridges, chokepoints, and safe corridors, then reward policies that find usable routes quickly.
- **Aid convoy safety:** Medical supplies, water, food, shelter materials, and rescue equipment can be routed through uncertain areas with aerial overwatch and local decision support.
- **Communications restoration:** Drones can act as mobile relays, keeping sensors, responders, edge compute, and ground vehicles connected when towers or backhaul are down.
- **Damage assessment:** Aerial perception can be tied directly to operational decisions, such as which road to use, where to send responders, and when a route is no longer safe.
- **Wildfire reconnaissance:** Drones can probe smoke-adjacent or heat-adjacent areas while parent drones preserve standoff relay positions and battery-aware coverage.
- **Industrial hazard response:** Chemical spills, explosions, power failures, and damaged facilities can be inspected from safer distances before responders enter.
- **Public-safety exercises:** Agencies can rehearse drone deployment, communications limits, privacy-aware data flow, and command decisions before an actual emergency.

## System Architecture

HADES is organized around four actor groups.

| Actor | Role | Key constraint |
|---|---|---|
| Small drones | Scouts, local observers, relay triggers | Very limited compute and battery |
| Parent drones | Coordinators, relays, heavier perception nodes | More compute, but still range and load constrained |
| Static edge nodes | Passive local compute targets | No sensors; only process received jobs |
| Convoy vehicles | Protected ground assets | Receive-only awareness and route commands |

The plan in `C:\Users\agni_\Documents\HADES-main\plan.md` defines the Track 2-4 target:

- 2 parent drones at the 100 TOPS tier.
- 6 small drones at the 0.5 TOPS tier.
- 18 static edge nodes at the 50 TOPS tier.
- 2 convoy vehicles with embedded receive-only edge capability.
- A 10 Hz bridge publishing state frames.
- Explicit compute, communications, threat, navigation, RL, and scoring modules.

The RL implementation source in `C:\Users\agni_\Documents\HADES-rl-training` provides the training-oriented branch:

- `hades/comms.py` models range-gated links and relay constraints.
- `hades/compute.py` models local/offload/drop scheduling.
- `hades/threats.py` creates deterministic or randomized threats.
- `hades/navigation.py` contains drone and convoy route logic.
- `hades/env/` defines the Isaac Lab style multi-agent environment.
- `scripts/train_headless.py` supports training without Isaac Sim installed.
- `scripts/train_rl.py` supports Isaac-backed training with `SimulationApp`.
- `scripts/eval_policy.py` evaluates checkpoints.
- `scripts/run_demo.py` runs the scored demo or stub fallback.

The most important invariant is that only drones sense. Edge nodes and convoy vehicles are receive-only. This prevents the simulation from cheating by letting static infrastructure know things it could not know without the drone network.

## Simulation Environment

The target visual simulation is Isaac Sim 6.0. NVIDIA describes Isaac Sim as an open-source reference framework built on Omniverse for robotics simulation, testing, and synthetic data generation in physically based virtual environments ([NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim)). HADES uses that direction because the environment must look, move, and fail like a real mission instead of a clean classroom grid.

The environment is designed as a real-world planning and training loop:

- **Real geography:** The main scenario uses the Laughlin/Bullhead City corridor around the Arizona/Nevada border, not an abstract test map.
- **Real terrain and imagery:** The visual branch targets Cesium for Omniverse with Cesium World Terrain and aerial imagery so the stage can represent real roads, water, open terrain, industrial edges, and route chokepoints.
- **Live or current public context:** The current HADES branch can enrich real-world route/elevation data with public context such as weather and OpenStreetMap/Overpass-style map features when enabled.
- **Real route planning:** The convoy route is not just a line on a board; it is a route choice problem with a direct route, bypasses, chokepoints, and threat penalties.
- **Realistic asset scale:** Parent drones, small drones, convoy vehicles, and 1U-style edge nodes are represented as separate actors with different roles and constraints.
- **Repeatable experiments:** The same route can be replayed with different policies, threat timing, battery budgets, edge placement, comms quality, or compute capacity.

The worktrees are split by purpose:

The main visual/Cesium plan lives in:

```text
C:\Users\agni_\Documents\HADES-main
```

The active docs file is being created in:

```text
C:\Users\agni_\Documents\HADES
```

The RL training implementation lives in:

```text
C:\Users\agni_\Documents\HADES-rl-training
```

The planned operational scene uses a 1500 m x 1500 m area of interest and a 1200 m route problem with three route choices:

- `main`: direct, exposed, crosses the central choke.
- `north_bypass`: longer, partial cover.
- `south_bypass`: alternate industrial approach.

Threat zones are defined around route choke points:

- `choke_a`: bridge-center threat zone.
- `flank_b`: bypass-entry threat zone.

The simulation does not just render a convoy. It simulates the operational forces that decide whether the concept works:

- **Latency:** Link delay increases with congestion and distance, so a policy must learn that late data can be less valuable than local action.
- **Compute pressure:** Small drones, parent drones, static edge nodes, and convoy edge compute have different TOPS budgets. Heavy jobs must be scheduled, offloaded, or dropped.
- **Attack and failure vectors:** The scenario can represent route denial, threat zones, degraded comms, congested links, drone loss, edge-node unavailability, and noisy or delayed detections.
- **Battery limits:** Drones are penalized for wasteful movement and can become mission liabilities if they burn energy without improving coverage or relay quality.
- **Partial observability:** The convoy and edge nodes do not perceive independently. They only know what the drone network sends them.
- **Sensor realism:** Drones provide the perception layer, while richer Isaac plans include RGB/depth, thermal, LiDAR, and IMU-style state.
- **Communications realism:** WiFi/mesh and long-range relay behavior are not treated as perfect. Links have range, quality, severance thresholds, and relay rules.
- **Route realism:** The convoy must choose between exposed direct movement and longer bypass routes based on received threat intelligence.
- **Scoring realism:** Success is not visual polish. Success means endpoint arrival, convoy survival, detected threats, successful reroutes, low latency, useful relays, and acceptable compute utilization.

This makes HADES a lifelike efficacy test for the architecture. It can answer questions that a normal video demo cannot:

- **Can the swarm keep useful awareness when the network is weak?**
- **Can edge compute reduce latency without overloading parent drones?**
- **Where should static edge nodes be placed before a mission?**
- **How many small drones are needed before coverage improves meaningfully?**
- **When does a bypass become safer than the direct route?**
- **Which policies waste battery, break relay chains, or overuse compute?**
- **How does the solution behave when one drone, edge node, or route segment fails?**

In the current training branch, sensor implementation is still evolving. The target plan describes richer parent drone sensing, including RGB/depth, thermal, LiDAR, and IMU. The current `HADES-rl-training` implementation uses procedural camera attachment through the drone stack and reads physics state for IMU-like motion information in headless/test-compatible ways. The architectural invariant remains the same: drones perceive, edge nodes compute, convoy receives.

## RL Training

The RL task is a cooperative multi-agent convoy-escort problem. The policy is trained to protect the convoy under the same limits that would matter in a fielded system: partial observability, unreliable links, compute pressure, battery drain, and time-critical rerouting.

HADES uses MAPPO-style training through SKRL. SKRL describes MAPPO as a multi-agent algorithm using centralized training and decentralized execution, where a centralized value function guides coordinated policy updates while agents still act through their own policies ([SKRL MAPPO](https://skrl.readthedocs.io/en/latest/api/multi_agents/mappo.html)).

The policy structure:

- **Centralized training:** During training, the critic can learn from the broader mission state so it understands cooperation, coverage, and convoy-level outcomes.
- **Decentralized execution:** At runtime, each drone acts from its own observation and role. This is closer to a real deployment where every drone cannot assume perfect global knowledge.
- **Tiered agents:** Parent drones and small drones learn different behaviors because they have different compute, mobility, sensing, and relay roles.
- **Rule-based convoy:** The convoy is currently controlled by route logic, so the RL problem focuses on the aerial swarm creating useful, timely intelligence.
- **Policy comparison:** Multiple policies can be trained against the same scenario and compared by score, not vibes.

The current agent set:

- **Parent agents:** `parent_0`, `parent_1`
- **Small agents:** `small_0`, `small_1`, `small_2`, `small_3`, `small_4`, `small_5`

Parent drone actions are continuous:

```text
[vx, vy, vz, yaw_rate]
```

Small drone actions are discrete:

```text
HOLD, MOVE_N, MOVE_S, MOVE_E, MOVE_W, MOVE_UP, RELAY_NOW
```

The observation and learning problem includes:

- **Own state:** pose, movement, battery, and compute load.
- **Relative mission geometry:** convoy-relative position, route progress, parent-relative position, and nearby threat-relative position.
- **Comms state:** link quality, relay usefulness, nearby parent availability, and offload queue pressure.
- **Threat picture:** nearest threat, confidence, threat histogram/grid, and new detections.
- **Edge compute context:** available edge capacity, expected latency, and dropped or completed jobs.
- **Time pressure:** the convoy keeps moving, so late detection can become equivalent to failed detection.

The reward design teaches the behavior HADES actually wants:

- **Protect the convoy:** reward route progress and endpoint arrival; heavily penalize convoy hits.
- **Find threats early:** reward new unique detections and confidence improvements.
- **Maintain coverage:** reward observation of the corridor ahead of the convoy.
- **Keep the network alive:** reward useful relay links and penalize broken or wasteful relay behavior indirectly through mission failure.
- **Use compute intelligently:** penalize dropped offload jobs and overloaded scheduling.
- **Respect energy limits:** penalize battery waste and drone loss.
- **Avoid fake success:** a policy does not win by hovering safely, chasing every detection, or exhausting the swarm. It wins by getting the convoy through the route alive and informed.

This RL setup is important because hand-coded rules can look good in one scripted run and fail when timing, route, threat, battery, or link conditions change. Training across repeated randomized episodes lets HADES search for robust behaviors:

- **Scouts learn when to spread out and when to relay.**
- **Parents learn where to position for both perception and offload.**
- **The swarm learns that compute is a scarce mission resource.**
- **The policy learns that a longer route can be better if it preserves convoy safety.**
- **The evaluator can measure whether improvements are real across many runs.**

## Demo And Scoring

The final Track 4 demonstration is a 60-second scored episode:

| Act | Time | Scenario |
|---|---:|---|
| Departure | 0-15 s | Convoy departs and the swarm forms an escort pattern. |
| Threat contact | 15-40 s | Threats appear near the choke; drones detect and relay; convoy reroutes. |
| Bypass and arrival | 40-60 s | Convoy follows the safer route while the swarm preserves coverage. |

The planned `EpisodeScore` measures:

- Convoy reached endpoint.
- Time to complete.
- Threats detected.
- Successful reroutes.
- Drone losses.
- Mean compute utilisation.
- Relay events.
- Mean detection latency.
- Drop rate, link quality, return, and route completion as supporting metrics.

This matters because a demo should not only look correct. It should produce a measurable answer to the question: did the swarm protect the convoy under constraints?

## Setup

### Current bridge and temporary visualizer

Run these from:

```text
C:\Users\agni_\Documents\HADES
```

Install the current project in editable mode:

```powershell
python -m pip install -e ".[dev]"
```

Start the bridge:

```powershell
python -m bridge.server
```

Open the temporary tactical visualizer:

```text
http://127.0.0.1:8000/viz
```

Smoke-check the 10 Hz frame stream:

```powershell
python .\scripts\check_bridge.py
```

Useful bridge endpoints:

```text
GET /healthz
GET /frame
WS  /stream
```

### Isaac Sim 6.0 and Cesium visual workflow

Run the visual/Cesium workflow from:

```text
C:\Users\agni_\Documents\HADES-main
```

Install project dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Install or configure Cesium for Omniverse support as provided by the main-branch scripts:

```powershell
python .\scripts\install_cesium_omniverse.py
```

Set a Cesium ion token:

```powershell
$env:CESIUM_ION_TOKEN="YOUR_TOKEN_HERE"
```

Record the Cesium/Isaac visual demo:

```powershell
python .\scripts\record_cesium_demo.py --duration-s 30 --fps 10
```

The main README currently treats Isaac Sim 6.0 and Cesium as the active visual target. The older generated terrain workflow remains useful as a fallback:

```powershell
python .\scripts\fetch_terrain.py
python .\scripts\build_terrain_usd.py
```

Only use terrain patching intentionally when switching away from the Cesium/OpenUSD scene.

### RL training branch

Run RL commands from:

```text
C:\Users\agni_\Documents\HADES-rl-training
```

Install the training branch with dev and demo extras:

```powershell
python -m pip install -e ".[dev,demo]"
```

Depending on the machine image, ensure PyTorch, Gymnasium, SKRL, Isaac Sim, Isaac Lab, and GPU drivers are installed through the appropriate CUDA/Isaac environment. The training scripts assume those runtime pieces are available when using full Isaac-backed training.

Headless training without Isaac Sim:

```powershell
$env:HADES_STUB="0"
python .\scripts\train_headless.py --num-envs 64 --timesteps 500000 --wandb --wandb-project hades-rl
```

Isaac-backed training:

```powershell
python .\scripts\train_rl.py --num-envs 64 --timesteps 500000 --checkpoint-dir checkpoints/hades_mappo
```

Evaluate a trained policy:

```powershell
python .\scripts\eval_policy.py --checkpoint-dir checkpoints/hades_mappo --episodes 10
```

Run the demo in stub/headless mode:

```powershell
python .\scripts\run_demo.py --stub --checkpoint-dir checkpoints/hades_mappo
```

Run the full visual demo with Isaac available:

```powershell
python .\scripts\run_demo.py --checkpoint-dir checkpoints/hades_mappo
```

## What Good Looks Like

For the current docs and bridge work:

- `HADES_README.md` exists in `C:\Users\agni_\Documents\HADES`.
- The existing `README.md` is unchanged.
- The bridge runs and publishes frames at 10 Hz.
- Temporary media links are clearly marked as temporary.

For Track 2:

- Communications links obey range, relay, and forbidden-path rules.
- Compute jobs follow the local-to-parent-to-edge-to-convoy-to-drop waterfall.
- Threats appear in the frame stream.
- Convoy route state changes when threat intelligence makes a bypass safer.
- Unit tests cover comms, compute, publisher behavior, and scoring.

For Track 3:

- The multi-agent environment resets and steps without crashing.
- Observation dimensions match parent and small drone policies.
- Random actions produce valid rewards and done flags.
- Headless training can run without Isaac Sim.
- Isaac-backed training can run when Isaac Sim 6.0 and Isaac Lab are installed.

For Track 4:

- The demo prints an `EpisodeScore`.
- The convoy reaches the endpoint or reports why it failed.
- Threat detections, reroutes, relay events, compute drops, and detection latency are visible in metrics.
- The final video is captured from the real Isaac/Cesium simulation, not from the temporary YouTube references.

## Research Sources

- [DIU Replicator](https://www.diu.mil/replicator)
- [DoD C-sUAS task force](https://www.defense.gov/News/Releases/Release/Article/4289621/dod-establishes-joint-interagency-task-force-to-deliver-affordable-c-suas-capab/)
- [UN Geneva Global Humanitarian Overview 2026](https://www.ungeneva.org/en/news-media/news/2025/12/113710/humanitarians-launch-33-billion-appeal-2026)
- [WMO Atlas of Mortality and Economic Losses from Weather, Climate and Water-related Hazards](https://wmo.int/publication-series/atlas-of-mortality-and-economic-losses-from-weather-climate-and-water-related-hazards-1970-2021)
- [UNDRR Global Assessment Report 2025](https://www.undrr.org/gar2025)
- [WFP drones](https://www.wfp.org/wfp-drones)
- [WFP AI and drones in emergencies](https://www.wfp.org/stories/joining-dots-how-ai-and-drones-are-transforming-emergencies)
- [WFP Rapid Response Connectivity Carrier](https://innovation.wfp.org/project/r2c2)
- [NIST resilient systems](https://www.nist.gov/ctl/pscr/resilient-systems)
- [NIST connected drones report](https://www.nist.gov/system/files/documents/2024/05/13/AUTONOMOUSAERIALDRONESCONNECTINGPUBLICSAFETYOPPORTUNITIESANDCHALLENGESFORTHEFUTURE.pdf)
- [FAA public-safety drone operations](https://www.faa.gov/uas/public_safety_gov/drone_program)
- [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim)
- [SKRL MAPPO](https://skrl.readthedocs.io/en/latest/api/multi_agents/mappo.html)
