import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
REPORT_PATH = MODEL_DIR / "reports" / "mesh-controller-index.json"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


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


def mesh_bounds_world(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_v = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    max_v = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    return min_v, max_v


def controller_location(obj, category):
    min_v, max_v = mesh_bounds_world(obj)
    center = (min_v + max_v) * 0.5
    if category == "building":
        return Vector((center.x, center.y, min_v.z))
    return center


def controller_size(obj, category):
    dimensions = obj.dimensions
    if category == "building":
        return max(2.0, min(18.0, max(dimensions.x, dimensions.y) * 0.18))
    return max(1.0, min(10.0, max(dimensions.x, dimensions.y, 1.0) * 0.08))


def display_type(category):
    if category == "building":
        return "CUBE"
    if category == "road":
        return "ARROWS"
    return "PLAIN_AXES"


def collection_for_category(root, category):
    label = {
        "building": "Building Controllers",
        "road": "Road Controllers",
    }.get(category, "Other Controllers")
    return ensure_collection(label, root)


def managed_meshes():
    meshes = []
    for obj in bpy.context.scene.objects:
        if obj.type != "MESH":
            continue
        category = obj.get("mwrld_category")
        if category in {"building", "road"} and obj.get("mwrld_osm_id"):
            meshes.append(obj)
    return sorted(meshes, key=lambda item: (item.get("mwrld_category", ""), item.name.lower()))


def link_to_collection(obj, collection):
    if obj.name not in collection.objects:
        collection.objects.link(obj)


def create_or_update_controller(obj, collection):
    category = obj.get("mwrld_category", "other")
    ctrl_name = f"ctrl__{obj.name}"
    ctrl = bpy.data.objects.get(ctrl_name)

    if not ctrl:
        ctrl = bpy.data.objects.new(ctrl_name, None)
        link_to_collection(ctrl, collection)
    else:
        link_to_collection(ctrl, collection)

    world_before = obj.matrix_world.copy()
    ctrl.empty_display_type = display_type(category)
    ctrl.empty_display_size = controller_size(obj, category)
    ctrl.location = controller_location(obj, category)
    ctrl.rotation_euler = (0, 0, 0)
    ctrl.show_name = True
    ctrl.show_in_front = True
    ctrl.hide_render = True
    ctrl["mwrld_controller"] = True
    ctrl["mwrld_target"] = obj.name
    ctrl["mwrld_category"] = category
    ctrl["mwrld_osm_id"] = obj.get("mwrld_osm_id", "")
    ctrl["mwrld_display_name"] = obj.get("mwrld_name", obj.name)

    obj.parent = ctrl
    obj.matrix_parent_inverse = ctrl.matrix_world.inverted()
    obj.matrix_world = world_before
    obj["mwrld_controller"] = ctrl.name

    if category == "road":
        ctrl.hide_viewport = True
    return ctrl


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    if not blend_path.exists():
        raise SystemExit(f"Blend file not found: {blend_path}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    root = ensure_collection("MWRLD Mesh Controllers")
    controller_index = {
        "sourceBlend": str(blend_path.relative_to(ROOT) if blend_path.is_relative_to(ROOT) else blend_path),
        "controllers": [],
    }

    meshes = managed_meshes()
    for index, obj in enumerate(meshes, start=1):
        category = obj.get("mwrld_category", "other")
        collection = collection_for_category(root, category)
        ctrl = create_or_update_controller(obj, collection)
        controller_index["controllers"].append(
            {
                "controller": ctrl.name,
                "target": obj.name,
                "category": category,
                "displayName": obj.get("mwrld_name", obj.name),
                "osmId": obj.get("mwrld_osm_id", ""),
                "hiddenByDefault": bool(ctrl.hide_viewport),
                "dimensions": {
                    "x": round(obj.dimensions.x, 6),
                    "y": round(obj.dimensions.y, 6),
                    "z": round(obj.dimensions.z, 6),
                },
            }
        )
        if index % 100 == 0:
            print(f"Created or updated {index}/{len(meshes)} controllers")

    REPORT_PATH.write_text(json.dumps(controller_index, indent=2), encoding="utf-8")
    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    building_count = sum(1 for item in controller_index["controllers"] if item["category"] == "building")
    road_count = sum(1 for item in controller_index["controllers"] if item["category"] == "road")
    print(f"Controllers ready. Buildings: {building_count}. Roads: {road_count}.")


if __name__ == "__main__":
    main()
