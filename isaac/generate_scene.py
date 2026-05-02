"""Generate the emergency fallback USD scene.

Run this with a Python environment that has Pixar USD available:

    python -m isaac.generate_scene

The checked-in `isaac/scene.usda` already contains a simple fallback scene.
This generator is kept so the scene can be regenerated or extended later.
"""

from __future__ import annotations

from pathlib import Path

from bridge.sim_publisher import SyntheticSimPublisher
from hades import config


def _cube(name: str, x: float, y: float, z: float, sx: float, sy: float, sz: float) -> str:
    return f'''        def Cube "{name}"
        {{
            double size = 1
            matrix4d xformOp:transform = ( ({sx}, 0, 0, 0), (0, {sy}, 0, 0), (0, 0, {sz}, 0), ({x}, {y}, {z}, 1) )
            uniform token[] xformOpOrder = ["xformOp:transform"]
        }}
'''


def generate_scene_usda(path: Path) -> None:
    frame = SyntheticSimPublisher().frame_at(0.0)
    parts = [
        "#usda 1.0\n",
        "(\n",
        f'    defaultPrim = "{config.SCENE.name}"\n',
        "    metersPerUnit = 1\n",
        "    upAxis = \"Z\"\n",
        ")\n\n",
        f'def Xform "{config.SCENE.name}"\n',
        "{\n",
        _cube("road", 0, 0, 0.02, 420, config.SCENE.road_width_m, 0.04),
        _cube("terrain_pad", 0, 0, -0.05, 520, 180, 0.02),
    ]
    for vehicle in frame.convoy:
        parts.append(_cube(vehicle.id, vehicle.pose.x, vehicle.pose.y, vehicle.pose.z, 6, 3, 1.6))
    for drone in frame.drones:
        scale = 2.8 if drone.tier == "PARENT" else 1.2
        parts.append(_cube(drone.id, drone.pose.x, drone.pose.y, drone.pose.z, scale, scale, 0.35))
    for edge in frame.edges:
        parts.append(_cube(edge.id, edge.pose.x, edge.pose.y, edge.pose.z, 1.6, 1.6, 2.4))
    parts.append("}\n")
    path.write_text("".join(parts), encoding="utf-8")


def main() -> None:
    generate_scene_usda(Path(__file__).with_name("scene.usda"))


if __name__ == "__main__":
    main()
