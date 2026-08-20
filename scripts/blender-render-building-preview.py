import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def object_matches(obj, query):
    haystack = " ".join([obj.name, obj.get("mwrld_name", ""), obj.get("mwrld_osm_id", "")]).lower()
    return query.lower() in haystack


def find_building(query):
    matches = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_category") == "building" and object_matches(obj, query)
    ]
    if not matches:
        raise SystemExit(f"No building matched {query!r}")
    return sorted(matches, key=lambda obj: obj.name)[0]


def slug(name):
    value = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return value or "building"


def bounds(objects):
    coords = []
    for obj in objects:
        if obj.type == "MESH":
            coords.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def look_at(camera, target):
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def render(path, camera_location, target, scale, wire=False):
    camera = bpy.data.objects.get("mwrld_preview_camera")
    if camera is None:
        bpy.ops.object.camera_add()
        camera = bpy.context.object
        camera.name = "mwrld_preview_camera"
    camera.location = camera_location
    look_at(camera, target)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = scale
    camera.data.clip_end = 10000
    bpy.context.scene.camera = camera

    wire_mods = []
    if wire:
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and not obj.hide_render:
                mod = obj.modifiers.new("preview_wire", "WIREFRAME")
                mod.thickness = 0.035
                mod.use_even_offset = True
                wire_mods.append((obj, mod))

    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)

    for obj, mod in wire_mods:
        obj.modifiers.remove(mod)


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    query = args[1] if len(args) > 1 else "dartmouth-hall"
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = find_building(query)
    details = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_detail_for") == parent.get("mwrld_osm_id", parent.name)
    ]
    visible = {parent, *details}
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            visible_obj = obj in visible
            obj.hide_render = not visible_obj
            obj.hide_viewport = not visible_obj

    out_dir = MODEL_DIR / "renders" / "buildings" / parent.name
    out_dir.mkdir(parents=True, exist_ok=True)
    min_v, max_v = bounds(list(visible))
    center = (min_v + max_v) * 0.5
    size = max(max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z)
    name = slug(parent.get("mwrld_name", parent.name))

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 1400
    scene.render.resolution_y = 1000
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "MATERIAL"
    scene.display.shading.background_type = "VIEWPORT"
    scene.display.shading.background_color = (0.26, 0.26, 0.26)
    scene.view_settings.view_transform = "Standard"
    scene.view_settings.look = "Medium High Contrast"

    views = [
        ("south", Vector((center.x, min_v.y - size * 1.05, center.z + size * 0.22))),
        ("north", Vector((center.x, max_v.y + size * 1.05, center.z + size * 0.22))),
        ("east", Vector((max_v.x + size * 1.05, center.y, center.z + size * 0.22))),
        ("west", Vector((min_v.x - size * 1.05, center.y, center.z + size * 0.22))),
        ("iso", Vector((center.x + size * 0.55, center.y - size * 0.65, center.z + size * 0.55))),
        ("top", Vector((center.x, center.y, max_v.z + size * 1.35))),
    ]
    for view_name, location in views:
        render(out_dir / f"{name}-preview-{view_name}.png", location, center, size * 1.42)
    render(out_dir / f"{name}-preview-wire.png", views[4][1], center, size * 1.42, wire=True)
    print(f"Rendered {parent.name} previews to {out_dir}")


if __name__ == "__main__":
    main()
