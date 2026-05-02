# HADES AWS Isaac Sim Notes

This directory contains optional AWS scaffolding for running Isaac Sim on a GPU
EC2 instance. Phase 1 can run locally without AWS; the cloud path is for cases
where the local workstation cannot run Isaac/Cesium comfortably.

## Recommended Defaults

- Instance type: `g5.2xlarge` if quota allows.
- AMI: NVIDIA GPU-optimized Ubuntu/Omniverse-compatible AMI.
- Disk: at least 250 GB gp3 for Isaac, containers, Cesium cache, and USD assets.
- Security group: restrict SSH and streaming ports to your IP.
- Never expose Isaac WebRTC/VNC directly to the public internet without TLS and auth.

## Flow

1. Confirm AWS GPU quota for G5 or G4dn.
2. Launch the instance with `launch-isaac-sim.ps1`.
3. SSH into the instance and verify `nvidia-smi`.
4. Run the Isaac Sim container or Docker Compose WebRTC stack.
5. Run `python -m bridge.server` either on the instance or locally.

The launch script is intentionally conservative: it creates the EC2 instance and
passes bootstrap user data, but it does not open broad public access.

After SSH, `start-isaac-sim-container.sh` can be copied to the instance and run
to pull/start the Isaac Sim container. Override `ISAAC_IMAGE` if the project
standardizes on a different Isaac Sim version.
