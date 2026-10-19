"""Recover the campus export's geographic frame from source footprint bounds.

Usage: python3 scripts/reference-tools/calibrate-campus-georeference.py source.geojson
Uses a consensus fit: historical nearest-neighbor naming mismatches must not
move individual buildings to the wrong footprint or distort the campus frame.
"""
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAMPUS = ROOT / "public/models/dartmouth-campus"


def points(coordinates):
    if isinstance(coordinates[0], (int, float)):
        return [coordinates]
    return [point for child in coordinates for point in points(child)]


def regression(rows, axis):
    xs = [row["local"][axis] for row in rows]
    ys = [row["geographic"][axis] for row in rows]
    mx, my = statistics.mean(xs), statistics.mean(ys)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
    return slope, my - slope * mx


def calibrate(source):
    features = json.loads(source.read_text())["features"]
    footprints = {}
    for feature in features:
        vertices = points(feature["geometry"]["coordinates"])
        footprints[feature.get("id", feature["properties"].get("@id"))] = [
            (min(p[i] for p in vertices) + max(p[i] for p in vertices)) / 2 for i in range(2)
        ]
    anchors = json.loads((CAMPUS / "terrain-anchors.json").read_text())["anchors"]
    rows = []
    for anchor in anchors:
        osm_id = "way/" + anchor["node"].split("__way_")[-1]
        if osm_id in footprints:
            east, _, south = anchor["position"]
            rows.append({"node": anchor["node"], "local": [east, -south], "geographic": footprints[osm_id]})
    selected = rows
    for _ in range(8):
        lon_scale, lon_origin = regression(selected, 0)
        lat_scale, lat_origin = regression(selected, 1)
        for row in rows:
            east, north = row["local"]
            lon, lat = row["geographic"]
            row["residualMeters"] = math.hypot(
                (lon_origin + east * lon_scale - lon) * 111320 * math.cos(math.radians(lat_origin)),
                (lat_origin + north * lat_scale - lat) * 111132,
            )
        selected = [row for row in rows if row["residualMeters"] < 2]
        if len(selected) < max(20, len(rows) // 2):
            raise ValueError("Insufficient geographic consensus; refusing to change the model frame")
    manifest_path = CAMPUS / "model-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    before = manifest["origin"].copy()
    manifest["origin"].update(longitude=lon_origin, latitude=lat_origin)
    manifest["georeference"] = {"longitudePerMeter": lon_scale, "latitudePerMeter": lat_scale}
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    report = {"source": source.name, "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "previousOrigin": before, "origin": manifest["origin"], "georeference": manifest["georeference"],
              "matchedFootprints": len(rows), "consensusFootprints": len(selected),
              "maxConsensusResidualMeters": max(row["residualMeters"] for row in selected),
              "controls": rows}
    (CAMPUS / "georeference-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "controls"}, indent=2))


if __name__ == "__main__":
    calibrate(Path(sys.argv[1]))
