"""Install Cesium for Omniverse v0.28.0 into the Kit shared extension folder."""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hades.cesium import DEFAULT_CESIUM_EXTENSION_ZIP_URL, extension_zip_url  # noqa: E402


def _default_install_dir() -> Path:
    return Path.home() / "Documents" / "Kit" / "Shared" / "exts"


def _download(url: str, dest: Path) -> None:
    print(f"[HADES] downloading Cesium extension: {url}", flush=True)
    with urllib.request.urlopen(url) as response:
        with dest.open("wb") as out:
            shutil.copyfileobj(response, out)


def _find_extension_dirs(root: Path) -> list[Path]:
    names = {"cesium.omniverse", "cesium.usd.plugins"}
    found: list[Path] = []
    for child in root.rglob("*"):
        if child.is_dir() and child.name.split("-")[0] in names:
            found.append(child)
    return found


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=extension_zip_url())
    parser.add_argument("--install-dir", type=Path, default=_default_install_dir())
    parser.add_argument("--force", action="store_true", help="Remove existing Cesium extension folders first.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    install_dir: Path = args.install_dir.expanduser().resolve()
    install_dir.mkdir(parents=True, exist_ok=True)

    if args.force:
        for child in install_dir.glob("cesium.*"):
            if child.is_dir():
                print(f"[HADES] removing old extension: {child}", flush=True)
                shutil.rmtree(child)

    with tempfile.TemporaryDirectory(prefix="hades_cesium_") as tmp:
        tmp_dir = Path(tmp)
        zip_path = tmp_dir / "cesium-omniverse.zip"
        _download(args.url, zip_path)
        print(f"[HADES] extracting to {install_dir}", flush=True)
        with zipfile.ZipFile(zip_path) as archive:
            archive.extractall(install_dir)

    found = _find_extension_dirs(install_dir)
    if not found:
        raise SystemExit(
            "Cesium zip extracted, but no cesium.omniverse or cesium.usd.plugins "
            f"extension folders were found under {install_dir}."
        )

    rel_found = ", ".join(str(path.relative_to(install_dir)) for path in found)
    print(f"[HADES] installed Cesium extension folders: {rel_found}", flush=True)
    if args.url == DEFAULT_CESIUM_EXTENSION_ZIP_URL:
        print("[HADES] installed requested Cesium for Omniverse v0.28.0 build.", flush=True)


if __name__ == "__main__":
    main()
