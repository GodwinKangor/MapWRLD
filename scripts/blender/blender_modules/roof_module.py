from .geometry_core import assign_detail_metadata, create_mesh_object, rectangle_box


def create_flat_roof(name, min_x, max_x, min_y, max_y, z, thickness, material, building=None, reference=None):
    obj = rectangle_box(name, min_x, max_x, min_y, max_y, z, z + thickness, material)
    assign_detail_metadata(obj, building, "roof", reference=reference)
    obj["mwrld_roof_type"] = "flat"
    return obj


def create_gable_roof(name, min_x, max_x, min_y, max_y, eave_z, ridge_z, axis, material, building=None, reference=None):
    if axis not in {"x", "y"}:
        raise ValueError("axis must be x or y")
    if axis == "x":
        mid_y = (min_y + max_y) * 0.5
        verts = [
            (min_x, min_y, eave_z),
            (max_x, min_y, eave_z),
            (max_x, max_y, eave_z),
            (min_x, max_y, eave_z),
            (min_x, mid_y, ridge_z),
            (max_x, mid_y, ridge_z),
        ]
        faces = [(0, 1, 5, 4), (3, 4, 5, 2), (0, 4, 3), (1, 2, 5), (0, 3, 2, 1)]
    else:
        mid_x = (min_x + max_x) * 0.5
        verts = [
            (min_x, min_y, eave_z),
            (max_x, min_y, eave_z),
            (max_x, max_y, eave_z),
            (min_x, max_y, eave_z),
            (mid_x, min_y, ridge_z),
            (mid_x, max_y, ridge_z),
        ]
        faces = [(0, 4, 5, 3), (1, 2, 5, 4), (0, 1, 4), (3, 5, 2), (0, 3, 2, 1)]
    obj = create_mesh_object(name, verts, faces, material)
    assign_detail_metadata(obj, building, "roof", reference=reference)
    obj["mwrld_roof_type"] = "gable_prism"
    obj["mwrld_roof_axis"] = axis
    return obj


def create_hip_roof(name, min_x, max_x, min_y, max_y, eave_z, ridge_z, inset, material, building=None, reference=None):
    verts = [
        (min_x, min_y, eave_z),
        (max_x, min_y, eave_z),
        (max_x, max_y, eave_z),
        (min_x, max_y, eave_z),
        (min_x + inset, min_y + inset, ridge_z),
        (max_x - inset, min_y + inset, ridge_z),
        (max_x - inset, max_y - inset, ridge_z),
        (min_x + inset, max_y - inset, ridge_z),
    ]
    faces = [(0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7), (4, 5, 6, 7), (0, 3, 2, 1)]
    obj = create_mesh_object(name, verts, faces, material)
    assign_detail_metadata(obj, building, "roof", reference=reference)
    obj["mwrld_roof_type"] = "hip_prism"
    return obj


def assign_roof_zone_metadata(obj, roof_zone):
    """Attach satellite-derived roof zone metadata to a generated roof object."""
    obj["mwrld_roof_zone_id"] = roof_zone.get("id", "")
    obj["mwrld_roof_zone_kind"] = roof_zone.get("kind", "")
    obj["mwrld_roof_zone_primitive"] = roof_zone.get("primitive", "")
    obj["mwrld_roof_zone_reference"] = roof_zone.get("sourceImage", "")
    obj["mwrld_roof_zone_status"] = roof_zone.get("status", "")
    return obj
