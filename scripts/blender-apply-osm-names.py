import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
OSM_PATH = MODEL_DIR / "reports" / "osm-campus-names.json"
REPORT_PATH = MODEL_DIR / "reports" / "osm-name-matches.json"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "unnamed"


def mesh_center(obj):
    corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    min_v = Vector((min(v.x for v in corners), min(v.y for v in corners), min(v.z for v in corners)))
    max_v = Vector((max(v.x for v in corners), max(v.y for v in corners), max(v.z for v in corners)))
    return (min_v + max_v) * 0.5


def object_bounds(objects):
    centers = [mesh_center(obj) for obj in objects]
    return (
        Vector((min(v.x for v in centers), min(v.y for v in centers), min(v.z for v in centers))),
        Vector((max(v.x for v in centers), max(v.y for v in centers), max(v.z for v in centers))),
    )


def projected_xy(record, bounds, min_v, max_v):
    lon = record["centroid"]["longitude"]
    lat = record["centroid"]["latitude"]
    x_ratio = (lon - bounds["west"]) / (bounds["east"] - bounds["west"])
    y_ratio = (lat - bounds["south"]) / (bounds["north"] - bounds["south"])
    return Vector((
        min_v.x + x_ratio * (max_v.x - min_v.x),
        min_v.y + y_ratio * (max_v.y - min_v.y),
        0,
    ))


def nearest_unmatched(obj, candidates, used_ids, bounds, min_v, max_v):
    center = mesh_center(obj)
    best = None
    best_distance = math.inf
    for candidate in candidates:
        if candidate["osmId"] in used_ids:
            continue
        point = projected_xy(candidate, bounds, min_v, max_v)
        distance = math.hypot(center.x - point.x, center.y - point.y)
        if distance < best_distance:
            best = candidate
            best_distance = distance
    return best, best_distance


def apply_name(obj, category, record, distance):
    original_name = obj.get("mwrld_original_name", obj.name)
    label = record["name"]
    way_id = str(record["wayId"])
    prefix = "building" if category == "building" else "road"
    obj.name = f"{prefix}__{slugify(label)}__way_{way_id}"
    obj.data.name = obj.name
    obj["mwrld_original_name"] = original_name
    obj["mwrld_category"] = category
    obj["mwrld_name"] = label
    obj["mwrld_osm_id"] = record["osmId"]
    obj["mwrld_osm_way_id"] = way_id
    obj["mwrld_has_real_name"] = bool(record.get("hasRealName"))
    obj["mwrld_match_distance"] = round(distance, 3)
    return {
        "originalName": original_name,
        "newName": obj.name,
        "category": category,
        "displayName": label,
        "osmId": record["osmId"],
        "hasRealName": bool(record.get("hasRealName")),
        "matchDistance": round(distance, 3),
    }


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    osm_path = Path(args[1]).resolve() if len(args) > 1 else OSM_PATH

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    osm = json.loads(osm_path.read_text(encoding="utf-8"))
    bounds = osm["bounds"]

    objects = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    named_building_objects = [obj for obj in objects if obj.get("mwrld_category") == "building" and obj.get("mwrld_osm_id")]
    named_road_objects = [obj for obj in objects if obj.get("mwrld_category") == "road" and obj.get("mwrld_osm_id")]

    matches = []
    used_buildings = set()
    used_roads = set()

    if named_building_objects or named_road_objects:
        records_by_id = {
            "building": {record["osmId"]: record for record in osm["buildings"]},
            "road": {record["osmId"]: record for record in osm["roads"]},
        }

        for category, categorized_objects, used_ids in (
            ("building", named_building_objects, used_buildings),
            ("road", named_road_objects, used_roads),
        ):
            for obj in sorted(categorized_objects, key=lambda item: item.name.lower()):
                record = records_by_id[category].get(obj.get("mwrld_osm_id"))
                if not record:
                    continue
                used_ids.add(record["osmId"])
                matches.append(apply_name(obj, category, record, obj.get("mwrld_match_distance", 0)))
    else:
        building_objects = sorted(
            [obj for obj in objects if obj.name.startswith("Areas") and obj.dimensions.z > 0.5],
            key=lambda obj: obj.name.lower(),
        )
        road_objects = sorted(
            [obj for obj in objects if obj.name.startswith("Ways")],
            key=lambda obj: natural_key(obj.name),
        )
        building_min, building_max = object_bounds(building_objects)
        road_min, road_max = object_bounds(road_objects)

        for obj in building_objects:
            record, distance = nearest_unmatched(obj, osm["buildings"], used_buildings, bounds, building_min, building_max)
            if record:
                used_buildings.add(record["osmId"])
                matches.append(apply_name(obj, "building", record, distance))

        for obj in road_objects:
            record, distance = nearest_unmatched(obj, osm["roads"], used_roads, bounds, road_min, road_max)
            if record:
                used_roads.add(record["osmId"])
                matches.append(apply_name(obj, "road", record, distance))

    for obj in objects:
        if obj.name == "Cube":
            obj["mwrld_category"] = "context"
        elif obj.name.startswith("Areas") and obj.dimensions.z <= 0.5:
            obj["mwrld_category"] = "area_context"

    REPORT_PATH.write_text(json.dumps({
        "sourceBlend": str(blend_path.relative_to(ROOT)),
        "sourceOsm": str(osm_path.relative_to(ROOT)),
        "matchedBuildings": len(used_buildings),
        "matchedRoads": len(used_roads),
        "unmatchedBuildings": len(osm["buildings"]) - len(used_buildings),
        "unmatchedRoads": len(osm["roads"]) - len(used_roads),
        "matches": matches,
    }, indent=2), encoding="utf-8")

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    print(f"Matched buildings: {len(used_buildings)}")
    print(f"Matched roads: {len(used_roads)}")


def natural_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


if __name__ == "__main__":
    main()
