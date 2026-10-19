#!/usr/bin/env python3
"""Apply visually reviewed reference colors to the assembled campus GLBs.

Generic (material-less) building meshes get per-vertex colors: faces whose normal points
up are roofs, everything else is wall. Reviewed, geographically aligned image matches
override the neutral fallback; unreviewed buildings are not colored by building category.
Existing detail materials receive scoped reference overrides without new geometry.
The source GLB is left untouched; the manifest points the map at the styled copy.

  python3 scripts/blender/style-campus-glb.py
"""
import hashlib
import copy
import json
import struct
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
CAMPUS = ROOT / "public/models/dartmouth-campus"
SOURCE = CAMPUS / "dartmouth-campus.glb"
OUTPUT = CAMPUS / "dartmouth-campus-styled.glb"
MANIFEST = CAMPUS / "model-manifest.json"
OSM_NAMES = ROOT / "public/models/dartmouth-energy-twin/reports/osm-campus-names.json"
REFERENCE_COLORS = ROOT / 'data/building-reference-colors.json'

CATEGORY_BY_TAG = {
    "university": "academic", "school": "academic", "college": "academic", "office": "academic",
    "house": "residential", "dormitory": "residential", "apartments": "residential", "semidetached_house": "residential",
    "fraternity": "residential", "cabin": "residential", "detached": "residential", "terrace": "residential",
    "grandstand": "athletic", "pavilion": "athletic", "boathouse": "athletic", "sports_centre": "athletic", "stadium": "athletic",
    "church": "civic", "chapel": "civic",
    "commercial": "commercial", "retail": "commercial",
    "garage": "utility", "garages": "utility", "shed": "utility", "roof": "utility", "carport": "utility",
    "parking": "utility", "warehouse": "utility", "industrial": "utility",
}
# real colors for the hand-modeled buildings' materials, matched by name suffix
NAMED_MATERIALS = {
    "limestone": "#D8CDB5", "brick": "#9C4A36", "clock_face": "#F2EEE4", "green_roof": "#4E7A5C",
    "black_metal": "#222426", "dark_window": "#2B3540", "white_door": "#F3F1EA", "flat_roof": "#6A6D70",
    "granite_base": "#8C8A85", "white_trim": "#F4F1E8", "green_cupola_cap": "#5E8C6A", "wall_feature": "#E6DFD1",
    "dark_metal": "#2A2C2E", "stair_stone": "#A8A39A", "slate_hip_roof": "#4A4F55", "white_brick": "#EFEBE2",
    "black_door": "#1E1F21",
}
ROOF_NORMAL_Y = 0.6  # glTF is Y-up; faces steeper than ~53 degrees from vertical count as roof


def category(tags):
    if tags.get("leisure") in ("sports_centre", "ice_rink", "stadium") or tags.get("sport"):
        return "athletic"
    if tags.get("amenity") in ("place_of_worship",) or tags.get("religion"):
        return "civic"
    if tags.get("power") or tags.get("man_made") or tags.get("amenity") in ("parking", "fuel"):
        return "utility"
    if tags.get("shop") or tags.get("amenity") in ("restaurant", "cafe", "bank", "fast_food", "pub"):
        return "commercial"
    return CATEGORY_BY_TAG.get(tags.get("building", ""), "default")


def srgb_to_linear(hex_color):
    rgb = np.array([int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)])
    return np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)


def read_glb(path):
    data = path.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + json_length])
    bin_offset = 20 + json_length
    bin_length = struct.unpack_from("<I", data, bin_offset)[0]
    return gltf, bytearray(data[bin_offset + 8:bin_offset + 8 + bin_length])


def write_glb(path, gltf, binary):
    while len(binary) % 4:
        binary.append(0)
    gltf["buffers"][0]["byteLength"] = len(binary)
    payload = json.dumps(gltf, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    total = 12 + 8 + len(payload) + 8 + len(binary)
    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(payload), 0x4E4F534A) + payload
        + struct.pack("<II", len(binary), 0x004E4942) + bytes(binary)
    )


def accessor_array(gltf, binary, index):
    accessor = gltf["accessors"][index]
    view = gltf["bufferViews"][accessor["bufferView"]]
    assert accessor["componentType"] == 5126 and accessor["type"] == "VEC3" and not view.get("byteStride")
    start = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
    return np.frombuffer(binary, dtype="<f4", count=accessor["count"] * 3, offset=start).reshape(-1, 3).copy()


def style_asset(source_path, output_path, references, alignment):
    gltf, binary = read_glb(source_path)
    osm = {b["osmId"]: b for b in json.loads(OSM_NAMES.read_text())["buildings"]}
    nodes = gltf["nodes"]
    parent = {child: index for index, node in enumerate(nodes) for child in node.get("children", [])}

    def root_of(index):
        while index in parent:
            index = parent[index]
        return nodes[index]

    for material in gltf["materials"]:
        suffix = next((key for key in sorted(NAMED_MATERIALS, key=len, reverse=True) if material.get("name", "").endswith(key)), None)
        if suffix:
            pbr = material.setdefault("pbrMetallicRoughness", {})
            pbr["baseColorFactor"] = [*srgb_to_linear(NAMED_MATERIALS[suffix]).round(4).tolist(), 1]
            pbr["metallicFactor"] = 0
            pbr["roughnessFactor"] = 0.85

    massing = len(gltf["materials"])
    gltf["materials"].append({"name": "mwrld_style_massing", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0, "roughnessFactor": 0.9}})

    counts = {}
    scoped_materials = {}
    reviewed_roots = set()
    for index, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        root = root_of(index)
        osm_id = (root.get("extras") or {}).get("osmId")
        if (root.get('extras') or {}).get('category') != 'buildings':
            continue
        kind = category(osm.get(osm_id, {}).get("tags", {}))
        candidate = references['buildings'].get(osm_id,{})
        reviewed = candidate.get('status') == 'observed' and alignment.get(osm_id,False)
        if reviewed:
            reviewed_roots.add(osm_id)
        palette = candidate if reviewed else references['unreviewedPalette']
        wall, roof = (srgb_to_linear(palette[color]) for color in ('wall','roof'))
        for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
            if 'material' in primitive:
                material_id = primitive['material']
                material = gltf['materials'][material_id]
                overrides = candidate.get('materialColors',{}) if reviewed else {}
                suffix = next((key for key in sorted(overrides,key=len,reverse=True)
                               if material.get('name','').endswith(key)),None)
                if suffix:
                    key = (osm_id,material_id)
                    if key not in scoped_materials:
                        replacement = copy.deepcopy(material)
                        replacement['name'] = material.get('name','material')+'::reference::'+osm_id
                        replacement.setdefault('pbrMetallicRoughness',{})['baseColorFactor'] = [*srgb_to_linear(overrides[suffix]).round(6).tolist(),1]
                        scoped_materials[key] = len(gltf['materials'])
                        gltf['materials'].append(replacement)
                    primitive['material'] = scoped_materials[key]
                continue
            if "NORMAL" not in primitive["attributes"]:
                continue
            normals = accessor_array(gltf, binary, primitive["attributes"]["NORMAL"])
            colors = np.where((normals[:, 1] > ROOF_NORMAL_Y)[:, None], roof, wall)
            # faces pointing down (soffits, overhang undersides) read darker
            colors = np.where((normals[:, 1] < -0.5)[:, None], colors * 0.6, colors)
            rgba = np.concatenate([np.round(colors * 255), np.full((len(colors), 1), 255)], axis=1).astype("u1")
            while len(binary) % 4:
                binary.append(0)
            gltf["bufferViews"].append({"buffer": 0, "byteOffset": len(binary), "byteLength": rgba.nbytes, "target": 34962})
            binary.extend(rgba.tobytes())
            gltf["accessors"].append({"bufferView": len(gltf["bufferViews"]) - 1, "componentType": 5121, "normalized": True, "count": len(rgba), "type": "VEC4"})
            primitive["attributes"]["COLOR_0"] = len(gltf["accessors"]) - 1
            primitive["material"] = massing
            counts[kind] = counts.get(kind, 0) + 1

    write_glb(output_path, gltf, binary)
    return {'asset':str(output_path.relative_to(ROOT)),'bytes':output_path.stat().st_size,
            'referenceMatchedBuildings':sorted(reviewed_roots),'massingPrimitivesByCategory':counts}


def main():
    references = json.loads(REFERENCE_COLORS.read_text())
    heights = json.loads((CAMPUS/'building-heights.json').read_text())
    alignment = {r['osmId']:r['modelFootprintAligned'] for r in heights['buildings']}
    reviewed = []
    for osm_id, entry in references['buildings'].items():
        sources = []
        for file in entry['references']:
            path = ROOT/file
            if not path.exists():
                raise FileNotFoundError(f'Missing reviewed image: {file}')
            sources.append({'path':file,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        applied = entry['status'] == 'observed' and alignment.get(osm_id,False)
        reviewed.append({'osmId':osm_id,'name':entry['name'],'applied':applied,
                         'reason':entry['reason'] if applied else ('Model/footprint identity mismatch.' if not alignment.get(osm_id,False) else entry['reason']),
                         'wall':entry['wall'],'roof':entry['roof'],'sources':sources})
    assets = [style_asset(SOURCE,OUTPUT,references,alignment)]
    evidence_source = CAMPUS/'dartmouth-evidence.glb'
    if evidence_source.exists():
        assets.append(style_asset(evidence_source,CAMPUS/'dartmouth-evidence-styled.glb',references,alignment))
    manifest = json.loads(MANIFEST.read_text())
    manifest["campusModel"] = "/models/dartmouth-campus/" + OUTPUT.name
    if evidence_source.exists():
        manifest['evidenceModel'] = '/models/dartmouth-campus/dartmouth-evidence-styled.glb'
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")
    report = {'method':references['method'],'reviewedImageSets':len(reviewed),
              'appliedBuildingCount':sum(r['applied'] for r in reviewed),
              'unreviewedPalette':references['unreviewedPalette'],
              'limitations':['Unreviewed buildings use neutral illustrative colors.',
                             'Photo lighting and age affect perceived colors; these are visual approximations.',
                             'Trim is colored only where the source model already has a corresponding material.'],
              'buildings':reviewed,'assets':assets}
    (CAMPUS/'building-color-report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(f"Reviewed {len(reviewed)} image sets; applied reference colors to {report['appliedBuildingCount']} aligned buildings.")
    for asset in assets:
        print(f"Wrote {asset['asset']} ({asset['bytes']/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
