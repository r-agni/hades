"""Environment candidate resolution for Phase 1."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EnvironmentCandidate:
    name: str
    kind: str
    source_url: str
    path_env_var: str | None
    notes: str


CESIUM = EnvironmentCandidate(
    name="cesium_for_omniverse",
    kind="real_world_geospatial",
    source_url="https://cesium.com/learn/omniverse/",
    path_env_var="HADES_CESIUM_STAGE_USD",
    notes="Preferred free visual path when Cesium for Omniverse is installed and a local stage has been saved.",
)

CITY_DEMO = EnvironmentCandidate(
    name="nvidia_openusd_city_demo",
    kind="openusd_city",
    source_url="https://docs-prod.omniverse.nvidia.com/usd/latest/usd_content_samples/downloadable_packs.html",
    path_env_var="HADES_CITY_DEMO_STAGE_USD",
    notes="Fallback free native OpenUSD scene with buildings and streets.",
)

GENERATED_FLAT_ROAD = EnvironmentCandidate(
    name="generated_flat_road",
    kind="local_fallback",
    source_url="isaac/scene.usda",
    path_env_var=None,
    notes="Always available local fallback with road, convoy, drones, and edge nodes.",
)


ENVIRONMENT_PRIORITY = [CESIUM, CITY_DEMO, GENERATED_FLAT_ROAD]


def resolve_environment() -> tuple[EnvironmentCandidate, Path]:
    """Return the first configured environment with an existing local path."""

    for candidate in ENVIRONMENT_PRIORITY:
        if candidate.path_env_var is None:
            return candidate, Path(__file__).with_name("scene.usda")

        raw_path = os.getenv(candidate.path_env_var)
        if raw_path:
            path = Path(raw_path).expanduser()
            if path.exists():
                return candidate, path

    return GENERATED_FLAT_ROAD, Path(__file__).with_name("scene.usda")


def main() -> None:
    candidate, path = resolve_environment()
    print(f"{candidate.name}: {path}")


if __name__ == "__main__":
    main()
