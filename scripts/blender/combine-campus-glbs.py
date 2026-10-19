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


def ground_anchor(doc):
    """Footprint center and base height in the exported east/up/south frame."""
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
    return [(low[0] + high[0]) / 2, low[1], (low[2] + high[2]) / 2]


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


def combine():
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
        part_name = json.loads(path.with_name("metadata.json").read_text())["name"]
        source, data = read_glb(path)
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
        # A named parent keeps all detail meshes associated with one building.
        parent = len(merged["nodes"])
        merged["nodes"].append({"name": "part::" + part_name, "extras": {"osmId": osm_id, "category": category},
                                "children": [n + offsets["nodes"] for n in doc["scenes"][doc.get("scene", 0)]["nodes"]]})
        merged["scenes"][0]["nodes"].append(parent)
        binary.extend(data)
        binary.extend(b"\0" * (-len(binary) % 4))
        sources.append({"category": category, "osmId": osm_id, "path": str(path.relative_to(ROOT)),
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "nodes": len(source["nodes"])})
    merged["buffers"] = [{"byteLength": len(binary)}]
    encoded = json.dumps(merged, separators=(",", ":")).encode()
    encoded += b" " * (-len(encoded) % 4)
    result = struct.pack("<4sII", b"glTF", 2, 28 + len(encoded) + len(binary))
    result += struct.pack("<II", len(encoded), 0x4E4F534A) + encoded
    result += struct.pack("<II", len(binary), 0x004E4942) + binary
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / "dartmouth-campus.glb"
    target.write_bytes(result)
    (OUT / "terrain-anchors.json").write_text(json.dumps({"anchors": anchors}, separators=(",", ":")) + "\n")
    report = {"parts": len(sources), "buildings": sum(s["category"] == "buildings" for s in sources),
              "roads": sum(s["category"] == "roads" for s in sources), "bytes": len(result),
              "skippedOlderExports": skipped, "sources": sources}
    (OUT / "assembly-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Combined {report['buildings']} buildings and {report['roads']} roads: {len(result) / 1048576:.2f} MiB")
    print(f"Skipped {len(skipped)} older exports. Wrote {target}")


if __name__ == "__main__":
    combine()
