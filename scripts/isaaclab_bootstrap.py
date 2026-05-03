"""Helpers for Isaac Lab installs that expose source packages via a shim."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


_ISAACLAB_PACKAGES = (
    "isaaclab",
    "isaaclab_assets",
    "isaaclab_contrib",
    "isaaclab_mimic",
    "isaaclab_rl",
    "isaaclab_tasks",
)


def add_isaaclab_source_paths() -> list[str]:
    """Add Isaac Lab source-layout packages to sys.path without importing env APIs."""
    shim = sys.modules.get("isaaclab")
    if shim is None:
        try:
            shim = importlib.import_module("isaaclab")
        except Exception:
            shim = None

    roots = []
    env_root = os.environ.get("ISAACLAB_SOURCE_ROOT")
    if env_root:
        roots.append(Path(env_root))
    if shim is not None and getattr(shim, "__file__", None):
        roots.append(Path(shim.__file__).resolve().parent / "source")
    roots.append(Path("/usr/local/lib/python3.11/dist-packages/isaaclab/source"))

    added: list[str] = []
    for root in roots:
        if not root.exists():
            continue
        for package_name in _ISAACLAB_PACKAGES:
            source = root / package_name
            package = source / package_name
            if not package.exists():
                continue
            if str(source) not in sys.path:
                sys.path.insert(0, str(source))
            if (
                package_name == "isaaclab"
                and shim is not None
                and hasattr(shim, "__path__")
                and str(package) not in shim.__path__
            ):
                shim.__path__.insert(0, str(package))
            added.append(str(source))
    return added


def ensure_isaaclab_api() -> None:
    """Make Isaac Lab's source-layout packages importable after SimulationApp."""
    try:
        importlib.import_module("isaaclab.envs")
        return
    except Exception:
        pass

    added = add_isaaclab_source_paths()

    try:
        importlib.import_module("isaaclab.envs")
        return
    except Exception:
        for name in list(sys.modules):
            if name == "isaaclab" or name.startswith("isaaclab."):
                del sys.modules[name]
        try:
            importlib.import_module("isaaclab.envs")
            return
        except Exception as retry_error:
            raise ModuleNotFoundError(
                "Unable to import isaaclab.envs after Isaac Lab source path bootstrap; "
                f"checked={added or [str(path) for path in roots]}"
            ) from retry_error
