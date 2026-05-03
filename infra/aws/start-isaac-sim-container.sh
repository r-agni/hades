#!/usr/bin/env bash
set -euo pipefail

ISAAC_IMAGE="${ISAAC_IMAGE:-nvcr.io/nvidia/isaac-sim:6.0.0-dev2}"
ISAAC_ENTRYPOINT="${ISAAC_ENTRYPOINT:-./runheadless.sh}"
WORKDIR="${HADES_REMOTE_WORKDIR:-/opt/hades}"

mkdir -p "${WORKDIR}/cache/kit" \
  "${WORKDIR}/cache/ov" \
  "${WORKDIR}/cache/pip" \
  "${WORKDIR}/cache/glcache" \
  "${WORKDIR}/logs" \
  "${WORKDIR}/data" \
  "${WORKDIR}/documents" \
  "${WORKDIR}/documents/Kit/Shared/exts"

docker pull "${ISAAC_IMAGE}"

docker run --rm --gpus all --network host \
  -e ACCEPT_EULA=Y \
  -e PRIVACY_CONSENT=Y \
  -e CESIUM_ION_TOKEN="${CESIUM_ION_TOKEN:-}" \
  -e CESIUM_EXTENSION_ZIP_URL="${CESIUM_EXTENSION_ZIP_URL:-}" \
  -v "${WORKDIR}/cache/kit:/isaac-sim/kit/cache:rw" \
  -v "${WORKDIR}/cache/ov:/root/.cache/ov:rw" \
  -v "${WORKDIR}/cache/pip:/root/.cache/pip:rw" \
  -v "${WORKDIR}/cache/glcache:/root/.cache/nvidia/GLCache:rw" \
  -v "${WORKDIR}/logs:/root/.nvidia-omniverse/logs:rw" \
  -v "${WORKDIR}/data:/root/.local/share/ov/data:rw" \
  -v "${WORKDIR}/documents:/root/Documents:rw" \
  "${ISAAC_IMAGE}" \
  "${ISAAC_ENTRYPOINT}"
