import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
REPORT_PATH = MODEL_DIR / "reports" / "model-law-audit-report.json"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def object_matches(obj, query):
    haystack = " ".join(
        [
            obj.name,
            obj.get("mwrld_name", ""),
            obj.get("mwrld_osm_id", ""),
            obj.get("mwrld_osm_way_id", ""),
        ]
    ).lower()
    return query.lower() in haystack


def managed_buildings(query):
    buildings = [
        obj
        for obj in bpy.context.scene.objects
        if obj.type == "MESH" and obj.get("mwrld_category") == "building" and obj.get("mwrld_osm_id")
    ]
    if query == "all":
        return sorted(buildings, key=lambda obj: obj.name.lower())
    matches = [obj for obj in buildings if object_matches(obj, query)]
    if not matches:
        raise SystemExit(f"No named building matched: {query}")
    return sorted(matches, key=lambda obj: obj.name.lower())


def edge_face_counts(mesh):
    counts = {}
    for polygon in mesh.polygons:
        for edge_key in polygon.edge_keys:
            key = tuple(sorted(edge_key))
            counts[key] = counts.get(key, 0) + 1
    return counts


def t_junction_suspects(mesh):
    if len(mesh.vertices) > 1200 or len(mesh.edges) > 2200:
        return "skipped-large-mesh"
    vertices = [vertex.co.copy() for vertex in mesh.vertices]
    suspects = 0
    epsilon = 0.002
    for edge in mesh.edges:
        a_index, b_index = edge.vertices
        a = vertices[a_index]
        b = vertices[b_index]
        ab = b - a
        length_squared = ab.length_squared
        if length_squared <= 0:
            continue
        for index, point in enumerate(vertices):
            if index in {a_index, b_index}:
                continue
            t = (point - a).dot(ab) / length_squared
            if t <= epsilon or t >= 1 - epsilon:
                continue
            closest = a + ab * t
            if (closest - point).length <= epsilon:
                suspects += 1
                break
    return suspects


def topology_stats(obj):
    mesh = obj.data
    edge_counts = edge_face_counts(mesh)
    used_vertices = {vertex for polygon in mesh.polygons for vertex in polygon.vertices}
    loose_vertices = len([vertex for vertex in mesh.vertices if vertex.index not in used_vertices])
    loose_edges = len([edge for edge in mesh.edges if tuple(sorted(edge.vertices)) not in edge_counts])
    triangles = len([polygon for polygon in mesh.polygons if len(polygon.vertices) == 3])
    quads = len([polygon for polygon in mesh.polygons if len(polygon.vertices) == 4])
    ngons = len([polygon for polygon in mesh.polygons if len(polygon.vertices) > 4])
    boundary_edges = len([count for count in edge_counts.values() if count == 1])
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "triangles": triangles,
        "quads": quads,
        "ngons": ngons,
        "looseVertices": loose_vertices,
        "looseEdges": loose_edges,
        "boundaryEdges": boundary_edges,
        "nonManifoldEdges": loose_edges + len([count for count in edge_counts.values() if count != 2]),
        "tJunctionSuspects": t_junction_suspects(mesh),
    }


def world_bounds(obj):
    coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def bottom_footprint(obj):
    min_v, _ = world_bounds(obj)
    eps = 0.05
    points = []
    for vertex in obj.data.vertices:
        co = obj.matrix_world @ vertex.co
        if abs(co.z - min_v.z) <= eps:
            points.append(Vector((co.x, co.y, 0)))
    unique = {(round(point.x, 3), round(point.y, 3)): point for point in points}
    points = list(unique.values())
    if len(points) < 3:
        return []
    center = sum(points, Vector()) / len(points)
    return sorted(points, key=lambda point: math.atan2(point.y - center.y, point.x - center.x))


def point_in_polygon(point, polygon, tolerance=0.0):
    if not polygon:
        return False
    x = point.x
    y = point.y
    inside = False
    count = len(polygon)
    for index in range(count):
        a = polygon[index]
        b = polygon[(index + 1) % count]
        if distance_point_to_segment_2d(point, a, b) <= tolerance:
            return True
        crosses = (a.y > y) != (b.y > y)
        if crosses:
            x_intersect = (b.x - a.x) * (y - a.y) / ((b.y - a.y) or 1e-9) + a.x
            if x < x_intersect:
                inside = not inside
    return inside


def distance_point_to_segment_2d(point, a, b):
    ap = Vector((point.x - a.x, point.y - a.y, 0))
    ab = Vector((b.x - a.x, b.y - a.y, 0))
    length_squared = ab.length_squared
    if length_squared <= 0:
        return ap.length
    t = max(0.0, min(1.0, ap.dot(ab) / length_squared))
    closest = a + ab * t
    return (Vector((point.x, point.y, 0)) - closest).length


def bbox_bottom_points(obj):
    min_v, max_v = world_bounds(obj)
    return [
        Vector((min_v.x, min_v.y, min_v.z)),
        Vector((max_v.x, min_v.y, min_v.z)),
        Vector((max_v.x, max_v.y, min_v.z)),
        Vector((min_v.x, max_v.y, min_v.z)),
        Vector(((min_v.x + max_v.x) / 2, (min_v.y + max_v.y) / 2, min_v.z)),
    ]


def details_for(building):
    target = building.get("mwrld_osm_id", building.name)
    return sorted(
        [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and obj.get("mwrld_detail_for") == target],
        key=lambda obj: obj.name.lower(),
    )


def load_rules(building):
    folder = MODEL_DIR / "renders" / "buildings" / building.name / "references" / "modeling-rules.json"
    if not folder.exists():
        return None
    return json.loads(folder.read_text())


def vertical_supports(building, details):
    surfaces = []
    surfaces.extend(upward_support_surfaces(building))
    for obj in details:
        obj_min, obj_max = world_bounds(obj)
        surfaces.extend(upward_support_surfaces(obj))
        surfaces.append({"name": obj.name, "topZ": obj_max.z, "footprint": bbox_bottom_points(obj), "plane": None})
    return surfaces


def upward_support_surfaces(obj):
    surfaces = []
    for poly in obj.data.polygons:
        coords = [obj.matrix_world @ obj.data.vertices[index].co for index in poly.vertices]
        if len(coords) < 3:
            continue
        if poly.normal.z < 0:
            continue
        normal = (coords[1] - coords[0]).cross(coords[2] - coords[0])
        if normal.length <= 0 or abs(normal.z) <= 1e-6:
            continue
        normal.normalize()
        footprint = [Vector((co.x, co.y, 0)) for co in coords]
        surfaces.append(
            {
                "name": f"{obj.name}:face:{poly.index}",
                "topZ": sum(co.z for co in coords) / len(coords),
                "footprint": footprint,
                "plane": {"point": coords[0], "normal": normal},
            }
        )
    if not surfaces:
        min_v, max_v = world_bounds(obj)
        surfaces.append({"name": obj.name, "topZ": max_v.z, "footprint": bottom_footprint(obj), "plane": None})
    return surfaces


def has_support(obj, surfaces, gap_tolerance, xy_tolerance):
    obj_min, obj_max = world_bounds(obj)
    point = Vector(((obj_min.x + obj_max.x) / 2, (obj_min.y + obj_max.y) / 2, 0))
    support_hits = []
    for surface in surfaces:
        if surface["name"] == obj.name:
            continue
        support_z = surface["topZ"]
        plane = surface.get("plane")
        if plane:
            normal = plane["normal"]
            point_on_plane = plane["point"]
            support_z = point_on_plane.z - (normal.x * (point.x - point_on_plane.x) + normal.y * (point.y - point_on_plane.y)) / normal.z
        z_gap = obj_min.z - support_z
        if -gap_tolerance <= z_gap <= gap_tolerance and point_in_polygon(point, surface["footprint"], xy_tolerance):
            support_hits.append({"support": surface["name"], "zGap": round(z_gap, 4)})
    return support_hits


def bbox_side_contact(obj, others, gap_tolerance):
    obj_min, obj_max = world_bounds(obj)
    hits = []
    for other in others:
        if other.name == obj.name:
            continue
        other_min, other_max = world_bounds(other)
        z_overlap = min(obj_max.z, other_max.z) - max(obj_min.z, other_min.z)
        y_overlap = min(obj_max.y, other_max.y) - max(obj_min.y, other_min.y)
        x_overlap = min(obj_max.x, other_max.x) - max(obj_min.x, other_min.x)
        touches_x = abs(obj_min.x - other_max.x) <= gap_tolerance or abs(obj_max.x - other_min.x) <= gap_tolerance
        touches_y = abs(obj_min.y - other_max.y) <= gap_tolerance or abs(obj_max.y - other_min.y) <= gap_tolerance
        if z_overlap > 0 and ((touches_x and y_overlap > 0) or (touches_y and x_overlap > 0)):
            hits.append(other.name)
    return hits


def audit_building(building, strict):
    rules = load_rules(building)
    details = details_for(building)
    objects = [building] + details
    findings = []
    footprint = bottom_footprint(building)
    supports = vertical_supports(building, details)
    gap_tolerance = 0.08
    xy_tolerance = 0.35

    for obj in objects:
        stats = topology_stats(obj)
        if stats["looseVertices"] or stats["looseEdges"]:
            findings.append({"severity": "fail", "law": "clean-geometry", "object": obj.name, "message": "Loose vertices/edges found.", "stats": stats})
        roof_cap_exception = (
            obj == building
            and obj.get("mwrld_roof_cap_status") == "source_footprint_cap_pending_approved_subdivision"
            and stats["ngons"] <= 1
        )
        if stats["ngons"] and not roof_cap_exception:
            findings.append({"severity": "fail" if strict else "warn", "law": "clean-geometry", "object": obj.name, "message": "N-gons found.", "stats": stats})
        elif roof_cap_exception:
            findings.append({"severity": "warn", "law": "clean-geometry", "object": obj.name, "message": "Temporary source roof-cap n-gon retained to avoid fake fan-triangle artifacts.", "stats": stats})
        if stats["tJunctionSuspects"] not in {0, "skipped-large-mesh"}:
            findings.append({"severity": "warn", "law": "clean-geometry", "object": obj.name, "message": "Possible T-junctions found.", "stats": stats})

    for obj in details:
        kind = obj.get("mwrld_detail_kind", "")
        obj_min, obj_max = world_bounds(obj)
        building_min, building_max = world_bounds(building)
        if kind in {"window", "window_panel", "door", "door_panel"}:
            findings.append({"severity": "fail", "law": "no-floating-openings", "object": obj.name, "message": "Windows and doors must be wall faces, not separate objects."})
        bottom_points = bbox_bottom_points(obj)
        is_on_main_roof = abs(obj_min.z - building_max.z) <= gap_tolerance
        outside = [point for point in bottom_points if not point_in_polygon(point, footprint, xy_tolerance)]
        bbox_inside = (
            obj_min.x >= building_min.x - xy_tolerance
            and obj_max.x <= building_max.x + xy_tolerance
            and obj_min.y >= building_min.y - xy_tolerance
            and obj_max.y <= building_max.y + xy_tolerance
        )
        if is_on_main_roof and outside and not (kind == "roof" and bbox_inside) and kind not in {"spire", "weathervane"}:
            findings.append({"severity": "fail", "law": "stay-on-wall-footprint", "object": obj.name, "message": "Detail bottom projects outside the building footprint."})
        support_hits = has_support(obj, supports, gap_tolerance, xy_tolerance)
        side_hits = bbox_side_contact(obj, [building] + details, gap_tolerance)
        if not support_hits and not side_hits and kind not in {"spire", "weathervane"}:
            findings.append({"severity": "fail", "law": "no-floating-objects", "object": obj.name, "message": "No supporting surface found directly under this object."})

    if rules:
        face_sources = json.loads(building.data.get("mwrld_face_reference_sources", "[]"))
        approved = set(rules.get("windowsAndDoors", {}).get("approvedWallSources", []))
        blocked = set(rules.get("windowsAndDoors", {}).get("blockedWallSources", []))
        openings = [item for item in face_sources if item.get("kind") in {"window", "door"}]
        if rules.get("windowsAndDoors", {}).get("mustBeIntegratedWallFaces") and not openings:
            findings.append({"severity": "fail", "law": "windows-doors-integrated", "object": building.name, "message": "No integrated window/door wall faces found."})
        for item in openings:
            source = item.get("source")
            if source in blocked or source not in approved:
                findings.append({"severity": "fail", "law": "follow-reference", "object": building.name, "message": f"Opening face uses unsupported reference source {source!r}.", "face": item.get("face")})
        if rules.get("windowsAndDoors", {}).get("countsMustMatchReferencePerWall"):
            actual_counts = json.loads(building.data.get("mwrld_wall_opening_counts", "{}"))
            for wall_id, plan in rules.get("windowsAndDoors", {}).get("wallOpeningPlans", {}).items():
                actual = actual_counts.get(wall_id, {"windows": 0, "doors": 0})
                expected_windows = int(plan.get("windows", 0))
                expected_doors = int(plan.get("doors", 0))
                if actual.get("windows", 0) != expected_windows:
                    findings.append(
                        {
                            "severity": "fail",
                            "law": "opening-counts-match-reference",
                            "object": building.name,
                            "message": f"{wall_id} has {actual.get('windows', 0)} windows, expected {expected_windows}.",
                            "reference": plan.get("reference"),
                        }
                    )
                if actual.get("doors", 0) != expected_doors:
                    findings.append(
                        {
                            "severity": "fail",
                            "law": "opening-counts-match-reference",
                            "object": building.name,
                            "message": f"{wall_id} has {actual.get('doors', 0)} doors, expected {expected_doors}.",
                            "reference": plan.get("reference"),
                        }
                    )

        material_names = [mat.name for mat in building.data.materials]
        material_counts = {}
        for polygon in building.data.polygons:
            name = material_names[polygon.material_index] if polygon.material_index < len(material_names) else "none"
            material_counts[name] = material_counts.get(name, 0) + 1
        for material_name in rules.get("roof", {}).get("requiredMaterials", []):
            if not material_counts.get(material_name):
                findings.append({"severity": "fail", "law": "roof-reference", "object": building.name, "message": f"Required roof zone/material missing: {material_name}"})
        detail_kinds = {obj.get("mwrld_detail_kind", "") for obj in details}
        for required_kind in rules.get("roof", {}).get("requiredDetailKinds", []):
            if required_kind not in detail_kinds:
                findings.append({"severity": "fail", "law": "roof-reference", "object": building.name, "message": f"Required roof detail kind missing: {required_kind}"})
        tower_rules = rules.get("tower", {})
        approved_tower_sources = set(tower_rules.get("approvedTowerSources", []))
        if tower_rules.get("mustHaveProperTowerReferences"):
            reference_manifest = tower_rules.get("referenceManifest")
            if not reference_manifest or not (MODEL_DIR / "renders" / "buildings" / building.name / reference_manifest).exists():
                findings.append({"severity": "fail", "law": "tower-reference", "object": building.name, "message": "Tower reference manifest is missing."})
            for source in approved_tower_sources:
                if not (MODEL_DIR / "renders" / "buildings" / building.name / source).exists():
                    findings.append({"severity": "fail", "law": "tower-reference", "object": building.name, "message": f"Approved tower source is missing: {source}"})
        for required_kind in tower_rules.get("requiredDetailKinds", []):
            matches = [obj for obj in details if obj.get("mwrld_detail_kind") == required_kind]
            if not matches:
                findings.append({"severity": "fail", "law": "tower-reference", "object": building.name, "message": f"Required tower detail kind missing: {required_kind}"})
            for obj in matches:
                source = obj.get("mwrld_reference_source")
                if source not in approved_tower_sources:
                    findings.append({"severity": "fail", "law": "tower-reference", "object": obj.name, "message": f"Tower detail uses unsupported reference source {source!r}."})
    else:
        findings.append({"severity": "warn", "law": "follow-reference", "object": building.name, "message": "No building-specific modeling-rules.json found."})

    return {
        "building": building.name,
        "displayName": building.get("mwrld_name", building.name),
        "osmId": building.get("mwrld_osm_id", ""),
        "rules": str((MODEL_DIR / "renders" / "buildings" / building.name / "references" / "modeling-rules.json").relative_to(ROOT)) if rules else None,
        "objectsAudited": len(objects),
        "findings": findings,
        "passed": not any(item["severity"] == "fail" for item in findings),
    }


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    query = args[1] if len(args) > 1 and not args[1].startswith("--") else "baker-library"
    strict = "--strict" in args

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    targets = [audit_building(building, strict) for building in managed_buildings(query)]
    report = {
        "sourceBlend": str(blend_path.relative_to(ROOT) if blend_path.is_relative_to(ROOT) else blend_path),
        "query": query,
        "strict": strict,
        "laws": [
            "clean-geometry",
            "roof-supported-and-reference-declared",
            "tower-and-details-stay-on-wall-footprint",
            "no-unnecessary-gaps-between-supported-objects",
            "no-floating-window-door-panels",
            "follow-approved-exterior-references",
        ],
        "targets": targets,
        "passed": all(target["passed"] for target in targets),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    total_failures = sum(1 for target in targets for finding in target["findings"] if finding["severity"] == "fail")
    total_warnings = sum(1 for target in targets for finding in target["findings"] if finding["severity"] == "warn")
    print(json.dumps({"passed": report["passed"], "targets": len(targets), "failures": total_failures, "warnings": total_warnings, "report": str(REPORT_PATH.relative_to(ROOT))}, indent=2))
    if total_failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
