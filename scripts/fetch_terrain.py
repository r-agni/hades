"""Fetch satellite imagery for the HADES map-derived Isaac terrain.

Default location: Laughlin/Bullhead City corridor, AZ/NV
  - Center: 35.1700, -114.5700
  - AOI: 1500 m x 1500 m
  - Zoom: 17

Outputs in assets/terrain/:
  satellite.png   - stitched satellite image covering the AOI
  satellite.json  - metadata used by build_terrain_usd.py
  road_mask.png   - simple road-like pixel mask for diagnostics

Requires GOOGLE_MAPS_API_KEY in .env or the environment.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
OUT_DIR = ROOT / "assets" / "terrain"


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()

try:
    import requests
    from PIL import Image, ImageFilter
except ImportError:
    print("Missing deps. Run: pip install requests pillow")
    sys.exit(1)


API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]
CENTER_LAT = float(os.getenv("HADES_SCENE_LAT", "35.1700"))
CENTER_LON = float(os.getenv("HADES_SCENE_LON", "-114.5700"))
HEADING_DEG = float(os.getenv("HADES_SCENE_HEADING_DEG", "90"))
AOI_M = int(os.getenv("HADES_SCENE_AOI_M", "1500"))
ZOOM = int(os.getenv("HADES_SCENE_ZOOM", "17"))
TILE_SIZE = 640
SCALE = 2


def meters_to_deg_lat(meters: float) -> float:
    return meters / 111_000.0


def meters_to_deg_lon(meters: float, lat: float) -> float:
    return meters / (111_000.0 * math.cos(math.radians(lat)))


def fetch_static_map(
    lat: float,
    lon: float,
    zoom: int,
    size: int,
    scale: int,
    maptype: str = "satellite",
) -> Image.Image:
    response = requests.get(
        "https://maps.googleapis.com/maps/api/staticmap",
        params={
            "center": f"{lat},{lon}",
            "zoom": zoom,
            "size": f"{size}x{size}",
            "scale": scale,
            "maptype": maptype,
            "key": API_KEY,
        },
        timeout=30,
    )
    response.raise_for_status()
    from io import BytesIO

    return Image.open(BytesIO(response.content)).convert("RGB")


def fetch_tiled_mosaic(lat: float, lon: float, aoi_m: float, zoom: int) -> tuple[Image.Image, dict]:
    """Fetch a tile grid centered on lat/lon and crop to the requested AOI."""
    earth_circ_m = 40_075_016.686
    meters_per_px = earth_circ_m * math.cos(math.radians(lat)) / (256 * 2**zoom)
    tile_m = TILE_SIZE * meters_per_px

    tiles_needed = math.ceil(aoi_m / tile_m) + 1
    half = tiles_needed // 2
    mosaic_tiles = tiles_needed * 2 + 1
    effective_tile_px = TILE_SIZE * SCALE
    mosaic = Image.new("RGB", (mosaic_tiles * effective_tile_px, mosaic_tiles * effective_tile_px))

    deg_lat_per_tile = meters_to_deg_lat(tile_m)
    deg_lon_per_tile = meters_to_deg_lon(tile_m, lat)

    print(
        f"Fetching {mosaic_tiles}x{mosaic_tiles} tile grid "
        f"({meters_per_px:.3f} m/px, tile={tile_m:.0f} m)..."
    )

    for row in range(-half, half + 1):
        for col in range(-half, half + 1):
            tile_lat = lat + row * deg_lat_per_tile
            tile_lon = lon + col * deg_lon_per_tile
            image = fetch_static_map(tile_lat, tile_lon, zoom, TILE_SIZE, SCALE)
            x_px = (col + half) * effective_tile_px
            y_px = (-row + half) * effective_tile_px
            mosaic.paste(image, (x_px, y_px))
            print(f"  tile ({row:+d},{col:+d}) at ({tile_lat:.5f},{tile_lon:.5f})")

    aoi_px = int(aoi_m / meters_per_px * SCALE)
    center_x = mosaic.width // 2
    center_y = mosaic.height // 2
    half_px = aoi_px // 2
    cropped = mosaic.crop((center_x - half_px, center_y - half_px, center_x + half_px, center_y + half_px))

    meta = {
        "center_lat": lat,
        "center_lon": lon,
        "heading_deg": HEADING_DEG,
        "aoi_m": aoi_m,
        "zoom": zoom,
        "meters_per_pixel": round(meters_per_px / SCALE, 4),
        "pixels_per_meter": round(SCALE / meters_per_px, 4),
        "image_px": aoi_px,
        "bbox": {
            "north": lat + meters_to_deg_lat(aoi_m / 2),
            "south": lat - meters_to_deg_lat(aoi_m / 2),
            "east": lon + meters_to_deg_lon(aoi_m / 2, lat),
            "west": lon - meters_to_deg_lon(aoi_m / 2, lat),
        },
    }
    return cropped, meta


def make_road_mask(satellite: Image.Image) -> Image.Image:
    import numpy as np

    arr = np.array(satellite).astype(float)
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    sat = arr.max(axis=2) - arr.min(axis=2)
    road = ((lum < 105) & (sat < 45)).astype("uint8") * 255
    return Image.fromarray(road).filter(ImageFilter.MedianFilter(5))


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Center: {CENTER_LAT}, {CENTER_LON} (Laughlin/Bullhead corridor)")
    satellite, meta = fetch_tiled_mosaic(CENTER_LAT, CENTER_LON, AOI_M, ZOOM)

    sat_path = OUT_DIR / "satellite.png"
    satellite.save(sat_path, "PNG")
    print(f"Saved satellite image -> {sat_path} ({satellite.width}x{satellite.height}px)")

    meta_path = OUT_DIR / "satellite.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"Saved metadata -> {meta_path}")

    try:
        mask = make_road_mask(satellite)
    except ImportError:
        print("numpy not available - skipping road mask")
    else:
        mask_path = OUT_DIR / "road_mask.png"
        mask.save(mask_path, "PNG")
        print(f"Saved road mask -> {mask_path}")

    print("\nDone. Next: run scripts/build_terrain_usd.py to generate the USD ground plane.")


if __name__ == "__main__":
    main()
