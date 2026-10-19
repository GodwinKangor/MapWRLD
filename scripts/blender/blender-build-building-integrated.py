"""Generic integrated-facade builder.

Replaces the old per-landmark drivers (blender-build-dartmouth-hall-integrated.py,
blender-build-baker-integrated-facades.py). Both of those hardcoded a single
building name and duplicated ~800 lines of shell/wall/roof logic between
them; that logic now lives once in blender_modules/integrated_facade_module.py
and blender_modules/landmark_features_module.py, and this script just picks
which building(s) to run it against.

Usage:
    Blender --background --factory-startup --python blender-build-building-integrated.py \\
        -- <blend_path> <building-query> [--require-rules]

<building-query> is a case-insensitive substring match against the
building's name/OSM id, or "all" to sweep every tracked building.

For "all", buildings without a references/modeling-rules.json are skipped
by default (nothing to build against yet, and we should not silently
flatten every OSM extrusion in the file). Pass a specific building query to
always build it, even with no rules yet -- useful while authoring a new
building's rules.json.
"""

import sys
from pathlib import Path

import bpy

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.blender.blender_modules.building_lookup_module import matching_buildings, slugify
from scripts.blender.blender_modules.integrated_facade_module import (
    add_opening_visual_details,
    add_wall_reference_features,
    build_pitched_roof,
    elevations_path_for,
    ensure_collection,
    ensure_materials,
    load_elevation_panels,
    load_rules,
    rebuild_shell,
    remove_old_details,
    reset_parent_to_source_mesh,
    rules_path_for,
    validate_rules,
)
from scripts.blender.blender_modules.landmark_features_module import FEATURE_PACKS, WALL_NAMING_STRATEGIES

MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def build_one(parent, require_rules):
    rules_path = rules_path_for(MODEL_DIR, parent)
    rules = load_rules(rules_path)
    if require_rules and not rules:
        return None

    elevation_panels = load_elevation_panels(elevations_path_for(MODEL_DIR, parent))
    display_name = parent.get("mwrld_name", parent.name)
    slug = slugify(display_name)
    detail_prefix = f"mwrld_integrated__{slug}__"

    mats = ensure_materials(slug, rules)
    remove_old_details(parent, detail_prefix)
    reset_parent_to_source_mesh(parent, rules)

    wall_id_fn = WALL_NAMING_STRATEGIES.get(rules.get("wallNaming"))
    min_v, max_v, wall_edges = rebuild_shell(parent, mats, rules, elevation_panels, detail_prefix, wall_id_fn)

    collection = ensure_collection(f"{display_name} Integrated Details")
    add_opening_visual_details(parent, collection, mats, wall_edges, elevation_panels, min_v, max_v, detail_prefix)
    add_wall_reference_features(parent, collection, mats, wall_edges, elevation_panels, min_v, max_v, detail_prefix)

    feature_pack_name = rules.get("roof", {}).get("landmarkFeaturePack")
    if feature_pack_name:
        feature_pack = FEATURE_PACKS.get(feature_pack_name)
        if feature_pack is None:
            raise SystemExit(f"{parent.name}: unknown landmarkFeaturePack {feature_pack_name!r}")
        feature_pack(parent, collection, mats, min_v, max_v, rules, detail_prefix)
    else:
        build_pitched_roof(parent, collection, mats, min_v, max_v, rules, detail_prefix)

    errors = validate_rules(parent, rules, rules_dir=rules_path.parent)
    detail_count = len([obj for obj in bpy.context.scene.objects if obj.get("mwrld_detail_for") == parent.get("mwrld_osm_id", parent.name)])
    parent["mwrld_generated_detail_count"] = detail_count
    parent["mwrld_detail_recipe"] = f"integrated_v3_{feature_pack_name or rules.get('roof', {}).get('type', 'flat')}"
    return errors


def main():
    args = args_after_double_dash()
    if not args:
        raise SystemExit("Usage: blender-build-building-integrated.py -- <blend_path> <building-query> [--require-rules]")
    blend_path = Path(args[0]).resolve()
    query = args[1] if len(args) > 1 else "all"
    require_rules = "--require-rules" in args or query == "all"

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    buildings = matching_buildings(query)

    failures = {}
    built = 0
    skipped = 0
    for parent in buildings:
        errors = build_one(parent, require_rules)
        if errors is None:
            skipped += 1
            continue
        built += 1
        if errors:
            failures[parent.name] = errors

    if built == 0:
        raise SystemExit(f"No buildings were built for query {query!r} (require_rules={require_rules}).")

    bpy.context.preferences.filepaths.save_version = 1
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))

    print(f"Built {built} building(s), skipped {skipped} without modeling-rules.json.")
    if failures:
        for name, errors in failures.items():
            print(f"-- {name} failed modeling rules:")
            for error in errors:
                print(f"   - {error}")
        raise SystemExit(f"{len(failures)} building(s) failed modeling rules.")


if __name__ == "__main__":
    main()
