from .geometry_core import assign_detail_metadata, create_mesh_object


def build_wall_grid(a, b, min_z, max_z, openings=None):
    """Return quad wall faces with openings represented as material-tagged cells."""
    openings = openings or []
    length = (b - a).length
    if length <= 0.01:
        return [], []

    u_breaks = {0.0, length}
    z_breaks = {min_z, max_z}
    for opening in openings:
        u_breaks.update([opening["u0"], opening["u1"]])
        z_breaks.update([opening["z0"], opening["z1"]])

    us = sorted(u_breaks)
    zs = sorted(z_breaks)
    verts = []
    index = {}
    for ui, u in enumerate(us):
        point = a.lerp(b, u / length)
        for zi, z in enumerate(zs):
            index[(ui, zi)] = len(verts)
            verts.append((point.x, point.y, z))

    cells = []
    for ui in range(len(us) - 1):
        u_mid = (us[ui] + us[ui + 1]) * 0.5
        for zi in range(len(zs) - 1):
            z_mid = (zs[zi] + zs[zi + 1]) * 0.5
            tag = "wall"
            source = None
            for opening in openings:
                if opening["u0"] <= u_mid <= opening["u1"] and opening["z0"] <= z_mid <= opening["z1"]:
                    tag = opening["kind"]
                    source = opening.get("reference")
                    break
            cells.append(
                {
                    "face": (index[(ui, zi)], index[(ui + 1, zi)], index[(ui + 1, zi + 1)], index[(ui, zi + 1)]),
                    "tag": tag,
                    "reference": source,
                }
            )
    return verts, cells


def create_integrated_wall(name, a, b, min_z, max_z, openings, materials, building=None, wall_id=None, reference=None, wall_features=None):
    wall_features = wall_features or []
    verts, cells = build_wall_grid(a, b, min_z, max_z, openings)
    mesh = create_mesh_object(name, verts, [cell["face"] for cell in cells])
    for material in materials.values():
        mesh.data.materials.append(material)
    for polygon, cell in zip(mesh.data.polygons, cells):
        polygon.material_index = list(materials).index(cell["tag"]) if cell["tag"] in materials else 0
    assign_detail_metadata(mesh, building, "major_wall_detail", reference=reference, wall_id=wall_id)
    mesh["mwrld_integrated_openings"] = True
    mesh["mwrld_opening_count"] = len([cell for cell in cells if cell["tag"] in {"window", "door"}])
    mesh["mwrld_major_wall_feature_count"] = len(wall_features)
    mesh["mwrld_major_wall_features"] = ",".join(feature.get("kind", feature.get("id", "wall_feature")) for feature in wall_features)
    return mesh
