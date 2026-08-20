import json
import re
import sys
from pathlib import Path

import bpy


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
BLEND_PATH = MODEL_DIR / "dartmouth-energy-twin.blend"
EXPORT_ROOT = MODEL_DIR / "renders"


def args_after_double_dash():
    if "--" not in sys.argv:
        return []
    return sys.argv[sys.argv.index("--") + 1 :]


def slugify(value):
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "unnamed"


def classify(obj):
    category = obj.get("mwrld_category")
    if category == "building":
        return "buildings"
    if category == "road":
        return "roads"
    return None


def export_selection_for(obj):
    selected = [obj]
    osm_id = obj.get("mwrld_osm_id", "")
    if osm_id:
        selected.extend(
            detail
            for detail in bpy.context.scene.objects
            if detail.type == "MESH" and detail.get("mwrld_detail_for") == osm_id
        )
    return selected


def topology_stats_for(obj):
    mesh = obj.data
    edge_counts = {}
    for polygon in mesh.polygons:
        for edge_key in polygon.edge_keys:
            key = tuple(sorted(edge_key))
            edge_counts[key] = edge_counts.get(key, 0) + 1

    used_vertices = {vertex for polygon in mesh.polygons for vertex in polygon.vertices}
    loose_edges = len([edge for edge in mesh.edges if tuple(sorted(edge.vertices)) not in edge_counts])
    boundary_edges = len([count for count in edge_counts.values() if count == 1])
    non_manifold_edges = loose_edges + len([count for count in edge_counts.values() if count != 2])
    triangles = len([polygon for polygon in mesh.polygons if len(polygon.vertices) == 3])
    quads = len([polygon for polygon in mesh.polygons if len(polygon.vertices) == 4])
    ngons = len([polygon for polygon in mesh.polygons if len(polygon.vertices) > 4])

    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": len(mesh.polygons),
        "triangles": triangles,
        "quads": quads,
        "ngons": ngons,
        "looseVertices": len([vertex for vertex in mesh.vertices if vertex.index not in used_vertices]),
        "looseEdges": loose_edges,
        "boundaryEdges": boundary_edges,
        "nonManifoldEdges": non_manifold_edges,
    }


def combine_topology_stats(objects):
    totals = {
        "vertices": 0,
        "edges": 0,
        "faces": 0,
        "triangles": 0,
        "quads": 0,
        "ngons": 0,
        "looseVertices": 0,
        "looseEdges": 0,
        "boundaryEdges": 0,
        "nonManifoldEdges": 0,
    }
    by_object = []
    for obj in objects:
        stats = topology_stats_for(obj)
        by_object.append({"name": obj.name, "kind": obj.get("mwrld_detail_kind", "base"), **stats})
        for key in totals:
            totals[key] += stats[key]
    return totals, by_object


def select_only(obj):
    bpy.ops.object.select_all(action="DESELECT")
    for selected in export_selection_for(obj):
        selected.select_set(True)
    bpy.context.view_layer.objects.active = obj


def export_object(obj, out_dir, force_export_all=False):
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = out_dir.name
    glb_path = out_dir / f"{safe_name}.glb"
    fbx_path = out_dir / f"{safe_name}.fbx"
    metadata_path = out_dir / "metadata.json"

    selected_objects = export_selection_for(obj)
    select_only(obj)

    has_generated_details = bool(obj.get("mwrld_generated_detail_count", 0))
    force_export = (
        force_export_all
        or has_generated_details
        or bool(obj.get("mwrld_restored_from_backup"))
        or bool(obj.get("mwrld_baker_massing_rebuilt"))
    )

    if force_export or not glb_path.exists():
        bpy.ops.export_scene.gltf(
            filepath=str(glb_path),
            export_format="GLB",
            use_selection=True,
        )

    if force_export or not fbx_path.exists():
        bpy.ops.export_scene.fbx(
            filepath=str(fbx_path),
            use_selection=True,
            apply_unit_scale=True,
            add_leaf_bones=False,
            bake_anim=False,
        )

    topology, topology_by_object = combine_topology_stats(selected_objects)
    metadata = {
        "name": obj.name,
        "displayName": obj.get("mwrld_name", obj.name),
        "osmId": obj.get("mwrld_osm_id", ""),
        "originalName": obj.get("mwrld_original_name", ""),
        "type": classify(obj),
        "dimensions": {
            "x": round(obj.dimensions.x, 6),
            "y": round(obj.dimensions.y, 6),
            "z": round(obj.dimensions.z, 6),
        },
        "location": {
            "x": round(obj.location.x, 6),
            "y": round(obj.location.y, 6),
            "z": round(obj.location.z, 6),
        },
        "vertices": topology["vertices"],
        "edges": topology["edges"],
        "faces": topology["faces"],
        "shapeCounts": {
            "triangles": topology["triangles"],
            "quads": topology["quads"],
            "ngons": topology["ngons"],
        },
        "topology": {
            "looseVertices": topology["looseVertices"],
            "looseEdges": topology["looseEdges"],
            "boundaryEdges": topology["boundaryEdges"],
            "nonManifoldEdges": topology["nonManifoldEdges"],
        },
        "topologyByObject": topology_by_object,
        "generatedDetails": int(obj.get("mwrld_generated_detail_count", 0)),
        "glb": glb_path.name,
        "fbx": fbx_path.name,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return metadata


def main():
    args = args_after_double_dash()
    blend_path = Path(args[0]).resolve() if args else BLEND_PATH
    force_export_all = "--force-export" in args
    only_query = None
    if "--only" in args:
        only_index = args.index("--only")
        if only_index + 1 >= len(args):
            raise SystemExit("--only requires an object name or search query")
        only_query = args[only_index + 1].lower()
    if not blend_path.exists():
        raise SystemExit(f"Blend file not found: {blend_path}")

    bpy.ops.wm.open_mainfile(filepath=str(blend_path))

    mesh_objects = sorted(
        [obj for obj in bpy.context.scene.objects if obj.type == "MESH" and classify(obj)],
        key=lambda obj: obj.name.lower(),
    )
    if only_query:
        mesh_objects = [
            obj for obj in mesh_objects
            if only_query in obj.name.lower()
            or only_query in str(obj.get("mwrld_name", "")).lower()
            or only_query in str(obj.get("mwrld_osm_id", "")).lower()
        ]
        if not mesh_objects:
            raise SystemExit(f"No exportable object matched --only {only_query!r}")

    manifest = {
        "source": str(blend_path.relative_to(ROOT) if blend_path.is_relative_to(ROOT) else blend_path),
        "buildings": [],
        "roads": [],
    }

    name_counts = {}
    for index, obj in enumerate(mesh_objects, start=1):
        category = classify(obj)
        base_slug = slugify(obj.name)
        seen = name_counts.get(base_slug, 0)
        name_counts[base_slug] = seen + 1
        folder_name = base_slug if seen == 0 else f"{base_slug}-{seen + 1}"
        out_dir = EXPORT_ROOT / category / folder_name

        metadata = export_object(obj, out_dir, force_export_all)
        manifest[category].append(
            {
                "name": obj.name,
                "folder": str(out_dir.relative_to(EXPORT_ROOT)),
                "glb": str((out_dir / f"{folder_name}.glb").relative_to(EXPORT_ROOT)),
                "fbx": str((out_dir / f"{folder_name}.fbx").relative_to(EXPORT_ROOT)),
                "dimensions": metadata["dimensions"],
            }
        )

        if index % 50 == 0:
            print(f"Exported or verified {index}/{len(mesh_objects)} objects")

    manifest_name = "parts-manifest.partial.json" if only_query else "parts-manifest.json"
    (EXPORT_ROOT / manifest_name).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Done. Buildings: {len(manifest['buildings'])}. Roads: {len(manifest['roads'])}.")


if __name__ == "__main__":
    main()
