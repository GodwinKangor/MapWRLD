"""Apply a processed facade texture (and reviewed relief features) to one wall in Blender.

Run as a controlled background process (the Mac worker does this); never from another thread
inside an interactive Blender session.

  Blender --background --factory-startup <campus.blend> --python scripts/blender/blender-apply-facade-texture.py -- \
      --registry data/field-surfaces/<building>.surfaces.json --surface-id <id> --result-dir <job output dir> \
      --out-blend <path> [--preview preview-blender.png] [--job-id ID]

Non-destructive: the building mesh is not edited (verified by hashing it before and after). The
texture goes on a separate plane `mwrld_facade__...` 3 cm in front of the wall in collection
"MWRLD Facade Textures"; re-running replaces that object, so updates are repeatable. Output is
saved to --out-blend; writing over the source .blend requires --in-place.

UV convention (documented in docs/field-capture/SPEC.md): UV (0,0) = bottom-left of the wall seen
from outside (S-frame u=0, v=0); UV (1,1) = top-right. Images load bottom-up in Blender, so the
texture (row 0 = top of wall) appears upright and unmirrored from outside.
"""
import hashlib
import json
import shutil
import sys
from pathlib import Path

import bpy
from mathutils import Vector

ROOT = Path(__file__).resolve().parents[2]
TEXTURE_COLLECTION = "MWRLD Facade Textures"
PROPOSED_COLLECTION = "MWRLD Facade Details (proposed)"
REVIEWED_COLLECTION = "MWRLD Facade Details (reviewed)"
OFFSET_M = 0.03


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts, i = {}, 0
    while i < len(argv):
        key = argv[i].lstrip("-")
        if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            opts[key] = argv[i + 1]
            i += 2
        else:
            opts[key] = True
            i += 1
    for required in ("registry", "surface-id", "result-dir", "out-blend"):
        if required not in opts:
            raise SystemExit(f"missing --{required}")
    return opts


def mesh_hash(obj):
    digest = hashlib.sha256()
    for v in obj.data.vertices:
        digest.update(("%.5f,%.5f,%.5f;" % tuple(v.co)).encode())
    for p in obj.data.polygons:
        digest.update((",".join(map(str, p.vertices)) + ";").encode())
    return digest.hexdigest()


def collection(name):
    coll = bpy.data.collections.get(name)
    if coll is None:
        coll = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(coll)
    return coll


def remove_object(name):
    obj = bpy.data.objects.get(name)
    if obj is not None:
        mesh = obj.data if obj.type == "MESH" else None
        bpy.data.objects.remove(obj, do_unlink=True)
        if mesh is not None and mesh.users == 0:
            bpy.data.meshes.remove(mesh)


def frame_point(surface, u, v, n=0.0):
    f = surface["frame"]
    o, ua, va, na = Vector(f["origin"]), Vector(f["uAxis"]), Vector(f["vAxis"]), Vector(f["normal"])
    return o + ua * u + va * v + na * n


def texture_material(name, image_path):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    tex = nodes.new("ShaderNodeTexImage")
    image = bpy.data.images.load(str(image_path), check_existing=False)
    image.name = f"{name}_image"
    image.alpha_mode = "STRAIGHT"
    tex.image = image
    tex.interpolation = "Linear"
    links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])  # unobserved texels stay transparent: the model shows through
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 0.85
    if hasattr(mat, "surface_render_method"):
        mat.surface_render_method = "DITHERED"
    if hasattr(mat, "blend_method"):
        mat.blend_method = "HASHED"
    return mat, image


def build_plane(surface, name, mat, coll):
    w, h = surface["widthM"], surface["heightM"]
    corners = [frame_point(surface, u, v, OFFSET_M) for u, v in ((0, 0), (w, 0), (w, h), (0, h))]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    # counter-clockwise seen from outside, so the face normal points outward (u x v = n)
    mesh.from_pydata([tuple(c) for c in corners], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name="facade_uv")
    for loop_index, (s, t) in zip(mesh.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[loop_index].uv = (s, t)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    return obj


def feature_box(surface, feature, name, coll, reviewed):
    b = feature["boundsM"]
    depth = float(feature["blender"].get("depthM") or 0.02)
    sign = -1.0 if feature["blender"]["operation"] == "inset" else 1.0
    n0, n1 = (0.0, sign * depth) if sign > 0 else (sign * depth, 0.0)
    pts = [frame_point(surface, u, v, n) for n in (n0, n1) for u, v in ((b["u0"], b["v0"]), (b["u1"], b["v0"]), (b["u1"], b["v1"]), (b["u0"], b["v1"]))]
    faces = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata([tuple(p) for p in pts], [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    coll.objects.link(obj)
    if not reviewed:
        obj.display_type = "WIRE"
        obj.hide_render = True
    obj["mwrld_feature_id"] = feature["featureId"]
    obj["mwrld_feature_kind"] = feature["kind"]
    obj["mwrld_feature_status"] = feature["status"]
    obj["mwrld_relief"] = json.dumps(feature["relief"])
    obj["mwrld_operation"] = feature["blender"]["operation"]
    obj["mwrld_geometry_role"] = "boolean-cutter" if sign < 0 else "added-volume"
    return obj


def render_preview(surface, target_objects, path):
    scene = bpy.context.scene
    w, h = surface["widthM"], surface["heightM"]
    centre = frame_point(surface, w / 2, h / 2, 0)
    distance = max(w, h) * 1.25
    cam_data = bpy.data.cameras.new("mwrld_preview_cam")
    cam_data.type = "ORTHO"
    cam_data.ortho_scale = max(w, h) * 1.15
    cam = bpy.data.objects.new("mwrld_preview_cam", cam_data)
    scene.collection.objects.link(cam)
    cam.location = frame_point(surface, w / 2, h / 2, distance)
    cam.rotation_euler = (centre - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.light = "FLAT"
    scene.display.shading.color_type = "TEXTURE"
    scene.render.resolution_x = 768
    scene.render.resolution_y = max(64, int(768 * min(1.0, h / max(w, 1e-6) * 1.0)))
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(cam, do_unlink=True)
    bpy.data.cameras.remove(cam_data)


def main():
    opts = args()
    registry = json.loads(Path(opts["registry"]).read_text())
    surface = next((s for s in registry["surfaces"] if s["surfaceId"] == opts["surface-id"]), None)
    if surface is None or surface.get("kind") != "wall":
        raise SystemExit(f"surface {opts['surface-id']} is not a wall in the registry")
    building = bpy.data.objects.get(surface["blender"]["object"])
    if building is None:
        raise SystemExit(f"Blender object {surface['blender']['object']} not found")
    before = mesh_hash(building)

    result_dir = Path(opts["result-dir"])
    out_blend = Path(opts["out-blend"]).resolve()
    if out_blend == Path(bpy.data.filepath).resolve() and not opts.get("in-place"):
        raise SystemExit("refusing to overwrite the source .blend without --in-place")
    texture_dir = out_blend.parent / "facade-textures"
    texture_dir.mkdir(parents=True, exist_ok=True)
    name = surface["blender"].get("facadeObject") or ("mwrld_facade__" + surface["surfaceId"].replace("osm:", "").replace("/", "_"))
    texture_path = texture_dir / f"{name}.png"
    shutil.copyfile(result_dir / "texture.png", texture_path)  # stable path: re-runs replace in place
    texture_sha = hashlib.sha256(texture_path.read_bytes()).hexdigest()

    remove_object(name)
    for old in list(bpy.data.materials):
        if old.name == f"{name}_material" and old.users == 0:
            bpy.data.materials.remove(old)
    for img in list(bpy.data.images):
        if img.name.startswith(f"{name}_material_image") and img.users == 0:
            bpy.data.images.remove(img)
    mat, _ = texture_material(f"{name}_material", texture_path)
    plane = build_plane(surface, name, mat, collection(TEXTURE_COLLECTION))
    provenance = json.loads((result_dir / "provenance.json").read_text()) if (result_dir / "provenance.json").exists() else {}
    coverage = json.loads((result_dir / "coverage.json").read_text()) if (result_dir / "coverage.json").exists() else {}
    plane["mwrld_surface_id"] = surface["surfaceId"]
    plane["mwrld_building_id"] = surface["buildingId"]
    plane["mwrld_osm_id"] = surface["osmId"]
    plane["mwrld_wall_panel_ids"] = json.dumps(surface["blender"].get("panelIds", []))
    plane["mwrld_detail_for"] = building.get("mwrld_osm_id", building.name)
    plane["mwrld_module"] = "field_capture_facade_texture"
    plane["mwrld_texture_sha256"] = texture_sha
    plane["mwrld_job_id"] = str(opts.get("job-id", ""))
    plane["mwrld_uv_convention"] = "UV(0,0)=bottom-left seen from outside (u=0,v=0); UV(1,1)=top-right; 1 UV unit = widthM x heightM"
    plane["mwrld_texture_scale"] = json.dumps({"widthM": surface["widthM"], "heightM": surface["heightM"],
                                               "pixelsPerMeter": provenance.get("texture", {}).get("pixelsPerMeter")})
    plane["mwrld_sources"] = json.dumps([{"captureId": s["captureId"], "imageSha256": s["imageSha256"], "alignment": s["alignment"]["method"]}
                                         for s in provenance.get("sources", [])])
    plane["mwrld_coverage_percent"] = json.dumps(coverage.get("percent", {}))
    plane["mwrld_offset_m"] = OFFSET_M

    # architectural details: reviewed -> geometry; proposed -> hidden wire boxes for inspection
    details_path = result_dir / "surface-details.json"
    counts = {"reviewed": 0, "proposed": 0}
    prefix = f"{name}__feature_"
    for obj in [o for o in bpy.data.objects if o.name.startswith(prefix)]:
        remove_object(obj.name)
    if details_path.exists():
        details = json.loads(details_path.read_text())
        for feature in details.get("features", []):
            if feature["blender"]["operation"] not in ("inset", "extrude") or feature["status"] == "rejected":
                continue
            reviewed = feature["status"] == "reviewed"
            coll = collection(REVIEWED_COLLECTION if reviewed else PROPOSED_COLLECTION)
            box = feature_box(surface, feature, f"{prefix}{feature['featureId']}", coll, reviewed)
            box["mwrld_surface_id"] = surface["surfaceId"]
            counts["reviewed" if reviewed else "proposed"] += 1

    after = mesh_hash(building)
    if before != after:
        raise SystemExit("building mesh changed during facade application; not saving")
    if opts.get("preview"):
        # render only this wall's facade objects: existing trim/shutters (which project more than the
        # 3 cm offset) and neighbouring geometry would otherwise hide the texture the phone wants to see
        keep = {plane.name} | {o.name for o in bpy.data.objects if o.name.startswith(f"{name}__feature_")}
        hidden = {o.name: o.hide_render for o in bpy.data.objects}
        for o in bpy.data.objects:
            o.hide_render = o.name not in keep or hidden[o.name]
        try:
            render_preview(surface, [plane], Path(opts["preview"]).resolve())
        finally:
            for o in bpy.data.objects:
                if o.name in hidden:
                    o.hide_render = hidden[o.name]
    out_blend.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(out_blend), copy=True, relative_remap=True)
    report = {"surfaceId": surface["surfaceId"], "object": name, "textureSha256": texture_sha, "buildingMeshHash": after,
              "buildingMeshUnchanged": True, "features": counts, "outBlend": str(out_blend),
              "facadeObjects": len([o for o in bpy.data.objects if o.name.startswith("mwrld_facade__") and "__feature_" not in o.name])}
    print("FACADE_REPORT " + json.dumps(report))


main()
