"""Build the HADES terrain USD from the fetched satellite texture.

Reads assets/terrain/satellite.png + satellite.json and writes
assets/terrain/terrain.usda — a 520×520m flat ground plane with:
  - Satellite texture mapped to exact real-world scale
  - PhysicsCollisionAPI so convoy/drones rest on it correctly
  - A sky dome (NVIDIA desert HDR) for lighting

Then patches scene.usda to reference terrain.usda instead of the
Jetracer track.

Usage:
    python scripts/build_terrain_usd.py
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parents[1]
ASSETS = ROOT / "assets" / "terrain"
SAT_PNG = ASSETS / "satellite.png"
SAT_JSON = ASSETS / "satellite.json"
TERRAIN_USDA = ASSETS / "terrain.usda"
SCENE_USDA = ROOT / "isaac" / "scene.usda"


def _require(path: Path, hint: str) -> None:
    if not path.exists():
        print(f"Missing: {path}\n{hint}")
        sys.exit(1)


def build_terrain_usd(meta: dict) -> str:
    aoi_m = meta["aoi_m"]
    half = aoi_m / 2.0
    heading = meta.get("heading_deg", 315.0)

    # Relative path from isaac/ to assets/terrain/
    rel_sat = "../assets/terrain/satellite.png"

    return f"""#usda 1.0
(
    defaultPrim = "terrain"
    metersPerUnit = 1
    upAxis = "Z"
)

def Xform "terrain"
{{
    # Flat ground plane — {aoi_m}m x {aoi_m}m centred on Route 375, NV (37.6530N, -115.7440W)
    def Mesh "ground"
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

        # Physics — static collision so convoy wheels land correctly
        prepend apiSchemas = ["PhysicsCollisionAPI", "PhysicsMeshCollisionAPI"]
        uniform token physics:approximation = "meshSimplification"

        # Satellite texture via MDL OmniPBR
        rel material:binding = </terrain/SatMaterial>
    }}

    def Material "SatMaterial"
    {{
        token outputs:mdl:displacement.connect = </terrain/SatMaterial/Shader.outputs:out>
        token outputs:mdl:surface.connect = </terrain/SatMaterial/Shader.outputs:out>
        token outputs:mdl:volume.connect = </terrain/SatMaterial/Shader.outputs:out>

        def Shader "Shader"
        {{
            uniform token info:implementationSource = "sourceAsset"
            uniform asset info:mdl:sourceAsset = @OmniPBR.mdl@
            uniform token info:mdl:sourceAsset:subIdentifier = "OmniPBR"
            asset inputs:diffuse_texture = @{rel_sat}@ (
                colorSpace = "sRGB"
            )
            float inputs:reflection_roughness_constant = 0.9
            float inputs:metallic_constant = 0.0
            token outputs:out
        }}
    }}

    # Heading rotation so road aligns with scene X-axis (convoy route)
    double3 xformOp:rotateXYZ = (0, 0, {heading - 315:.1f})
    uniform token[] xformOpOrder = ["xformOp:rotateXYZ"]
}}
"""


def patch_scene_usda(terrain_rel_path: str) -> None:
    scene = SCENE_USDA.read_text(encoding="utf-8")

    old = """    def Xform "environment"
    {
        def Xform "jetracer_track_context" (
            prepend references = @https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/5.1/Isaac/Environments/Jetracer/Tracks/track_solid_line.usd@
        )
        {
            double3 xformOp:translate = (0, 0, -0.04)
            double3 xformOp:scale = (42, 42, 1)
            uniform token[] xformOpOrder = ["xformOp:translate", "xformOp:scale"]
        }
    }"""

    new = f"""    def Xform "environment"
    {{
        def Xform "terrain_nv375" (
            prepend references = @{terrain_rel_path}@
        )
        {{
            double3 xformOp:translate = (0, 0, 0)
            uniform token[] xformOpOrder = ["xformOp:translate"]
        }}
    }}"""

    if old not in scene:
        print("WARNING: could not find Jetracer block to replace — scene.usda may already be patched.")
        return

    SCENE_USDA.write_text(scene.replace(old, new), encoding="utf-8")
    print(f"Patched scene.usda → environment now references {terrain_rel_path}")


def main() -> None:
    _require(SAT_PNG, "Run scripts/fetch_terrain.py first to download satellite imagery.")
    _require(SAT_JSON, "Run scripts/fetch_terrain.py first to generate metadata.")

    meta = json.loads(SAT_JSON.read_text())
    print(f"Building terrain USD for {meta['aoi_m']}m AOI centred at "
          f"{meta['center_lat']}°N, {meta['center_lon']}°W")

    usd_text = build_terrain_usd(meta)
    ASSETS.mkdir(parents=True, exist_ok=True)
    TERRAIN_USDA.write_text(usd_text, encoding="utf-8")
    print(f"Written → {TERRAIN_USDA}")

    # Path from isaac/ to assets/terrain/terrain.usda
    terrain_rel = "../assets/terrain/terrain.usda"
    patch_scene_usda(terrain_rel)

    print("\nDone. Open isaac/scene.usda in Isaac Sim to verify the terrain.")
    print(f"Satellite coverage: {meta['bbox']}")
    print(f"Resolution: {meta['pixels_per_meter']} px/m")


if __name__ == "__main__":
    main()
