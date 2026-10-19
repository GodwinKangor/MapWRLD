#!/usr/bin/env python3
"""Detect individual trees on campus from Meta/WRI's 1 m global canopy height map.

Reads only the campus window of the canopy height GeoTIFF over HTTP, finds treetops as local
height maxima, drops any that fall inside a building (footprints projected from the campus GLB,
so they match what the map renders) or on a vehicle road, and writes
public/models/dartmouth-campus/campus-trees.json for the map to instance.

Data: High Resolution Canopy Height Maps, Meta & World Resources Institute (CC BY 4.0).
Requires: pip install rasterio numpy scipy

  python3 scripts/reference-tools/fetch-campus-trees.py
"""
import hashlib
import json
import math
import struct
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.warp import transform, transform_bounds, transform_geom
from rasterio.windows import from_bounds
from scipy import ndimage

ROOT = Path(__file__).resolve().parents[2]
OSM_NAMES = ROOT / "public/models/dartmouth-energy-twin/reports/osm-campus-names.json"
ROADS = ROOT / "public/models/dartmouth-campus/campus-roads.json"
CAMPUS_GLB = ROOT / "public/models/dartmouth-campus/dartmouth-campus.glb"
MANIFEST = ROOT / "public/models/dartmouth-campus/model-manifest.json"
OUTPUT = ROOT / "public/models/dartmouth-campus/campus-trees.json"
CHM_URL = "https://dataforgood-fb-data.s3.amazonaws.com/forests/v1/alsgedi_global_v6_float/chm/{quadkey}.tif"
MIN_HEIGHT = 3.0          # meters; lower canopy is shrubs/hedges
CONIFER_SHARE = 0.35      # the canopy map has no species; mix forms so woods don't look uniform
VEHICLE_ROADS = {"primary", "secondary", "tertiary", "residential", "unclassified", "service"}


def quadkey(lat, lon, zoom=9):
    x = (lon + 180) / 360 * (1 << zoom)
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * (1 << zoom)
    key = ""
    for i in range(zoom, 0, -1):
        mask = 1 << (i - 1)
        key += str((1 if int(x) & mask else 0) + (2 if int(y) & mask else 0))
    return key


def glb_footprints():
    """Top-down triangles of every building mesh in the campus GLB, as lon/lat polygons."""
    data = CAMPUS_GLB.read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + json_length])
    binary = memoryview(data)[20 + json_length + 8:]
    manifest = json.loads(MANIFEST.read_text())
    origin, geo = manifest["origin"], manifest["georeference"]

    def array(index, dtype, width):
        accessor = gltf["accessors"][index]
        view = gltf["bufferViews"][accessor["bufferView"]]
        offset = view.get("byteOffset", 0) + accessor.get("byteOffset", 0)
        return np.frombuffer(binary, dtype=dtype, count=accessor["count"] * width, offset=offset).reshape(-1, width)

    index_types = {5121: "<u1", 5123: "<u2", 5125: "<u4"}
    polygons = []
    for node in gltf["nodes"]:
        if "mesh" not in node or not node.get("name", "").startswith("building__"):
            continue
        for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
            positions = array(primitive["attributes"]["POSITION"], "<f4", 3)
            # glTF frame is east / up / south in meters from the manifest origin
            lon = origin["longitude"] + positions[:, 0] * geo["longitudePerMeter"]
            lat = origin["latitude"] - positions[:, 2] * geo["latitudePerMeter"]
            accessor = gltf["accessors"][primitive["indices"]] if "indices" in primitive else None
            triangles = array(primitive["indices"], index_types[accessor["componentType"]], 1).reshape(-1, 3) if accessor else np.arange(len(positions)).reshape(-1, 3)
            for a, b, c in triangles:
                ring = [[float(lon[i]), float(lat[i])] for i in (a, b, c, a)]
                polygons.append({"type": "Polygon", "coordinates": [ring]})
    return polygons


def main():
    bounds = json.loads(OSM_NAMES.read_text())["bounds"]
    center = ((bounds["south"] + bounds["north"]) / 2, (bounds["west"] + bounds["east"]) / 2)
    url = CHM_URL.format(quadkey=quadkey(*center))
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"), rasterio.open("/vsicurl/" + url) as src:
        window = from_bounds(*transform_bounds("EPSG:4326", src.crs, bounds["west"], bounds["south"], bounds["east"], bounds["north"]), transform=src.transform).round_offsets().round_lengths()
        chm = src.read(1, window=window).astype("f4")
        grid = src.window_transform(window)
        crs = src.crs
    pixel = abs(grid.a)
    print(f"Canopy window {chm.shape} at {pixel:.2f} m/px, max {chm.max():.0f} m")

    # Treetops: local maxima of the lightly smoothed canopy, with a wider search for taller trees.
    smooth = ndimage.gaussian_filter(chm, sigma=1)
    small = smooth == ndimage.maximum_filter(smooth, size=5)   # ~6 m crowns
    large = smooth == ndimage.maximum_filter(smooth, size=9)   # ~11 m crowns
    tops = (smooth >= MIN_HEIGHT) & np.where(smooth >= 14, large, small)

    # Keep trunks off buildings and vehicle roads.
    shapes = [(transform_geom("EPSG:4326", crs, polygon), 1) for polygon in glb_footprints()]
    roads = json.loads(ROADS.read_text())["roads"]
    road_lines = [(transform_geom("EPSG:4326", crs, {"type": "LineString", "coordinates": r["coordinates"]}), 1) for r in roads if r["highway"] in VEHICLE_ROADS]
    blocked = rasterize(shapes, out_shape=chm.shape, transform=grid, fill=0, all_touched=True, dtype="u1").astype(bool)
    on_road = rasterize(road_lines, out_shape=chm.shape, transform=grid, fill=0, all_touched=True, dtype="u1").astype(bool)
    blocked |= ndimage.binary_dilation(on_road, iterations=max(1, round(3 / pixel)))
    rows, cols = np.nonzero(tops & ~blocked)
    print(f"Treetops: {int(tops.sum())} detected, {len(rows)} kept after building/road filter")

    xs, ys = rasterio.transform.xy(grid, rows, cols)
    lons, lats = transform(crs, "EPSG:4326", xs, ys)
    trees = []
    for lon, lat, height in zip(lons, lats, chm[rows, cols]):
        if not (bounds["west"] <= lon <= bounds["east"] and bounds["south"] <= lat <= bounds["north"]):
            continue
        key = f"{lon:.6f},{lat:.6f}"
        conifer = int(hashlib.sha1(key.encode()).hexdigest()[:4], 16) / 0xFFFF < CONIFER_SHARE
        crown = min(6.0, max(1.5, 0.6 + 0.16 * float(height)))
        trees.append([round(lon, 7), round(lat, 7), round(float(height), 1), round(crown, 1), 1 if conifer else 0])

    OUTPUT.write_text(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "High Resolution Canopy Height Maps, Meta & World Resources Institute",
        "license": "CC BY 4.0",
        "url": url,
        "bounds": bounds,
        "fields": ["longitude", "latitude", "heightMeters", "crownRadiusMeters", "conifer"],
        "trees": trees,
    }, separators=(",", ":")) + "\n")
    print(f"Wrote {len(trees)} trees -> {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size / 1e3:.0f} KB)")


if __name__ == "__main__":
    main()
