"""Bespoke architectural feature packs for landmark buildings.

Ordinary buildings are fully described by modeling-rules.json plus the
generic roof/wall logic in integrated_facade_module. A handful of landmark
buildings (Dartmouth Hall's cupola, Baker Library's clock tower) have
one-of-a-kind geometry that cannot be inferred from data alone. Those live
here as small, named functions instead of as whole separate driver
scripts, and a building opts in by setting `roof.landmarkFeaturePack` in
its own modeling-rules.json.
"""

from mathutils import Vector

from .integrated_facade_module import (
    add_box,
    add_cone_detail,
    add_mesh_detail,
    build_pitched_roof,
    gable_mesh,
    material,
)

FEATURE_PACKS = {}
WALL_NAMING_STRATEGIES = {}


def register(name):
    def decorator(fn):
        FEATURE_PACKS[name] = fn
        return fn

    return decorator


def register_wall_naming(name):
    def decorator(fn):
        WALL_NAMING_STRATEGIES[name] = fn
        return fn

    return decorator


@register_wall_naming("dartmouth_hall_wings")
def dartmouth_hall_wall_id_for_edge(a, b, side, min_v, max_v):
    """Named-wing wall ids matching Dartmouth Hall's curated
    modeling-rules.json (e.g. "west-south-wing"), preserved verbatim from
    the original one-off script so its existing per-wall reference data
    keeps lining up."""
    mid = (a + b) * 0.5
    length = (b - a).length
    y_mid = (min_v.y + max_v.y) * 0.5
    if side == "west":
        if length >= 14 and mid.y < y_mid:
            return "west-south-wing"
        if length >= 14:
            return "west-north-wing"
        if 8 <= length <= 14:
            return "west-center-entry"
    if side == "east":
        if length >= 14 and mid.y < y_mid:
            return "east-south-wing"
        if length >= 14:
            return "east-north-wing"
        if 8 <= length <= 14:
            return "east-center-bay"
    if side == "north" and length >= 14:
        return "north-main"
    if side == "south" and length >= 14:
        return "south-main"
    return f"{side}-connector"


def roof_point_from_fraction(point, x0, x1, y0, y1, z):
    return (x0 + (x1 - x0) * float(point[0]), y0 + (y1 - y0) * float(point[1]), z)


@register("dartmouth_hall_cupola")
def dartmouth_hall_cupola(parent, collection, mats, min_v, max_v, rules, detail_prefix):
    """Front pediment, satellite-derived roof zones, dormers/chimneys, and
    the tiered cupola + spire, ported from the original one-off Dartmouth
    Hall integrated-facade script."""
    roof = build_pitched_roof(parent, collection, mats, min_v, max_v, rules, detail_prefix)
    roof_rules = rules.get("roof", {})
    rise = float(roof_rules.get("riseMeters", 3.3))
    z = max_v.z
    ridge_z = z + rise
    x0, x1 = min_v.x, max_v.x
    y0, y1 = min_v.y, max_v.y
    cx = (x0 + x1) * 0.5
    cy = y0 + (y1 - y0) * 0.5
    tower_context = "references/tower/tower-front-context.jpg"
    roof_context = "references/tower/tower-roof-satellite-context.jpg"
    satellite_source = "references/roof-satellite.jpg"
    details = [roof] if roof else []

    # Front triangular pediment below the cupola axis.
    half_w = 3.9
    front_x = x0 - 0.04
    wall_z = z - 0.05
    roof_z = z + 2.1
    pediment_verts = [
        (front_x, cy - half_w, wall_z),
        (front_x, cy + half_w, wall_z),
        (front_x, cy + half_w, roof_z),
        (front_x, cy, roof_z + 2.4),
        (front_x, cy - half_w, roof_z),
    ]
    pediment = add_mesh_detail(
        f"{detail_prefix}front_gable_pediment", parent, collection, pediment_verts, [(0, 1, 2, 4), (4, 2, 3)], mats["trim"], "front_gable_pediment", tower_context
    )
    details.append(pediment)

    # Satellite-derived roof zones (dormers, ridge caps, pediment roof) as flat polygons.
    for zone in roof_rules.get("roofZones", []):
        shape = zone.get("roofPlanShape", {})
        if shape.get("kind") != "polygon" or zone.get("id") == "R01":
            continue
        points = shape.get("points", [])
        if len(points) < 3:
            continue
        verts = [roof_point_from_fraction(point, x0, x1, y0, y1, z + 0.018) for point in points]
        faces = [(0, index, index + 1) for index in range(1, len(verts) - 1)]
        mat = mats["trim"] if zone.get("kind") in {"front_gable_pediment_roof", "cupola_roof_support_zone"} else mats["roof"]
        zone_obj = add_mesh_detail(
            f"{detail_prefix}roof_zone_{zone.get('id', 'zone').lower()}", parent, collection, verts, faces, mat, zone.get("kind", "roof_zone"),
            zone.get("sourceImage", satellite_source),
        )
        details.append(zone_obj)

    # Dark roof dormers and chimney masses visible in the satellite reference.
    width, depth = x1 - x0, y1 - y0
    for name, dx, dy in [
        ("front_south", x0 + width * 0.30, y0 + depth * 0.25),
        ("front_north", x0 + width * 0.70, y0 + depth * 0.25),
        ("rear_south", x0 + width * 0.30, y0 + depth * 0.75),
        ("rear_north", x0 + width * 0.70, y0 + depth * 0.75),
    ]:
        details.append(add_box(f"{detail_prefix}roof_dormer_{name}", parent, collection, Vector((dx, dy, z + 0.45)), (1.55, 1.05, 0.9), mats["roof"], "roof_dormer", satellite_source))
    for name, dx, dy in [("front_south", x0 + width * 0.18, y0 + depth * 0.26), ("rear_north", x0 + width * 0.83, y0 + depth * 0.74)]:
        details.append(add_box(f"{detail_prefix}chimney_{name}", parent, collection, Vector((dx, dy, z + 1.1)), (0.95, 0.95, 2.2), mats["base"], "chimney", satellite_source))
    for index, zone in enumerate(roof_rules.get("approvedDormerZones", []), start=1):
        details.append(add_box(f"{detail_prefix}roof_dormer_{index:02d}", parent, collection, Vector(zone["center"]), tuple(zone["size"]), mats["trim"], "dormer", zone.get("source", satellite_source)))

    # Tiered cupola tower with balustrade, lantern, copper cap, spire, weathervane.
    copper = material(f"mwrld_{parent.name}_cupola_copper", (0.16, 0.42, 0.32, 1))
    details.append(add_box(f"{detail_prefix}cupola_base", parent, collection, Vector((cx, cy, ridge_z + 0.38)), (2.95, 2.95, 0.76), mats["trim"], "cupola_base", roof_context))
    details.append(add_box(f"{detail_prefix}cupola_lower_plinth", parent, collection, Vector((cx, cy, ridge_z + 0.92)), (2.35, 2.35, 0.32), mats["trim"], "cupola_base", tower_context))
    details.append(add_box(f"{detail_prefix}cupola_lantern", parent, collection, Vector((cx, cy, ridge_z + 1.78)), (1.82, 1.82, 1.4), mats["trim"], "cupola_lantern", tower_context))
    for index, (ox, oy) in enumerate([(-0.72, -0.72), (-0.72, 0.72), (0.72, -0.72), (0.72, 0.72)], start=1):
        details.append(add_box(f"{detail_prefix}cupola_post_{index:02d}", parent, collection, Vector((cx + ox, cy + oy, ridge_z + 1.08 + 0.75)), (0.12, 0.12, 1.5), mats["trim"], "cupola_post", tower_context))
    for name, center, size in [
        ("north", Vector((cx, cy + 0.72, ridge_z + 1.08 + 0.34)), (1.32, 0.08, 0.12)),
        ("south", Vector((cx, cy - 0.72, ridge_z + 1.08 + 0.34)), (1.32, 0.08, 0.12)),
        ("east", Vector((cx + 0.72, cy, ridge_z + 1.08 + 0.34)), (0.08, 1.32, 0.12)),
        ("west", Vector((cx - 0.72, cy, ridge_z + 1.08 + 0.34)), (0.08, 1.32, 0.12)),
    ]:
        details.append(add_box(f"{detail_prefix}cupola_rail_{name}", parent, collection, center, size, mats["trim"], "cupola_rail", tower_context))
    opening_z = ridge_z + 1.82
    for name, center in [
        ("north", Vector((cx, cy + 0.921, opening_z))),
        ("south", Vector((cx, cy - 0.921, opening_z))),
        ("east", Vector((cx + 0.921, cy, opening_z))),
        ("west", Vector((cx - 0.921, cy, opening_z))),
    ]:
        size = (0.82, 0.035, 1.05) if name in {"north", "south"} else (0.035, 0.82, 1.05)
        details.append(add_box(f"{detail_prefix}cupola_lantern_opening_{name}", parent, collection, center, size, mats["window"], "cupola_lantern_opening", tower_context))
    details.append(add_box(f"{detail_prefix}cupola_upper_plinth", parent, collection, Vector((cx, cy, ridge_z + 2.64)), (1.42, 1.42, 0.32), mats["trim"], "cupola_lantern", tower_context))
    details.append(add_cone_detail(f"{detail_prefix}cupola_cap", parent, collection, Vector((cx, cy, ridge_z + 3.16)), 0.9, 0.24, 0.72, 16, copper, "cupola_cap", tower_context))
    details.append(add_box(f"{detail_prefix}spire", parent, collection, Vector((cx, cy, ridge_z + 4.23)), (0.11, 0.11, 1.42), mats["metal"], "spire", tower_context))
    details.append(add_box(f"{detail_prefix}weathervane", parent, collection, Vector((cx, cy, ridge_z + 4.94)), (0.9, 0.05, 0.05), mats["metal"], "weathervane", tower_context))
    return [detail for detail in details if detail is not None]


@register("baker_library_tower")
def baker_library_tower(parent, collection, mats, min_v, max_v, rules, detail_prefix):
    """Central support plinth, tiered clock tower, and the green gable roof
    runs, ported from the original one-off Baker Library integrated-facade
    script. The footprint-shaped flat roof cap itself now comes for free
    from rebuild_shell (see integrated_facade_module.add_source_cap_faces),
    so this pack only adds what is actually unique to Baker."""
    clock = material(f"mwrld_{parent.name}_clock_face", (0.92, 0.89, 0.78, 1))
    black = material(f"mwrld_{parent.name}_black_metal", (0.03, 0.03, 0.03, 1))
    tower_source = "references/south.jpg"
    satellite_source = "references/roof-satellite.jpg"

    x_span, y_span = max_v.x - min_v.x, max_v.y - min_v.y
    center = Vector(((min_v.x + max_v.x) / 2, min_v.y + y_span * 0.34, max_v.z))
    sx, sy = x_span * 0.145 * 1.08, y_span * 0.14 * 1.08

    details = [
        add_box(f"{detail_prefix}tower_support", parent, collection, Vector((center.x, center.y, (min_v.z + max_v.z) / 2)), (sx, sy, max_v.z - min_v.z), mats["wall"], "tower_support", tower_source)
    ]

    z = max_v.z
    for name, w, d, h, mat in [
        ("brick_base", sx * 1.08, sy * 1.08, 12.0, mats["wall"]),
        ("clock_stage", sx * 0.94, sy * 0.94, 7.0, mats["trim"]),
        ("belfry_stage", sx * 0.74, sy * 0.74, 8.0, mats["trim"]),
        ("green_cupola", sx * 0.58, sy * 0.58, 3.2, mats["roof"]),
        ("lantern", sx * 0.34, sy * 0.34, 4.0, mats["trim"]),
    ]:
        details.append(add_box(f"{detail_prefix}{name}", parent, collection, Vector((center.x, center.y, z + h / 2)), (w, d, h), mat, "tower", tower_source))
        z += h
    for side, dx, dy, size in [
        ("south", 0, -sy * 0.48, (sx * 0.34, 0.08, sx * 0.34)),
        ("north", 0, sy * 0.48, (sx * 0.34, 0.08, sx * 0.34)),
        ("east", sx * 0.48, 0, (0.08, sy * 0.34, sy * 0.34)),
        ("west", -sx * 0.48, 0, (0.08, sy * 0.34, sy * 0.34)),
    ]:
        details.append(add_box(f"{detail_prefix}clock_{side}", parent, collection, Vector((center.x + dx, center.y + dy, max_v.z + 15.5)), size, clock, "clock_face", tower_source))
    spire_h = 12.0
    details.append(add_box(f"{detail_prefix}spire_mast", parent, collection, Vector((center.x, center.y, z + spire_h / 2)), (0.38, 0.38, spire_h), black, "spire", tower_source))
    details.append(add_box(f"{detail_prefix}weathervane_hint", parent, collection, Vector((center.x, center.y, z + spire_h + 0.35)), (sx * 0.46, 0.08, 0.08), black, "weathervane", tower_source))

    if rules.get("roof", {}).get("approvedPrismZones"):
        roof_z = max_v.z + 0.08
        # Ridge orientation is inferred from each strip's aspect ratio by
        # gable_mesh, which matches the original explicit x/y axis choices
        # here since these strips are always long in their ridge direction.
        roof_runs = [
            (min_v.x + x_span * 0.07, min_v.x + x_span * 0.34, min_v.y + y_span * 0.08, min_v.y + y_span * 0.24),
            (min_v.x + x_span * 0.66, max_v.x - x_span * 0.07, min_v.y + y_span * 0.08, min_v.y + y_span * 0.24),
            (min_v.x + x_span * 0.14, min_v.x + x_span * 0.36, min_v.y + y_span * 0.66, max_v.y - y_span * 0.08),
            (min_v.x + x_span * 0.64, max_v.x - x_span * 0.14, min_v.y + y_span * 0.66, max_v.y - y_span * 0.08),
        ]
        for index, (x0, x1, y0, y1) in enumerate(roof_runs, start=1):
            verts, faces = gable_mesh(x0, x1, y0, y1, roof_z, 2.2)
            details.append(add_mesh_detail(f"{detail_prefix}roof_run_{index:02d}", parent, collection, verts, faces, mats["roof"], "roof", satellite_source))

    return [detail for detail in details if detail is not None]
