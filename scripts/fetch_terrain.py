"""Fetch satellite imagery for the HADES scene location and write terrain assets.

Location: Nevada Route 375, Sand Spring Valley (37.6530°N, 115.7440°W)
  - Dead-straight desert highway, flat valley floor, ~420m AOI

Outputs (written to assets/terrain/):
  satellite.png   — stitched satellite image covering the 420m AOI
  satellite.json  — metadata: center, bbox, pixels-per-meter, heading
  road_mask.png   — greyscale mask isolating the road stripe (for USD material)

Usage:
    python scripts/fetch_terrain.py

Requires GOOGLE_MAPS_API_KEY in .env or environment.
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# Load .env if present
_env = Path(__file__).parents[1] / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

try:
    import requests
    from PIL import Image, ImageFilter
except ImportError:
    print("Missing deps. Run: pip install requests pillow")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

API_KEY = os.environ["GOOGLE_MAPS_API_KEY"]
CENTER_LAT = float(os.getenv("HADES_SCENE_LAT", "37.6530"))
CENTER_LON = float(os.getenv("HADES_SCENE_LON", "-115.7440"))
HEADING_DEG = float(os.getenv("HADES_SCENE_HEADING_DEG", "315"))

# 420m AOI — fetch slightly larger for margin
AOI_M = 520
ZOOM = 18          # ~0.6 m/px at this latitude
TILE_SIZE = 640    # Google Static Maps max (with high-dpi would be 1280)
SCALE = 2          # retina, doubles effective resolution to 1280×1280 per tile

OUT_DIR = Path(__file__).parents[1] / "assets" / "terrain"


# ---------------------------------------------------------------------------
# Geo helpers
# ---------------------------------------------------------------------------

def meters_to_deg_lat(m: float) -> float:
    return m / 111_000.0


def meters_to_deg_lon(m: float, lat: float) -> float:
    return m / (111_000.0 * math.cos(math.radians(lat)))


def latlon_to_tile(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n
    return x, y


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_static_map(lat: float, lon: float, zoom: int, size: int, scale: int, maptype: str = "satellite") -> Image.Image:
    url = "https://maps.googleapis.com/maps/api/staticmap"
    params = {
        "center": f"{lat},{lon}",
        "zoom": zoom,
        "size": f"{size}x{size}",
        "scale": scale,
        "maptype": maptype,
        "key": API_KEY,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    from io import BytesIO
    return Image.open(BytesIO(r.content)).convert("RGB")


def fetch_tiled_mosaic(lat: float, lon: float, aoi_m: float, zoom: int) -> tuple[Image.Image, dict]:
    """Fetch a 3×3 grid of tiles centred on lat/lon and crop to aoi_m × aoi_m."""
    # Pixels per meter at this zoom/lat
    earth_circ = 40_075_016.686
    ppm = (earth_circ * math.cos(math.radians(lat))) / (256 * 2 ** zoom)
    tile_m = TILE_SIZE * ppm  # metres covered by one 640px tile

    # Number of tiles needed each side
    tiles_needed = math.ceil(aoi_m / tile_m) + 1
    half = tiles_needed // 2

    # Build mosaic
    eff_size = TILE_SIZE * SCALE
    mosaic_tiles = tiles_needed * 2 + 1
    mosaic = Image.new("RGB", (mosaic_tiles * eff_size, mosaic_tiles * eff_size))

    deg_lat_per_tile = meters_to_deg_lat(tile_m)
    deg_lon_per_tile = meters_to_deg_lon(tile_m, lat)

    print(f"Fetching {mosaic_tiles}×{mosaic_tiles} tile grid ({ppm:.3f} m/px, tile={tile_m:.0f}m)…")

    for row in range(-half, half + 1):
        for col in range(-half, half + 1):
            tlat = lat + row * deg_lat_per_tile
            tlon = lon + col * deg_lon_per_tile
            img = fetch_static_map(tlat, tlon, zoom, TILE_SIZE, SCALE)
            px = (col + half) * eff_size
            py = (-row + half) * eff_size  # row increases south, y increases down
            mosaic.paste(img, (px, py))
            print(f"  tile ({row:+d},{col:+d}) at ({tlat:.5f},{tlon:.5f})")

    # Crop to AOI
    aoi_px = int(aoi_m / ppm * SCALE)
    cx = mosaic.width // 2
    cy = mosaic.height // 2
    half_px = aoi_px // 2
    cropped = mosaic.crop((cx - half_px, cy - half_px, cx + half_px, cy + half_px))

    meta = {
        "center_lat": lat,
        "center_lon": lon,
        "heading_deg": HEADING_DEG,
        "aoi_m": aoi_m,
        "zoom": zoom,
        "pixels_per_meter": round(ppm * SCALE, 4),
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
    """Simple luminance + edge mask to isolate the dark road stripe."""
    import numpy as np
    arr = np.array(satellite).astype(float)
    # Road is dark grey — low luminance, low saturation
    lum = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    sat = arr.max(axis=2) - arr.min(axis=2)
    road = ((lum < 90) & (sat < 30)).astype("uint8") * 255
    mask = Image.fromarray(road, mode="L").filter(ImageFilter.MedianFilter(5))
    return mask


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Center: {CENTER_LAT}°N, {CENTER_LON}°W  (Nevada Route 375)")
    satellite, meta = fetch_tiled_mosaic(CENTER_LAT, CENTER_LON, AOI_M, ZOOM)

    sat_path = OUT_DIR / "satellite.png"
    satellite.save(sat_path, "PNG")
    print(f"Saved satellite image → {sat_path} ({satellite.width}×{satellite.height}px)")

    meta_path = OUT_DIR / "satellite.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    print(f"Saved metadata → {meta_path}")

    try:
        import numpy  # noqa: F401
        mask = make_road_mask(satellite)
        mask_path = OUT_DIR / "road_mask.png"
        mask.save(mask_path, "PNG")
        print(f"Saved road mask → {mask_path}")
    except ImportError:
        print("numpy not available — skipping road mask (pip install numpy)")

    print("\nDone. Next: run scripts/build_terrain_usd.py to generate the USD ground plane.")


if __name__ == "__main__":
    main()
