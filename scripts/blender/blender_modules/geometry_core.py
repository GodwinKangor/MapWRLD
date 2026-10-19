from mathutils import Vector
import bpy


def ensure_material(name, color):
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.diffuse_color = color
    return mat


def local_bounds(obj):
    coords = [vertex.co.copy() for vertex in obj.data.vertices]
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def world_bounds(obj):
    coords = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    return (
        Vector((min(v.x for v in coords), min(v.y for v in coords), min(v.z for v in coords))),
        Vector((max(v.x for v in coords), max(v.y for v in coords), max(v.z for v in coords))),
    )


def create_mesh_object(name, verts, faces, material=None, collection=None):
    mesh = bpy.data.meshes.new(f"{name}_mesh")
    mesh.from_pydata(verts, [], faces)
    mesh.update(calc_edges=True)
    obj = bpy.data.objects.new(name, mesh)
    if material is not None:
        obj.data.materials.append(material)
    (collection or bpy.context.collection).objects.link(obj)
    return obj


def assign_detail_metadata(obj, building, module, reference=None, wall_id=None):
    target = building.get("mwrld_osm_id", building.name) if building is not None else ""
    obj["mwrld_detail_for"] = target
    obj["mwrld_module"] = module
    if reference:
        obj["mwrld_reference"] = reference
    if wall_id:
        obj["mwrld_wall_id"] = wall_id
    return obj


def rectangle_box(name, min_x, max_x, min_y, max_y, min_z, max_z, material=None, collection=None):
    verts = [
        (min_x, min_y, min_z),
        (max_x, min_y, min_z),
        (max_x, max_y, min_z),
        (min_x, max_y, min_z),
        (min_x, min_y, max_z),
        (max_x, min_y, max_z),
        (max_x, max_y, max_z),
        (min_x, max_y, max_z),
    ]
    faces = [
        (0, 1, 2, 3),
        (4, 7, 6, 5),
        (0, 4, 5, 1),
        (1, 5, 6, 2),
        (2, 6, 7, 3),
        (3, 7, 4, 0),
    ]
    return create_mesh_object(name, verts, faces, material, collection)


def bottom_edges(obj, min_v=None, min_length=0.5, z_epsilon=0.02):
    if min_v is None:
        min_v, _ = local_bounds(obj)
    edges = []
    for edge in obj.data.edges:
        a = obj.data.vertices[edge.vertices[0]].co
        b = obj.data.vertices[edge.vertices[1]].co
        if abs(a.z - min_v.z) <= z_epsilon and abs(b.z - min_v.z) <= z_epsilon and (a.xy - b.xy).length >= min_length:
            edges.append((a.copy(), b.copy()))
    return edges


def side_for_edge(a, b, min_v, max_v):
    mid = (a + b) * 0.5
    distances = {
        "south": abs(mid.y - min_v.y),
        "north": abs(mid.y - max_v.y),
        "west": abs(mid.x - min_v.x),
        "east": abs(mid.x - max_v.x),
    }
    return min(distances, key=distances.get)

