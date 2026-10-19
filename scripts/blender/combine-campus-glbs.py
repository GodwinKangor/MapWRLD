"""Combine current static part exports without touching the Blender source.

One export per category/OSM ID; newest file wins if renamed exports coexist.
Preserves world-space vertices, node transforms, and all detail meshes.
Rejects unsupported glTF features rather than silently corrupting them.
"""
import copy
import hashlib
import json
import struct
from itertools import product
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARTS = ROOT / "public/models/dartmouth-energy-twin/renders"
OUT = ROOT / "public/models/dartmouth-campus"
TABLES = ("nodes", "meshes", "materials", "accessors", "bufferViews")


def transform_point(node, point):
    if "matrix" in node:
        matrix = node["matrix"]
        return [sum(matrix[column * 4 + row] * value for column, value in enumerate([*point, 1])) for row in range(3)]
    point = [v * s for v, s in zip(point, node.get("scale", [1, 1, 1]))]
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    # Quaternion rotation, followed by translation (glTF T * R * S).
    cross = [2 * (y * point[2] - z * point[1]), 2 * (z * point[0] - x * point[2]), 2 * (x * point[1] - y * point[0])]
    rotated = [point[0] + w * cross[0] + y * cross[2] - z * cross[1],
               point[1] + w * cross[1] + z * cross[0] - x * cross[2],
               point[2] + w * cross[2] + x * cross[1] - y * cross[0]]
    return [v + t for v, t in zip(rotated, node.get("translation", [0, 0, 0]))]


def geometry_bounds(doc):
    """World bounds in the exported east/up/south frame."""
    points = []

    def visit(index, ancestors):
        node = doc["nodes"][index]
        chain = [node, *ancestors]
        if "mesh" in node:
            for primitive in doc["meshes"][node["mesh"]]["primitives"]:
                accessor = doc["accessors"][primitive["attributes"]["POSITION"]]
                for point in product(*zip(accessor["min"], accessor["max"])):
                    for transform in chain:
                        point = transform_point(transform, point)
                    points.append(point)
        for child in node.get("children", []):
            visit(child, chain)

    for root in doc["scenes"][doc.get("scene", 0)]["nodes"]:
        visit(root, [])
    if not points:
        return None
    low = [min(p[i] for p in points) for i in range(3)]
    high = [max(p[i] for p in points) for i in range(3)]
    return low, high


def ground_anchor(doc):
    bounds = geometry_bounds(doc)
    if bounds is None:
        return None
    low, high = bounds
    return [(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2]


def height_adjustment(meta, source, record):
    """Rescale only simple 20 m fallback models, about their existing base."""
    if not record or record['heightMeters'] is None:
        return None, 'no_usable_height'
    if not record['modelFootprintAligned']:
        return None, 'model_footprint_identity_mismatch'
    if meta.get('generatedDetails', 0) or len(source.get('meshes', [])) != 1:
        return None, 'preserved_detailed_geometry'
    bounds = geometry_bounds(source)
    if bounds is None:
        return None, 'empty_geometry'
    low, high = bounds
    current = high[1] - low[1]
    if abs(current - 20) > .05 or abs(meta['dimensions']['z'] - 20) > .05:
        return None, 'preserved_nondefault_height'
    target = record['heightMeters']
    assert 2.5 <= target <= 100, f'Invalid building height: {target}'
    scale = target / current
    # glTF Y is up. Preserve every horizontal coordinate and the ground plane.
    matrix = [1,0,0,0, 0,scale,0,0, 0,0,1,0, 0,low[1]*(1-scale),0,1]
    return {'matrix':matrix,'originalHeightMeters':current,'heightMeters':target,
            'method':record['method'],'sourceUrl':record['sourceUrl'],'reviewRequired':True}, 'applied'


def read_glb(path):
    raw = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", raw)
    assert (magic, version, length) == (b"glTF", 2, len(raw)), path
    size, kind = struct.unpack_from("<II", raw, 12)
    assert kind == 0x4E4F534A, path
    doc = json.loads(raw[20:20 + size])
    offset = 20 + size
    if offset == len(raw):
        assert not doc.get("buffers") and not doc.get("meshes"), path
        return doc, b""
    size, kind = struct.unpack_from("<II", raw, offset)
    assert kind == 0x004E4942, path
    assert set(doc) <= {*TABLES, "asset", "scene", "scenes", "buffers"}, path
    assert len(doc["buffers"]) == 1 and "uri" not in doc["buffers"][0], path
    return doc, raw[offset + 8:offset + 8 + doc["buffers"][0]["byteLength"]]


def encode_glb(doc, binary):
    encoded = json.dumps(doc, separators=(',', ':')).encode()
    encoded += b' ' * (-len(encoded) % 4)
    return (struct.pack('<4sII', b'glTF', 2, 28 + len(encoded) + len(binary))
            + struct.pack('<II', len(encoded), 0x4E4F534A) + encoded
            + struct.pack('<II', len(binary), 0x004E4942) + binary)


def subset_glb(source, binary, root_names):
    """Keep only selected subtrees and their geometry/material/buffer resources."""
    node_ids = set()

    def visit(index):
        if index in node_ids:
            return
        node_ids.add(index)
        for child in source['nodes'][index].get('children', []):
            visit(child)

    roots = [i for i in source['scenes'][source.get('scene', 0)]['nodes']
             if source['nodes'][i].get('name') in root_names]
    for index in roots:
        visit(index)
    meshes = {source['nodes'][i]['mesh'] for i in node_ids if 'mesh' in source['nodes'][i]}
    primitives = [p for i in meshes for p in source['meshes'][i]['primitives']]
    accessors = {i for p in primitives for i in p['attributes'].values()}
    accessors |= {p['indices'] for p in primitives if 'indices' in p}
    materials = {p['material'] for p in primitives if 'material' in p}
    views = {source['accessors'][i]['bufferView'] for i in accessors if 'bufferView' in source['accessors'][i]}
    used = {'nodes':node_ids,'meshes':meshes,'accessors':accessors,'materials':materials,'bufferViews':views}
    maps = {key:{old:new for new,old in enumerate(sorted(indices))} for key,indices in used.items()}
    doc = {'asset':copy.deepcopy(source['asset']),'scene':0,
           'scenes':[{'nodes':[maps['nodes'][i] for i in roots]}],
           **{key:[copy.deepcopy(source[key][i]) for i in sorted(indices)] for key,indices in used.items()}}
    data = bytearray()
    for old in sorted(views):
        view = doc['bufferViews'][maps['bufferViews'][old]]
        start, length = view.get('byteOffset',0), view['byteLength']
        view['byteOffset'] = len(data)
        data.extend(binary[start:start+length])
        data.extend(b'\0' * (-len(data) % 4))
    for accessor in doc['accessors']:
        if 'bufferView' in accessor:
            accessor['bufferView'] = maps['bufferViews'][accessor['bufferView']]
    for mesh in doc['meshes']:
        for primitive in mesh['primitives']:
            primitive['attributes'] = {key:maps['accessors'][i] for key,i in primitive['attributes'].items()}
            for key,table in [('indices','accessors'),('material','materials')]:
                if key in primitive:
                    primitive[key] = maps[table][primitive[key]]
    for node in doc['nodes']:
        if 'mesh' in node:
            node['mesh'] = maps['meshes'][node['mesh']]
        if 'children' in node:
            node['children'] = [maps['nodes'][i] for i in node['children']]
    doc['buffers'] = [{'byteLength':len(data)}]
    return doc, data


def combine():
    heights_path = OUT / 'building-heights.json'
    heights = {r['osmId']: r for r in json.loads(heights_path.read_text())['buildings']} if heights_path.exists() else {}
    height_results = []
    selected, skipped = {}, []
    for path in sorted(PARTS.glob("*/*/*.glb"), key=lambda p: (p.stat().st_mtime_ns, str(p))):
        meta = json.loads(path.with_name("metadata.json").read_text())
        assert meta["osmId"], f"Missing stable ID: {path}"
        key = (meta["type"], meta["osmId"])
        if key in selected:
            skipped.append(str(selected[key].relative_to(ROOT)))
        selected[key] = path
    assert selected, "No part exports found"
    merged = {"asset": {"version": "2.0", "generator": "MapWRLD campus combiner"},
              "scene": 0, "scenes": [{"nodes": []}], **{key: [] for key in TABLES}}
    binary, sources, anchors = bytearray(), [], []
    for (category, osm_id), path in sorted(selected.items()):
        # Filenames are for people; scene-node identity comes from metadata.
        metadata = json.loads(path.with_name("metadata.json").read_text())
        part_name = metadata['name']
        source, data = read_glb(path)
        adjustment, height_status = height_adjustment(metadata, source, heights.get(osm_id)) if category == 'buildings' else (None, None)
        anchor = ground_anchor(source)
        if anchor is not None:
            anchors.append({"node": "part::" + part_name, "position": anchor})
        doc = copy.deepcopy(source)
        offsets = {key: len(merged[key]) for key in TABLES}
        for view in doc.get("bufferViews", []):
            assert view.get("buffer", 0) == 0 and "extensions" not in view
            view["byteOffset"] = view.get("byteOffset", 0) + len(binary)
        for accessor in doc.get("accessors", []):
            assert "sparse" not in accessor and "extensions" not in accessor
            if "bufferView" in accessor:
                accessor["bufferView"] += offsets["bufferViews"]
        for material in doc.get("materials", []):
            assert "Texture" not in json.dumps(material) and "extensions" not in material
        for mesh in doc.get("meshes", []):
            for primitive in mesh["primitives"]:
                assert "extensions" not in primitive and "targets" not in primitive
                primitive["attributes"] = {k: v + offsets["accessors"] for k, v in primitive["attributes"].items()}
                if "indices" in primitive:
                    primitive["indices"] += offsets["accessors"]
                if "material" in primitive:
                    primitive["material"] += offsets["materials"]
        for node in doc.get("nodes", []):
            assert not ({"skin", "camera", "extensions"} & node.keys())
            if "mesh" in node:
                node["mesh"] += offsets["meshes"]
            if "children" in node:
                node["children"] = [n + offsets["nodes"] for n in node["children"]]
        for key in TABLES:
            merged[key].extend(doc.get(key, []))
        roots = [n + offsets['nodes'] for n in doc['scenes'][doc.get('scene', 0)]['nodes']]
        if adjustment:
            height_node = len(merged['nodes'])
            merged['nodes'].append({'name':'height::'+part_name, 'children':roots,
                                    'matrix':adjustment['matrix'],
                                    'extras':{k:v for k,v in adjustment.items() if k != 'matrix'}})
            roots = [height_node]
        if category == 'buildings':
            height_results.append({'osmId':osm_id,'node':'part::'+part_name,'status':height_status,
                                   **({k:v for k,v in adjustment.items() if k != 'matrix'} if adjustment else {})})
        # Terrain placement replaces this parent's matrix at runtime. Keep the
        # independent height transform on a child so terrain cannot erase it.
        parent = len(merged["nodes"])
        merged["nodes"].append({"name": "part::" + part_name, "extras": {"osmId": osm_id, "category": category},
                                "children": roots})
        merged["scenes"][0]["nodes"].append(parent)
        binary.extend(data)
        binary.extend(b"\0" * (-len(binary) % 4))
        sources.append({"category": category, "osmId": osm_id, "path": str(path.relative_to(ROOT)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "nodes": len(source["nodes"])})
    merged["buffers"] = [{"byteLength": len(binary)}]
    result = encode_glb(merged, binary)
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "dartmouth-campus.glb"
    target.write_bytes(result)
    evidence_file = ROOT / 'data/energy-evidence.json'
    evidence_roots = set()
    if evidence_file.exists():
        evidence_roots = {'part::'+name for building in json.loads(evidence_file.read_text())['buildings'].values()
                          for name in building['twinObjects']}
    evidence_doc, evidence_binary = subset_glb(merged, binary, evidence_roots)
    evidence_result = encode_glb(evidence_doc, evidence_binary)
    (OUT/'dartmouth-evidence.glb').write_bytes(evidence_result)
    manifest_path = OUT/'model-manifest.json'
    manifest = json.loads(manifest_path.read_text())
    manifest['evidenceModel'] = '/models/dartmouth-campus/dartmouth-evidence.glb'
    manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
    (OUT / "terrain-anchors.json").write_text(json.dumps({"anchors": anchors}, separators=(",", ":")) + "\n")
    report = {"parts": len(sources), "buildings": sum(s["category"] == "buildings" for s in sources),
              "roads": sum(s["category"] == "roads" for s in sources), "bytes": len(result),
              "skippedOlderExports": skipped, "heightAdjustments":height_results, "sources": sources,
              "evidenceModel":{"buildings":len(evidence_doc['scenes'][0]['nodes']),
                               "nodes":len(evidence_doc['nodes']),"meshes":len(evidence_doc['meshes']),
                               "bytes":len(evidence_result)}}
    (OUT / "assembly-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Combined {report['buildings']} buildings and {report['roads']} roads: {len(result) / 1048576:.2f} MiB")
    print(f"Skipped {len(skipped)} older exports. Wrote {target}")
    print(f"Applied {sum(r['status'] == 'applied' for r in height_results)} sourced height estimates; source part exports are unchanged.")


if __name__ == "__main__":
    combine()
