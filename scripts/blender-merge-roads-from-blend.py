import sys
from pathlib import Path

import bpy


def args_after_double_dash():
    if "--" not in sys.argv:
        raise SystemExit("Usage: blender --background --python script.py -- <target.blend> <source.blend>")
    args = sys.argv[sys.argv.index("--") + 1 :]
    if len(args) != 2:
        raise SystemExit("Usage: blender --background --python script.py -- <target.blend> <source.blend>")
    return Path(args[0]).resolve(), Path(args[1]).resolve()


def main():
    target_path, source_path = args_after_double_dash()
    bpy.ops.wm.open_mainfile(filepath=str(target_path))

    existing_roads = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_category") == "road"
    ]
    for obj in existing_roads:
        bpy.data.objects.remove(obj, do_unlink=True)

    with bpy.data.libraries.load(str(source_path), link=False) as (data_from, data_to):
        data_to.objects = list(data_from.objects)

    appended = []
    skipped = []
    for obj in data_to.objects:
        if obj is None:
            continue
        if obj.type == "MESH" and obj.get("mwrld_category") == "road":
            bpy.context.collection.objects.link(obj)
            appended.append(obj.name)
        else:
            skipped.append(obj.name)
            bpy.data.objects.remove(obj, do_unlink=True)

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(target_path))
    print(f"Removed existing roads: {len(existing_roads)}")
    print(f"Appended roads: {len(appended)}")


if __name__ == "__main__":
    main()
