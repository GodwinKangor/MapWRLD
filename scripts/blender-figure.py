import math
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "public" / "models" / "figure"
RENDER_DIR = OUT_DIR / "renders"


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()


def ensure_dirs():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_DIR.mkdir(parents=True, exist_ok=True)


def make_material(name, color, roughness=0.65):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = color
    bsdf.inputs["Roughness"].default_value = roughness
    return mat


def assign(obj, mat):
    obj.data.materials.append(mat)
    return obj


def shade_smooth(obj):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.shade_smooth()
    obj.select_set(False)
    return obj


def uv_sphere(name, location, scale, mat, segments=32, rings=16):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=segments,
        ring_count=rings,
        location=location,
    )
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    assign(obj, mat)
    return shade_smooth(obj)


def cube(name, location, scale, mat):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.scale = scale
    assign(obj, mat)
    bevel = obj.modifiers.new("softened_edges", "BEVEL")
    bevel.width = 0.05
    bevel.segments = 4
    obj.modifiers.new("weighted_normals", "WEIGHTED_NORMAL")
    return obj


def capsule(name, start, end, radius, mat):
    start_v = Vector(start)
    end_v = Vector(end)
    midpoint = (start_v + end_v) * 0.5
    direction = end_v - start_v
    length = direction.length

    bpy.ops.mesh.primitive_cylinder_add(
        vertices=32,
        radius=radius,
        depth=length,
        location=midpoint,
    )
    cyl = bpy.context.object
    cyl.name = f"{name}_shaft"
    cyl.rotation_euler = direction.to_track_quat("Z", "Y").to_euler()
    assign(cyl, mat)
    shade_smooth(cyl)

    uv_sphere(f"{name}_start_cap", start, (radius, radius, radius), mat, 24, 12)
    uv_sphere(f"{name}_end_cap", end, (radius, radius, radius), mat, 24, 12)
    return cyl


def add_labelled_marker(name, location, radius, mat):
    obj = uv_sphere(name, location, (radius, radius, radius), mat, 16, 8)
    obj.display_type = "TEXTURED"
    return obj


def build_figure():
    clay = make_material("mat_clay_warm_gray", (0.62, 0.60, 0.56, 1.0))
    joint = make_material("mat_joint_dark_gray", (0.18, 0.18, 0.18, 1.0))
    accent = make_material("mat_reference_blue", (0.1, 0.28, 0.55, 1.0))
    floor_mat = make_material("mat_floor", (0.42, 0.43, 0.42, 1.0))

    # Main body volumes.
    cube("pelvis_block", (0, 0, 1.55), (0.42, 0.24, 0.22), clay)
    cube("ribcage_block", (0, 0, 2.35), (0.48, 0.26, 0.46), clay)
    capsule("neck", (0, 0, 2.78), (0, 0, 2.98), 0.12, clay)
    uv_sphere("head", (0, 0, 3.25), (0.26, 0.22, 0.32), clay)

    # Arms in a relaxed A-pose.
    capsule("left_upper_arm", (-0.48, 0, 2.6), (-0.9, 0.03, 2.1), 0.12, clay)
    capsule("left_forearm", (-0.9, 0.03, 2.1), (-1.1, 0.02, 1.55), 0.1, clay)
    uv_sphere("left_hand", (-1.1, 0.02, 1.38), (0.11, 0.08, 0.15), clay, 24, 12)

    capsule("right_upper_arm", (0.48, 0, 2.6), (0.9, 0.03, 2.1), 0.12, clay)
    capsule("right_forearm", (0.9, 0.03, 2.1), (1.1, 0.02, 1.55), 0.1, clay)
    uv_sphere("right_hand", (1.1, 0.02, 1.38), (0.11, 0.08, 0.15), clay, 24, 12)

    # Legs with simple boots.
    capsule("left_thigh", (-0.22, 0, 1.35), (-0.28, 0.02, 0.78), 0.15, clay)
    capsule("left_shin", (-0.28, 0.02, 0.78), (-0.3, 0.02, 0.2), 0.12, clay)
    cube("left_foot", (-0.3, -0.1, 0.08), (0.17, 0.33, 0.08), clay)

    capsule("right_thigh", (0.22, 0, 1.35), (0.28, 0.02, 0.78), 0.15, clay)
    capsule("right_shin", (0.28, 0.02, 0.78), (0.3, 0.02, 0.2), 0.12, clay)
    cube("right_foot", (0.3, -0.1, 0.08), (0.17, 0.33, 0.08), clay)

    # Visible joint handles make proportional edits easier to discuss.
    for name, loc in {
        "joint_left_shoulder": (-0.5, 0, 2.62),
        "joint_right_shoulder": (0.5, 0, 2.62),
        "joint_left_elbow": (-0.9, 0.03, 2.1),
        "joint_right_elbow": (0.9, 0.03, 2.1),
        "joint_left_knee": (-0.28, 0.02, 0.78),
        "joint_right_knee": (0.28, 0.02, 0.78),
    }.items():
        add_labelled_marker(name, loc, 0.055, joint)

    # Simple vertical measuring guide at the side.
    capsule("height_reference_3m", (1.45, 0, 0), (1.45, 0, 3.0), 0.015, accent)

    bpy.ops.mesh.primitive_plane_add(size=4.0, location=(0, 0, 0))
    floor = bpy.context.object
    floor.name = "ground_plane"
    assign(floor, floor_mat)


def setup_camera_and_lights():
    bpy.ops.object.light_add(type="AREA", location=(-2.0, -3.0, 4.5))
    key = bpy.context.object
    key.name = "large_softbox_key"
    key.data.energy = 400
    key.data.size = 4.0

    bpy.ops.object.camera_add(location=(3.3, -5.2, 2.45))
    camera = bpy.context.object
    camera.name = "preview_camera"
    bpy.context.scene.camera = camera
    target = Vector((0, 0, 1.65))
    direction = target - Vector(camera.location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 3.9
    camera.data.dof.use_dof = False


def render(path, wireframe=False):
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.eevee.taa_render_samples = 64
    scene.render.resolution_x = 1600
    scene.render.resolution_y = 1600
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.world.color = (0.78, 0.78, 0.76)
    scene.render.filepath = str(path)

    if wireframe:
        for obj in bpy.context.scene.objects:
            if obj.type == "MESH" and obj.name != "ground_plane":
                mod = obj.modifiers.new("preview_wire", "WIREFRAME")
                mod.thickness = 0.012
                mod.use_even_offset = True
        scene.world.color = (0.92, 0.92, 0.9)

    bpy.ops.render.render(write_still=True)


def export_assets():
    blend_path = OUT_DIR / "figure.blend"
    backup_path = OUT_DIR / "figure.blend1"
    fbx_path = OUT_DIR / "figure.fbx"
    glb_path = OUT_DIR / "figure.glb"

    bpy.context.preferences.filepaths.save_version = 0
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    if backup_path.exists():
        backup_path.unlink()

    exportable = [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.name != "ground_plane"]
    bpy.ops.object.select_all(action="DESELECT")
    for obj in exportable:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = exportable[0]

    bpy.ops.export_scene.fbx(filepath=str(fbx_path), use_selection=True, apply_unit_scale=True, add_leaf_bones=False)
    bpy.ops.export_scene.gltf(filepath=str(glb_path), export_format="GLB", use_selection=True)


def main():
    ensure_dirs()
    clear_scene()
    build_figure()
    setup_camera_and_lights()
    export_assets()
    render(RENDER_DIR / "clay.png", wireframe=False)
    render(RENDER_DIR / "wireframe.png", wireframe=True)


if __name__ == "__main__":
    main()
