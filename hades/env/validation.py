"""Runtime validation for real HADES Isaac assets and sensors."""

from __future__ import annotations

from typing import Any


REQUIRED_ASSET_SUFFIXES: tuple[str, ...] = (
    "environment",
    "convoy_0",
    "convoy_1",
    "parent_0",
    "parent_1",
    "small_0",
    "small_1",
    "small_2",
    "small_3",
    "small_4",
    "small_5",
    "edge_0",
    "edge_1",
    "edge_2",
    "edge_3",
    "edge_4",
    "edge_5",
    "edge_6",
    "edge_7",
    "edge_8",
    "edge_9",
    "edge_10",
    "edge_11",
    "edge_12",
    "edge_13",
    "edge_14",
    "edge_15",
    "edge_16",
    "edge_17",
)

REQUIRED_SENSOR_KEYS: tuple[str, ...] = (
    "parent_nav_rgb",
    "parent_nav_depth",
    "parent_thermal",
    "parent_lidar",
    "parent_imu_acc",
    "parent_imu_gyr",
    "small_rgb",
    "small_imu_acc",
    "small_imu_gyr",
)


def validate_stage_assets(
    stage: Any,
    *,
    candidate_roots: tuple[str, ...] = (
        "/World/envs/env_0/hades_phase_1",
        "/hades_phase_1",
    ),
) -> str:
    """Validate that the real HADES actor hierarchy is present on the stage."""
    if stage is None:
        raise RuntimeError("Isaac stage is not available")

    best_root = candidate_roots[0]
    best_missing: list[str] = list(REQUIRED_ASSET_SUFFIXES)
    for root in candidate_roots:
        missing = [
            suffix
            for suffix in REQUIRED_ASSET_SUFFIXES
            if not stage.GetPrimAtPath(f"{root}/{suffix}").IsValid()
        ]
        if not missing:
            return root
        if len(missing) < len(best_missing):
            best_root = root
            best_missing = missing

    missing_preview = ", ".join(best_missing[:8])
    if len(best_missing) > 8:
        missing_preview += f", ... (+{len(best_missing) - 8} more)"
    raise RuntimeError(
        f"HADES real asset validation failed at {best_root}: missing {missing_preview}"
    )


def validate_sensor_payload(sensor_data: dict[str, Any]) -> None:
    """Validate that every required real sensor produced a non-empty tensor."""
    missing = [key for key in REQUIRED_SENSOR_KEYS if key not in sensor_data]
    empty = [
        key
        for key in REQUIRED_SENSOR_KEYS
        if key in sensor_data and not _has_values(sensor_data[key])
    ]
    if missing or empty:
        details = []
        if missing:
            details.append("missing=" + ",".join(missing))
        if empty:
            details.append("empty=" + ",".join(empty))
        raise RuntimeError("HADES real sensor validation failed: " + "; ".join(details))


def _has_values(value: Any) -> bool:
    if value is None:
        return False
    numel = getattr(value, "numel", None)
    if callable(numel):
        return int(numel()) > 0
    shape = getattr(value, "shape", None)
    if shape is not None:
        total = 1
        for dim in shape:
            total *= int(dim)
        return total > 0
    return True
