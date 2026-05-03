"""Viewport presentation helpers for the outdoor Cesium demo.

The actor USD references stay intact. These helpers only make small physical
assets readable from an outdoor camera and add lightweight tracking beacons.
"""

from __future__ import annotations

import math

from hades import config


ROOT_PRIM = "/hades_phase_1"
MARKER_ROOT = f"{ROOT_PRIM}/visual_markers"
GOOGLE_PHOTOREALISTIC_3D_TILES = "/Google_Photorealistic_3D_Tiles"
GOOGLE_PHOTOREALISTIC_3D_TILES_ASSET_ID = 2275207

PARENT_PRESENTATION_SCALE = 8.0
SMALL_PRESENTATION_SCALE = 32.0
EDGE_PRESENTATION_SCALE = 0.16
CONVOY_PRESENTATION_SCALE = 2.4

MATERIAL_COLORS: dict[str, tuple[str, tuple[float, float, float]]] = {
    "parent": ("parent_drone_orange", (1.0, 0.56, 0.12)),
    "small": ("small_drone_green", (0.1, 1.0, 0.45)),
    "edge": ("edge_node_blue", (0.15, 0.62, 1.0)),
    "convoy": ("convoy_yellow", (1.0, 0.95, 0.38)),
    "threat": ("threat_red", (1.0, 0.05, 0.05)),
    "investigate": ("investigation_magenta", (1.0, 0.1, 0.85)),
    "wifi": ("wifi_cyan", (0.0, 0.9, 1.0)),
    "lora": ("lora_green", (0.1, 1.0, 0.35)),
    "route": ("route_dim", (0.45, 0.45, 0.45)),
    "active_route": ("active_route_yellow", (1.0, 0.83, 0.1)),
}


def configure_cesium_map(map_mode: str, ion_token: str) -> None:
    """Tune Cesium tilesets and optionally switch to a photorealistic 3D Tiles map."""
    import omni.usd
    from pxr import Sdf

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return

    _tune_world_terrain(stage)
    mode = map_mode.strip().lower()
    terrain = stage.GetPrimAtPath("/Cesium_World_Terrain")
    photoreal = stage.GetPrimAtPath(GOOGLE_PHOTOREALISTIC_3D_TILES)

    if mode == "photorealistic":
        if terrain and terrain.IsValid():
            terrain.SetActive(False)
        photoreal = stage.DefinePrim(GOOGLE_PHOTOREALISTIC_3D_TILES, "CesiumTilesetPrim")
        photoreal.SetActive(True)
        _set_attr(photoreal, "cesium:sourceType", Sdf.ValueTypeNames.Token, "ion")
        _set_attr(photoreal, "cesium:ionAssetId", Sdf.ValueTypeNames.Int64, GOOGLE_PHOTOREALISTIC_3D_TILES_ASSET_ID)
        _set_attr(photoreal, "cesium:ionAccessToken", Sdf.ValueTypeNames.String, ion_token)
        _set_attr(photoreal, "cesium:maximumScreenSpaceError", Sdf.ValueTypeNames.Float, 4.0)
        _set_attr(photoreal, "cesium:maximumSimultaneousTileLoads", Sdf.ValueTypeNames.UInt, 64)
        _set_attr(photoreal, "cesium:maximumCachedBytes", Sdf.ValueTypeNames.UInt64, 2_147_483_648)
        _set_attr(photoreal, "cesium:forbidHoles", Sdf.ValueTypeNames.Bool, True)
        _set_attr(photoreal, "cesium:smoothNormals", Sdf.ValueTypeNames.Bool, True)
        _set_attr(photoreal, "cesium:showCreditsOnScreen", Sdf.ValueTypeNames.Bool, False)
        photoreal.CreateRelationship("cesium:georeferenceBinding").SetTargets([Sdf.Path("/CesiumGeoreference")])
        photoreal.CreateRelationship("cesium:ionServerBinding").SetTargets([Sdf.Path("/CesiumServers/IonOfficial")])
    elif mode == "world-terrain":
        if terrain and terrain.IsValid():
            terrain.SetActive(True)
        if photoreal and photoreal.IsValid():
            photoreal.SetActive(False)
    else:
        raise ValueError(f"Unsupported Cesium map mode: {map_mode!r}")


def apply_actor_presentation() -> None:
    """Apply display-scale overrides and create visible marker prims."""
    import omni.usd
    from pxr import Gf, UsdGeom

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return

    for idx in range(config.COUNTS.parent_drones):
        _set_scale(stage, f"{ROOT_PRIM}/parent_{idx}", PARENT_PRESENTATION_SCALE)
    for idx in range(config.COUNTS.small_drones):
        _set_scale(stage, f"{ROOT_PRIM}/small_{idx}", SMALL_PRESENTATION_SCALE)
    for idx in range(config.COUNTS.edge_nodes):
        _set_scale(stage, f"{ROOT_PRIM}/edge_{idx}", EDGE_PRESENTATION_SCALE)
    for idx in range(config.COUNTS.convoy_vehicles):
        _set_scale(stage, f"{ROOT_PRIM}/convoy_{idx}", CONVOY_PRESENTATION_SCALE)

    UsdGeom.Xform.Define(stage, MARKER_ROOT)
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/drones")
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/edges")
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/convoy")
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/routes")
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/threats")
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/vectors")
    UsdGeom.Xform.Define(stage, f"{MARKER_ROOT}/comms")
    materials = _ensure_materials(stage)
    _define_route_overlays(stage, materials)

    for idx in range(config.COUNTS.parent_drones):
        prim = _define_sphere_marker(
            stage,
            f"{MARKER_ROOT}/drones/parent_{idx}_beacon",
            radius=2.4,
            color=(1.0, 0.56, 0.12),
        )
        _bind_material(prim, materials["parent"])
    for idx in range(config.COUNTS.small_drones):
        prim = _define_sphere_marker(
            stage,
            f"{MARKER_ROOT}/drones/small_{idx}_beacon",
            radius=1.7,
            color=(0.1, 1.0, 0.45),
        )
        _bind_material(prim, materials["small"])
    for idx in range(config.COUNTS.edge_nodes):
        prim = _define_cylinder_marker(
            stage,
            f"{MARKER_ROOT}/edges/edge_{idx}_mast",
            radius=1.25,
            height=16.0,
            color=(0.15, 0.62, 1.0),
        )
        _bind_material(prim, materials["edge"])
        top = _define_sphere_marker(
            stage,
            f"{MARKER_ROOT}/edges/edge_{idx}_beacon",
            radius=3.2,
            color=(0.15, 0.62, 1.0),
        )
        _bind_material(top, materials["edge"])
    for idx in range(config.COUNTS.convoy_vehicles):
        mast = _define_cylinder_marker(
            stage,
            f"{MARKER_ROOT}/convoy/convoy_{idx}_mast",
            radius=2.2,
            height=34.0,
            color=(1.0, 0.95, 0.38),
        )
        _bind_material(mast, materials["convoy"])
        beacon = _define_sphere_marker(
            stage,
            f"{MARKER_ROOT}/convoy/convoy_{idx}_beacon",
            radius=7.2,
            color=(1.0, 0.95, 0.38),
        )
        _bind_material(beacon, materials["convoy"])
        heading = _define_beam(stage, f"{MARKER_ROOT}/convoy/convoy_{idx}_heading", materials["convoy"])
        heading.GetAttribute("visibility").Set("invisible")

    # Give the overview/follow camera a wider, closer lens for the route.
    camera = stage.GetPrimAtPath(f"{ROOT_PRIM}/RecordCamera")
    if camera and camera.IsValid():
        camera.GetAttribute("focalLength").Set(24.0)
        camera.GetAttribute("focusDistance").Set(280.0)
        _set_translate(stage, f"{ROOT_PRIM}/RecordCamera", Gf.Vec3d(-520.0, -260.0, 155.0))
        _set_rotate(stage, f"{ROOT_PRIM}/RecordCamera", Gf.Vec3f(58.0, 0.0, 0.0))


def update_visual_markers(frame, *, follow_camera: bool = True) -> None:
    """Move beacons with the simulation frame."""
    import omni.usd
    from pxr import Gf

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return

    for drone in frame.drones:
        offset = 5.0 if drone.tier == "PARENT" else 3.4
        path = f"{MARKER_ROOT}/drones/{drone.id}_beacon"
        _set_translate(stage, path, Gf.Vec3d(drone.pose.x, drone.pose.y, drone.pose.z + offset))

    for edge in frame.edges:
        _set_translate(stage, f"{MARKER_ROOT}/edges/{edge.id}_mast", Gf.Vec3d(edge.pose.x, edge.pose.y, edge.pose.z + 8.0))
        _set_translate(stage, f"{MARKER_ROOT}/edges/{edge.id}_beacon", Gf.Vec3d(edge.pose.x, edge.pose.y, edge.pose.z + 17.5))

    for convoy in frame.convoy:
        _set_translate(
            stage,
            f"{MARKER_ROOT}/convoy/{convoy.id}_mast",
            Gf.Vec3d(convoy.pose.x, convoy.pose.y, convoy.pose.z + 17.0),
        )
        _set_translate(
            stage,
            f"{MARKER_ROOT}/convoy/{convoy.id}_beacon",
            Gf.Vec3d(convoy.pose.x, convoy.pose.y, convoy.pose.z + 36.0),
        )
        heading_len = 46.0
        heading_end = (
            convoy.pose.x + heading_len * math.cos(convoy.pose.yaw),
            convoy.pose.y + heading_len * math.sin(convoy.pose.yaw),
            convoy.pose.z + 9.0,
        )
        _set_beam_between(
            stage,
            f"{MARKER_ROOT}/convoy/{convoy.id}_heading",
            (convoy.pose.x, convoy.pose.y, convoy.pose.z + 9.0),
            heading_end,
            thickness=2.6,
            material_name="convoy",
        )

    _update_active_route_overlay(stage, frame)
    _update_threat_overlay(stage, frame)
    _update_comms_overlay(stage, frame)

    if follow_camera and frame.convoy:
        convoy_x = frame.convoy[0].pose.x
        convoy_y = frame.convoy[0].pose.y
        drone_x = sum(drone.pose.x for drone in frame.drones) / max(1, len(frame.drones))
        drone_y = sum(drone.pose.y for drone in frame.drones) / max(1, len(frame.drones))
        target_x = 0.65 * convoy_x + 0.35 * drone_x
        target_y = 0.65 * convoy_y + 0.35 * drone_y
        _set_translate(stage, f"{ROOT_PRIM}/RecordCamera", Gf.Vec3d(target_x, target_y - 260.0, 155.0))


def _set_scale(stage, path: str, scale: float) -> None:
    from pxr import Gf

    _set_xform_op(stage, path, "xformOp:scale", Gf.Vec3d(scale, scale, scale), "scale")


def _set_translate(stage, path: str, value) -> None:
    _set_xform_op(stage, path, "xformOp:translate", value, "translate")


def _set_rotate(stage, path: str, value) -> None:
    _set_xform_op(stage, path, "xformOp:rotateXYZ", value, "rotate")


def _set_xform_op(stage, path: str, op_name: str, value, op_kind: str) -> None:
    from pxr import UsdGeom

    prim = stage.GetPrimAtPath(path)
    if not prim or not prim.IsValid():
        return
    xf = UsdGeom.Xformable(prim)
    ops = {op.GetOpName(): op for op in xf.GetOrderedXformOps()}
    op = ops.get(op_name)
    if op is None:
        if op_kind == "translate":
            op = xf.AddTranslateOp()
        elif op_kind == "rotate":
            op = xf.AddRotateXYZOp()
        elif op_kind == "scale":
            op = xf.AddScaleOp()
        else:
            raise ValueError(f"Unsupported xform op kind: {op_kind}")
    op.Set(value)


def _update_active_route_overlay(stage, frame) -> None:
    active_route = frame.convoy[0].active_route_id if frame.convoy else "main"
    for route_id, waypoints in config.ROUTE_WAYPOINTS.items():
        for idx in range(len(waypoints) - 1):
            prim = stage.GetPrimAtPath(f"{MARKER_ROOT}/routes/{route_id}_{idx}")
            if prim and prim.IsValid():
                prim.GetAttribute("visibility").Set("inherited")
                scale = prim.GetAttribute("xformOp:scale")
                value = scale.Get()
                thickness = 4.0 if route_id == active_route else 1.4
                scale.Set((value[0], thickness, thickness))


def _update_threat_overlay(stage, frame) -> None:
    from pxr import Gf

    materials = _ensure_materials(stage)
    active_ids = {threat.id for threat in frame.threats}
    existing_root = stage.GetPrimAtPath(f"{MARKER_ROOT}/threats")
    if existing_root and existing_root.IsValid():
        for prim in existing_root.GetChildren():
            if prim.GetName().split("_")[0] not in active_ids:
                prim.GetAttribute("visibility").Set("invisible")

    convoy = frame.convoy[0] if frame.convoy else None
    drones_by_id = {drone.id: drone for drone in frame.drones}
    vector_index = 0
    for threat in frame.threats:
        base_path = f"{MARKER_ROOT}/threats/{threat.id}"
        column = _define_cylinder_marker(stage, f"{base_path}_column", radius=5.0, height=42.0, color=(1.0, 0.05, 0.05))
        beacon = _define_sphere_marker(stage, f"{base_path}_beacon", radius=9.0, color=(1.0, 0.05, 0.05))
        _bind_material(column, materials["threat"])
        _bind_material(beacon, materials["threat"])
        _set_translate(stage, f"{base_path}_column", Gf.Vec3d(threat.pose.x, threat.pose.y, threat.pose.z + 21.0))
        _set_translate(stage, f"{base_path}_beacon", Gf.Vec3d(threat.pose.x, threat.pose.y, threat.pose.z + 45.0))
        column.GetAttribute("visibility").Set("inherited")
        beacon.GetAttribute("visibility").Set("inherited")

        _set_beam_between(
            stage,
            f"{base_path}_cross_x",
            (threat.pose.x - 20.0, threat.pose.y, threat.pose.z + 6.0),
            (threat.pose.x + 20.0, threat.pose.y, threat.pose.z + 6.0),
            thickness=2.0,
            material_name="threat",
        )
        _set_beam_between(
            stage,
            f"{base_path}_cross_y",
            (threat.pose.x, threat.pose.y - 20.0, threat.pose.z + 6.0),
            (threat.pose.x, threat.pose.y + 20.0, threat.pose.z + 6.0),
            thickness=2.0,
            material_name="threat",
        )

        if convoy is not None:
            _set_beam_between(
                stage,
                f"{MARKER_ROOT}/vectors/threat_{vector_index}",
                (convoy.pose.x, convoy.pose.y, convoy.pose.z + 14.0),
                (threat.pose.x, threat.pose.y, threat.pose.z + 14.0),
                thickness=2.2,
                material_name="threat",
            )
            vector_index += 1

        for drone in frame.drones:
            if drone.current_task.endswith(threat.id) and drone.id in drones_by_id:
                _set_beam_between(
                    stage,
                    f"{MARKER_ROOT}/vectors/threat_{vector_index}",
                    (drone.pose.x, drone.pose.y, drone.pose.z - 3.0),
                    (threat.pose.x, threat.pose.y, threat.pose.z + 18.0),
                    thickness=1.6,
                    material_name="investigate",
                )
                vector_index += 1

    _hide_unused_vector_prims(stage, vector_index, prefix="threat_")


def _update_comms_overlay(stage, frame) -> None:
    positions = {
        actor.id: (actor.pose.x, actor.pose.y, actor.pose.z)
        for group in (frame.drones, frame.edges, frame.convoy)
        for actor in group
    }
    max_links = 56
    used = 0
    for link in frame.links[:max_links]:
        src = positions.get(link.from_id)
        dst = positions.get(link.to_id)
        if src is None or dst is None:
            continue
        z = max(src[2], dst[2]) + 2.0
        material_name = "lora" if link.type == "LORA" else "wifi"
        _set_beam_between(
            stage,
            f"{MARKER_ROOT}/comms/link_{used:02d}",
            (src[0], src[1], z),
            (dst[0], dst[1], z),
            thickness=0.65 if link.type == "LORA" else 0.95,
            material_name=material_name,
        )
        used += 1

    for idx in range(used, max_links):
        prim = stage.GetPrimAtPath(f"{MARKER_ROOT}/comms/link_{idx:02d}")
        if prim and prim.IsValid():
            prim.GetAttribute("visibility").Set("invisible")


def _define_route_overlays(stage, materials) -> None:
    for route_id, waypoints in config.ROUTE_WAYPOINTS.items():
        material_name = "active_route" if route_id == "main" else "route"
        for idx, (start, end) in enumerate(zip(waypoints, waypoints[1:])):
            path = f"{MARKER_ROOT}/routes/{route_id}_{idx}"
            _define_beam(stage, path, materials[material_name])
            _set_beam_between(
                stage,
                path,
                (float(start[0]), float(start[1]), 2.4),
                (float(end[0]), float(end[1]), 2.4),
                thickness=2.0,
                material_name=material_name,
            )


def _set_beam_between(
    stage,
    path: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    *,
    thickness: float,
    material_name: str,
) -> None:
    from pxr import Gf

    prim = _define_beam(stage, path, _get_material(stage, material_name))
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = max(0.001, math.sqrt(dx * dx + dy * dy + dz * dz))
    yaw = math.degrees(math.atan2(dy, dx))
    _set_translate(stage, path, Gf.Vec3d((start[0] + end[0]) / 2.0, (start[1] + end[1]) / 2.0, (start[2] + end[2]) / 2.0))
    _set_rotate(stage, path, Gf.Vec3f(0.0, 0.0, yaw))
    _set_scale(stage, path, 1.0)
    _set_xform_op(stage, path, "xformOp:scale", Gf.Vec3d(length, thickness, thickness), "scale")
    prim.GetAttribute("visibility").Set("inherited")


def _hide_unused_vector_prims(stage, start_index: int, *, prefix: str) -> None:
    root = stage.GetPrimAtPath(f"{MARKER_ROOT}/vectors")
    if not root or not root.IsValid():
        return
    for prim in root.GetChildren():
        name = prim.GetName()
        if name.startswith(prefix):
            try:
                index = int(name.removeprefix(prefix))
            except ValueError:
                continue
            if index >= start_index:
                prim.GetAttribute("visibility").Set("invisible")


def _tune_world_terrain(stage) -> None:
    from pxr import Sdf

    terrain = stage.GetPrimAtPath("/Cesium_World_Terrain")
    if terrain and terrain.IsValid():
        _set_attr(terrain, "cesium:maximumScreenSpaceError", Sdf.ValueTypeNames.Float, 4.0)
        _set_attr(terrain, "cesium:maximumSimultaneousTileLoads", Sdf.ValueTypeNames.UInt, 64)
        _set_attr(terrain, "cesium:maximumCachedBytes", Sdf.ValueTypeNames.UInt64, 2_147_483_648)
        _set_attr(terrain, "cesium:forbidHoles", Sdf.ValueTypeNames.Bool, True)
        _set_attr(terrain, "cesium:smoothNormals", Sdf.ValueTypeNames.Bool, True)
        _set_attr(terrain, "cesium:showCreditsOnScreen", Sdf.ValueTypeNames.Bool, False)

    imagery = stage.GetPrimAtPath("/Cesium_World_Terrain/Bing_Maps_Aerial_imagery")
    if imagery and imagery.IsValid():
        _set_attr(imagery, "cesium:maximumScreenSpaceError", Sdf.ValueTypeNames.Float, 1.0)
        _set_attr(imagery, "cesium:maximumTextureSize", Sdf.ValueTypeNames.Int, 4096)
        _set_attr(imagery, "cesium:maximumSimultaneousTileLoads", Sdf.ValueTypeNames.UInt, 32)
        _set_attr(imagery, "cesium:showCreditsOnScreen", Sdf.ValueTypeNames.Bool, False)


def _set_attr(prim, attr_name: str, value_type, value) -> None:
    attr = prim.GetAttribute(attr_name)
    if not attr:
        attr = prim.CreateAttribute(attr_name, value_type)
    attr.Set(value)


def _ensure_materials(stage):
    from pxr import Gf, Sdf, UsdGeom, UsdShade

    UsdGeom.Scope.Define(stage, f"{MARKER_ROOT}/materials")

    def material(name: str, color: tuple[float, float, float]):
        mat = UsdShade.Material.Define(stage, f"{MARKER_ROOT}/materials/{name}")
        shader = UsdShade.Shader.Define(stage, f"{MARKER_ROOT}/materials/{name}/PreviewSurface")
        shader.CreateIdAttr("UsdPreviewSurface")
        shader.CreateInput("diffuseColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput("emissiveColor", Sdf.ValueTypeNames.Color3f).Set(Gf.Vec3f(*color))
        shader.CreateInput("roughness", Sdf.ValueTypeNames.Float).Set(0.32)
        shader.CreateInput("metallic", Sdf.ValueTypeNames.Float).Set(0.0)
        mat.CreateSurfaceOutput().ConnectToSource(shader.ConnectableAPI(), "surface")
        return mat

    return {key: material(name, color) for key, (name, color) in MATERIAL_COLORS.items()}


def _get_material(stage, key: str):
    from pxr import UsdShade

    if key not in MATERIAL_COLORS:
        raise KeyError(f"Unknown material key: {key}")
    name, _ = MATERIAL_COLORS[key]
    path = f"{MARKER_ROOT}/materials/{name}"
    prim = stage.GetPrimAtPath(path)
    if prim and prim.IsValid():
        return UsdShade.Material(prim)
    return _ensure_materials(stage)[key]


def _bind_material(prim, material) -> None:
    from pxr import UsdShade

    UsdShade.MaterialBindingAPI.Apply(prim).Bind(material)


def _define_sphere_marker(stage, path: str, *, radius: float, color: tuple[float, float, float]):
    from pxr import Gf, UsdGeom

    sphere = UsdGeom.Sphere.Define(stage, path)
    sphere.CreateRadiusAttr(radius)
    sphere.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
    return sphere.GetPrim()


def _define_cylinder_marker(stage, path: str, *, radius: float, height: float, color: tuple[float, float, float]):
    from pxr import Gf, UsdGeom

    cylinder = UsdGeom.Cylinder.Define(stage, path)
    cylinder.CreateRadiusAttr(radius)
    cylinder.CreateHeightAttr(height)
    cylinder.GetDisplayColorAttr().Set([Gf.Vec3f(*color)])
    return cylinder.GetPrim()


def _define_beam(stage, path: str, material):
    from pxr import UsdGeom

    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(1.0)
    prim = cube.GetPrim()
    _bind_material(prim, material)
    return prim
