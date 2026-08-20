import inspect
import sys
from pathlib import Path

import bpy


def args_after_double_dash():
    if "--" not in sys.argv:
        raise SystemExit("Usage: blender --background --python script.py -- <source.fbx> <out.blend>")
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) != 2:
        raise SystemExit("Usage: blender --background --python script.py -- <source.fbx> <out.blend>")
    return Path(args[0]).resolve(), Path(args[1]).resolve()


def patch_blender_52_fbx_light_bug():
    try:
        import io_scene_fbx.import_fbx as import_fbx
    except Exception:
        return

    source = inspect.getsource(import_fbx.blen_read_light)
    old = '    if hasattr(lamp, "cycles"):\n        lamp.cycles.cast_shadow = lamp.use_shadow\n'
    new = (
        '    if hasattr(lamp, "cycles") and hasattr(lamp.cycles, "cast_shadow"):\n'
        "        lamp.cycles.cast_shadow = lamp.use_shadow\n"
    )
    if old in source:
        exec(source.replace(old, new), import_fbx.__dict__)


def main():
    source_fbx, out_blend = args_after_double_dash()
    out_blend.parent.mkdir(parents=True, exist_ok=True)

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    patch_blender_52_fbx_light_bug()
    bpy.ops.import_scene.fbx(filepath=str(source_fbx))

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(out_blend))
    mesh_count = len([obj for obj in bpy.context.scene.objects if obj.type == "MESH"])
    print(f"Converted FBX to blend: {out_blend}")
    print(f"Mesh objects: {mesh_count}")


if __name__ == "__main__":
    main()
