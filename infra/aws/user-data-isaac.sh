#!/usr/bin/env bash
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive

apt-get update
apt-get install -y docker.io awscli git
systemctl enable --now docker

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi || true
fi

mkdir -p /opt/hades
cat >/opt/hades/README.txt <<'EOF'
HADES Isaac Sim host bootstrap complete.

Next manual steps:
1. Confirm NVIDIA drivers with: nvidia-smi
2. Authenticate to NGC if required.
3. Pull the Isaac Sim container version approved for this project.
4. Start Isaac Sim headless/WebRTC on a private security group.
EOF
