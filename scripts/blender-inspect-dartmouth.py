import csv
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
REPORTS_DIR = MODEL_DIR / "reports"


def mesh_bounds(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_v = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    max_v = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    return min_v, max_v


def bounds_for(objects):
    mins = []
    maxs = []
    for obj in objects:
        min_v, max_v = mesh_bounds(obj)
        mins.append(min_v)
        maxs.append(max_v)
    if not mins:
        return Vector((0, 0, 0)), Vector((0, 0, 0))
    return (
        Vector((min(v.x for v in mins), min(v.y for v in mins), min(v.z for v in mins))),
        Vector((max(v.x for v in maxs), max(v.y for v in maxs), max(v.z for v in maxs))),
    )


def make_material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def set_material(obj, mat):
    obj.data.materials.clear()
    obj.data.materials.append(mat)


def classify(obj):
    dims = obj.dimensions
    if dims.z > 0.5 and dims.x > 0.1 and dims.y > 0.1:
        return "building"
    if dims.z <= 0.5:
        return "road_or_path"
    return "other_mesh"


def region_for(center, campus_min, campus_max):
    mid_x = (campus_min.x + campus_max.x) / 2
    mid_y = (campus_min.y + campus_max.y) / 2
    east_west = "east" if center.x >= mid_x else "west"
    north_south = "north" if center.y >= mid_y else "south"
    return f"{north_south}_{east_west}"


def add_or_update_camera(name, location, target, ortho_scale, clip_end):
    camera = bpy.data.objects.get(name)
    if camera is None:
        bpy.ops.object.camera_add(location=location)
        camera = bpy.context.object
        camera.name = name
    else:
        camera.location = location
    direction = target - Vector(location)
    camera.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = ortho_scale
    camera.data.clip_start = 0.1
    camera.data.clip_end = clip_end
    return camera


def add_or_update_light(name, location, size, energy):
    light = bpy.data.objects.get(name)
    if light is None:
        bpy.ops.object.light_add(type="AREA", location=location)
        light = bpy.context.object
        light.name = name
    else:
        light.location = location
    light.data.size = size
    light.data.energy = energy
    return light


def write_reports(rows, buildings, roads, campus_min, campus_max):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    csv_path = REPORTS_DIR / "building-index.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "name",
                "region",
                "center_x",
                "center_y",
                "min_z",
                "height",
                "width",
                "depth",
                "footprint_area",
                "vertices",
                "faces",
            ],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in writer.fieldnames})

    json_path = REPORTS_DIR / "object-index.json"
    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    by_region = {}
    for row in rows:
        by_region.setdefault(row["region"], []).append(row)
    for region_rows in by_region.values():
        region_rows.sort(key=lambda r: r["footprint_area"], reverse=True)

    largest = sorted(rows, key=lambda r: r["footprint_area"], reverse=True)[:35]
    tallest = sorted(rows, key=lambda r: r["height"], reverse=True)[:20]

    lines = [
        "# Dartmouth Energy Twin Modeling Plan",
        "",
        "## Scene Snapshot",
        "",
        f"- Local blend: `{BLEND_PATH.relative_to(ROOT)}`",
        f"- Building candidates: {len(buildings)}",
        f"- Road/path candidates: {len(roads)}",
        f"- Building bounds min: ({campus_min.x:.2f}, {campus_min.y:.2f}, {campus_min.z:.2f})",
        f"- Building bounds max: ({campus_max.x:.2f}, {campus_max.y:.2f}, {campus_max.z:.2f})",
        "",
        "## Recommended Modeling Order",
        "",
        "1. Start with the largest central landmarks so the campus reads correctly from far away.",
        "2. Add roof forms and height corrections before facade detail.",
        "3. Work one region at a time using crop renders: northwest, northeast, southwest, southeast.",
        "4. Keep roads/paths as context until building massing is stable.",
        "5. Export web-ready GLB only after each region has clean naming, scale, and materials.",
        "",
        "## Largest Building Candidates",
        "",
    ]

    for row in largest:
        lines.append(
            f"- `{row['name']}` [{row['region']}]: "
            f"{row['width']:.1f} x {row['depth']:.1f} x {row['height']:.1f}, "
            f"center=({row['center_x']:.1f}, {row['center_y']:.1f})"
        )

    lines.extend(["", "## Tallest Building Candidates", ""])
    for row in tallest:
        lines.append(
            f"- `{row['name']}` [{row['region']}]: height={row['height']:.1f}, "
            f"footprint={row['footprint_area']:.0f}"
        )

    lines.extend(["", "## Regional Work Queues", ""])
    for region in ["north_west", "north_east", "south_west", "south_east"]:
        region_rows = by_region.get(region, [])
        lines.extend(["", f"### {region.replace('_', ' ').title()}", ""])
        for row in region_rows[:15]:
            lines.append(
                f"- `{row['name']}`: footprint={row['footprint_area']:.0f}, "
                f"height={row['height']:.1f}, center=({row['center_x']:.1f}, {row['center_y']:.1f})"
            )

    (REPORTS_DIR / "modeling-plan.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    blend_path = Path(sys.argv[sys.argv.index("--") + 1]).resolve() if "--" in sys.argv else BLEND_PATH
    if not blend_path.exists():
        raise SystemExit(f"Blend file not found: {blend_path}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    mesh_objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    buildings = [obj for obj in mesh_objects if classify(obj) == "building"]
    roads = [obj for obj in mesh_objects if classify(obj) == "road_or_path"]
    campus_min, campus_max = bounds_for(buildings)
    center = (campus_min + campus_max) * 0.5
    size = max((campus_max - campus_min).length, 1.0)

    building_mat = make_material("MWRLD_building_clay", (0.66, 0.65, 0.61, 1.0))
    road_mat = make_material("MWRLD_roads_paths_dark", (0.22, 0.23, 0.22, 1.0))
    other_mat = make_material("MWRLD_other_context", (0.38, 0.40, 0.42, 1.0))

    rows = []
    for obj in mesh_objects:
        obj_type = classify(obj)
        if obj_type == "building":
            set_material(obj, building_mat)
        elif obj_type == "road_or_path":
            set_material(obj, road_mat)
        else:
            set_material(obj, other_mat)

        min_v, max_v = mesh_bounds(obj)
        obj_center = (min_v + max_v) * 0.5
        dims = obj.dimensions
        row = {
            "name": obj.name,
            "type": obj_type,
            "region": region_for(obj_center, campus_min, campus_max),
            "center_x": round(obj_center.x, 3),
            "center_y": round(obj_center.y, 3),
            "center_z": round(obj_center.z, 3),
            "min_x": round(min_v.x, 3),
            "min_y": round(min_v.y, 3),
            "min_z": round(min_v.z, 3),
            "max_x": round(max_v.x, 3),
            "max_y": round(max_v.y, 3),
            "max_z": round(max_v.z, 3),
            "height": round(dims.z, 3),
            "width": round(dims.x, 3),
            "depth": round(dims.y, 3),
            "footprint_area": round(dims.x * dims.y, 3),
            "vertices": len(obj.data.vertices),
            "faces": len(obj.data.polygons),
        }
        if obj_type == "building":
            rows.append(row)

    add_or_update_light(
        "MWRLD_preview_area_light",
        (center.x - size * 0.25, center.y - size * 0.35, campus_max.z + size * 0.45),
        size * 0.35,
        max(700, size * 20),
    )
    add_or_update_camera(
        "MWRLD_cam_campus_iso",
        (center.x + size * 0.35, center.y - size * 0.45, campus_max.z + size * 0.65),
        center,
        max(campus_max.x - campus_min.x, campus_max.y - campus_min.y) * 1.15,
        max(size * 4, 10000),
    )
    add_or_update_camera(
        "MWRLD_cam_campus_top",
        (center.x, center.y, campus_max.z + size),
        center,
        max(campus_max.x - campus_min.x, campus_max.y - campus_min.y) * 1.1,
        max(size * 4, 10000),
    )

    write_reports(rows, buildings, roads, campus_min, campus_max)
    bpy.context.scene.camera = bpy.data.objects.get("MWRLD_cam_campus_iso")
    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))


if __name__ == "__main__":
    main()
