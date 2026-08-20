import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
BUILDING_NAME = "building__dartmouth-hall__way_48784540"
SOURCE_BLEND = Path("/Users/godwinkangor/Downloads/dartmouth energy twin.blend")
SOURCE_OBJECT = "Areas.046"
DETAIL_PREFIX = "mwrld_dartmouth_hall__"
RULES_PATH = MODEL_DIR / "renders" / "buildings" / BUILDING_NAME / "references" / "modeling-rules.json"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def ensure_materials():
    return {
        "wall": material("mwrld_dartmouth_hall_white_brick", (0.82, 0.82, 0.78, 1)),
        "stone": material("mwrld_dartmouth_hall_granite_base", (0.48, 0.47, 0.44, 1)),
        "window": material("mwrld_dartmouth_hall_dark_window", (0.035, 0.04, 0.04, 1)),
        "door": material("mwrld_dartmouth_hall_black_door", (0.025, 0.025, 0.02, 1)),
        "roof": material("mwrld_dartmouth_hall_slate_hip_roof", (0.25, 0.25, 0.26, 1)),
        "trim": material("mwrld_dartmouth_hall_white_trim", (0.9, 0.89, 0.84, 1)),
        "copper": material("mwrld_dartmouth_hall_green_cupola_cap", (0.16, 0.42, 0.32, 1)),
        "metal": material("mwrld_dartmouth_hall_dark_metal", (0.03, 0.03, 0.03, 1)),
    }


def local_bounds(obj):
    coords = [v.co.copy() for v in obj.data.vertices]
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def remove_old_details(parent):
    target = parent.get("mwrld_osm_id", parent.name)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(DETAIL_PREFIX) or obj.get("mwrld_detail_for") == target:
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0 and mesh.name.startswith(DETAIL_PREFIX):
            bpy.data.meshes.remove(mesh)


def reset_parent_to_source_mesh(parent):
    if not SOURCE_BLEND.exists():
        return False
    with bpy.data.libraries.load(str(SOURCE_BLEND), link=False) as (data_from, data_to):
        if SOURCE_OBJECT not in data_from.objects:
            return False
        data_to.objects = [SOURCE_OBJECT]
    source_obj = data_to.objects[0]
    if source_obj is None or source_obj.type != "MESH":
        return False
    old_mesh = parent.data
    parent.data = source_obj.data.copy()
    parent.data.name = parent.name + "_source_mesh"
    bpy.data.objects.remove(source_obj, do_unlink=True)
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    parent["mwrld_reset_from_source_blend"] = str(SOURCE_BLEND)
    parent["mwrld_reset_from_source_object"] = SOURCE_OBJECT
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


def wall_id_for_edge(a, b, side, min_v, max_v):
    mid = (a + b) * 0.5
    length = (b - a).length
    y_mid = (min_v.y + max_v.y) * 0.5
    if side == "west":
        if length >= 14 and mid.y < y_mid:
            return "west-south-wing"
        if length >= 14:
            return "west-north-wing"
        if 8 <= length <= 14:
            return "west-center-entry"
    if side == "east":
        if length >= 14 and mid.y < y_mid:
            return "east-south-wing"
        if length >= 14:
            return "east-north-wing"
        if 8 <= length <= 14:
            return "east-center-bay"
    if side == "north" and length >= 14:
        return "north-main"
    if side == "south" and length >= 14:
        return "south-main"
    return f"{side}-connector"


def source_id_from_reference(reference):
    path = Path(reference)
    stem = path.stem
    if path.parent.name == "walls":
        return stem
    return stem


def opening_layout_for_wall(wall_id, plan):
    windows = int(plan.get("windows", 0))
    doors = int(plan.get("doors", 0))
    source = source_id_from_reference(plan.get("reference", ""))
    openings = []
    if windows:
        floors = 3
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


def add_wall_faces(verts, faces, wall_counts, a, b, side, wall_id, plan, min_z, max_z):
    length = (b - a).length
    if length < 0.5:
        return
    openings = []
    for item in opening_layout_for_wall(wall_id, plan):
        cx = item["along"] * length
        if item["kind"] == "door":
            half = min(max(length * item["width"], 0.45), 0.62)
        else:
            half = min(max(length * item["width"], 0.38), 0.68)
        openings.append(
            {
                **item,
                "u0": max(0.0, cx - half),
                "u1": min(length, cx + half),
                "z0": min_z + item["z0"],
                "z1": min(min_z + item["z1"], max_z - 1.3),
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
            kind = "stone" if z_mid < min_z + 1.4 else "wall"
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


def roof_outline_from_source(mesh, max_z):
    candidates = []
    for poly in mesh.polygons:
        coords = [mesh.vertices[index].co.copy() for index in poly.vertices]
        if coords and all(abs(co.z - max_z) <= 0.02 for co in coords):
            candidates.append(coords)
    if not candidates:
        return []
    return max(candidates, key=len)


def rebuild_shell(parent, mats, rules):
    old_mesh = parent.data
    min_v, max_v = local_bounds(parent)
    roof_outline = roof_outline_from_source(old_mesh, max_v.z)
    parent["mwrld_source_min_z"] = float(min_v.z)
    parent["mwrld_source_max_z"] = float(max_v.z)
    verts = []
    faces = []
    wall_counts = {}
    wall_plans = rules.get("windowsAndDoors", {}).get("wallOpeningPlans", {})
    for a, b in bottom_edges(parent, min_v):
        side = side_for_edge(a, b, min_v, max_v)
        wall_id = wall_id_for_edge(a, b, side, min_v, max_v)
        plan = wall_plans.get(wall_id, {"windows": 0, "doors": 0, "reference": side})
        add_wall_faces(verts, faces, wall_counts, a, b, side, wall_id, plan, min_v.z, max_v.z)

    mesh = bpy.data.meshes.new(parent.name + "_integrated_mesh")
    mesh.from_pydata(verts, [], [face for face, _, _, _ in faces])
    mesh.update()
    for key in ["wall", "stone", "window", "door"]:
        mesh.materials.append(mats[key])
    mat_indices = {"wall": 0, "stone": 1, "window": 2, "door": 3}
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
    parent["mwrld_roof_rule"] = "hip_roof_from_roof_satellite_reference"
    return min_v, max_v, roof_outline


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
    bpy.ops.mesh.primitive_cone_add(vertices=vertices, radius1=radius1, radius2=radius2, depth=depth, end_fill_type="NOTHING", location=parent.matrix_world @ center)
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


def roof_rect_mesh(x0, x1, y0, y1, z, ridge_z, hip_inset):
    cx = (x0 + x1) * 0.5
    return (
        [
            (x0, y0, z),
            (x1, y0, z),
            (x1, y1, z),
            (x0, y1, z),
            (cx, y0 + hip_inset, ridge_z),
            (cx, y1 - hip_inset, ridge_z),
        ],
        [
            (0, 1, 4),
            (3, 5, 2),
            (0, 4, 5, 3),
            (1, 2, 5, 4),
        ],
    )


def add_front_pediment(parent, collection, mats, front_x, cy, wall_z, roof_z, source):
    half_w = 3.9
    verts = [
        (front_x, cy - half_w, wall_z),
        (front_x, cy + half_w, wall_z),
        (front_x, cy + half_w, roof_z),
        (front_x, cy, roof_z + 2.4),
        (front_x, cy - half_w, roof_z),
    ]
    faces = [(0, 1, 2, 4), (4, 2, 3)]
    obj = add_mesh_detail(f"{DETAIL_PREFIX}front_pediment", parent, collection, verts, faces, mats["trim"], "front_pediment", source)
    obj["mwrld_roof_reference_note"] = "front triangular pediment from west facade reference"
    return obj


def add_roof_boxes(parent, collection, mats, x0, x1, y0, y1, z, source):
    width = x1 - x0
    depth = y1 - y0
    dormers = [
        ("front_south", x0 + width * 0.30, y0 + depth * 0.25),
        ("front_north", x0 + width * 0.70, y0 + depth * 0.25),
        ("rear_south", x0 + width * 0.30, y0 + depth * 0.75),
        ("rear_north", x0 + width * 0.70, y0 + depth * 0.75),
    ]
    for name, dx, dy in dormers:
        obj = add_box(f"{DETAIL_PREFIX}roof_dormer_{name}", parent, collection, Vector((dx, dy, z + 0.45)), (1.55, 1.05, 0.9), mats["roof"], "roof_dormer", source)
        obj["mwrld_roof_reference_note"] = "dark roof dormer/box visible in roof-satellite.jpg"
    chimneys = [
        ("front_south", x0 + width * 0.18, y0 + depth * 0.26),
        ("rear_north", x0 + width * 0.83, y0 + depth * 0.74),
    ]
    for name, dx, dy in chimneys:
        obj = add_box(f"{DETAIL_PREFIX}chimney_{name}", parent, collection, Vector((dx, dy, z + 1.1)), (0.95, 0.95, 2.2), mats["stone"], "chimney", source)
        obj["mwrld_roof_reference_note"] = "chimney mass visible in roof-satellite.jpg/front context"


def add_cupola_posts_and_rails(parent, collection, mats, cx, cy, base_z, source):
    post_offsets = [(-0.72, -0.72), (-0.72, 0.72), (0.72, -0.72), (0.72, 0.72)]
    for index, (ox, oy) in enumerate(post_offsets, start=1):
        add_box(
            f"{DETAIL_PREFIX}cupola_post_{index:02d}",
            parent,
            collection,
            Vector((cx + ox, cy + oy, base_z + 0.75)),
            (0.12, 0.12, 1.5),
            mats["trim"],
            "cupola_post",
            source,
        )
    rails = [
        ("north", Vector((cx, cy + 0.72, base_z + 0.34)), (1.32, 0.08, 0.12)),
        ("south", Vector((cx, cy - 0.72, base_z + 0.34)), (1.32, 0.08, 0.12)),
        ("east", Vector((cx + 0.72, cy, base_z + 0.34)), (0.08, 1.32, 0.12)),
        ("west", Vector((cx - 0.72, cy, base_z + 0.34)), (0.08, 1.32, 0.12)),
    ]
    for name, center, size in rails:
        add_box(f"{DETAIL_PREFIX}cupola_rail_{name}", parent, collection, center, size, mats["trim"], "cupola_rail", source)


def add_hip_roof(parent, collection, mats, min_v, max_v, roof_outline, rules):
    z = max_v.z
    x0, x1 = min_v.x, max_v.x
    y0, y1 = min_v.y, max_v.y
    ridge_z = z + 3.3
    hip_inset = min((y1 - y0) * 0.16, 8.0)
    verts, faces = roof_rect_mesh(x0, x1, y0, y1, z, ridge_z, hip_inset)
    roof = add_mesh_detail(f"{DETAIL_PREFIX}hip_roof", parent, collection, verts, faces, mats["roof"], "roof", "references/roof-satellite.jpg")
    roof["mwrld_roof_reference_note"] = "main long-hip roof ridge from roof-satellite.jpg, replacing rejected radial fan roof"

    cx = (x0 + x1) * 0.5
    cy = y0 + (y1 - y0) * 0.5
    roof_context = "references/tower/tower-roof-satellite-context.jpg"
    tower_context = "references/tower/tower-front-context.jpg"
    add_front_pediment(parent, collection, mats, x0 - 0.04, cy, z - 0.05, z + 2.1, tower_context)
    add_roof_boxes(parent, collection, mats, x0, x1, y0, y1, z, "references/roof-satellite.jpg")
    add_box(f"{DETAIL_PREFIX}cupola_base", parent, collection, Vector((cx, cy, ridge_z + 0.38)), (2.95, 2.95, 0.76), mats["trim"], "cupola_base", roof_context)
    add_box(f"{DETAIL_PREFIX}cupola_lower_plinth", parent, collection, Vector((cx, cy, ridge_z + 0.92)), (2.35, 2.35, 0.32), mats["trim"], "cupola_base", tower_context)
    add_box(f"{DETAIL_PREFIX}cupola_lantern", parent, collection, Vector((cx, cy, ridge_z + 1.78)), (1.82, 1.82, 1.4), mats["trim"], "cupola_lantern", tower_context)
    add_cupola_posts_and_rails(parent, collection, mats, cx, cy, ridge_z + 1.08, tower_context)
    opening_z = ridge_z + 1.82
    add_box(f"{DETAIL_PREFIX}cupola_lantern_opening_north", parent, collection, Vector((cx, cy + 0.921, opening_z)), (0.82, 0.035, 1.05), mats["window"], "cupola_lantern_opening", tower_context)
    add_box(f"{DETAIL_PREFIX}cupola_lantern_opening_south", parent, collection, Vector((cx, cy - 0.921, opening_z)), (0.82, 0.035, 1.05), mats["window"], "cupola_lantern_opening", tower_context)
    add_box(f"{DETAIL_PREFIX}cupola_lantern_opening_east", parent, collection, Vector((cx + 0.921, cy, opening_z)), (0.035, 0.82, 1.05), mats["window"], "cupola_lantern_opening", tower_context)
    add_box(f"{DETAIL_PREFIX}cupola_lantern_opening_west", parent, collection, Vector((cx - 0.921, cy, opening_z)), (0.035, 0.82, 1.05), mats["window"], "cupola_lantern_opening", tower_context)
    add_box(f"{DETAIL_PREFIX}cupola_upper_plinth", parent, collection, Vector((cx, cy, ridge_z + 2.64)), (1.42, 1.42, 0.32), mats["trim"], "cupola_lantern", tower_context)
    add_cone_detail(f"{DETAIL_PREFIX}cupola_cap", parent, collection, Vector((cx, cy, ridge_z + 3.16)), 0.9, 0.24, 0.72, 16, mats["copper"], "cupola_cap", tower_context)
    add_box(f"{DETAIL_PREFIX}spire", parent, collection, Vector((cx, cy, ridge_z + 4.23)), (0.11, 0.11, 1.42), mats["metal"], "spire", tower_context)
    add_box(f"{DETAIL_PREFIX}weathervane", parent, collection, Vector((cx, cy, ridge_z + 4.94)), (0.9, 0.05, 0.05), mats["metal"], "weathervane", tower_context)

    for index, zone in enumerate(rules.get("roof", {}).get("approvedDormerZones", []), start=1):
        add_box(f"{DETAIL_PREFIX}roof_dormer_{index:02d}", parent, collection, Vector(zone["center"]), tuple(zone["size"]), mats["trim"], "dormer", zone.get("source", "references/roof-satellite.jpg"))
    return roof


def load_rules():
    if not RULES_PATH.exists():
        raise SystemExit(f"Missing Dartmouth Hall modeling rules: {RULES_PATH}")
    return json.loads(RULES_PATH.read_text())


def validate_rules(parent, rules):
    errors = []
    if rules["sourceReset"]["required"] and parent.get("mwrld_reset_from_source_object") != rules["sourceReset"]["sourceObject"]:
        errors.append("Dartmouth Hall was not reset from the required clean source object.")
    face_sources = json.loads(parent.data.get("mwrld_face_reference_sources", "[]"))
    openings = [item for item in face_sources if item.get("kind") in {"window", "door"}]
    approved = set(rules["windowsAndDoors"]["approvedWallSources"])
    if not openings:
        errors.append("No integrated window/door faces were generated.")
    for item in openings:
        if item.get("source") not in approved:
            errors.append(f"Opening face {item['face']} uses unsupported reference source {item.get('source')!r}.")
    if rules.get("windowsAndDoors", {}).get("countsMustMatchReferencePerWall"):
        actual_counts = json.loads(parent.data.get("mwrld_wall_opening_counts", "{}"))
        for wall_id, plan in rules.get("windowsAndDoors", {}).get("wallOpeningPlans", {}).items():
            actual = actual_counts.get(wall_id, {"windows": 0, "doors": 0})
            if actual.get("windows", 0) != int(plan.get("windows", 0)):
                errors.append(f"{wall_id} has {actual.get('windows', 0)} windows, expected {plan.get('windows', 0)} from {plan.get('reference')}.")
            if actual.get("doors", 0) != int(plan.get("doors", 0)):
                errors.append(f"{wall_id} has {actual.get('doors', 0)} doors, expected {plan.get('doors', 0)} from {plan.get('reference')}.")
    tower_rules = rules.get("tower", {})
    if tower_rules.get("mustHaveProperTowerReferences"):
        manifest = RULES_PATH.parent / Path(tower_rules["referenceManifest"]).relative_to("references")
        if not manifest.exists():
            errors.append(f"Tower reference manifest is missing: {tower_rules['referenceManifest']}")
        for source in tower_rules.get("approvedTowerSources", []):
            source_path = RULES_PATH.parent / Path(source).relative_to("references")
            if not source_path.exists():
                errors.append(f"Approved tower reference is missing: {source}")
    target = parent.get("mwrld_osm_id", parent.name)
    detail_sources = {
        obj.get("mwrld_reference_source")
        for obj in bpy.context.scene.objects
        if obj.get("mwrld_detail_for") == target and obj.get("mwrld_detail_kind") in set(tower_rules.get("requiredDetailKinds", []))
    }
    approved_tower_sources = set(tower_rules.get("approvedTowerSources", []))
    for source in detail_sources:
        if source not in approved_tower_sources:
            errors.append(f"Tower detail uses unsupported reference source {source!r}.")
    detail_kinds = {
        obj.get("mwrld_detail_kind")
        for obj in bpy.context.scene.objects
        if obj.get("mwrld_detail_for") == target
    }
    for kind in tower_rules.get("requiredDetailKinds", []):
        if kind not in detail_kinds:
            errors.append(f"Required tower detail kind missing: {kind}.")
    if errors:
        raise SystemExit("Dartmouth Hall modeling rules failed:\n- " + "\n- ".join(errors))


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = bpy.data.objects.get(BUILDING_NAME)
    if parent is None:
        raise SystemExit(f"Missing {BUILDING_NAME}")
    mats = ensure_materials()
    rules = load_rules()
    remove_old_details(parent)
    reset_parent_to_source_mesh(parent)
    min_v, max_v, roof_outline = rebuild_shell(parent, mats, rules)
    collection = ensure_collection("Dartmouth Hall Integrated Details")
    add_hip_roof(parent, collection, mats, min_v, max_v, roof_outline, rules)
    validate_rules(parent, rules)
    parent["mwrld_generated_detail_count"] = len([obj for obj in bpy.context.scene.objects if obj.get("mwrld_detail_for") == parent.get("mwrld_osm_id")])
    parent["mwrld_detail_recipe"] = "dartmouth_hall_integrated_v1"
    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Integrated Dartmouth Hall facade mesh. Details: {parent['mwrld_generated_detail_count']}")


if __name__ == "__main__":
    main()
