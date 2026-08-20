import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
REPORT_PATH = MODEL_DIR / "reports" / "detail-controller-rigs.json"
RIG_PREFIX = "mwrld_detail__"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "unnamed"


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


def find_target(query):
    matches = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_category") == "building" and object_matches(obj, query)
    ]
    if not matches:
        raise SystemExit(f"No named building matched: {query}")
    return sorted(matches, key=lambda obj: len(obj.name))[0]


def local_bounds(obj):
    vertices = [vertex.co.copy() for vertex in obj.data.vertices]
    min_v = Vector((min(v.x for v in vertices), min(v.y for v in vertices), min(v.z for v in vertices)))
    max_v = Vector((max(v.x for v in vertices), max(v.y for v in vertices), max(v.z for v in vertices)))
    return min_v, max_v


def local_to_world(obj, value):
    return obj.matrix_world @ value


def threshold(span):
    return max(span * 0.055, 0.35)


def vertex_groups_for_box(obj):
    min_v, max_v = local_bounds(obj)
    span = max_v - min_v
    tx = threshold(span.x)
    ty = threshold(span.y)
    tz = threshold(span.z)
    vertices = obj.data.vertices

    groups = {
        "face_roof": [v.index for v in vertices if v.co.z >= max_v.z - tz],
        "face_base": [v.index for v in vertices if v.co.z <= min_v.z + tz],
        "face_east": [v.index for v in vertices if v.co.x >= max_v.x - tx],
        "face_west": [v.index for v in vertices if v.co.x <= min_v.x + tx],
        "face_north": [v.index for v in vertices if v.co.y >= max_v.y - ty],
        "face_south": [v.index for v in vertices if v.co.y <= min_v.y + ty],
        "edge_roof_east": [v.index for v in vertices if v.co.z >= max_v.z - tz and v.co.x >= max_v.x - tx],
        "edge_roof_west": [v.index for v in vertices if v.co.z >= max_v.z - tz and v.co.x <= min_v.x + tx],
        "edge_roof_north": [v.index for v in vertices if v.co.z >= max_v.z - tz and v.co.y >= max_v.y - ty],
        "edge_roof_south": [v.index for v in vertices if v.co.z >= max_v.z - tz and v.co.y <= min_v.y + ty],
    }

    corners = {
        "vertex_bottom_sw": Vector((min_v.x, min_v.y, min_v.z)),
        "vertex_bottom_se": Vector((max_v.x, min_v.y, min_v.z)),
        "vertex_bottom_nw": Vector((min_v.x, max_v.y, min_v.z)),
        "vertex_bottom_ne": Vector((max_v.x, max_v.y, min_v.z)),
        "vertex_roof_sw": Vector((min_v.x, min_v.y, max_v.z)),
        "vertex_roof_se": Vector((max_v.x, min_v.y, max_v.z)),
        "vertex_roof_nw": Vector((min_v.x, max_v.y, max_v.z)),
        "vertex_roof_ne": Vector((max_v.x, max_v.y, max_v.z)),
    }
    for name, point in corners.items():
        nearest = min(vertices, key=lambda vertex: (vertex.co - point).length)
        groups[name] = [nearest.index]

    positions = {
        "face_roof": Vector(((min_v.x + max_v.x) / 2, (min_v.y + max_v.y) / 2, max_v.z)),
        "face_base": Vector(((min_v.x + max_v.x) / 2, (min_v.y + max_v.y) / 2, min_v.z)),
        "face_east": Vector((max_v.x, (min_v.y + max_v.y) / 2, (min_v.z + max_v.z) / 2)),
        "face_west": Vector((min_v.x, (min_v.y + max_v.y) / 2, (min_v.z + max_v.z) / 2)),
        "face_north": Vector(((min_v.x + max_v.x) / 2, max_v.y, (min_v.z + max_v.z) / 2)),
        "face_south": Vector(((min_v.x + max_v.x) / 2, min_v.y, (min_v.z + max_v.z) / 2)),
        "edge_roof_east": Vector((max_v.x, (min_v.y + max_v.y) / 2, max_v.z)),
        "edge_roof_west": Vector((min_v.x, (min_v.y + max_v.y) / 2, max_v.z)),
        "edge_roof_north": Vector(((min_v.x + max_v.x) / 2, max_v.y, max_v.z)),
        "edge_roof_south": Vector(((min_v.x + max_v.x) / 2, min_v.y, max_v.z)),
        **corners,
    }

    return {key: value for key, value in groups.items() if value}, positions


def controller_type(group_name):
    if group_name.startswith("face_"):
        return "CUBE"
    if group_name.startswith("edge_"):
        return "ARROWS"
    return "SPHERE"


def controller_kind(group_name):
    return group_name.split("_", 1)[0]


def controller_size(obj, group_name):
    longest = max(obj.dimensions.x, obj.dimensions.y, obj.dimensions.z, 1.0)
    if group_name.startswith("face_"):
        return max(1.2, min(6.0, longest * 0.08))
    if group_name.startswith("edge_"):
        return max(0.8, min(4.0, longest * 0.055))
    return max(0.55, min(2.2, longest * 0.035))


def ensure_vertex_group(obj, name, indices):
    group = obj.vertex_groups.get(name) or obj.vertex_groups.new(name=name)
    group.add(indices, 1.0, "REPLACE")
    return group


def remove_existing_detail_hooks(obj):
    for modifier in list(obj.modifiers):
        if modifier.name.startswith(RIG_PREFIX):
            obj.modifiers.remove(modifier)


def create_controller(obj, collection, group_name, local_position):
    display_name = slugify(obj.get("mwrld_name", obj.name))
    ctrl_name = f"ctrl__detail__{display_name}__{group_name}"
    ctrl = bpy.data.objects.get(ctrl_name)
    if not ctrl:
        ctrl = bpy.data.objects.new(ctrl_name, None)
    link_to_collection(ctrl, collection)

    ctrl.empty_display_type = controller_type(group_name)
    ctrl.empty_display_size = controller_size(obj, group_name)
    ctrl.location = local_to_world(obj, local_position)
    ctrl.rotation_euler = (0, 0, 0)
    ctrl.show_name = True
    ctrl.show_in_front = True
    ctrl.hide_render = True
    ctrl["mwrld_detail_controller"] = True
    ctrl["mwrld_component_kind"] = controller_kind(group_name)
    ctrl["mwrld_component_group"] = group_name
    ctrl["mwrld_target"] = obj.name
    ctrl["mwrld_osm_id"] = obj.get("mwrld_osm_id", "")
    return ctrl


def add_hook(obj, ctrl, group_name):
    modifier = obj.modifiers.new(f"{RIG_PREFIX}{group_name}", "HOOK")
    modifier.object = ctrl
    modifier.vertex_group = group_name
    modifier.falloff_type = "SMOOTH"
    modifier.falloff_radius = 0
    return modifier


def rig_building(obj):
    root = ensure_collection("MWRLD Detail Controllers")
    rig_name = f"{obj.get('mwrld_name', obj.name)} ({obj.get('mwrld_osm_id', 'no-osm-id')})"
    rig_collection = ensure_collection(rig_name, root)
    groups, positions = vertex_groups_for_box(obj)

    remove_existing_detail_hooks(obj)
    controllers = []
    for group_name, indices in sorted(groups.items()):
        ensure_vertex_group(obj, group_name, indices)
        ctrl = create_controller(obj, rig_collection, group_name, positions[group_name])
        add_hook(obj, ctrl, group_name)
        controllers.append(
            {
                "controller": ctrl.name,
                "component": group_name,
                "kind": controller_kind(group_name),
                "vertexCount": len(indices),
            }
        )

    obj["mwrld_detail_rigged"] = True
    obj["mwrld_detail_controller_count"] = len(controllers)
    return controllers


def read_existing_report():
    if not REPORT_PATH.exists():
        return {"rigs": []}
    return json.loads(REPORT_PATH.read_text(encoding="utf-8"))


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    query = args[1] if len(args) > 1 else "baker-library"
    if not blend_path.exists():
        raise SystemExit(f"Blend file not found: {blend_path}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    target = find_target(query)
    controllers = rig_building(target)

    report = read_existing_report()
    report["rigs"] = [rig for rig in report["rigs"] if rig.get("target") != target.name]
    report["rigs"].append(
        {
            "sourceBlend": str(blend_path.relative_to(ROOT) if blend_path.is_relative_to(ROOT) else blend_path),
            "target": target.name,
            "displayName": target.get("mwrld_name", target.name),
            "osmId": target.get("mwrld_osm_id", ""),
            "controllers": controllers,
        }
    )
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Detail rig ready for {target.name}. Controllers: {len(controllers)}.")


if __name__ == "__main__":
    main()
