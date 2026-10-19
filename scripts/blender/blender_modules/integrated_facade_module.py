"""Generic integrated-facade pipeline.

This generalizes the two hand-built "integrated facade" scripts that used
to exist only for Dartmouth Hall and Baker Library: windows and doors are
cut into the wall mesh as real openings (not floating panels), a roof is
built from either the source footprint or a simple pitched primitive, and
everything is driven by each building's own `references/modeling-rules.json`
+ `references/elevation-sheets/orthographic-elevations.json` instead of by
per-building Python.

A building with no modeling-rules.json yet still gets a reasonable plain
shell (solid walls, footprint-shaped roof cap) so this same driver can run
across every tracked building, not just the two landmarks that currently
have curated reference data.
"""

import json
from pathlib import Path

import bpy
from mathutils import Vector

from .building_lookup_module import building_folder_name

DEFAULT_MATERIAL_PALETTE = {
    "wall": (0.75, 0.73, 0.68, 1),
    "base": (0.45, 0.44, 0.40, 1),
    "window": (0.035, 0.04, 0.04, 1),
    "door": (0.12, 0.10, 0.08, 1),
    "roof": (0.22, 0.24, 0.24, 1),
    "trim": (0.85, 0.83, 0.78, 1),
    "metal": (0.03, 0.03, 0.03, 1),
    "feature": (0.80, 0.78, 0.70, 1),
    "stair": (0.50, 0.49, 0.46, 1),
}


def rules_path_for(model_dir, obj):
    return model_dir / "renders" / "buildings" / building_folder_name(obj) / "references" / "modeling-rules.json"


def elevations_path_for(model_dir, obj):
    return (
        model_dir
        / "renders"
        / "buildings"
        / building_folder_name(obj)
        / "references"
        / "elevation-sheets"
        / "orthographic-elevations.json"
    )


def load_rules(rules_path):
    if not rules_path.exists():
        return {}
    return json.loads(rules_path.read_text())


def load_elevation_panels(elevations_path):
    if not elevations_path.exists():
        return {}
    data = json.loads(elevations_path.read_text())
    return {panel["id"]: panel for panel in data.get("panels", [])}


def material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def ensure_materials(building_slug, rules):
    palette = dict(DEFAULT_MATERIAL_PALETTE)
    palette.update(rules.get("materials", {}))
    return {key: material(f"mwrld_{building_slug}_{key}", tuple(color)) for key, color in palette.items()}


def local_bounds(obj):
    coords = [v.co.copy() for v in obj.data.vertices]
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def remove_old_details(parent, detail_prefix):
    target = parent.get("mwrld_osm_id", parent.name)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(detail_prefix) or obj.get("mwrld_detail_for") == target:
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0 and mesh.name.startswith(detail_prefix):
            bpy.data.meshes.remove(mesh)


def reset_parent_to_source_mesh(parent, rules):
    source_reset = rules.get("sourceReset", {})
    source_blend = source_reset.get("sourceBlend")
    source_object = source_reset.get("sourceObject")
    if not source_blend or not source_object:
        return False
    source_blend_path = Path(source_blend)
    if not source_blend_path.exists():
        return False
    with bpy.data.libraries.load(str(source_blend_path), link=False) as (data_from, data_to):
        if source_object not in data_from.objects:
            return False
        data_to.objects = [source_object]
    source_obj = data_to.objects[0]
    if source_obj is None or source_obj.type != "MESH":
        return False
    old_mesh = parent.data
    parent.data = source_obj.data.copy()
    parent.data.name = parent.name + "_source_mesh"
    bpy.data.objects.remove(source_obj, do_unlink=True)
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    parent["mwrld_reset_from_source_blend"] = str(source_blend_path)
    parent["mwrld_reset_from_source_object"] = source_object
    return True


def bottom_edges(obj, min_v):
    edges = []
    for edge in obj.data.edges:
        a = obj.data.vertices[edge.vertices[0]].co
        b = obj.data.vertices[edge.vertices[1]].co
        if abs(a.z - min_v.z) <= 0.02 and abs(b.z - min_v.z) <= 0.02 and (a.xy - b.xy).length > 0.5:
            edges.append((a.copy(), b.copy()))
    return edges


def side_for_edge(a, b, min_v, max_v):
    mid = (a + b) * 0.5
    distances = {
        "south": abs(mid.y - min_v.y),
        "north": abs(mid.y - max_v.y),
        "west": abs(mid.x - min_v.x),
        "east": abs(mid.x - max_v.x),
    }
    return min(distances, key=distances.get)


def assign_generic_wall_ids(edges_with_sides):
    """Default wall-naming strategy: `{side}-{index}`, numbered in a stable
    reading order along each side. Buildings with curated wing-level names
    (see landmark_features_module) pass their own wall_id_fn instead."""
    order_key = {
        "west": lambda a, b: (a.y + b.y) * 0.5,
        "east": lambda a, b: (a.y + b.y) * 0.5,
        "north": lambda a, b: (a.x + b.x) * 0.5,
        "south": lambda a, b: (a.x + b.x) * 0.5,
    }
    by_side = {}
    for index, (a, b, side) in enumerate(edges_with_sides):
        by_side.setdefault(side, []).append(index)
    wall_ids = [None] * len(edges_with_sides)
    for side, indices in by_side.items():
        indices.sort(key=lambda i: order_key[side](edges_with_sides[i][0], edges_with_sides[i][1]))
        for position, index in enumerate(indices, start=1):
            wall_ids[index] = f"{side}-{position:02d}"
    return wall_ids


def source_id_from_reference(reference):
    return Path(reference).stem


def opening_layout_for_wall(wall_id, plan, panel=None):
    if panel and panel.get("openingLayout"):
        panel_width = float(panel.get("widthMeters", 1.0))
        panel_height = float(panel.get("estimatedHeightMeters", 14.0))
        openings = []
        for item in panel["openingLayout"]:
            openings.append(
                {
                    "kind": item["kind"],
                    "along": float(item.get("centerFraction", 0.5)),
                    "z0Meters": float(item.get("zMeters", 0.0)),
                    "z1Meters": float(item.get("zMeters", 0.0)) + float(item.get("heightMeters", 0.0)),
                    "widthFraction": float(item.get("widthMeters", 1.0)) / panel_width if panel_width else 0.08,
                    "heightFraction": float(item.get("heightMeters", 1.0)) / panel_height if panel_height else 0.18,
                    "source": source_id_from_reference(item.get("sourceImage") or panel.get("sourceImage", "")),
                    "wallId": wall_id,
                }
            )
        return openings

    windows = int(plan.get("windows", 0))
    doors = int(plan.get("doors", 0))
    source = source_id_from_reference(plan.get("reference", ""))
    floors = max(1, int(plan.get("floors", 3)))
    openings = []
    if windows:
        columns = max(1, round(windows / floors))
        extra = windows - columns * floors
        for floor in range(floors):
            count = columns + (1 if floor < extra else 0)
            if count <= 0:
                continue
            for col in range(count):
                openings.append(
                    {
                        "kind": "window",
                        "along": (col + 1) / (count + 1),
                        "z0": 2.1 + floor * 5.3,
                        "z1": 4.9 + floor * 5.3,
                        "width": min(0.11, max(0.052, 0.38 / count)),
                        "source": source,
                        "wallId": wall_id,
                    }
                )
    if doors:
        positions = plan.get("doorPositions") or ([0.5] if doors == 1 else [0.17, 0.5, 0.83][:doors])
        for position in positions:
            openings.append(
                {
                    "kind": "door",
                    "along": position,
                    "z0": 0.0,
                    "z1": 4.8,
                    "width": 0.09,
                    "source": source,
                    "wallId": wall_id,
                }
            )
    return openings


def add_wall_faces(verts, faces, wall_counts, a, b, side, wall_id, plan, min_z, max_z, panel=None):
    length = (b - a).length
    if length < 0.5:
        return
    openings = []
    wall_height = max_z - min_z
    panel_height = float(panel.get("estimatedHeightMeters", 14.0)) if panel else 14.0
    for item in opening_layout_for_wall(wall_id, plan, panel):
        cx = item["along"] * length
        if item.get("widthFraction"):
            half = max(0.18, length * item["widthFraction"] * 0.5)
        elif item["kind"] == "door":
            half = min(max(length * item["width"], 0.45), 0.62)
        else:
            half = min(max(length * item["width"], 0.38), 0.68)
        if "z0Meters" in item:
            z0 = min_z + wall_height * (item["z0Meters"] / panel_height)
            z1 = min_z + wall_height * (item["z1Meters"] / panel_height)
        else:
            z0 = min_z + item["z0"]
            z1 = min(min_z + item["z1"], max_z - 1.3)
        openings.append(
            {
                **item,
                "u0": max(0.0, cx - half),
                "u1": min(length, cx + half),
                "z0": max(min_z, z0),
                "z1": min(max_z - 0.08, z1),
            }
        )
    if openings:
        wall_counts.setdefault(wall_id, {"windows": 0, "doors": 0})
        wall_counts[wall_id]["windows"] += len([item for item in openings if item["kind"] == "window"])
        wall_counts[wall_id]["doors"] += len([item for item in openings if item["kind"] == "door"])

    u_breaks = {0.0, length}
    z_breaks = {min_z, min_z + 1.4, max_z}
    for opening in openings:
        u_breaks.update([opening["u0"], opening["u1"]])
        z_breaks.update([opening["z0"], opening["z1"]])
    us = sorted(u_breaks)
    zs = sorted(z_breaks)
    index = {}
    for ui, u in enumerate(us):
        point = a.lerp(b, u / length)
        for zi, z in enumerate(zs):
            index[(ui, zi)] = len(verts)
            verts.append((point.x, point.y, z))
    for ui in range(len(us) - 1):
        u_mid = (us[ui] + us[ui + 1]) * 0.5
        for zi in range(len(zs) - 1):
            z_mid = (zs[zi] + zs[zi + 1]) * 0.5
            kind = "base" if z_mid < min_z + 1.4 else "wall"
            source = side
            wall_source = wall_id
            for opening in openings:
                if opening["u0"] <= u_mid <= opening["u1"] and opening["z0"] <= z_mid <= opening["z1"]:
                    kind = opening["kind"]
                    source = opening["source"]
                    wall_source = opening["wallId"]
                    break
            face = (index[(ui, zi)], index[(ui + 1, zi)], index[(ui + 1, zi + 1)], index[(ui, zi + 1)])
            faces.append((face, kind, source, wall_source))


def add_source_cap_faces(mesh, verts, faces, z, is_top):
    """Reuse the source mesh's own top/bottom-facing polygons as a cap, so
    the shell stays footprint-accurate for any plan shape, not just
    rectangles."""
    for poly in mesh.polygons:
        coords = [mesh.vertices[i].co.copy() for i in poly.vertices]
        if coords and all(abs(co.z - z) <= 0.02 for co in coords):
            idx = []
            for co in coords:
                idx.append(len(verts))
                verts.append((co.x, co.y, co.z))
            face = tuple(idx) if is_top else tuple(reversed(idx))
            kind = "roof" if is_top else "base"
            source = "roof-satellite" if is_top else "footprint-base"
            faces.append((face, kind, source, None))


def rebuild_shell(parent, mats, rules, elevation_panels, detail_prefix, wall_id_fn=None):
    old_mesh = parent.data
    min_v, max_v = local_bounds(parent)
    parent["mwrld_source_min_z"] = float(min_v.z)
    parent["mwrld_source_max_z"] = float(max_v.z)
    verts = []
    faces = []
    wall_counts = {}
    wall_edges = []
    wall_plans = rules.get("windowsAndDoors", {}).get("wallOpeningPlans", {})

    raw_edges = bottom_edges(parent, min_v)
    edges_with_sides = [(a, b, side_for_edge(a, b, min_v, max_v)) for a, b in raw_edges]
    if wall_id_fn:
        wall_ids = [wall_id_fn(a, b, side, min_v, max_v) for a, b, side in edges_with_sides]
    else:
        wall_ids = assign_generic_wall_ids(edges_with_sides)

    for (a, b, side), wall_id in zip(edges_with_sides, wall_ids):
        plan = wall_plans.get(wall_id, {"windows": 0, "doors": 0, "reference": side})
        wall_edges.append({"a": a.copy(), "b": b.copy(), "side": side, "wall_id": wall_id})
        add_wall_faces(verts, faces, wall_counts, a, b, side, wall_id, plan, min_v.z, max_v.z, elevation_panels.get(wall_id))

    roof_type = rules.get("roof", {}).get("type", "flat")
    if roof_type not in {"gable", "hip"}:
        add_source_cap_faces(old_mesh, verts, faces, max_v.z, is_top=True)
    add_source_cap_faces(old_mesh, verts, faces, min_v.z, is_top=False)

    mesh = bpy.data.meshes.new(parent.name + "_integrated_mesh")
    mesh.from_pydata(verts, [], [face for face, _, _, _ in faces])
    mesh.update()
    for key in ["wall", "base", "window", "door", "roof"]:
        mesh.materials.append(mats[key])
    mat_indices = {"wall": 0, "base": 1, "window": 2, "door": 3, "roof": 4}
    face_sources = []
    for poly, (_, kind, source, wall_id) in zip(mesh.polygons, faces):
        poly.material_index = mat_indices.get(kind, 0)
        face_sources.append({"face": poly.index, "kind": kind, "source": source, "wallId": wall_id})
    mesh["mwrld_face_reference_sources"] = json.dumps(face_sources)
    mesh["mwrld_wall_opening_counts"] = json.dumps(wall_counts)
    parent.data = mesh
    bpy.data.meshes.remove(old_mesh)
    parent["mwrld_integrated_facades"] = True
    parent["mwrld_integrated_facade_rule"] = "windows_and_doors_are_wall_faces_with_edge_loops"
    return min_v, max_v, wall_edges


def ensure_collection(name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def add_mesh_detail(name, parent, collection, verts, faces, mat, kind, source):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    mesh.materials.append(mat)
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.parent = parent
    obj["mwrld_generated_detail"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    obj["mwrld_detail_kind"] = kind
    obj["mwrld_reference_source"] = source
    return obj


def add_box(name, parent, collection, center, size, mat, kind, source):
    bpy.ops.mesh.primitive_cube_add(size=1, location=parent.matrix_world @ center)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world
    obj["mwrld_generated_detail"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    obj["mwrld_detail_kind"] = kind
    obj["mwrld_reference_source"] = source
    return obj


def add_cone_detail(name, parent, collection, center, radius1, radius2, depth, vertices, mat, kind, source):
    bpy.ops.mesh.primitive_cone_add(
        vertices=vertices, radius1=radius1, radius2=radius2, depth=depth, end_fill_type="NOTHING", location=parent.matrix_world @ center
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    obj.data.materials.append(mat)
    if obj.name not in collection.objects:
        collection.objects.link(obj)
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world
    obj["mwrld_generated_detail"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    obj["mwrld_detail_kind"] = kind
    obj["mwrld_reference_source"] = source
    return obj


def side_normal(side):
    if side == "west":
        return Vector((-1, 0, 0))
    if side == "east":
        return Vector((1, 0, 0))
    if side == "north":
        return Vector((0, 1, 0))
    return Vector((0, -1, 0))


def wall_box_size(side, along_size, thickness, height):
    if side in {"west", "east"}:
        return (thickness, along_size, height)
    return (along_size, thickness, height)


def add_wall_attached_box(name, parent, collection, center, side, along_size, thickness, height, mat, kind, source, wall_id, feature_id):
    obj = add_box(name, parent, collection, center, wall_box_size(side, along_size, thickness, height), mat, kind, source)
    obj["mwrld_wall_id"] = wall_id
    obj["mwrld_reference_feature_id"] = feature_id
    return obj


def add_opening_frame_strips(
    name_prefix, parent, collection, center, side, tangent, normal, opening_width, opening_height, mat, kind, source, wall_id, feature_id, include_bottom=True
):
    strip = 0.08
    reveal = strip * 0.5
    frame_w = opening_width + strip * 2.0
    frame_h = opening_height + strip * 2.0
    pieces = [
        ("left", center - tangent * (opening_width * 0.5 + reveal), strip, frame_h),
        ("right", center + tangent * (opening_width * 0.5 + reveal), strip, frame_h),
        ("top", center + Vector((0, 0, opening_height * 0.5 + reveal)), frame_w, strip),
    ]
    if include_bottom:
        pieces.append(("bottom", center - Vector((0, 0, opening_height * 0.5 + reveal)), frame_w, strip))
    for suffix, piece_center, along_size, height in pieces:
        add_wall_attached_box(
            f"{name_prefix}_{suffix}", parent, collection, piece_center + normal * 0.018, side, along_size, 0.09, height, mat, kind, source, wall_id, feature_id
        )


def add_opening_visual_details(parent, collection, mats, wall_edges, elevation_panels, min_v, max_v, detail_prefix):
    wall_height = max_v.z - min_v.z
    detail_counts = {"windowTrim": 0, "shutters": 0, "doorTrim": 0}
    for edge in wall_edges:
        panel = elevation_panels.get(edge["wall_id"])
        if not panel:
            continue
        a = edge["a"]
        b = edge["b"]
        side = edge["side"]
        length = (b - a).length
        if length <= 0.01:
            continue
        normal = side_normal(side)
        panel_width = float(panel.get("widthMeters", 1.0))
        panel_height = float(panel.get("estimatedHeightMeters", 14.0))
        for opening in panel.get("openingLayout", []):
            kind = opening.get("kind")
            source = opening.get("sourceImage", panel.get("sourceImage", ""))
            opening_id = opening.get("id", "opening")
            opening_width = max(0.26, length * float(opening.get("widthMeters", 0.8)) / panel_width)
            opening_height = max(0.32, wall_height * float(opening.get("heightMeters", 1.0)) / panel_height)
            along = (float(opening.get("xMeters", 0.0)) + float(opening.get("widthMeters", 0.5)) * 0.5) / panel_width
            z = min_v.z + wall_height * ((float(opening.get("zMeters", 0.0)) + float(opening.get("heightMeters", 0.5)) * 0.5) / panel_height)
            point = a.lerp(b, max(0.0, min(1.0, along)))
            center = Vector((point.x, point.y, z)) + normal * 0.105
            tangent = (b - a).normalized()
            if kind == "window":
                add_opening_frame_strips(
                    f"{detail_prefix}{edge['wall_id']}__{opening_id}_trim", parent, collection, center, side, tangent, normal, opening_width, opening_height,
                    mats["trim"], "window_trim", source, edge["wall_id"], opening_id,
                )
                shutter_w = max(0.14, min(0.34, opening_width * 0.32))
                shutter_h = opening_height + 0.16
                offset = opening_width * 0.58 + shutter_w * 0.52
                for suffix, sign in [("left_shutter", -1), ("right_shutter", 1)]:
                    add_wall_attached_box(
                        f"{detail_prefix}{edge['wall_id']}__{opening_id}_{suffix}", parent, collection, center + tangent * (offset * sign) + normal * 0.025,
                        side, shutter_w, 0.09, shutter_h, mats["metal"], "window_shutter", source, edge["wall_id"], opening_id,
                    )
                    detail_counts["shutters"] += 1
                detail_counts["windowTrim"] += 1
            elif kind == "door":
                add_opening_frame_strips(
                    f"{detail_prefix}{edge['wall_id']}__{opening_id}_door_surround", parent, collection, center, side, tangent, normal, opening_width,
                    opening_height, mats["trim"], "door_surround", source, edge["wall_id"], opening_id, include_bottom=False,
                )
                threshold_center = Vector((point.x, point.y, min_v.z + 0.08)) + normal * 0.18
                add_wall_attached_box(
                    f"{detail_prefix}{edge['wall_id']}__{opening_id}_threshold", parent, collection, threshold_center, side, opening_width + 0.22, 0.32,
                    0.16, mats["stair"], "door_threshold", source, edge["wall_id"], opening_id,
                )
                detail_counts["doorTrim"] += 1
    parent["mwrld_window_trim_count"] = detail_counts["windowTrim"]
    parent["mwrld_window_shutter_count"] = detail_counts["shutters"]
    parent["mwrld_door_trim_count"] = detail_counts["doorTrim"]
    return detail_counts


def add_wall_reference_features(parent, collection, mats, wall_edges, elevation_panels, min_v, max_v, detail_prefix):
    wall_height = max_v.z - min_v.z
    feature_counts = {"majorWallFeatures": 0, "stairFeatures": 0}
    for edge in wall_edges:
        panel = elevation_panels.get(edge["wall_id"])
        if not panel:
            continue
        a = edge["a"]
        b = edge["b"]
        side = edge["side"]
        length = (b - a).length
        if length <= 0.01:
            continue
        normal = side_normal(side)
        panel_width = float(panel.get("widthMeters", 1.0))
        panel_height = float(panel.get("estimatedHeightMeters", 14.0))
        for group_name, mat_key, detail_kind, thickness in [
            ("majorWallFeatures", "feature", "major_wall_feature", 0.14),
            ("stairFeatures", "stair", "stair_or_platform", 0.34),
        ]:
            for feature in panel.get(group_name, []):
                feature_width = max(0.18, length * float(feature.get("widthMeters", 0.5)) / panel_width)
                feature_height = max(0.08, wall_height * float(feature.get("heightMeters", 0.5)) / panel_height)
                along = (float(feature.get("xMeters", 0.0)) + float(feature.get("widthMeters", 0.5)) * 0.5) / panel_width
                z = min_v.z + wall_height * ((float(feature.get("zMeters", 0.0)) + float(feature.get("heightMeters", 0.5)) * 0.5) / panel_height)
                point = a.lerp(b, max(0.0, min(1.0, along)))
                center = Vector((point.x, point.y, z)) + normal * (thickness * 0.52)
                obj = add_box(
                    f"{detail_prefix}{edge['wall_id']}__{feature.get('id', group_name)}", parent, collection, center,
                    wall_box_size(side, feature_width, thickness, feature_height), mats[mat_key], feature.get("kind", detail_kind),
                    feature.get("sourceImage", panel.get("sourceImage", "")),
                )
                obj["mwrld_wall_id"] = edge["wall_id"]
                obj["mwrld_reference_feature_id"] = feature.get("id", "")
                obj["mwrld_reference_feature_primitive"] = feature.get("primitive", "")
                feature_counts[group_name] += 1
    parent["mwrld_major_wall_feature_count"] = feature_counts["majorWallFeatures"]
    parent["mwrld_stair_feature_count"] = feature_counts["stairFeatures"]
    return feature_counts


def roof_rect_mesh(x0, x1, y0, y1, z, ridge_z, hip_inset):
    cx = (x0 + x1) * 0.5
    return (
        [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), (cx, y0 + hip_inset, ridge_z), (cx, y1 - hip_inset, ridge_z)],
        [(0, 1, 4), (3, 5, 2), (0, 4, 5, 3), (1, 2, 5, 4)],
    )


def gable_mesh(x0, x1, y0, y1, z, rise):
    ridge_along_x = (x1 - x0) >= (y1 - y0)
    if ridge_along_x:
        ym = (y0 + y1) * 0.5
        verts = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, ym, z + rise), (x1, ym, z + rise)]
        faces = [(0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5)]
    else:
        xm = (x0 + x1) * 0.5
        verts = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), (xm, y0, z + rise), (xm, y1, z + rise)]
        faces = [(0, 4, 5, 3), (4, 1, 2, 5), (0, 1, 4), (3, 5, 2)]
    return verts, faces


def build_pitched_roof(parent, collection, mats, min_v, max_v, rules, detail_prefix):
    """Generic gable/hip primitive for buildings without a landmark feature
    pack. Flat roofs are handled inside rebuild_shell via the source
    footprint cap, so there is nothing to add here for those."""
    roof_rules = rules.get("roof", {})
    roof_type = roof_rules.get("type", "flat")
    if roof_type not in {"gable", "hip"}:
        return None
    if "riseMeters" in roof_rules:
        rise = float(roof_rules["riseMeters"])
    else:
        rise = max((max_v.z - min_v.z) * float(roof_rules.get("heightRatio", 0.16)), 1.2)
    x0, x1, y0, y1, z = min_v.x, max_v.x, min_v.y, max_v.y, max_v.z
    source = roof_rules.get("referenceSource", "")
    if roof_type == "hip":
        hip_inset = min((y1 - y0) * 0.16, 8.0)
        verts, faces = roof_rect_mesh(x0, x1, y0, y1, z, z + rise, hip_inset)
    else:
        verts, faces = gable_mesh(x0, x1, y0, y1, z, rise)
    return add_mesh_detail(f"{detail_prefix}roof", parent, collection, verts, faces, mats["roof"], "roof", source)


def validate_rules(parent, rules, rules_dir=None):
    if not rules:
        return []
    errors = []
    target = parent.get("mwrld_osm_id", parent.name)

    source_reset = rules.get("sourceReset", {})
    if source_reset.get("required") and parent.get("mwrld_reset_from_source_object") != source_reset.get("sourceObject"):
        errors.append(f"{parent.name} was not reset from the required clean source object.")

    wd_rules = rules.get("windowsAndDoors", {})
    face_sources = json.loads(parent.data.get("mwrld_face_reference_sources", "[]"))
    openings = [item for item in face_sources if item.get("kind") in {"window", "door"}]
    approved = set(wd_rules.get("approvedWallSources", []))
    blocked = set(wd_rules.get("blockedWallSources", []))
    if wd_rules.get("wallOpeningPlans") and not openings:
        errors.append("No integrated window/door faces were generated.")
    for item in openings:
        source = item.get("source")
        if approved and source not in approved:
            errors.append(f"Opening face {item['face']} uses unsupported reference source {source!r}.")
        if source in blocked:
            errors.append(f"Opening face {item['face']} uses a blocked reference source {source!r}.")
    if wd_rules.get("noFloatingPanels"):
        floating = [
            obj.name
            for obj in bpy.context.scene.objects
            if obj.get("mwrld_detail_for") == target and obj.get("mwrld_detail_kind") in {"window", "window_panel", "door", "door_panel"}
        ]
        if floating:
            errors.append(f"Floating window/door objects are not allowed: {floating}")
    if wd_rules.get("countsMustMatchReferencePerWall"):
        actual_counts = json.loads(parent.data.get("mwrld_wall_opening_counts", "{}"))
        for wall_id, plan in wd_rules.get("wallOpeningPlans", {}).items():
            actual = actual_counts.get(wall_id, {"windows": 0, "doors": 0})
            if actual.get("windows", 0) != int(plan.get("windows", 0)):
                errors.append(f"{wall_id} has {actual.get('windows', 0)} windows, expected {plan.get('windows', 0)} from {plan.get('reference')}.")
            if actual.get("doors", 0) != int(plan.get("doors", 0)):
                errors.append(f"{wall_id} has {actual.get('doors', 0)} doors, expected {plan.get('doors', 0)} from {plan.get('reference')}.")

    roof_rules = rules.get("roof", {})
    required_materials = roof_rules.get("requiredMaterials", [])
    if required_materials:
        materials = [mat.name for mat in parent.data.materials]
        material_counts = {}
        for poly in parent.data.polygons:
            name = materials[poly.material_index] if poly.material_index < len(materials) else "none"
            material_counts[name] = material_counts.get(name, 0) + 1
        for material_name in required_materials:
            if material_counts.get(material_name, 0) == 0:
                errors.append(f"Required roof material is missing: {material_name}")

    landmark_rules = rules.get("tower") or rules.get("landmarkFeatures") or {}
    if landmark_rules:
        if landmark_rules.get("mustHaveProperTowerReferences") and rules_dir:
            manifest = rules_dir / Path(landmark_rules["referenceManifest"]).relative_to("references")
            if not manifest.exists():
                errors.append(f"Landmark reference manifest is missing: {landmark_rules['referenceManifest']}")
        required_kinds = set(landmark_rules.get("requiredDetailKinds", []))
        detail_kinds = {obj.get("mwrld_detail_kind") for obj in bpy.context.scene.objects if obj.get("mwrld_detail_for") == target}
        for kind in required_kinds:
            if kind not in detail_kinds:
                errors.append(f"Required landmark detail kind missing: {kind}.")
        approved_sources = set(landmark_rules.get("approvedTowerSources", []))
        if approved_sources:
            detail_sources = {
                obj.get("mwrld_reference_source")
                for obj in bpy.context.scene.objects
                if obj.get("mwrld_detail_for") == target and obj.get("mwrld_detail_kind") in required_kinds
            }
            for source in detail_sources:
                if source not in approved_sources:
                    errors.append(f"Landmark detail uses unsupported reference source {source!r}.")

    return errors
