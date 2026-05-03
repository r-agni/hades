"""Cesium for Omniverse runtime helpers."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from hades import config


LINUX_CESIUM_EXTENSION_ZIP_URL = (
    "https://github.com/CesiumGS/cesium-omniverse/releases/download/v0.28.0/"
    "CesiumGS-cesium-omniverse-linux-x86_64-v0.28.0.zip"
)
WINDOWS_CESIUM_EXTENSION_ZIP_URL = (
    "https://github.com/CesiumGS/cesium-omniverse/releases/download/v0.28.0/"
    "CesiumGS-cesium-omniverse-windows-x86_64-v0.28.0.zip"
)
DEFAULT_CESIUM_EXTENSION_ZIP_URL = (
    WINDOWS_CESIUM_EXTENSION_ZIP_URL if sys.platform.startswith("win") else LINUX_CESIUM_EXTENSION_ZIP_URL
)
REQUIRED_ISAAC_SIM_VERSION = (6, 0, 0)
REQUIRED_KIT_MAJOR = 109


@dataclass(frozen=True)
class CesiumRuntimeConfig:
    extension_zip_url: str
    ion_token: str
    latitude_deg: float
    longitude_deg: float
    height_m: float


def scene_latitude() -> float:
    return float(os.environ.get("HADES_SCENE_LAT", config.SCENE.latitude_deg))


def scene_longitude() -> float:
    return float(os.environ.get("HADES_SCENE_LON", config.SCENE.longitude_deg))


def scene_height() -> float:
    return float(os.environ.get("HADES_SCENE_HEIGHT", config.SCENE.height_m))


def extension_zip_url() -> str:
    return os.environ.get("CESIUM_EXTENSION_ZIP_URL", "").strip() or DEFAULT_CESIUM_EXTENSION_ZIP_URL


def _dotenv_value(name: str) -> str:
    if os.environ.get("CESIUM_DISABLE_DOTENV", "").strip() == "1":
        return ""
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env",
        Path("/opt/hades/.env"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                if key.strip() == name:
                    return value.strip().strip('"').strip("'")
        except OSError:
            continue
    return ""


def require_ion_token() -> str:
    token = os.environ.get("CESIUM_ION_TOKEN", "").strip() or _dotenv_value("CESIUM_ION_TOKEN")
    if not token:
        raise RuntimeError(
            "CESIUM_ION_TOKEN is required for the Cesium outdoor scene. "
            "Create a Cesium ion token with read access to World Terrain and Bing imagery, "
            "then export CESIUM_ION_TOKEN before running the Cesium capture."
        )
    return token


def runtime_config(*, require_token: bool = True) -> CesiumRuntimeConfig:
    token = require_ion_token() if require_token else os.environ.get("CESIUM_ION_TOKEN", "").strip()
    return CesiumRuntimeConfig(
        extension_zip_url=extension_zip_url(),
        ion_token=token,
        latitude_deg=scene_latitude(),
        longitude_deg=scene_longitude(),
        height_m=scene_height(),
    )


def parse_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    match = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3) or 0)
    return major, minor, patch


def assert_isaac_runtime_compatible(
    *,
    app_version: str | None,
    build_version: str | None,
) -> None:
    """Validate the requested Cesium v0.28 runtime floor."""
    parsed_app = parse_version(app_version)
    if parsed_app is not None and parsed_app < REQUIRED_ISAAC_SIM_VERSION:
        raise RuntimeError(
            "Cesium for Omniverse v0.28.0 requires Isaac Sim 6.0.0 / Kit 109. "
            f"Detected Isaac Sim {app_version!r}."
        )

    parsed_kit = parse_version(build_version)
    if parsed_kit is not None and parsed_kit[0] != REQUIRED_KIT_MAJOR:
        raise RuntimeError(
            "Cesium for Omniverse v0.28.0 is targeted at Kit 109. "
            f"Detected Kit build {build_version!r}."
        )

    if parsed_app is None and parsed_kit is None:
        raise RuntimeError(
            "Unable to determine Isaac Sim / Kit version; refusing to run Cesium v0.28.0 "
            "without confirming Isaac Sim 6.0.0 / Kit 109 compatibility."
        )
