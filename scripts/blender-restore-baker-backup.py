import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
BAKER_NAME = "building__baker-library__way_295888783"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def remove_details(parent):
    target_id = parent.get("mwrld_osm_id", parent.name)
    for obj in list(bpy.data.objects):
        if obj.get("mwrld_backup_of"):
            continue
        if obj.get("mwrld_detail_for") == target_id:
            bpy.data.objects.remove(obj, do_unlink=True)


def restore_backup(parent):
    backups = [
        obj
        for obj in bpy.data.objects
        if obj.get("mwrld_backup_of") == BAKER_NAME and obj.type == "MESH"
    ]
    if not backups:
        raise SystemExit("No Baker backup mesh found in blend.")
    backup = sorted(backups, key=lambda obj: obj.name)[-1]

    old_mesh = parent.data
    parent.data = backup.data.copy()
    parent.data.name = f"{BAKER_NAME}_restored_mesh"
    parent.matrix_world = backup.matrix_world.copy()

    for material in parent.data.materials:
        if material:
            material.diffuse_color = (0.72, 0.72, 0.70, 1)

    parent["mwrld_detail_recipe"] = "restored_original_footprint"
    parent["mwrld_generated_detail_count"] = 0
    parent["mwrld_baker_massing_rebuilt"] = False
    parent["mwrld_restored_from_backup"] = backup.name

    if old_mesh.users == 0:
        bpy.data.meshes.remove(old_mesh)
    return backup.name


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    parent = bpy.data.objects.get(BAKER_NAME)
    if not parent:
        raise SystemExit(f"Missing {BAKER_NAME}")

    remove_details(parent)
    backup_name = restore_backup(parent)
    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Restored Baker visible mesh from {backup_name}.")


if __name__ == "__main__":
    main()
