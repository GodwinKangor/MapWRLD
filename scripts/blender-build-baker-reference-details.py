import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
BAKER_NAME = "building__baker-library__way_295888783"
DETAIL_PREFIX = "mwrld_refdetail__baker-library__"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return re.sub(r"-+", "-", value).strip("-") or "unnamed"


def material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def ensure_materials():
    return {
        "brick": material("mwrld_baker_reference_brick", (0.42, 0.16, 0.11, 1)),
        "trim": material("mwrld_baker_reference_limestone", (0.80, 0.78, 0.69, 1)),
        "roof": material("mwrld_baker_reference_green_roof", (0.22, 0.46, 0.36, 1)),
        "glass": material("mwrld_baker_reference_dark_window", (0.04, 0.055, 0.06, 1)),
        "door": material("mwrld_baker_reference_white_door", (0.86, 0.84, 0.78, 1)),
        "clock": material("mwrld_baker_reference_clock_face", (0.92, 0.89, 0.78, 1)),
        "black": material("mwrld_baker_reference_black_metal", (0.03, 0.03, 0.03, 1)),
    }


def ensure_collection(name):
    collection = bpy.data.collections.get(name)
    if collection is None:
        collection = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(collection)
    return collection


def local_bounds(obj):
    coords = [vertex.co.copy() for vertex in obj.data.vertices]
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def remove_existing(parent):
    target = parent.get("mwrld_osm_id", parent.name)
    for obj in list(bpy.data.objects):
        if obj.get("mwrld_detail_for") == target and obj.name.startswith(DETAIL_PREFIX):
            bpy.data.objects.remove(obj, do_unlink=True)


def link_parent(obj, parent, collection, kind, source):
    collection.objects.link(obj)
    world = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world
    obj["mwrld_generated_detail"] = True
    obj["mwrld_reference_driven"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    obj["mwrld_detail_kind"] = kind
    obj["mwrld_reference_source"] = source
    return obj


def box(name, parent, collection, local_center, size, mat, kind, source):
    bpy.ops.mesh.primitive_cube_add(size=1, location=parent.matrix_world @ local_center)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    obj.dimensions = size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    return link_parent(obj, parent, collection, kind, source)


def plane_panel(name, parent, collection, side, min_v, max_v, along, z, width, height, depth, mat, kind, source):
    if side in {"south", "north"}:
        x = min_v.x + along * (max_v.x - min_v.x)
        y = min_v.y - depth if side == "south" else max_v.y + depth
        size = (width, depth, height)
        loc = Vector((x, y, z))
    else:
        x = min_v.x - depth if side == "west" else max_v.x + depth
        y = min_v.y + along * (max_v.y - min_v.y)
        size = (depth, width, height)
        loc = Vector((x, y, z))
    return box(name, parent, collection, loc, size, mat, kind, source)


def add_floor_windows(parent, collection, min_v, max_v, mats, side, wall_id, columns, floors, x_start=0.1, x_end=0.9):
    made = []
    usable = x_end - x_start
    for floor in range(floors):
        z = min_v.z + 3.1 + floor * 5.05
        if z > max_v.z - 2:
            continue
        for col in range(columns):
            along = x_start + usable * ((col + 1) / (columns + 1))
            made.append(
                plane_panel(
                    f"{DETAIL_PREFIX}{wall_id}__window_f{floor + 1}_c{col + 1}",
                    parent,
                    collection,
                    side,
                    min_v,
                    max_v,
                    along,
                    z,
                    2.2,
                    2.8,
                    0.08,
                    mats["glass"],
                    "window_panel",
                    f"references/walls/{wall_id}.jpg",
                )
            )
            made.append(
                plane_panel(
                    f"{DETAIL_PREFIX}{wall_id}__window_trim_f{floor + 1}_c{col + 1}",
                    parent,
                    collection,
                    side,
                    min_v,
                    max_v,
                    along,
                    z,
                    2.55,
                    3.15,
                    0.04,
                    mats["trim"],
                    "window_trim",
                    f"references/walls/{wall_id}.jpg",
                )
            )
    return made


def add_reference_facades(parent, collection, min_v, max_v, mats):
    details = []
    details += add_floor_windows(parent, collection, min_v, max_v, mats, "south", "wall-02", 5, 3, 0.18, 0.82)
    details += add_floor_windows(parent, collection, min_v, max_v, mats, "east", "wall-03", 4, 3, 0.20, 0.82)
    details += add_floor_windows(parent, collection, min_v, max_v, mats, "west", "wall-14", 4, 3, 0.18, 0.80)

    center_door = plane_panel(
        f"{DETAIL_PREFIX}wall-02__south_arched_entry_door",
        parent,
        collection,
        "south",
        min_v,
        max_v,
        0.50,
        min_v.z + 2.4,
        4.1,
        4.8,
        0.14,
        mats["door"],
        "door_panel",
        "references/south.jpg",
    )
    details.append(center_door)
    details.append(
        plane_panel(
            f"{DETAIL_PREFIX}wall-02__south_entry_trim",
            parent,
            collection,
            "south",
            min_v,
            max_v,
            0.50,
            min_v.z + 3.15,
            5.0,
            6.4,
            0.09,
            mats["trim"],
            "door_trim",
            "references/south.jpg",
        )
    )
    return details


def add_roof_bands(parent, collection, min_v, max_v, mats):
    details = []
    roof_z = max_v.z + 0.22
    x_span = max_v.x - min_v.x
    y_span = max_v.y - min_v.y
    details.append(
        box(
            f"{DETAIL_PREFIX}green_roof_south_band",
            parent,
            collection,
            Vector(((min_v.x + max_v.x) / 2, min_v.y + y_span * 0.18, roof_z)),
            (x_span * 0.88, y_span * 0.12, 0.42),
            mats["roof"],
            "roof_band",
            "references/roof-satellite.jpg",
        )
    )
    details.append(
        box(
            f"{DETAIL_PREFIX}green_roof_north_band",
            parent,
            collection,
            Vector(((min_v.x + max_v.x) / 2, max_v.y - y_span * 0.18, roof_z)),
            (x_span * 0.86, y_span * 0.12, 0.42),
            mats["roof"],
            "roof_band",
            "references/roof-satellite.jpg",
        )
    )
    details.append(
        box(
            f"{DETAIL_PREFIX}stone_roof_edge_front",
            parent,
            collection,
            Vector(((min_v.x + max_v.x) / 2, min_v.y - 0.38, max_v.z + 0.48)),
            (x_span * 0.92, 0.75, 0.72),
            mats["trim"],
            "roof_edge",
            "references/south.jpg",
        )
    )
    return details


def add_clock_face(parent, collection, center, side, sx, sy, z, mats):
    if side in {"south", "north"}:
        y = center.y - sy / 2 - 0.12 if side == "south" else center.y + sy / 2 + 0.12
        loc = Vector((center.x, y, z))
        size = (sx * 0.36, 0.10, sx * 0.36)
    else:
        x = center.x - sx / 2 - 0.12 if side == "west" else center.x + sx / 2 + 0.12
        loc = Vector((x, center.y, z))
        size = (0.10, sy * 0.36, sy * 0.36)
    return box(
        f"{DETAIL_PREFIX}tower_clock_{side}",
        parent,
        collection,
        loc,
        size,
        mats["clock"],
        "clock_face",
        "references/south.jpg",
    )


def add_tower(parent, collection, min_v, max_v, mats):
    details = []
    x_span = max_v.x - min_v.x
    y_span = max_v.y - min_v.y
    tower_center = Vector(((min_v.x + max_v.x) / 2, min_v.y + y_span * 0.34, max_v.z))
    sx = x_span * 0.17
    sy = y_span * 0.16
    tiers = [
        ("brick_tower_base", sx * 1.10, sy * 1.10, 12.0, mats["brick"]),
        ("white_clock_stage", sx * 0.94, sy * 0.94, 7.0, mats["trim"]),
        ("open_belfry_stage", sx * 0.72, sy * 0.72, 8.0, mats["trim"]),
        ("green_cupola", sx * 0.58, sy * 0.58, 3.2, mats["roof"]),
        ("lantern", sx * 0.36, sy * 0.36, 4.4, mats["trim"]),
    ]
    z = max_v.z
    for name, w, d, h, mat in tiers:
        details.append(
            box(
                f"{DETAIL_PREFIX}tower__{name}",
                parent,
                collection,
                Vector((tower_center.x, tower_center.y, z + h / 2)),
                (w, d, h),
                mat,
                "tower_mass",
                "references/south.jpg",
            )
        )
        z += h

    clock_z = max_v.z + 15.5
    for side in ["south", "north", "east", "west"]:
        details.append(add_clock_face(parent, collection, tower_center, side, sx * 0.94, sy * 0.94, clock_z, mats))

    belfry_z = max_v.z + 23.0
    for side in ["south", "north"]:
        for shift in [-0.26, 0.0, 0.26]:
            details.append(
                box(
                    f"{DETAIL_PREFIX}tower_belfry_{side}_{int((shift + 0.26) * 100):02d}",
                    parent,
                    collection,
                    Vector((tower_center.x + shift * sx, tower_center.y + (-sy * 0.37 if side == "south" else sy * 0.37), belfry_z)),
                    (sx * 0.14, 0.11, 4.8),
                    mats["glass"],
                    "belfry_opening",
                    "references/south.jpg",
                )
            )

    spire_h = 12.0
    details.append(
        box(
            f"{DETAIL_PREFIX}tower_spire_mast",
            parent,
            collection,
            Vector((tower_center.x, tower_center.y, z + spire_h / 2)),
            (0.42, 0.42, spire_h),
            mats["black"],
            "spire",
            "references/south.jpg",
        )
    )
    details.append(
        box(
            f"{DETAIL_PREFIX}tower_weathervane_hint",
            parent,
            collection,
            Vector((tower_center.x, tower_center.y, z + spire_h + 0.4)),
            (sx * 0.46, 0.10, 0.10),
            mats["black"],
            "weathervane",
            "references/south.jpg",
        )
    )
    return details


def approve_reference_manifest():
    manifest_path = MODEL_DIR / "renders" / "buildings" / BAKER_NAME / "references" / "references-manifest.json"
    if not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    approvals = manifest.setdefault("approvedForModeling", {})
    approvals["roof"] = True
    approvals["south"] = True
    approvals["east"] = True
    approvals["west"] = True
    wall_approvals = approvals.setdefault("walls", {})
    for wall in manifest.get("walls", []):
        status = wall.get("linkReview", {}).get("status", "")
        approved = status == "linked-partial"
        wall["approvedForModeling"] = approved
        wall_approvals[wall["id"]] = approved
    approvals["north"] = False
    manifest["modelingApproval"] = {
        "approvedAt": "2026-08-19",
        "approvedBy": "user",
        "scope": "Exterior-only Baker identity scaffold. Rejected/detail-only/needs-verify walls remain blocked.",
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = bpy.data.objects.get(BAKER_NAME)
    if parent is None:
        raise SystemExit(f"Missing Baker object: {BAKER_NAME}")

    mats = ensure_materials()
    parent.data.materials.clear()
    parent.data.materials.append(mats["brick"])
    remove_existing(parent)
    collection = ensure_collection("Baker Library Reference Details")
    min_v, max_v = local_bounds(parent)

    details = []
    details += add_roof_bands(parent, collection, min_v, max_v, mats)
    details += add_reference_facades(parent, collection, min_v, max_v, mats)
    details += add_tower(parent, collection, min_v, max_v, mats)

    parent["mwrld_generated_detail_count"] = len(details)
    parent["mwrld_detail_recipe"] = "baker_reference_scaffold_v1"
    parent["mwrld_reference_detail_scope"] = "non_destructive_exterior_only"
    approve_reference_manifest()

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Built Baker reference details: {len(details)} objects")
    print("Base mesh unchanged: details are separate child objects")


if __name__ == "__main__":
    main()
