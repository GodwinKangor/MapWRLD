from mathutils import Vector


def topology_stats(obj):
    mesh = obj.data
    edge_counts = {}
    for polygon in mesh.polygons:
        for edge_key in polygon.edge_keys:
            key = tuple(sorted(edge_key))
            edge_counts[key] = edge_counts.get(key, 0) + 1
    used_vertices = {vertex for polygon in mesh.polygons for vertex in polygon.vertices}
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "triangles": len([polygon for polygon in mesh.polygons if len(polygon.vertices) == 3]),
        "quads": len([polygon for polygon in mesh.polygons if len(polygon.vertices) == 4]),
        "ngons": len([polygon for polygon in mesh.polygons if len(polygon.vertices) > 4]),
        "looseVertices": len([vertex for vertex in mesh.vertices if vertex.index not in used_vertices]),
        "looseEdges": len([edge for edge in mesh.edges if tuple(sorted(edge.vertices)) not in edge_counts]),
        "boundaryEdges": len([count for count in edge_counts.values() if count == 1]),
        "nonManifoldEdges": len([count for count in edge_counts.values() if count != 2]),
    }


def object_bounds(obj):
    coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return {
        "min": [min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords)],
        "max": [max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords)],
    }


def inspect_detail_object(obj):
    return {
        "name": obj.name,
        "module": obj.get("mwrld_module", ""),
        "reference": obj.get("mwrld_reference", ""),
        "wallId": obj.get("mwrld_wall_id", ""),
        "bounds": object_bounds(obj),
        "topology": topology_stats(obj),
    }


def validate_clean_quads(obj, allow_triangles=False):
    stats = topology_stats(obj)
    issues = []
    if stats["ngons"]:
        issues.append(f"{obj.name}: {stats['ngons']} n-gons")
    if stats["triangles"] and not allow_triangles:
        issues.append(f"{obj.name}: {stats['triangles']} triangles")
    if stats["looseVertices"] or stats["looseEdges"]:
        issues.append(f"{obj.name}: loose geometry")
    return issues
