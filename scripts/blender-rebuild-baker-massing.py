import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
DETAIL_PREFIX = "mwrld_detail__baker-library__"
BAKER_NAME = "building__baker-library__way_295888783"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def ensure_material(name, color):
    material = bpy.data.materials.get(name)
    if not material:
        material = bpy.data.materials.new(name)
    material.diffuse_color = color
    return material


def local_bounds(obj):
    vertices = [vertex.co.copy() for vertex in obj.data.vertices]
    return (
        Vector((min(v.x for v in vertices), min(v.y for v in vertices), min(v.z for v in vertices))),
        Vector((max(v.x for v in vertices), max(v.y for v in vertices), max(v.z for v in vertices))),
    )


def box_vertices(center, size):
    cx, cy, cz = center
    sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
    return [
        (cx - sx, cy - sy, cz - sz),
        (cx + sx, cy - sy, cz - sz),
        (cx + sx, cy + sy, cz - sz),
        (cx - sx, cy + sy, cz - sz),
        (cx - sx, cy - sy, cz + sz),
        (cx + sx, cy - sy, cz + sz),
        (cx + sx, cy + sy, cz + sz),
        (cx - sx, cy + sy, cz + sz),
    ]


def append_box(vertices, faces, material_indices, center, size, material_index):
    start = len(vertices)
    vertices.extend(box_vertices(center, size))
    faces.extend(
        [
            (start + 0, start + 1, start + 2, start + 3),
            (start + 4, start + 7, start + 6, start + 5),
            (start + 0, start + 4, start + 5, start + 1),
            (start + 1, start + 5, start + 6, start + 2),
            (start + 2, start + 6, start + 7, start + 3),
            (start + 3, start + 7, start + 4, start + 0),
        ]
    )
    material_indices.extend([material_index] * 6)


def rebuild_base_mesh(obj):
    min_v, max_v = local_bounds(obj)
    width = max_v.x - min_v.x
    depth = max_v.y - min_v.y
    cx = (min_v.x + max_v.x) / 2
    cy = (min_v.y + max_v.y) / 2
    z0 = min_v.z

    brick = ensure_material("mwrld_baker_brick", (0.42, 0.17, 0.12, 1))
    trim = ensure_material("mwrld_baker_limestone_trim", (0.78, 0.76, 0.68, 1))
    roof = ensure_material("mwrld_baker_green_roof", (0.24, 0.48, 0.38, 1))

    obj.data.materials.clear()
    for material in (brick, trim, roof):
        obj.data.materials.append(material)

    vertices = []
    faces = []
    material_indices = []

    front_y = min_v.y + depth * 0.18
    rear_y = max_v.y - depth * 0.12
    mid_y = cy + depth * 0.04
    low_h = 12.5
    main_h = 15.5
    tower_bay_h = 27.0

    blocks = [
        ((cx, front_y, z0 + main_h / 2), (width * 0.92, depth * 0.23, main_h), 0),
        ((cx, rear_y, z0 + low_h / 2), (width * 0.88, depth * 0.18, low_h), 0),
        ((min_v.x + width * 0.12, mid_y, z0 + low_h / 2), (width * 0.22, depth * 0.62, low_h), 0),
        ((max_v.x - width * 0.12, mid_y, z0 + low_h / 2), (width * 0.22, depth * 0.62, low_h), 0),
        ((cx, cy, z0 + main_h / 2), (width * 0.22, depth * 0.72, main_h), 0),
        ((cx, front_y - depth * 0.04, z0 + tower_bay_h / 2), (width * 0.19, depth * 0.20, tower_bay_h), 0),
    ]
    for center, size, material_index in blocks:
        append_box(vertices, faces, material_indices, center, size, material_index)

    belt_h = 0.7
    append_box(vertices, faces, material_indices, (cx, front_y - depth * 0.04, z0 + tower_bay_h + belt_h / 2), (width * 0.23, depth * 0.22, belt_h), 1)
    append_box(vertices, faces, material_indices, (cx, z0 + 0 + rear_y, z0 + low_h + 0.35), (width * 0.90, depth * 0.20, 0.7), 2)
    append_box(vertices, faces, material_indices, (cx, front_y, z0 + main_h + 0.35), (width * 0.94, depth * 0.25, 0.7), 2)
    append_box(vertices, faces, material_indices, (min_v.x + width * 0.12, mid_y, z0 + low_h + 0.35), (width * 0.24, depth * 0.64, 0.7), 2)
    append_box(vertices, faces, material_indices, (max_v.x - width * 0.12, mid_y, z0 + low_h + 0.35), (width * 0.24, depth * 0.64, 0.7), 2)

    mesh = bpy.data.meshes.new(f"{BAKER_NAME}_massing_mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    for index, polygon in enumerate(mesh.polygons):
        polygon.material_index = material_indices[index]
    old_mesh = obj.data
    obj.data = mesh
    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    obj["mwrld_baker_massing_rebuilt"] = True
    return {
        "min": min_v,
        "max": max_v,
        "center": Vector((cx, front_y - depth * 0.04, z0 + tower_bay_h)),
        "width": width,
        "depth": depth,
        "tower_bay_height": tower_bay_h,
    }


def create_detail_box(name, parent, local_center, size, material, kind, collection):
    world_center = parent.matrix_world @ local_center
    bpy.ops.mesh.primitive_cube_add(size=1, location=world_center)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = f"{name}_mesh"
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(material)
    world_before = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world_before
    obj["mwrld_generated_detail"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    obj["mwrld_detail_kind"] = kind
    collection.objects.link(obj)
    return obj


def ensure_collection(name):
    collection = bpy.data.collections.get(name)
    if collection:
        return collection
    collection = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(collection)
    return collection


def backup_current_baker(parent):
    backup_collection = ensure_collection("MWRLD Backups - Baker Library")
    target_id = parent.get("mwrld_osm_id", parent.name)
    backup_index = len([obj for obj in backup_collection.objects if obj.name.startswith("backup__baker-library")]) + 1
    objects = [parent] + [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_detail_for") == target_id
    ]
    for obj in objects:
        clone = obj.copy()
        clone.data = obj.data.copy()
        clone.name = f"backup__baker-library__{backup_index:02d}__{obj.name}"
        clone.data.name = f"{clone.name}_mesh"
        clone.hide_viewport = True
        clone.hide_render = True
        clone["mwrld_backup_of"] = obj.name
        clone["mwrld_backup_reason"] = "before Baker reference massing rebuild"
        if "mwrld_detail_for" in clone:
            del clone["mwrld_detail_for"]
        clone["mwrld_category"] = "backup"
        backup_collection.objects.link(clone)
    return len(objects)


def remove_existing_details(parent):
    target_id = parent.get("mwrld_osm_id", parent.name)
    for obj in list(bpy.data.objects):
        if obj.get("mwrld_backup_of"):
            continue
        if obj.get("mwrld_detail_for") == target_id:
            bpy.data.objects.remove(obj, do_unlink=True)


def add_baker_tower(parent, massing):
    collection = ensure_collection("Baker Library Rebuilt Exterior Details")
    brick = ensure_material("mwrld_baker_brick", (0.42, 0.17, 0.12, 1))
    trim = ensure_material("mwrld_baker_limestone_trim", (0.78, 0.76, 0.68, 1))
    copper = ensure_material("mwrld_baker_green_roof", (0.24, 0.48, 0.38, 1))
    dark = ensure_material("mwrld_baker_dark_openings", (0.06, 0.07, 0.07, 1))
    clock = ensure_material("mwrld_baker_clock_face", (0.92, 0.90, 0.82, 1))

    center = massing["center"]
    width = massing["width"]
    depth = massing["depth"]
    z = center.z
    tower_w = width * 0.145
    tower_d = depth * 0.14
    details = []

    tiers = [
        ("clock_base", tower_w * 1.02, tower_d * 1.02, 7.0, trim, "tower"),
        ("clock_stage", tower_w * 0.86, tower_d * 0.86, 7.0, trim, "tower"),
        ("belfry", tower_w * 0.70, tower_d * 0.70, 8.0, trim, "tower"),
        ("cupola", tower_w * 0.58, tower_d * 0.58, 3.0, copper, "roof"),
        ("lantern", tower_w * 0.34, tower_d * 0.34, 5.2, trim, "tower"),
    ]
    for name, sx, sy, sz, material, kind in tiers:
        z += sz / 2
        details.append(create_detail_box(f"{DETAIL_PREFIX}{name}", parent, Vector((center.x, center.y, z)), (sx, sy, sz), material, kind, collection))
        z += sz / 2

    for side, dy, heading in (("south", -tower_d / 2 - 0.05, 0), ("north", tower_d / 2 + 0.05, 180)):
        details.append(create_detail_box(f"{DETAIL_PREFIX}clock_{side}", parent, Vector((center.x, center.y + dy, center.z + 11.0)), (tower_w * 0.42, 0.12, tower_w * 0.42), clock, "clock", collection))
    for side, dx in (("east", tower_w / 2 + 0.05), ("west", -tower_w / 2 - 0.05)):
        details.append(create_detail_box(f"{DETAIL_PREFIX}louver_{side}_upper", parent, Vector((center.x + dx, center.y, center.z + 20.5)), (0.12, tower_d * 0.42, 4.0), dark, "louver", collection))
    for side, dy in (("south", -tower_d / 2 - 0.06), ("north", tower_d / 2 + 0.06)):
        details.append(create_detail_box(f"{DETAIL_PREFIX}louver_{side}_upper", parent, Vector((center.x, center.y + dy, center.z + 20.5)), (tower_w * 0.42, 0.12, 4.0), dark, "louver", collection))

    spire_h = 17.0
    details.append(create_detail_box(f"{DETAIL_PREFIX}spire_mast", parent, Vector((center.x, center.y, z + spire_h / 2)), (0.45, 0.45, spire_h), copper, "spire", collection))
    details.append(create_detail_box(f"{DETAIL_PREFIX}weathervane_cross", parent, Vector((center.x, center.y, z + spire_h + 0.5)), (tower_w * 0.52, 0.12, 0.12), dark, "spire", collection))
    parent["mwrld_generated_detail_count"] = len(details)
    parent["mwrld_detail_recipe"] = "baker_reference_massing_v1"
    return details


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = bpy.data.objects.get(BAKER_NAME)
    if not parent:
        raise SystemExit(f"Missing {BAKER_NAME}")

    backup_count = backup_current_baker(parent)
    remove_existing_details(parent)
    massing = rebuild_base_mesh(parent)
    details = add_baker_tower(parent, massing)

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Backed up {backup_count} Baker objects.")
    print(f"Rebuilt Baker massing. Detail objects: {len(details)}.")


if __name__ == "__main__":
    main()
