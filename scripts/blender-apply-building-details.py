import json
import math
import re
import sys
from copy import deepcopy
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
RECIPE_PATH = MODEL_DIR / "reports" / "building-detail-recipes.json"
REPORT_PATH = MODEL_DIR / "reports" / "building-detail-report.json"
DETAIL_PREFIX = "mwrld_detail__"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "unnamed"


def deep_merge(base, override):
    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def ensure_collection(name, parent=None):
    collection = bpy.data.collections.get(name)
    if collection:
        return collection
    collection = bpy.data.collections.new(name)
    if parent:
        parent.children.link(collection)
    else:
        bpy.context.scene.collection.children.link(collection)
    return collection


def link_to_collection(obj, collection):
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def ensure_material(name, color):
    material = bpy.data.materials.get(name)
    if not material:
        material = bpy.data.materials.new(name)
        material.diffuse_color = color
    return material


MATERIALS = {}


def material(name):
    if not MATERIALS:
        MATERIALS.update(
            {
                "glass": ensure_material("mwrld_window_dark_glass", (0.06, 0.09, 0.11, 1)),
                "door": ensure_material("mwrld_door_warm_gray", (0.19, 0.16, 0.13, 1)),
                "roof": ensure_material("mwrld_roof_slate", (0.20, 0.22, 0.23, 1)),
                "copper": ensure_material("mwrld_aged_copper_roof", (0.28, 0.50, 0.42, 1)),
                "parapet": ensure_material("mwrld_parapet_stone", (0.62, 0.59, 0.52, 1)),
                "tower": ensure_material("mwrld_tower_white_trim", (0.86, 0.86, 0.80, 1)),
                "chimney": ensure_material("mwrld_chimney_brick", (0.40, 0.16, 0.12, 1)),
                "clock": ensure_material("mwrld_clock_face", (0.92, 0.90, 0.84, 1)),
                "clockHand": ensure_material("mwrld_clock_hands", (0.08, 0.07, 0.07, 1)),
                "trim": ensure_material("mwrld_facade_trim", (0.78, 0.75, 0.67, 1)),
            }
        )
    return MATERIALS[name]


def local_bounds(obj):
    vertices = [vertex.co.copy() for vertex in obj.data.vertices]
    min_v = Vector((min(v.x for v in vertices), min(v.y for v in vertices), min(v.z for v in vertices)))
    max_v = Vector((max(v.x for v in vertices), max(v.y for v in vertices), max(v.z for v in vertices)))
    return min_v, max_v


def object_matches(obj, query):
    haystack = " ".join(
        [
            obj.name,
            obj.get("mwrld_name", ""),
            obj.get("mwrld_osm_id", ""),
            obj.get("mwrld_osm_way_id", ""),
        ]
    ).lower()
    return query.lower() in haystack


def target_buildings(query):
    buildings = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_category") == "building" and obj.get("mwrld_osm_id")
    ]
    if query == "all":
        return sorted(buildings, key=lambda obj: obj.name.lower())
    matches = [obj for obj in buildings if object_matches(obj, query)]
    if not matches:
        raise SystemExit(f"No named building matched: {query}")
    return sorted(matches, key=lambda obj: obj.name.lower())


def has_explicit_recipe(obj, recipes):
    slug = slugify(obj.get("mwrld_name", obj.name))
    return slug in recipes.get("buildings", {})


def recipe_for(obj, recipes):
    slug = slugify(obj.get("mwrld_name", obj.name))
    return deep_merge(recipes.get("defaults", {}), recipes.get("buildings", {}).get(slug, {}))


def building_folder_name(obj):
    name = obj.name.split(".", 1)[0]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def reference_manifest_for(obj):
    reference_path = MODEL_DIR / "renders" / "buildings" / building_folder_name(obj) / "references" / "references-manifest.json"
    if not reference_path.exists():
        return None
    return json.loads(reference_path.read_text(encoding="utf-8"))


def facades_requiring_reference(recipe):
    requirements = []
    for side, spec in recipe.get("facades", {}).items():
        window_columns = int(spec.get("windowColumns", 0))
        floors = int(spec.get("floors", 0))
        door_count = int(spec.get("doors", 0))
        if (window_columns > 0 and floors > 0) or door_count > 0:
            wall_ids = spec.get("referenceWallIds", [])
            if wall_ids:
                requirements.extend([{"type": "wall", "id": wall_id} for wall_id in wall_ids])
            else:
                requirements.append({"type": "side", "id": side})
    return requirements


def reference_gate_failures(obj, recipe):
    needs = []
    roof = recipe.get("roof", {})
    if roof.get("type", "flat") != "none" or roof.get("parapet"):
        needs.append("roof")
    if int(recipe.get("chimneys", 0)) > 0:
        needs.append("roof")
    facade_needs = facades_requiring_reference(recipe)
    if not needs and not facade_needs:
        return []

    references = reference_manifest_for(obj)
    if not references:
        needed = needs + [item["id"] for item in facade_needs]
        return [f"missing references-manifest.json for {', '.join(sorted(set(needed)))}"]

    approvals = references.get("approvedForModeling", {})
    failures = []
    for item in sorted(set(needs)):
        if not approvals.get(item):
            failures.append(f"{item} reference is not approvedForModeling")
    wall_approvals = approvals.get("walls", {})
    reviewed_walls = {wall.get("id"): wall for wall in references.get("walls", [])}
    for item in facade_needs:
        if item["type"] == "wall":
            if not wall_approvals.get(item["id"]):
                failures.append(f"{item['id']} wall reference is not approvedForModeling")
            wall_review = reviewed_walls.get(item["id"], {}).get("linkReview", {})
            if not wall_review.get("status", "").startswith("linked"):
                failures.append(f"{item['id']} wall reference is not visually linked to an exterior face")
        elif not approvals.get(item["id"]):
            failures.append(f"{item['id']} reference is not approvedForModeling")
    return failures


def remove_existing_details(obj):
    target_id = obj.get("mwrld_osm_id", obj.name)
    for detail in list(bpy.data.objects):
        if detail.get("mwrld_detail_for") == target_id:
            bpy.data.objects.remove(detail, do_unlink=True)


def create_box(name, location, scale, mat, parent, collection):
    bpy.ops.mesh.primitive_cube_add(size=1, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    obj.data.materials.append(mat)
    world_before = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world_before
    obj["mwrld_generated_detail"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    link_to_collection(obj, collection)
    return obj


def create_recess_panel(name, parent, side, local, width, height, depth, mat, collection):
    if side == "north":
        location = Vector((local.x, local.y - depth / 2, local.z))
        scale = (width, depth, height)
    elif side == "south":
        location = Vector((local.x, local.y + depth / 2, local.z))
        scale = (width, depth, height)
    elif side == "east":
        location = Vector((local.x - depth / 2, local.y, local.z))
        scale = (depth, width, height)
    else:
        location = Vector((local.x + depth / 2, local.y, local.z))
        scale = (depth, width, height)

    obj = create_box(name, parent.matrix_world @ location, scale, mat, parent, collection)
    obj["mwrld_detail_surface"] = "inset"
    obj["mwrld_wall_side"] = side
    return obj


def create_world_box(name, parent, world_location, scale, mat, collection, kind):
    obj = create_box(name, world_location, scale, mat, parent, collection)
    obj["mwrld_detail_kind"] = kind
    return obj


def create_roof_mesh(name, parent, min_v, max_v, recipe, collection):
    roof = recipe.get("roof", {})
    roof_type = roof.get("type", "flat")
    if roof_type == "none":
        return []
    overhang = float(roof.get("overhang", 1.0))
    height = max((max_v.z - min_v.z) * float(roof.get("heightRatio", 0.16)), 1.2)

    x0, x1 = min_v.x - overhang, max_v.x + overhang
    y0, y1 = min_v.y - overhang, max_v.y + overhang
    z = max_v.z + 0.06

    if roof_type == "flat":
        roof_obj = create_box(
            f"{DETAIL_PREFIX}{slugify(parent.get('mwrld_name', parent.name))}__flat_roof",
            parent.matrix_world @ Vector(((x0 + x1) / 2, (y0 + y1) / 2, z + 0.18)),
            (x1 - x0, y1 - y0, 0.36),
            material("roof"),
            parent,
            collection,
        )
        roof_obj["mwrld_detail_kind"] = "roof"
        return [roof_obj]

    if roof_type == "gable":
        ridge_along_x = (max_v.x - min_v.x) >= (max_v.y - min_v.y)
        if ridge_along_x:
            verts = [
                parent.matrix_world @ Vector((x0, y0, z)),
                parent.matrix_world @ Vector((x1, y0, z)),
                parent.matrix_world @ Vector((x1, y1, z)),
                parent.matrix_world @ Vector((x0, y1, z)),
                parent.matrix_world @ Vector((x0, (y0 + y1) / 2, z + height)),
                parent.matrix_world @ Vector((x1, (y0 + y1) / 2, z + height)),
            ]
            faces = [(0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5)]
        else:
            verts = [
                parent.matrix_world @ Vector((x0, y0, z)),
                parent.matrix_world @ Vector((x1, y0, z)),
                parent.matrix_world @ Vector((x1, y1, z)),
                parent.matrix_world @ Vector((x0, y1, z)),
                parent.matrix_world @ Vector(((x0 + x1) / 2, y0, z + height)),
                parent.matrix_world @ Vector(((x0 + x1) / 2, y1, z + height)),
            ]
            faces = [(0, 4, 5, 3), (1, 2, 5, 4), (0, 1, 4), (3, 5, 2)]
        mesh = bpy.data.meshes.new(f"{name}_mesh")
        mesh.from_pydata([tuple(v) for v in verts], [], faces)
        mesh.update()
        obj = bpy.data.objects.new(name, mesh)
        obj.data.materials.append(material("copper"))
        world_before = obj.matrix_world.copy()
        obj.parent = parent
        obj.matrix_parent_inverse = parent.matrix_world.inverted()
        obj.matrix_world = world_before
        obj["mwrld_generated_detail"] = True
        obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
        obj["mwrld_detail_kind"] = "roof"
        link_to_collection(obj, collection)
        return [obj]

    center = Vector(((x0 + x1) / 2, (y0 + y1) / 2, z + height))
    verts = [
        parent.matrix_world @ Vector((x0, y0, z)),
        parent.matrix_world @ Vector((x1, y0, z)),
        parent.matrix_world @ Vector((x1, y1, z)),
        parent.matrix_world @ Vector((x0, y1, z)),
        parent.matrix_world @ center,
    ]
    faces = [(0, 1, 4), (1, 2, 4), (2, 3, 4), (3, 0, 4), (0, 3, 2, 1)]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata([tuple(v) for v in verts], [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    obj.data.materials.append(material("roof"))
    world_before = obj.matrix_world.copy()
    obj.parent = parent
    obj.matrix_parent_inverse = parent.matrix_world.inverted()
    obj.matrix_world = world_before
    obj["mwrld_generated_detail"] = True
    obj["mwrld_detail_for"] = parent.get("mwrld_osm_id", parent.name)
    obj["mwrld_detail_kind"] = "roof"
    link_to_collection(obj, collection)
    return [obj]


def add_parapet(parent, min_v, max_v, collection):
    slug = slugify(parent.get("mwrld_name", parent.name))
    z = max_v.z + 0.55
    thickness = 0.65
    height = 1.1
    pieces = [
        ("north", Vector(((min_v.x + max_v.x) / 2, max_v.y + thickness / 2, z)), (max_v.x - min_v.x + thickness * 2, thickness, height)),
        ("south", Vector(((min_v.x + max_v.x) / 2, min_v.y - thickness / 2, z)), (max_v.x - min_v.x + thickness * 2, thickness, height)),
        ("east", Vector((max_v.x + thickness / 2, (min_v.y + max_v.y) / 2, z)), (thickness, max_v.y - min_v.y, height)),
        ("west", Vector((min_v.x - thickness / 2, (min_v.y + max_v.y) / 2, z)), (thickness, max_v.y - min_v.y, height)),
    ]
    details = []
    for side, local, scale in pieces:
        obj = create_box(
            f"{DETAIL_PREFIX}{slug}__parapet_{side}",
            parent.matrix_world @ local,
            scale,
            material("parapet"),
            parent,
            collection,
        )
        obj["mwrld_detail_kind"] = "parapet"
        details.append(obj)
    return details


def auto_count(span, target_spacing, minimum=2, maximum=14):
    return max(minimum, min(maximum, int(span / target_spacing)))


def facade_layout(side, min_v, max_v, spec):
    windows = spec.get("windows", {})
    span_x = max_v.x - min_v.x
    span_y = max_v.y - min_v.y
    height = max_v.z - min_v.z
    horizontal_span = span_x if side in {"north", "south"} else span_y
    columns = windows.get("columns", "auto")
    floors = windows.get("floors", "auto")
    if columns == "auto":
        columns = auto_count(horizontal_span, 8.0)
    if floors == "auto":
        floors = max(1, min(5, int(height / 5.2)))
    return int(columns), int(floors)


def facade_position(side, min_v, max_v, along_ratio, z):
    x = min_v.x + along_ratio * (max_v.x - min_v.x)
    y = min_v.y + along_ratio * (max_v.y - min_v.y)
    if side == "north":
        return Vector((x, max_v.y, z))
    if side == "south":
        return Vector((x, min_v.y, z))
    if side == "east":
        return Vector((max_v.x, y, z))
    return Vector((min_v.x, y, z))


def add_windows(parent, min_v, max_v, recipe, collection):
    slug = slugify(parent.get("mwrld_name", parent.name))
    created = []
    for side, spec in recipe.get("facades", {}).items():
        columns, floors = facade_layout(side, min_v, max_v, spec)
        window_spec = spec.get("windows", {})
        width = float(window_spec.get("width", 2.0))
        height = float(window_spec.get("height", 2.6))
        for floor in range(floors):
            z = min_v.z + 3.0 + floor * max(height + 2.1, 4.2)
            if z + height / 2 > max_v.z - 1.2:
                continue
            for col in range(columns):
                along = (col + 1) / (columns + 1)
                local = facade_position(side, min_v, max_v, along, z)
                obj = create_recess_panel(
                    f"{DETAIL_PREFIX}{slug}__window_{side}_{floor + 1}_{col + 1}",
                    parent,
                    side,
                    local,
                    width,
                    height,
                    0.18,
                    material("glass"),
                    collection,
                )
                obj["mwrld_detail_kind"] = "window"
                created.append(obj)
    return created


def add_doors(parent, min_v, max_v, recipe, collection):
    slug = slugify(parent.get("mwrld_name", parent.name))
    created = []
    for side, spec in recipe.get("facades", {}).items():
        door_count = int(spec.get("doors", 0))
        for index in range(door_count):
            along = (index + 1) / (door_count + 1)
            local = facade_position(side, min_v, max_v, along, min_v.z + 2.1)
            obj = create_recess_panel(
                f"{DETAIL_PREFIX}{slug}__door_{side}_{index + 1}",
                parent,
                side,
                local,
                2.6,
                4.2,
                0.26,
                material("door"),
                collection,
            )
            obj["mwrld_detail_kind"] = "door"
            created.append(obj)
    return created


def add_chimneys(parent, min_v, max_v, count, collection):
    slug = slugify(parent.get("mwrld_name", parent.name))
    created = []
    count = int(count or 0)
    for index in range(count):
        ratio = (index + 1) / (count + 1)
        x = min_v.x + ratio * (max_v.x - min_v.x)
        y = min_v.y + (0.72 if index % 2 == 0 else 0.28) * (max_v.y - min_v.y)
        scale = (2.1, 2.1, max(4.0, (max_v.z - min_v.z) * 0.24))
        local = Vector((x, y, max_v.z + scale[2] / 2 + 0.5))
        obj = create_box(
            f"{DETAIL_PREFIX}{slug}__chimney_{index + 1}",
            parent.matrix_world @ local,
            scale,
            material("chimney"),
            parent,
            collection,
        )
        obj["mwrld_detail_kind"] = "chimney"
        created.append(obj)
    return created


def side_panel_world(center, side, offset, width, height, depth):
    if side == "north":
        return center + Vector((0, offset.y + depth / 2, offset.z)), (width, depth, height)
    if side == "south":
        return center + Vector((0, -offset.y - depth / 2, offset.z)), (width, depth, height)
    if side == "east":
        return center + Vector((offset.x + depth / 2, 0, offset.z)), (depth, width, height)
    return center + Vector((-offset.x - depth / 2, 0, offset.z)), (depth, width, height)


def add_clock_face(parent, slug, collection, center, side, half_width, half_depth, z_offset, size):
    local, scale = side_panel_world(center, side, Vector((half_width, half_depth, z_offset)), size, size, 0.12)
    face = create_world_box(
        f"{DETAIL_PREFIX}{slug}__clock_{side}",
        parent,
        parent.matrix_world @ local,
        scale,
        material("clock"),
        collection,
        "clock",
    )
    hand_z = z_offset
    vertical, v_scale = side_panel_world(center, side, Vector((half_width, half_depth, hand_z)), 0.16, size * 0.72, 0.16)
    horizontal, h_scale = side_panel_world(center, side, Vector((half_width, half_depth, hand_z)), size * 0.56, 0.14, 0.18)
    for name, loc, hand_scale in (
        ("minute_hand", vertical, v_scale),
        ("hour_hand", horizontal, h_scale),
    ):
        create_world_box(
            f"{DETAIL_PREFIX}{slug}__clock_{side}_{name}",
            parent,
            parent.matrix_world @ loc,
            hand_scale,
            material("clockHand"),
            collection,
            "clock",
        )
    return [face]


def add_louver_openings(parent, slug, collection, center, sides, half_width, half_depth, z_offset, slot_width, slot_height):
    created = []
    for side in sides:
        for index, shift in enumerate((-0.32, 0, 0.32), start=1):
            if side in {"north", "south"}:
                local_offset = Vector((shift * half_width, half_depth, z_offset))
            else:
                local_offset = Vector((half_width, shift * half_depth, z_offset))
            local, scale = side_panel_world(center, side, local_offset, slot_width, slot_height, 0.16)
            created.append(
                create_world_box(
                    f"{DETAIL_PREFIX}{slug}__tower_louver_{side}_{index}",
                    parent,
                    parent.matrix_world @ local,
                    scale,
                    material("glass"),
                    collection,
                    "louver",
                )
            )
    return created


def add_tower(parent, min_v, max_v, recipe, collection):
    tower = recipe.get("tower", {})
    if not tower.get("enabled"):
        return []

    slug = slugify(parent.get("mwrld_name", parent.name))
    width = (max_v.x - min_v.x) * float(tower.get("baseWidthRatio", 0.18))
    depth = (max_v.y - min_v.y) * float(tower.get("baseDepthRatio", 0.2))
    base_height = max_v.z - min_v.z
    tower_height = max(base_height * float(tower.get("heightRatio", 2.0)), 22)
    center = Vector(((min_v.x + max_v.x) / 2, (min_v.y + max_v.y) / 2, max_v.z))
    half_width = width / 2
    half_depth = depth / 2
    created = []

    tiers = [
        ("brick_core", width, depth, tower_height * 0.36, material("chimney")),
        ("clock_stage", width * 0.86, depth * 0.86, tower_height * 0.2, material("tower")),
        ("belfry", width * 0.68, depth * 0.68, tower_height * 0.19, material("tower")),
        ("cupola_base", width * 0.56, depth * 0.56, tower_height * 0.08, material("copper")),
        ("lantern", width * 0.34, depth * 0.34, tower_height * 0.08, material("tower")),
    ]
    z_cursor = 0
    for tier_name, tier_width, tier_depth, tier_height, mat in tiers:
        local = center + Vector((0, 0, z_cursor + tier_height / 2))
        created.append(
            create_world_box(
                f"{DETAIL_PREFIX}{slug}__tower_{tier_name}",
                parent,
                parent.matrix_world @ local,
                (tier_width, tier_depth, tier_height),
                mat,
                collection,
                "tower",
            )
        )
        z_cursor += tier_height

    clock_z = tower_height * 0.44
    for side in tower.get("clockFaces", ["north", "south"]):
        created.extend(add_clock_face(parent, slug, collection, center, side, half_width * 0.86, half_depth * 0.86, clock_z, min(width, depth) * 0.32))

    created.extend(
        add_louver_openings(
            parent,
            slug,
            collection,
            center,
            ["north", "south", "east", "west"],
            half_width * 0.68,
            half_depth * 0.68,
            tower_height * 0.65,
            min(width, depth) * 0.09,
            tower_height * 0.13,
        )
    )

    if tower.get("spire", True):
        spire_height = tower_height * 0.36
        created.append(
            create_world_box(
                f"{DETAIL_PREFIX}{slug}__spire_mast",
                parent,
                parent.matrix_world @ (center + Vector((0, 0, z_cursor + spire_height / 2))),
                (0.55, 0.55, spire_height),
                material("copper"),
                collection,
                "spire",
            )
        )
        created.append(
            create_world_box(
                f"{DETAIL_PREFIX}{slug}__weathervane_cross",
                parent,
                parent.matrix_world @ (center + Vector((0, 0, z_cursor + spire_height + 0.45))),
                (width * 0.55, 0.16, 0.16),
                material("clockHand"),
                collection,
                "spire",
            )
        )

    return created


def detail_building(obj, recipe, root_collection):
    remove_existing_details(obj)
    min_v, max_v = local_bounds(obj)
    label = obj.get("mwrld_name", obj.name)
    collection = ensure_collection(f"{label} Details ({obj.get('mwrld_osm_id', 'no-id')})", root_collection)
    details = []
    details.extend(create_roof_mesh(f"{DETAIL_PREFIX}{slugify(label)}__roof", obj, min_v, max_v, recipe, collection))
    if recipe.get("roof", {}).get("parapet"):
        details.extend(add_parapet(obj, min_v, max_v, collection))
    details.extend(add_tower(obj, min_v, max_v, recipe, collection))
    details.extend(add_windows(obj, min_v, max_v, recipe, collection))
    details.extend(add_doors(obj, min_v, max_v, recipe, collection))
    details.extend(add_chimneys(obj, min_v, max_v, recipe.get("chimneys", 0), collection))
    obj["mwrld_detail_recipe"] = recipe.get("style", "generic")
    obj["mwrld_generated_detail_count"] = len(details)
    return details


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    query = args[1] if len(args) > 1 else "baker-library"
    recipe_path = Path(args[2]).resolve() if len(args) > 2 else RECIPE_PATH
    allow_defaults = "--allow-defaults" in args
    ignore_reference_gate = "--ignore-reference-gate" in args

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    recipes = json.loads(recipe_path.read_text(encoding="utf-8"))
    root_collection = ensure_collection("MWRLD Generated Building Details")

    report = {
        "sourceBlend": str(blend_path.relative_to(ROOT) if blend_path.is_relative_to(ROOT) else blend_path),
        "recipeSource": str(recipe_path.relative_to(ROOT) if recipe_path.is_relative_to(ROOT) else recipe_path),
        "targets": [],
    }
    targets = target_buildings(query)
    skipped = []
    for index, obj in enumerate(targets, start=1):
        if not allow_defaults and not has_explicit_recipe(obj, recipes):
            skipped.append({
                "target": obj.name,
                "displayName": obj.get("mwrld_name", obj.name),
                "osmId": obj.get("mwrld_osm_id", ""),
                "reason": "No explicit detail recipe. Use Google Street View facade references first, then add a building-specific recipe.",
            })
            continue
        recipe = recipe_for(obj, recipes)
        failures = [] if ignore_reference_gate else reference_gate_failures(obj, recipe)
        if failures:
            skipped.append({
                "target": obj.name,
                "displayName": obj.get("mwrld_name", obj.name),
                "osmId": obj.get("mwrld_osm_id", ""),
                "reason": "Reference approval required before procedural facade/roof generation.",
                "referenceGate": failures,
            })
            continue
        details = detail_building(obj, recipe, root_collection)
        counts = {}
        for detail in details:
            kind = detail.get("mwrld_detail_kind", "detail")
            counts[kind] = counts.get(kind, 0) + 1
        report["targets"].append(
            {
                "target": obj.name,
                "displayName": obj.get("mwrld_name", obj.name),
                "osmId": obj.get("mwrld_osm_id", ""),
                "detailCount": len(details),
                "counts": counts,
            }
        )
        if index % 25 == 0:
            print(f"Detailed {index}/{len(targets)} buildings")

    report["skipped"] = skipped
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    total = sum(item["detailCount"] for item in report["targets"])
    print(f"Generated details for {len(targets)} building(s). Detail objects: {total}.")


if __name__ == "__main__":
    main()
