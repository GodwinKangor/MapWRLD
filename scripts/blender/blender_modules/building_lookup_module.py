"""Shared building lookup/matching helpers.

Every building-facing script (recipe details, model-law audit, preview
renders, integrated facades) used to carry its own copy of this matching
logic. It now lives here once so "which buildings match this query" means
the same thing everywhere.
"""

import re

import bpy


def slugify(value):
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "unnamed"


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


def all_buildings():
    return sorted(
        (
            obj
            for obj in bpy.context.scene.objects
            if obj.type == "MESH" and obj.get("mwrld_category") == "building" and obj.get("mwrld_osm_id")
        ),
        key=lambda obj: obj.name.lower(),
    )


def matching_buildings(query):
    """Query "all" returns every tracked building; anything else is a
    case-insensitive substring match against name/osm id."""
    buildings = all_buildings()
    if query == "all":
        return buildings
    matches = [obj for obj in buildings if object_matches(obj, query)]
    if not matches:
        raise SystemExit(f"No named building matched: {query}")
    return matches


def building_folder_name(obj):
    name = obj.name.split(".", 1)[0]
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)
