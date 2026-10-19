"""Read-only helper: dump the real mesh-derived wall ids for a building.

`assign_generic_wall_ids` (blender_modules/integrated_facade_module.py) is
the same function `blender-build-building-integrated.py` uses at build time
to assign each bottom-edge a `{side}-{index}` id. This script reuses it
directly so the ids printed here are guaranteed to match what a real build
assigns -- no separate/duplicated wall-id logic to drift out of sync.

Used by scripts/blender/extract-wall-openings.mjs to correlate each named
reference photo (references-manifest.json's wall-01..wall-NN ids, assigned
by the reference-photo generator) with the mesh wall id it actually belongs
to, before writing modeling-rules.json.

Usage:
    Blender --background --factory-startup --python blender-list-wall-ids.py \\
        -- <blend_path> <building-query>

<building-query> is a case-insensitive substring match against the
building's name/OSM id, or "all" to list every tracked building.
"""

import json
import re
import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.blender.blender_modules.building_lookup_module import matching_buildings
from scripts.blender.blender_modules.integrated_facade_module import (
    assign_generic_wall_ids,
    bottom_edges,
    load_rules,
    local_bounds,
    rules_path_for,
    side_for_edge,
)
from scripts.blender.blender_modules.landmark_features_module import WALL_NAMING_STRATEGIES

MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def order_in_side(wall_id, side):
    match = re.match(rf"^{re.escape(side)}-(\d+)$", wall_id)
    return int(match.group(1)) if match else None


def wall_list_for_building(parent):
    rules_path = rules_path_for(MODEL_DIR, parent)
    rules = load_rules(rules_path)
    wall_naming = rules.get("wallNaming")
    wall_id_fn = WALL_NAMING_STRATEGIES.get(wall_naming) if wall_naming else None

    min_v, max_v = local_bounds(parent)
    raw_edges = bottom_edges(parent, min_v)
    edges_with_sides = [(a, b, side_for_edge(a, b, min_v, max_v)) for a, b in raw_edges]
    if wall_id_fn:
        wall_ids = [wall_id_fn(a, b, side, min_v, max_v) for a, b, side in edges_with_sides]
    else:
        wall_ids = assign_generic_wall_ids(edges_with_sides)

    walls = [
        {
            "wallId": wall_id,
            "side": side,
            "lengthMeters": round((b - a).length, 2),
            "orderInSide": order_in_side(wall_id, side) if not wall_id_fn else None,
        }
        for (a, b, side), wall_id in zip(edges_with_sides, wall_ids)
    ]
    return {
        "building": parent.get("mwrld_osm_id", parent.name),
        "displayName": parent.get("mwrld_name", parent.name),
        "wallNaming": wall_naming,
        "customWallNaming": bool(wall_id_fn),
        "walls": walls,
    }


def main():
    args = args_after_double_dash()
    if not args:
        raise SystemExit("Usage: blender-list-wall-ids.py -- <blend_path> <building-query>")
    blend_path = Path(args[0]).resolve()
    query = args[1] if len(args) > 1 else "all"

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    buildings = matching_buildings(query)

    payload = json.dumps({"buildings": [wall_list_for_building(parent) for parent in buildings]}, indent=2)
    # Blender writes its own progress/version lines to stdout around our
    # output, so callers parsing this as a subprocess should scan for these
    # markers rather than assuming stdout is pure JSON.
    print("===WALL_LIST_JSON_START===")
    print(payload)
    print("===WALL_LIST_JSON_END===")


if __name__ == "__main__":
    main()
