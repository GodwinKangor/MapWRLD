import json
import inspect
import math
import sys

import bpy


def parse_args():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("Usage: blender --background --python script.py -- <fbx> [target_name] [target_x target_y target_z]")
    args = argv[argv.index("--") + 1 :]
    if not args:
        raise SystemExit("Missing FBX path")
    fbx_path = args[0]
    target_name = args[1] if len(args) > 1 else ""
    target_dims = None
    if len(args) >= 5:
        target_dims = tuple(float(v) for v in args[2:5])
    return fbx_path, target_name, target_dims


def score_object(obj, target_name, target_dims):
    score = 0.0
    reasons = []
    name_l = obj.name.lower()
    if target_name and target_name.lower() in name_l:
        score += 1000
        reasons.append("name")
    original = str(obj.get("mwrld_original_name", ""))
    if target_name and target_name.lower() in original.lower():
        score += 1000
        reasons.append("original_name")
    if target_dims:
        dims = tuple(float(v) for v in obj.dimensions)
        diff = math.sqrt(sum((dims[i] - target_dims[i]) ** 2 for i in range(3)))
        score += max(0, 500 - diff * 20)
        reasons.append(f"dim_diff={diff:.3f}")
    return score, reasons


def mesh_summary(obj):
    mesh = obj.data
    counts = {"triangles": 0, "quads": 0, "ngons": 0}
    for poly in mesh.polygons:
        if len(poly.vertices) == 3:
            counts["triangles"] += 1
        elif len(poly.vertices) == 4:
            counts["quads"] += 1
        else:
            counts["ngons"] += 1
    return {
        "name": obj.name,
        "originalName": obj.get("mwrld_original_name"),
        "displayName": obj.get("mwrld_display_name"),
        "vertices": len(mesh.vertices),
        "faces": len(mesh.polygons),
        "shapeCounts": counts,
        "dimensions": [round(float(v), 6) for v in obj.dimensions],
        "location": [round(float(v), 6) for v in obj.location],
    }


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
    if old not in source:
        return
    exec(source.replace(old, new), import_fbx.__dict__)


def main():
    fbx_path, target_name, target_dims = parse_args()
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete()
    patch_blender_52_fbx_light_bug()
    bpy.ops.import_scene.fbx(filepath=fbx_path)

    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    candidates = []
    for obj in meshes:
        score, reasons = score_object(obj, target_name, target_dims)
        data = mesh_summary(obj)
        data["score"] = round(score, 3)
        data["reasons"] = reasons
        candidates.append(data)

    candidates.sort(key=lambda item: item["score"], reverse=True)
    print(
        "CODEX_FBX_INSPECT",
        json.dumps(
            {
                "fbx": fbx_path,
                "meshObjects": len(meshes),
                "topCandidates": candidates[:20],
            },
            sort_keys=True,
        ),
    )


if __name__ == "__main__":
    main()
