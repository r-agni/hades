"""Build the fallback HADES map terrain USD from fetched satellite imagery.

Reads assets/terrain/satellite.png and satellite.json, writes
assets/terrain/terrain.usda. Cesium is the primary visual scene; pass
--patch-scene only when intentionally reverting to the local terrain fallback.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "assets" / "terrain"
SAT_PNG = ASSETS / "satellite.png"
SAT_JSON = ASSETS / "satellite.json"
TERRAIN_USDA = ASSETS / "terrain.usda"
SCENE_USDA = ROOT / "isaac" / "scene.usda"
TERRAIN_REL_FROM_SCENE = "../assets/terrain/terrain.usda"


def _require(path: Path, hint: str) -> None:
    if not path.exists():
        print(f"Missing: {path}\n{hint}")
        sys.exit(1)


def build_terrain_usd(meta: dict) -> str:
    aoi_m = float(meta["aoi_m"])
    half = aoi_m / 2.0
    heading = float(meta.get("heading_deg", 90.0))
    lat = meta.get("center_lat", 35.1700)
    lon = meta.get("center_lon", -114.5700)

    return f"""#usda 1.0
(
    defaultPrim = "terrain"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "terrain"
{{
    custom string hades:environment = "laughlin_bullhead_map_terrain"
    custom double hades:centerLat = {lat}
    custom double hades:centerLon = {lon}
    custom double hades:aoiMeters = {aoi_m}

    def Mesh "ground" (
        prepend apiSchemas = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI"]
    )
    {{
        int[] faceVertexCounts = [4]
        int[] faceVertexIndices = [0, 1, 2, 3]
        point3f[] points = [
            ({-half}, {-half}, 0),
            ( {half}, {-half}, 0),
            ( {half},  {half}, 0),
            ({-half},  {half}, 0)
        ]
        texCoord2f[] primvars:st = [(0,0),(1,0),(1,1),(0,1)] (
            interpolation = "faceVarying"
        )
        int[] primvars:st:indices = [0, 1, 2, 3]
        normal3f[] normals = [(0,0,1),(0,0,1),(0,0,1),(0,0,1)]
        uniform token physics:approximation = "meshSimplification"
        rel material:binding = </terrain/SatMaterial>
    }}

    def Material "SatMaterial"
    {{
        token outputs:mdl:surface.connect = </terrain/SatMaterial/Shader.outputs:out>

        def Shader "Shader"
        {{
            uniform token info:implementationSource = "sourceAsset"
            uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
            uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
            asset inputs:diffuse_texture = @satellite.png@ (
                colorSpace = "sRGB"
            )
            float inputs:reflection_roughness_constant = 0.9
            float inputs:metallic_constant = 0.0
            token outputs:out
        }}
    }}

    double3 xformOp:rotateXYZ = (0, 0, {heading - 90.0:.1f})
    uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
}}
"""


def _terrain_environment_block(terrain_rel_path: str) -> str:
    return f"""    def Xform "environment"
    {{
        def Xform "terrain_laughlin_bullhead" (
            prepend references = @{terrain_rel_path}@
        )
        {{
            double3 xformOp:translate = (0, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }}
    }}"""


def patch_scene_usda(terrain_rel_path: str = TERRAIN_REL_FROM_SCENE) -> None:
    scene = SCENE_USDA.read_text(encoding="utf-8")
    block = _terrain_environment_block(terrain_rel_path)

    env_pattern = re.compile(
        r'    def Xform "environment"\n'
        r"    \{\n"
        r".*?"
        r"\n    \}",
        re.DOTALL,
    )
    patched, count = env_pattern.subn(block, scene, count=1)
    if count == 0:
        raise RuntimeError(f"Could not find environment block in {SCENE_USDA}")

    if "Jetracer" in patched or "track_solid_line.usd" in patched:
        raise RuntimeError("Jetracer reference remained after scene patch")

    SCENE_USDA.write_text(patched, encoding="utf-8")
    print(f"Patched scene.usda -> environment references {terrain_rel_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--patch-scene",
        action="store_true",
        help="Patch isaac/scene.usda to reference the generated local terrain fallback.",
    )
    args = parser.parse_args()

    _require(SAT_PNG, "Run scripts/fetch_terrain.py first to download satellite imagery.")
    _require(SAT_JSON, "Run scripts/fetch_terrain.py first to generate metadata.")

    meta = json.loads(SAT_JSON.read_text(encoding="utf-8"))
    print(
        f"Building terrain USD for {meta['aoi_m']}m AOI centered at "
        f"{meta['center_lat']}, {meta['center_lon']}"
    )

    ASSETS.mkdir(parents=True, exist_ok=True)
    TERRAIN_USDA.write_text(build_terrain_usd(meta), encoding="utf-8")
    print(f"Written -> {TERRAIN_USDA}")

    if args.patch_scene:
        patch_scene_usda()
    else:
        print("Skipped scene patch; Cesium remains the primary visual environment.")

    print("\nDone. Use --patch-scene only for the local terrain fallback.")
    print(f"Satellite coverage: {meta['bbox']}")
    print(f"Resolution: {meta['pixels_per_meter']} px/m")


if __name__ == "__main__":
    main()
