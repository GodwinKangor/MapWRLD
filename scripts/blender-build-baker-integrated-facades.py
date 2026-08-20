import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
BAKER_NAME = "building__baker-library__way_295888783"
RULES_PATH = (
    MODEL_DIR
    / "renders"
    / "buildings"
    / BAKER_NAME
    / "references"
    / "modeling-rules.json"
)
SOURCE_BLEND = Path("/Users/godwinkangor/Downloads/dartmouth energy twin.blend")
SOURCE_OBJECT = "Areas.222"
OLD_DETAIL_PREFIX = "mwrld_refdetail__baker-library__"
DETAIL_PREFIX = "mwrld_tower__baker-library__"


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
        "brick": material("mwrld_baker_reference_brick", (0.42, 0.16, 0.11, 1)),
        "window": material("mwrld_baker_reference_dark_window", (0.035, 0.045, 0.05, 1)),
        "door": material("mwrld_baker_reference_white_door", (0.86, 0.84, 0.78, 1)),
        "trim": material("mwrld_baker_reference_limestone", (0.80, 0.78, 0.69, 1)),
        "flat_roof": material("mwrld_baker_reference_flat_roof", (0.23, 0.24, 0.23, 1)),
        "roof": material("mwrld_baker_reference_green_roof", (0.22, 0.46, 0.36, 1)),
        "clock": material("mwrld_baker_reference_clock_face", (0.92, 0.89, 0.78, 1)),
        "black": material("mwrld_baker_reference_black_metal", (0.03, 0.03, 0.03, 1)),
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
        if obj.name.startswith(OLD_DETAIL_PREFIX) or obj.name.startswith(DETAIL_PREFIX) or obj.get("mwrld_detail_for") == target:
            bpy.data.objects.remove(obj, do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users == 0 and (mesh.name.startswith(OLD_DETAIL_PREFIX) or mesh.name.startswith(DETAIL_PREFIX)):
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


def bottom_edges(obj, min_v, max_v):
    edges = []
    eps = 0.02
    for edge in obj.data.edges:
        a = obj.data.vertices[edge.vertices[0]].co
        b = obj.data.vertices[edge.vertices[1]].co
        if abs(a.z - min_v.z) <= eps and abs(b.z - min_v.z) <= eps:
            length = (a.xy - b.xy).length
            if length > 0.5:
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
    side = min(distances, key=distances.get)
    return side


def openings_for_side(side):
    if side == "south":
        openings = []
        for floor in range(3):
            for col in range(5):
                openings.append(
                    {
                        "kind": "window",
                        "along": 0.18 + 0.64 * ((col + 1) / 6),
                        "z0": 1.9 + floor * 5.05,
                        "z1": 4.7 + floor * 5.05,
                        "width": 0.038,
                        "source": "wall-02",
                    }
                )
        openings.append({"kind": "door", "along": 0.5, "z0": 0.0, "z1": 4.9, "width": 0.06, "source": "wall-02"})
        return openings
    if side in {"east", "west"}:
        source = "wall-03" if side == "east" else "wall-14"
        openings = []
        for floor in range(3):
            for col in range(4):
                openings.append(
                    {
                        "kind": "window",
                        "along": 0.20 + 0.60 * ((col + 1) / 5),
                        "z0": 1.9 + floor * 5.05,
                        "z1": 4.7 + floor * 5.05,
                        "width": 0.05,
                        "source": source,
                    }
                )
        return openings
    return []


def add_wall_faces(verts, faces, mats, a, b, side, min_z, max_z):
    height = max_z - min_z
    vec = b - a
    length = vec.length
    if length <= 0.01:
        return

    allow_openings = side in {"south", "east", "west"} and length >= 14.0
    openings = []
    for item in openings_for_side(side) if allow_openings else []:
        cx = item["along"] * length
        half = max(length * item["width"], 1.0)
        openings.append(
            {
                **item,
                "u0": max(0.0, cx - half),
                "u1": min(length, cx + half),
                "z0": min_z + item["z0"],
                "z1": min(min_z + item["z1"], max_z - 0.7),
            }
        )

    u_breaks = {0.0, length}
    z_breaks = {min_z, max_z}
    for op in openings:
        u_breaks.add(op["u0"])
        u_breaks.add(op["u1"])
        z_breaks.add(op["z0"])
        z_breaks.add(op["z1"])
    us = sorted(u_breaks)
    zs = sorted(z_breaks)

    index = {}
    for ui, u in enumerate(us):
        t = 0 if length == 0 else u / length
        p = a.lerp(b, t)
        for zi, z in enumerate(zs):
            index[(ui, zi)] = len(verts)
            verts.append((p.x, p.y, z))

    for ui in range(len(us) - 1):
        u_mid = (us[ui] + us[ui + 1]) * 0.5
        for zi in range(len(zs) - 1):
            z_mid = (zs[zi] + zs[zi + 1]) * 0.5
            kind = "brick"
            source = side
            for op in openings:
                if op["u0"] <= u_mid <= op["u1"] and op["z0"] <= z_mid <= op["z1"]:
                    kind = op["kind"]
                    source = op["source"]
                    break
            face = (index[(ui, zi)], index[(ui + 1, zi)], index[(ui + 1, zi + 1)], index[(ui, zi + 1)])
            faces.append((face, kind, source))


def rebuild_baker_mesh(parent, mats, rules):
    old_mesh = parent.data
    min_v, max_v = local_bounds(parent)
    parent["mwrld_source_min_z"] = float(min_v.z)
    parent["mwrld_source_max_z"] = float(max_v.z)
    edges = bottom_edges(parent, min_v, max_v)
    verts = []
    faces = []

    for a, b in edges:
        side = side_for_edge(a, b, min_v, max_v)
        add_wall_faces(verts, faces, mats, a, b, side, min_v.z, max_v.z)

    for poly in old_mesh.polygons:
        coords = [old_mesh.vertices[i].co.copy() for i in poly.vertices]
        if all(abs(v.z - max_v.z) < 0.02 for v in coords):
            idx = []
            for co in coords:
                idx.append(len(verts))
                verts.append(tuple(co))
            faces.append((tuple(idx), "flat_roof", "roof-satellite"))
        elif all(abs(v.z - min_v.z) < 0.02 for v in coords):
            idx = []
            for co in coords:
                idx.append(len(verts))
                verts.append(tuple(co))
            faces.append((tuple(reversed(idx)), "brick", "base"))

    add_tower_support_wall(verts, faces, min_v, max_v)
    if rules.get("roof", {}).get("approvedPrismZones"):
        add_prism_roof_runs(verts, faces, min_v, max_v)

    mesh = bpy.data.meshes.new(parent.name + "_integrated_mesh")
    mesh.from_pydata(verts, [], [face for face, _, _ in faces])
    mesh.update()
    mesh.materials.append(mats["brick"])
    mesh.materials.append(mats["window"])
    mesh.materials.append(mats["door"])
    mesh.materials.append(mats["flat_roof"])
    mesh.materials.append(mats["roof"])
    mat_indices = {"brick": 0, "window": 1, "door": 2, "flat_roof": 3, "roof": 4}
    face_sources = []
    for poly, (_, kind, source) in zip(mesh.polygons, faces):
        poly.material_index = mat_indices.get(kind, 0)
        face_sources.append({"face": poly.index, "kind": kind, "source": source})
    mesh["mwrld_face_reference_sources"] = json.dumps(face_sources)

    parent.data = mesh
    bpy.data.meshes.remove(old_mesh)
    parent["mwrld_integrated_facades"] = True
    parent["mwrld_integrated_facade_rule"] = "windows_and_doors_are_wall_faces_with_edge_loops"
    parent["mwrld_roof_rule"] = "flat_and_prism_roof_zones_from_roof_satellite_reference"
    parent["mwrld_roof_cap_status"] = "source_footprint_cap_pending_approved_subdivision"
    parent["mwrld_original_footprint_preserved"] = True


def tower_base_spec(min_v, max_v):
    x_span = max_v.x - min_v.x
    y_span = max_v.y - min_v.y
    center = Vector(((min_v.x + max_v.x) / 2, min_v.y + y_span * 0.34, max_v.z))
    sx = x_span * 0.145
    sy = y_span * 0.14
    return center, sx * 1.08, sy * 1.08


def add_tower_support_wall(verts, faces, min_v, max_v):
    center, width, depth = tower_base_spec(min_v, max_v)
    x0 = center.x - width / 2
    x1 = center.x + width / 2
    y0 = center.y - depth / 2
    y1 = center.y + depth / 2
    z0 = min_v.z
    z1 = max_v.z
    start = len(verts)
    verts.extend(
        [
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y1, z0),
            (x0, y1, z0),
            (x0, y0, z1),
            (x1, y0, z1),
            (x1, y1, z1),
            (x0, y1, z1),
        ]
    )
    faces.extend(
        [
            ((start + 0, start + 1, start + 5, start + 4), "brick", "references/south.jpg"),
            ((start + 1, start + 2, start + 6, start + 5), "brick", "references/south.jpg"),
            ((start + 2, start + 3, start + 7, start + 6), "brick", "references/south.jpg"),
            ((start + 3, start + 0, start + 4, start + 7), "brick", "references/south.jpg"),
            ((start + 4, start + 5, start + 6, start + 7), "roof", "references/roof-satellite.jpg"),
        ]
    )


def add_gable_prism(verts, faces, x0, x1, y0, y1, z, rise, ridge_axis, source):
    start = len(verts)
    if ridge_axis == "x":
        ym = (y0 + y1) / 2
        verts.extend(
            [
                (x0, y0, z),
                (x1, y0, z),
                (x1, y1, z),
                (x0, y1, z),
                (x0, ym, z + rise),
                (x1, ym, z + rise),
            ]
        )
        faces.extend(
            [
                ((start + 0, start + 1, start + 5, start + 4), "roof", source),
                ((start + 4, start + 5, start + 2, start + 3), "roof", source),
                ((start + 0, start + 4, start + 3), "roof", source),
                ((start + 1, start + 2, start + 5), "roof", source),
            ]
        )
    else:
        xm = (x0 + x1) / 2
        verts.extend(
            [
                (x0, y0, z),
                (x1, y0, z),
                (x1, y1, z),
                (x0, y1, z),
                (xm, y0, z + rise),
                (xm, y1, z + rise),
            ]
        )
        faces.extend(
            [
                ((start + 0, start + 4, start + 5, start + 3), "roof", source),
                ((start + 4, start + 1, start + 2, start + 5), "roof", source),
                ((start + 0, start + 1, start + 4), "roof", source),
                ((start + 3, start + 5, start + 2), "roof", source),
            ]
        )


def add_prism_roof_runs(verts, faces, min_v, max_v):
    z = max_v.z + 0.08
    x_span = max_v.x - min_v.x
    y_span = max_v.y - min_v.y
    source = "references/roof-satellite.jpg"

    # Baker has long green gable runs around the front and rear wings.
    # Keep these inside the source footprint and clear of the central tower block.
    roof_runs = [
        (min_v.x + x_span * 0.07, min_v.x + x_span * 0.34, min_v.y + y_span * 0.08, min_v.y + y_span * 0.24, "x"),
        (min_v.x + x_span * 0.66, max_v.x - x_span * 0.07, min_v.y + y_span * 0.08, min_v.y + y_span * 0.24, "x"),
        (min_v.x + x_span * 0.14, min_v.x + x_span * 0.36, min_v.y + y_span * 0.66, max_v.y - y_span * 0.08, "y"),
        (min_v.x + x_span * 0.64, max_v.x - x_span * 0.14, min_v.y + y_span * 0.66, max_v.y - y_span * 0.08, "y"),
    ]
    for x0, x1, y0, y1, axis in roof_runs:
        add_gable_prism(verts, faces, x0, x1, y0, y1, z, 2.2, axis, source)


def load_modeling_rules():
    if not RULES_PATH.exists():
        raise SystemExit(f"Missing Baker modeling rules: {RULES_PATH}")
    return json.loads(RULES_PATH.read_text())


def validate_modeling_rules(parent, rules):
    errors = []
    if rules["sourceReset"]["required"] and parent.get("mwrld_reset_from_source_object") != rules["sourceReset"]["sourceObject"]:
        errors.append("Baker was not reset from the required clean source object.")
    if parent.get("mwrld_integrated_facade_rule") != "windows_and_doors_are_wall_faces_with_edge_loops":
        errors.append("Windows and doors are not marked as integrated wall faces with edge loops.")

    floating_openings = [
        obj.name
        for obj in bpy.context.scene.objects
        if obj.get("mwrld_detail_for") == parent.get("mwrld_osm_id", parent.name)
        and obj.get("mwrld_detail_kind") in {"window", "window_panel", "door", "door_panel"}
    ]
    if floating_openings and rules["windowsAndDoors"]["noFloatingPanels"]:
        errors.append(f"Floating window/door objects are not allowed: {floating_openings}")

    face_sources = json.loads(parent.data.get("mwrld_face_reference_sources", "[]"))
    approved = set(rules["windowsAndDoors"]["approvedWallSources"])
    blocked = set(rules["windowsAndDoors"]["blockedWallSources"])
    opening_faces = [item for item in face_sources if item["kind"] in {"window", "door"}]
    if not opening_faces:
        errors.append("No integrated window or door faces were generated.")
    for item in opening_faces:
        source = item.get("source")
        if source in blocked or source not in approved:
            errors.append(f"Opening face {item['face']} uses unsupported reference source {source!r}.")

    material_counts = {}
    materials = [mat.name for mat in parent.data.materials]
    for poly in parent.data.polygons:
        name = materials[poly.material_index] if poly.material_index < len(materials) else "none"
        material_counts[name] = material_counts.get(name, 0) + 1
    for material_name in rules["roof"]["requiredMaterials"]:
        if material_counts.get(material_name, 0) == 0:
            errors.append(f"Required roof material is missing from Baker mesh: {material_name}")
    if rules.get("roof", {}).get("approvedPrismZones") and material_counts.get("mwrld_baker_reference_green_roof", 0) <= 2:
        errors.append("Prism roof zones were not generated; green roof has too few faces.")

    if errors:
        raise SystemExit("Baker modeling rules failed:\n- " + "\n- ".join(errors))


def ensure_collection(name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def box(name, parent, collection, local_center, size, mat, kind, source):
    bpy.ops.mesh.primitive_cube_add(size=1, location=parent.matrix_world @ local_center)
    obj = bpy.context.object
    obj.name = name + "__tmp"
    obj.data.name = name + "__tmp_mesh"
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


def add_tower(parent, collection, mats):
    min_v, max_v = local_bounds(parent)
    source_min = Vector((min_v.x, min_v.y, float(parent.get("mwrld_source_min_z", min_v.z))))
    source_max = Vector((max_v.x, max_v.y, float(parent.get("mwrld_source_max_z", max_v.z))))
    center, base_width, base_depth = tower_base_spec(source_min, source_max)
    sx = base_width / 1.08
    sy = base_depth / 1.08
    details = []
    z = source_max.z
    tiers = [
        ("brick_base", sx * 1.08, sy * 1.08, 12.0, mats["brick"]),
        ("clock_stage", sx * 0.94, sy * 0.94, 7.0, mats["trim"]),
        ("belfry_stage", sx * 0.74, sy * 0.74, 8.0, mats["trim"]),
        ("green_cupola", sx * 0.58, sy * 0.58, 3.2, mats["roof"]),
        ("lantern", sx * 0.34, sy * 0.34, 4.0, mats["trim"]),
    ]
    for name, w, d, h, mat in tiers:
        details.append(box(f"{DETAIL_PREFIX}{name}", parent, collection, Vector((center.x, center.y, z + h / 2)), (w, d, h), mat, "tower", "references/south.jpg"))
        z += h
    for side, dx, dy, scale in [
        ("south", 0, -sy * 0.48, (sx * 0.34, 0.08, sx * 0.34)),
        ("north", 0, sy * 0.48, (sx * 0.34, 0.08, sx * 0.34)),
        ("east", sx * 0.48, 0, (0.08, sy * 0.34, sy * 0.34)),
        ("west", -sx * 0.48, 0, (0.08, sy * 0.34, sy * 0.34)),
    ]:
        details.append(box(f"{DETAIL_PREFIX}clock_{side}", parent, collection, Vector((center.x + dx, center.y + dy, max_v.z + 15.5)), scale, mats["clock"], "clock_face", "references/south.jpg"))
    spire_h = 12.0
    details.append(box(f"{DETAIL_PREFIX}spire_mast", parent, collection, Vector((center.x, center.y, z + spire_h / 2)), (0.38, 0.38, spire_h), mats["black"], "spire", "references/south.jpg"))
    details.append(box(f"{DETAIL_PREFIX}weathervane_hint", parent, collection, Vector((center.x, center.y, z + spire_h + 0.35)), (sx * 0.46, 0.08, 0.08), mats["black"], "weathervane", "references/south.jpg"))
    return details


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = bpy.data.objects.get(BAKER_NAME)
    if parent is None:
        raise SystemExit(f"Missing {BAKER_NAME}")

    mats = ensure_materials()
    rules = load_modeling_rules()
    remove_old_details(parent)
    reset_parent_to_source_mesh(parent)
    rebuild_baker_mesh(parent, mats, rules)
    collection = ensure_collection("Baker Library Integrated Details")
    tower_details = add_tower(parent, collection, mats)
    validate_modeling_rules(parent, rules)
    parent["mwrld_generated_detail_count"] = len(tower_details)
    parent["mwrld_detail_recipe"] = "baker_integrated_facades_v1"

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Integrated Baker facade mesh. Tower details: {len(tower_details)}")


if __name__ == "__main__":
    main()
