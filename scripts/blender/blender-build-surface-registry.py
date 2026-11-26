"""Build the persistent surface registry for one building (read-only on the .blend).

Usage:
  Blender --background --factory-startup <campus.blend> --python scripts/blender/blender-build-surface-registry.py -- \
      --building-id mcnutt-hall-261793901 --osm data/field-surfaces/osm/way-261793901.json \
      --out data/field-surfaces/mcnutt-hall-261793901.surfaces.json

Walls come from the OSM footprint (node IDs give persistent identity); Blender is
consulted only to map each wall onto the existing object and its side-ordered
panel IDs (mwrld_wall_id / mwrld_face_reference_sources) and to measure how far
the two geometries disagree. The .blend is never modified or saved.
"""
import json
import math
import sys
from collections import Counter
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "field-worker"))
from mwrld_field.geometry import (  # noqa: E402
    SCHEMA_SURFACES, Georeference, registry_digest, roof_surface_id, walls_from_footprint,
)

# OSM and the Blender export agree to within a few metres (the georeference is a
# consensus fit; see calibrate-campus-georeference.py). Beyond this the mapping
# is flagged for review instead of trusted.
MATCH_TOLERANCE_M = 3.0


def args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {}
    for key, value in zip(argv[::2], argv[1::2]):
        out[key.lstrip("-")] = value
    for required in ("building-id", "osm", "out"):
        if required not in out:
            raise SystemExit(f"missing --{required}")
    return out


def point_segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy)), t


def main():
    opts = args()
    osm = json.loads(Path(opts["osm"]).read_text())
    way = next(e for e in osm["elements"] if e["type"] == "way")
    nodes = {e["id"]: e for e in osm["elements"] if e["type"] == "node"}
    osm_id = f"way/{way['id']}"
    terrain = json.loads((ROOT / "public/models/dartmouth-campus/terrain/campus-terrain.json").read_text())
    geo = Georeference.from_campus_terrain(terrain)

    obj = next((o for o in bpy.data.objects if o.get("mwrld_osm_id") == osm_id and o.type == "MESH" and o.parent is None), None)
    if obj is None:
        raise SystemExit(f"no Blender object with mwrld_osm_id={osm_id}")
    if any(abs(v) > 1e-9 for row in (obj.matrix_world - obj.matrix_world.Identity(4)) for v in row):
        raise SystemExit(f"{obj.name} has a non-identity transform; registry assumes campus-frame vertices")
    height = float(obj.get("mwrld_wall_height_m") or obj.get("mwrld_source_max_z") or max(v.co.z for v in obj.data.vertices))
    base_z = float(obj.get("mwrld_source_min_z", 0.0))

    ring = [(nid, *geo.to_campus(nodes[nid]["lon"], nodes[nid]["lat"])) for nid in way["nodes"]]
    walls = walls_from_footprint(opts["building-id"], osm_id, ring, height - base_z, base_z)

    # Blender side: bottom vertices and the wall ID each wall face was built for.
    mesh = obj.data
    bottom = [(v.co.x, v.co.y) for v in mesh.vertices if abs(v.co.z - base_z) < 0.02]
    face_sources = json.loads(mesh.get("mwrld_face_reference_sources", "[]"))
    face_wall = {entry["face"]: entry.get("wallId") for entry in face_sources if entry.get("wallId")}

    for wall in walls:
        ax, ay = wall.origin[0], wall.origin[1]
        bx, by = ax + wall.u_axis[0] * wall.width_m, ay + wall.u_axis[1] * wall.width_m
        # how far each OSM corner is from the nearest Blender footprint vertex
        corner_error = [min((math.hypot(px - qx, py - qy) for qx, qy in bottom), default=float("inf")) for px, py in ((ax, ay), (bx, by))]
        votes = Counter()
        inward = outward = 0.0
        for poly in mesh.polygons:
            wall_id = face_wall.get(poly.index)
            if not wall_id or abs(poly.normal.z) > 0.3:
                continue
            c = poly.center
            distance, t = point_segment_distance(c.x, c.y, ax, ay, bx, by)
            facing = poly.normal.x * wall.normal[0] + poly.normal.y * wall.normal[1]
            # orientation-agnostic: the integrated shells were found with inward normals
            if distance < MATCH_TOLERANCE_M and 0.0 < t < 1.0 and abs(facing) > 0.7:
                votes[wall_id] += poly.area
                if facing > 0:
                    outward += poly.area
                else:
                    inward += poly.area
        panel_ids = [wid for wid, _ in votes.most_common()]
        worst = max(corner_error)
        wall.blender = {
            "object": obj.name,
            "panelIds": panel_ids,  # existing side-ordered mwrld_wall_id values covering this wall
            "cornerMatchErrorM": [round(e, 3) for e in corner_error],
            # area-weighted: a shell built with flipped winding reports "inward"
            "meshNormals": "inward" if inward > outward else "outward" if outward else "none-matched",
            "mappingStatus": "matched" if worst <= MATCH_TOLERANCE_M and panel_ids else "needs-review",
            "facadeObject": f"mwrld_facade__{wall.surface_id.replace('osm:', '').replace('/', '_')}",
        }

    xs = [x for _, x, _ in ring]
    ys = [y for _, _, y in ring]
    roof = {
        "surfaceId": roof_surface_id(osm_id), "kind": "roof", "buildingId": opts["building-id"], "osmId": osm_id,
        "roofType": str(obj.get("mwrld_detail_recipe", "")).split("_")[-1] or "unknown",
        "frame": {"origin": [min(xs), min(ys), height], "uAxis": [1, 0, 0], "vAxis": [0, 1, 0], "normal": [0, 0, 1]},
        "widthM": round(max(xs) - min(xs), 4), "heightM": round(max(ys) - min(ys), 4),
        "footprint": [[round(x, 4), round(y, 4)] for _, x, y in (ring[:-1] if ring[0][0] == ring[-1][0] else ring)],
        "note": "Horizontal plane at eave height over the footprint bounding box; pitched roof planes are not yet separate surfaces.",
        "blender": {"object": obj.name, "mappingStatus": "approximate"},
    }

    registry = {
        "schema": SCHEMA_SURFACES,
        "buildingId": opts["building-id"],
        "osmId": osm_id,
        "displayName": obj.get("mwrld_name", obj.name),
        "frame": {
            "name": "campus",
            "axes": "x east, y north, z up (metres); GLB/Three.js uses (x, z, -y)",
            "zOrigin": "building base (Blender mwrld_source_min_z), not terrain elevation",
            "georeference": geo.as_dict(),
        },
        "sources": {
            "osm": {"file": str(Path(opts["osm"]).resolve().relative_to(ROOT)), "timestamp": osm.get("osm3s", {}).get("timestamp_osm_base"),
                    "license": "© OpenStreetMap contributors (ODbL)"},
            "blend": Path(bpy.data.filepath).name,
            "heightM": {"value": height - base_z, "from": "mwrld_wall_height_m"},
        },
        "surfaces": [w.as_dict() for w in walls] + [roof],
    }
    registry["digest"] = registry_digest(registry)
    out = Path(opts["out"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(registry, indent=2) + "\n")
    for w in walls:
        print(f"REGISTRY {w.surface_id} facing={w.facing} width={w.width_m:.2f} panels={w.blender['panelIds']} "
              f"err={w.blender['cornerMatchErrorM']} normals={w.blender['meshNormals']} {w.blender['mappingStatus']}")
    print(f"REGISTRY wrote {out} ({len(walls)} walls + roof)")


main()
