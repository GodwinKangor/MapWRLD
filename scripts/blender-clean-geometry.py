import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
REPORT_PATH = MODEL_DIR / "reports" / "geometry-cleanup-report.json"


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


def cleanup_set_for(building):
    osm_id = building.get("mwrld_osm_id", "")
    objects = [building]
    if osm_id:
        objects.extend(
            obj
            for obj in bpy.context.scene.objects
            if obj.type == "MESH" and obj.get("mwrld_detail_for") == osm_id
        )
    return sorted(objects, key=lambda obj: obj.name.lower())


def edge_face_counts(mesh):
    counts = {}
    for polygon in mesh.polygons:
        for edge_key in polygon.edge_keys:
            key = tuple(sorted(edge_key))
            counts[key] = counts.get(key, 0) + 1
    return counts


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
    non_manifold_edges = loose_edges + len([count for count in edge_counts.values() if count != 2])

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
        "nonManifoldEdges": non_manifold_edges,
        "tJunctionSuspects": t_junction_suspects(mesh),
    }


def t_junction_suspects(mesh):
    # Cheap geometric audit: a vertex lying on an unrelated edge often means
    # loop tools, bevels, and smoothing will behave unpredictably.
    if len(mesh.vertices) > 400 or len(mesh.edges) > 700:
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


def cleanup_mesh(obj, merge_distance):
    mesh = obj.data
    before = topology_stats(obj)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bm.verts.ensure_lookup_table()
    bm.edges.ensure_lookup_table()
    bm.faces.ensure_lookup_table()

    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=merge_distance)

    loose_edges = [edge for edge in bm.edges if not edge.link_faces]
    loose_vertices = [vertex for vertex in bm.verts if not vertex.link_edges]
    if loose_edges:
        bmesh.ops.delete(bm, geom=loose_edges, context="EDGES")
    if loose_vertices:
        bmesh.ops.delete(bm, geom=loose_vertices, context="VERTS")

    bm.faces.ensure_lookup_table()
    triangles = [face for face in bm.faces if len(face.verts) == 3]
    if triangles:
        bmesh.ops.join_triangles(
            bm,
            faces=triangles,
            angle_face_threshold=0.01,
            angle_shape_threshold=0.01,
            cmp_seam=False,
            cmp_sharp=False,
            cmp_uvs=False,
            cmp_vcols=False,
            cmp_materials=True,
        )

    bm.faces.ensure_lookup_table()
    ngons = [face for face in bm.faces if len(face.verts) > 4]
    if ngons:
        bmesh.ops.triangulate(bm, faces=ngons, quad_method="BEAUTY", ngon_method="BEAUTY")

    bm.faces.ensure_lookup_table()
    if bm.faces:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)

    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    after = topology_stats(obj)
    return before, after


def projected_shell_points(obj):
    mesh = obj.data
    points = {}
    for vertex in mesh.vertices:
        key = (round(vertex.co.x, 4), round(vertex.co.y, 4))
        points[key] = Vector((vertex.co.x, vertex.co.y, 0))
    center = sum(points.values(), Vector()) / max(len(points), 1)
    return sorted(
        points.values(),
        key=lambda point: math.atan2(point.y - center.y, point.x - center.x),
    )


def rebuild_quad_wall_shell(obj):
    before = topology_stats(obj)
    mesh = obj.data
    points = projected_shell_points(obj)
    if len(points) < 4:
        return before, before

    min_z = min(vertex.co.z for vertex in mesh.vertices)
    max_z = max(vertex.co.z for vertex in mesh.vertices)
    verts = []
    for point in points:
        verts.append((point.x, point.y, min_z))
        verts.append((point.x, point.y, max_z))

    faces = []
    count = len(points)
    for index in range(count):
        next_index = (index + 1) % count
        faces.append((index * 2, next_index * 2, next_index * 2 + 1, index * 2 + 1))

    mesh.clear_geometry()
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    after = topology_stats(obj)
    return before, after


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    query = args[1] if len(args) > 1 and not args[1].startswith("--") else "baker-library"
    report_only = "--report-only" in args
    quad_shell = "--quad-shell" in args
    merge_distance = 0.001
    for arg in args:
        if arg.startswith("--merge-distance="):
            merge_distance = float(arg.split("=", 1)[1])

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    report = {
        "sourceBlend": str(blend_path.relative_to(ROOT) if blend_path.is_relative_to(ROOT) else blend_path),
        "mode": "report-only" if report_only else "cleanup",
        "mergeDistance": merge_distance,
        "targets": [],
    }

    for building in managed_buildings(query):
        object_reports = []
        for obj in cleanup_set_for(building):
            if report_only:
                before = topology_stats(obj)
                after = before
            elif quad_shell and obj == building:
                before, after = rebuild_quad_wall_shell(obj)
                cleanup_mesh(obj, merge_distance)
                after = topology_stats(obj)
            else:
                before, after = cleanup_mesh(obj, merge_distance)
            object_reports.append(
                {
                    "name": obj.name,
                    "kind": obj.get("mwrld_detail_kind", "building"),
                    "before": before,
                    "after": after,
                }
            )
        report["targets"].append(
            {
                "building": building.name,
                "displayName": building.get("mwrld_name", building.name),
                "osmId": building.get("mwrld_osm_id", ""),
                "objects": object_reports,
            }
        )

    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")

    if not report_only:
        bpy.context.preferences.filepaths.save_version = 1
        bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    changed = 0
    remaining_ngons = 0
    for target in report["targets"]:
        for obj in target["objects"]:
            changed += int(obj["before"] != obj["after"])
            remaining_ngons += obj["after"]["ngons"]
    print(f"Geometry {'audited' if report_only else 'cleaned'} for {len(report['targets'])} building(s).")
    print(f"Objects changed: {changed}. Remaining n-gons: {remaining_ngons}.")


if __name__ == "__main__":
    main()
