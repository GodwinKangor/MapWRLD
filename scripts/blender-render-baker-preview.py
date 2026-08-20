import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
OUT_DIR = MODEL_DIR / "renders" / "buildings" / "building__baker-library__way_295888783"
BAKER_NAME = "building__baker-library__way_295888783"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def bounds(objects):
    coords = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        coords.extend(obj.matrix_world @ Vector(corner) for corner in obj.bound_box)
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def look_at(camera, target):
    direction = target - camera.location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()


def render(path, camera_location, target, scale, wire=False):
    camera = bpy.data.objects.get("baker_preview_camera")
    if camera is None:
        bpy.ops.object.camera_add()
        camera = bpy.context.object
        camera.name = "baker_preview_camera"
    camera.location = camera_location
    look_at(camera, target)
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = scale
    camera.data.clip_end = 10000
    bpy.context.scene.camera = camera

    if wire:
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and not obj.hide_render and not obj.modifiers.get("preview_wire"):
                mod = obj.modifiers.new("preview_wire", "WIREFRAME")
                mod.thickness = 0.035
                mod.use_even_offset = True

    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = bpy.data.objects[BAKER_NAME]
    details = [
        obj
        for obj in bpy.context.scene.objects
        if obj.get("mwrld_detail_for") == parent.get("mwrld_osm_id")
        and (
            obj.name.startswith("mwrld_refdetail__baker-library__")
            or obj.name.startswith("mwrld_tower__baker-library__")
        )
    ]
    visible = {parent, *details}
    for obj in bpy.context.scene.objects:
        if obj.type == "MESH":
            visible_obj = obj in visible
            obj.hide_render = not visible_obj
            obj.hide_viewport = not visible_obj

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    min_v, max_v = bounds(list(visible))
    center = (min_v + max_v) * 0.5
    size = max(max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z)

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

    bpy.ops.object.light_add(type="AREA", location=(center.x - size * 0.3, center.y - size * 0.45, max_v.z + size * 0.7))
    light = bpy.context.object
    light.data.energy = 650
    light.data.size = size * 0.45

    render(
        OUT_DIR / "baker-reference-preview-south.png",
        Vector((center.x, min_v.y - size * 1.05, center.z + size * 0.28)),
        center,
        size * 1.42,
    )
    render(
        OUT_DIR / "baker-reference-preview-north.png",
        Vector((center.x, max_v.y + size * 1.05, center.z + size * 0.28)),
        center,
        size * 1.42,
    )
    render(
        OUT_DIR / "baker-reference-preview-east.png",
        Vector((max_v.x + size * 1.05, center.y, center.z + size * 0.28)),
        center,
        size * 1.42,
    )
    render(
        OUT_DIR / "baker-reference-preview-west.png",
        Vector((min_v.x - size * 1.05, center.y, center.z + size * 0.28)),
        center,
        size * 1.42,
    )
    render(
        OUT_DIR / "baker-reference-preview-iso.png",
        Vector((center.x + size * 0.55, center.y - size * 0.65, center.z + size * 0.55)),
        center,
        size * 1.42,
    )
    render(
        OUT_DIR / "baker-reference-preview-top.png",
        Vector((center.x, center.y, max_v.z + size * 1.35)),
        center,
        size * 1.42,
    )
    render(
        OUT_DIR / "baker-reference-preview-wire.png",
        Vector((center.x + size * 0.55, center.y - size * 0.65, center.z + size * 0.55)),
        center,
        size * 1.42,
        wire=True,
    )
    print(f"Rendered Baker previews to {OUT_DIR}")


if __name__ == "__main__":
    main()
