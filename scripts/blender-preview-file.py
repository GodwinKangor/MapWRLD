import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
OUT_ROOT = ROOT / "public" / "models" / "dartmouth-energy-twin"
RENDER_DIR = OUT_ROOT / "renders"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def scene_bounds(objects):
    coords = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            coords.append(obj.matrix_world @ Vector(corner))
    if not coords:
        return Vector((-1, -1, -1)), Vector((1, 1, 1))
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def primary_preview_objects(objects):
    raised = [
        obj
        for obj in objects
        if obj.type == "MESH" and obj.dimensions.z > 0.5 and obj.dimensions.x > 0.1 and obj.dimensions.y > 0.1
    ]
    return raised or [obj for obj in objects if obj.type == "MESH"]


def region_for(center, min_v, max_v):
    mid_x = (min_v.x + max_v.x) / 2
    mid_y = (min_v.y + max_v.y) / 2
    east_west = "east" if center.x >= mid_x else "west"
    north_south = "north" if center.y >= mid_y else "south"
    return f"{north_south}_{east_west}"


def make_material(name, color, roughness=0.7):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def write_scene_report(blend_path, objects, min_v, max_v):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    mesh_objects = [obj for obj in objects if obj.type == "MESH"]
    collections = sorted(bpy.data.collections, key=lambda c: c.name.lower())
    lines = [
        "# Dartmouth Energy Twin Scene Report",
        "",
        f"Source: `{blend_path}`",
        f"Objects: {len(objects)}",
        f"Mesh objects: {len(mesh_objects)}",
        f"Materials: {len(bpy.data.materials)}",
        f"Collections: {len(collections)}",
        f"Bounds min: ({min_v.x:.3f}, {min_v.y:.3f}, {min_v.z:.3f})",
        f"Bounds max: ({max_v.x:.3f}, {max_v.y:.3f}, {max_v.z:.3f})",
        "",
        "## Collections",
        "",
    ]
    for collection in collections:
        lines.append(f"- {collection.name}: {len(collection.objects)} direct objects")

    lines.extend(["", "## Mesh Objects", ""])
    for obj in sorted(mesh_objects, key=lambda o: o.name.lower()):
        dims = obj.dimensions
        mat_names = [slot.material.name for slot in obj.material_slots if slot.material]
        mat_summary = ", ".join(mat_names[:4]) if mat_names else "no material"
        if len(mat_names) > 4:
            mat_summary += f", +{len(mat_names) - 4} more"
        lines.append(
            f"- {obj.name}: dims=({dims.x:.2f}, {dims.y:.2f}, {dims.z:.2f}), "
            f"verts={len(obj.data.vertices)}, faces={len(obj.data.polygons)}, mats={mat_summary}"
        )

    (OUT_ROOT / "scene-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup_preview_scene(objects, min_v, max_v, visible_objects):
    center = (min_v + max_v) * 0.5
    size = max((max_v - min_v).length, 1.0)
    height = max(max_v.z - min_v.z, 1.0)
    clay = make_material("preview_clay_gray", (0.62, 0.61, 0.58, 1.0))

    for obj in objects:
        if obj.type == "MESH":
            obj.data.materials.clear()
            obj.data.materials.append(clay)
            if obj not in visible_objects:
                obj.hide_render = True
                obj.hide_viewport = True
            else:
                obj.hide_render = False
                obj.hide_viewport = False

    bpy.ops.object.light_add(type="AREA", location=(center.x - size * 0.35, center.y - size * 0.45, max_v.z + size * 0.5))
    key = bpy.context.object
    key.name = "preview_area_light"
    key.data.energy = max(500, size * 18)
    key.data.size = max(size * 0.35, 8)

    camera_location = Vector((center.x + size * 0.35, center.y - size * 0.45, max_v.z + size * 0.65))
    bpy.ops.object.camera_add(location=camera_location)
    camera = bpy.context.object
    camera.name = "preview_camera"
    direction = center - camera_location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z) * 1.25
    camera.data.clip_start = 0.1
    camera.data.clip_end = max(size * 4, 10000)
    bpy.context.scene.camera = camera

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 1800
    scene.render.resolution_y = 1400
    scene.eevee.taa_render_samples = 64
    scene.world.color = (0.78, 0.78, 0.76)
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"


def set_top_camera(min_v, max_v):
    center = (min_v + max_v) * 0.5
    size = max((max_v - min_v).length, 1.0)
    camera_location = Vector((center.x, center.y, max_v.z + size))
    camera = bpy.context.scene.camera
    camera.location = camera_location
    camera.rotation_euler = (0, 0, 0)
    direction = center - camera_location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.ortho_scale = max(max_v.x - min_v.x, max_v.y - min_v.y) * 1.1


def set_iso_camera(min_v, max_v):
    center = (min_v + max_v) * 0.5
    size = max((max_v - min_v).length, 1.0)
    camera_location = Vector((center.x + size * 0.35, center.y - size * 0.45, max_v.z + size * 0.65))
    camera = bpy.context.scene.camera
    camera.location = camera_location
    direction = center - camera_location
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.ortho_scale = max(max_v.x - min_v.x, max_v.y - min_v.y, max_v.z - min_v.z) * 1.2


def set_visible_region(all_objects, visible_objects):
    visible_set = set(visible_objects)
    for obj in all_objects:
        if obj.type == "MESH":
            is_visible = obj in visible_set
            obj.hide_render = not is_visible
            obj.hide_viewport = not is_visible


def render_region_crops(all_objects, primary_objects, campus_min, campus_max):
    regions = {
        "north_west": [],
        "north_east": [],
        "south_west": [],
        "south_east": [],
    }
    for obj in primary_objects:
        min_v, max_v = scene_bounds([obj])
        center = (min_v + max_v) * 0.5
        regions[region_for(center, campus_min, campus_max)].append(obj)

    for region, region_objects in regions.items():
        if not region_objects:
            continue
        min_v, max_v = scene_bounds(region_objects)
        set_visible_region(all_objects, region_objects)
        set_iso_camera(min_v, max_v)
        render(RENDER_DIR / f"{region}_iso.png", wireframe=False)
        set_top_camera(min_v, max_v)
        render(RENDER_DIR / f"{region}_top.png", wireframe=False)


def render(path, wireframe=False):
    if wireframe:
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH":
                mod = obj.modifiers.new("preview_wire", "WIREFRAME")
                mod.thickness = 0.02
                mod.use_even_offset = True
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def main():
    args = args_after_double_dash()
    if not args:
        raise SystemExit("Usage: blender --background --factory-startup --python scripts/blender-preview-file.py -- /path/to/file.blend")

    blend_path = Path(args[0]).expanduser().resolve()
    if not blend_path.exists():
        raise SystemExit(f"Blend file not found: {blend_path}")

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    objects = list(bpy.context.scene.objects)
    primary_objects = primary_preview_objects(objects)
    min_v, max_v = scene_bounds(primary_objects)
    write_scene_report(blend_path, objects, min_v, max_v)
    setup_preview_scene(objects, min_v, max_v, primary_objects)
    render(RENDER_DIR / "clay.png", wireframe=False)
    set_top_camera(min_v, max_v)
    render(RENDER_DIR / "top.png", wireframe=False)
    render_region_crops(objects, primary_objects, min_v, max_v)
    set_visible_region(objects, primary_objects)
    set_top_camera(min_v, max_v)
    render(RENDER_DIR / "wireframe.png", wireframe=True)


if __name__ == "__main__":
    main()
