#!/usr/bin/env python3
"""Pre-build the standalone campus scene's ground: bare-earth terrain, aerial imagery, and
per-building ground elevations. Run before deploying; nothing here runs at request time.

Sources (both U.S. public domain, attribution preserved in campus-terrain.json):
  - Terrain: USGS 3D Elevation Program (3DEP) bare-earth DEM, ~1 m lidar, NAVD88 meters.
  - Imagery: USGS The National Map Orthoimagery (USDA NAIP), natural color, from the cached
    USGSImageryOnly map service (the NAIP image services time out on campus-sized exports).
The above-ground building heights come separately from the NH GRANIT nDSM
(public/models/dartmouth-campus/building-heights.json); this script only handles ground.

Frame: the campus GLB's local meters (x east, y up, z south) from the manifest's calibrated
origin, linear in longitude/latitude. The DEM is exported in EPSG:4326 (linear in that same
frame) at ~1 m and bilinearly resampled onto the ~2 m mesh lattice.

  pip install rasterio numpy pillow
  python3 scripts/terrain/build-campus-terrain.py
"""
import hashlib
import io
import json
import struct
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from rasterio.features import rasterize
from scipy.ndimage import map_coordinates

ROOT = Path(__file__).resolve().parents[2]
CAMPUS = ROOT / "public/models/dartmouth-campus"
OUT = CAMPUS / "terrain"
NAMES = ROOT / "public/models/dartmouth-energy-twin/reports/osm-campus-names.json"
MANIFEST = CAMPUS / "model-manifest.json"
DEM_SERVICE = "https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage"
IMAGERY_SERVICE = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
GRID_METERS = 2.0          # terrain sample spacing; the client can decimate for lower quality
IMAGERY_WIDTH = 4000       # service maximum
MOBILE_IMAGERY_WIDTH = 2048


def fetch(url, params, timeout=180):
    request = urllib.request.Request(url + "?" + urllib.parse.urlencode(params), headers={"User-Agent": "MapWRLD campus terrain build"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def export(url, params, attempts=4):
    """ArcGIS exportImage: ask for JSON (retrying gateway timeouts), then download the file."""
    for attempt in range(attempts):
        try:
            meta = json.loads(fetch(url, {**params, "f": "json"}))
            if "href" not in meta:
                raise RuntimeError(f"export failed: {meta}")
            return meta, fetch(meta["href"], {})
        except (urllib.error.URLError, TimeoutError, RuntimeError) as error:
            if attempt == attempts - 1:
                raise
            print(f"  export retry {attempt + 1} after: {error}")


def main():
    bounds = json.loads(NAMES.read_text())["bounds"]
    manifest = json.loads(MANIFEST.read_text())
    origin, geo = manifest["origin"], manifest["georeference"]
    to_x = lambda lon: (lon - origin["longitude"]) / geo["longitudePerMeter"]
    to_z = lambda lat: (origin["latitude"] - lat) / geo["latitudePerMeter"]
    width_m = to_x(bounds["east"]) - to_x(bounds["west"])
    depth_m = to_z(bounds["south"]) - to_z(bounds["north"])
    cols = int(round(width_m / GRID_METERS)) + 1
    rows = int(round(depth_m / GRID_METERS)) + 1
    dlon = (bounds["east"] - bounds["west"]) / (cols - 1)
    dlat = (bounds["north"] - bounds["south"]) / (rows - 1)
    OUT.mkdir(parents=True, exist_ok=True)

    # ---- DEM: ArcGIS keeps pixels square in degrees, so export ~1 m square-degree pixels over a
    # padded box and resample onto the lattice using the TIFF's own georeferencing
    pad = 4 * max(dlon, dlat)
    bbox = [bounds["west"] - pad, bounds["south"] - pad, bounds["east"] + pad, bounds["north"] + pad]
    export_width = 1600
    export_height = int(round(export_width * (bbox[3] - bbox[1]) / (bbox[2] - bbox[0])))
    meta, tif = export(DEM_SERVICE, {
        "bbox": ",".join(f"{v:.9f}" for v in bbox), "bboxSR": 4326, "imageSR": 4326, "size": f"{export_width},{export_height}",
        "format": "tiff", "pixelType": "F32", "interpolation": "RSP_BilinearInterpolation", "noData": -9999,
    })
    with rasterio.MemoryFile(tif) as memory, memory.open() as src:
        source = src.read(1).astype("f8")
        inverse = ~src.transform
    lon_grid, lat_grid = np.meshgrid(bounds["west"] + np.arange(cols) * dlon, bounds["north"] - np.arange(rows) * dlat)
    col_f, row_f = inverse * (lon_grid, lat_grid)
    dem = map_coordinates(source, [row_f - 0.5, col_f - 0.5], order=1, mode="nearest")  # row 0 = north
    if (source < -1000).any() or (dem < -1000).any() or not np.isfinite(dem).all():
        raise RuntimeError("DEM has gaps inside the campus rectangle")
    if (dem < -1000).any() or not np.isfinite(dem).all():
        raise RuntimeError("DEM has gaps inside the campus rectangle")
    base = float(np.floor(dem.min()))
    encoded = np.round((dem - base) * 100).astype("<u2")  # centimeters above `base`
    (OUT / "campus-terrain.bin").write_bytes(encoded.tobytes())
    print(f"DEM {cols}x{rows} at ~{width_m / (cols - 1):.2f} x {depth_m / (rows - 1):.2f} m, elevation {dem.min():.1f}-{dem.max():.1f} m")

    # ---- imagery: exactly the campus bbox, aspect kept so the service doesn't widen it
    aspect = depth_m / width_m
    lon_span = bounds["east"] - bounds["west"]
    lat_span = bounds["north"] - bounds["south"]
    height_px = int(round(IMAGERY_WIDTH * lat_span / lon_span))
    # 2x2 tiles: a single 4000 px export regularly times out at the gateway
    image = Image.new("RGB", (IMAGERY_WIDTH, height_px))
    half_w, half_h = IMAGERY_WIDTH // 2, height_px // 2
    for ty in range(2):
        for tx in range(2):
            px0, py0 = tx * half_w, ty * half_h
            px1, py1 = (IMAGERY_WIDTH if tx else half_w), (height_px if ty else half_h)
            west = bounds["west"] + lon_span * px0 / IMAGERY_WIDTH
            east = bounds["west"] + lon_span * px1 / IMAGERY_WIDTH
            north = bounds["north"] - lat_span * py0 / height_px
            south = bounds["north"] - lat_span * py1 / height_px
            imeta, jpg = export(IMAGERY_SERVICE, {
                "bbox": f"{west},{south},{east},{north}", "bboxSR": 4326, "imageSR": 4326,
                "size": f"{px1 - px0},{py1 - py0}", "format": "jpg", "transparent": "false",
            })
            # the service rounds extents to whole pixels; anything under half a pixel is fine
            if abs(imeta["extent"]["xmin"] - west) > 0.5 * lon_span / IMAGERY_WIDTH or abs(imeta["extent"]["ymax"] - north) > 0.5 * lat_span / height_px:
                raise RuntimeError(f"imagery extent not honored: {imeta['extent']}")
            image.paste(Image.open(io.BytesIO(jpg)).convert("RGB"), (px0, py0))
    image.save(OUT / "campus-imagery.jpg", quality=82, optimize=True, progressive=True)
    small = image.resize((MOBILE_IMAGERY_WIDTH, int(round(MOBILE_IMAGERY_WIDTH * image.height / image.width))), Image.LANCZOS)
    small.save(OUT / "campus-imagery-2048.jpg", quality=80, optimize=True, progressive=True)
    print(f"Imagery {image.width}x{image.height} (~{width_m / image.width:.2f} m/px)")

    # ---- per-building ground elevation from the GLB footprints
    ground = building_ground(dem, bounds, cols, rows, origin, geo)
    (OUT / "building-ground.json").write_text(json.dumps(ground, separators=(",", ":")) + "\n")

    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    (OUT / "campus-terrain.json").write_text(json.dumps({
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "bounds": bounds,
        "frame": {"description": "campus GLB local meters: x east, y up (elevation - baseElevation), z south", "origin": origin, "georeference": geo},
        "grid": {"cols": cols, "rows": rows, "rowOrder": "north-to-south", "encoding": "uint16 little-endian centimeters above baseElevation", "baseElevation": base,
                 "minElevation": round(float(dem.min()), 2), "maxElevation": round(float(dem.max()), 2), "spacingMeters": [round(width_m / (cols - 1), 3), round(depth_m / (rows - 1), 3)]},
        "imagery": {"file": "campus-imagery.jpg", "mobileFile": "campus-imagery-2048.jpg", "width": image.width, "height": image.height},
        "files": {name: digest(OUT / name) for name in ("campus-terrain.bin", "campus-imagery.jpg", "campus-imagery-2048.jpg", "building-ground.json")},
        "attribution": [
            {"layer": "terrain", "text": "Elevation: USGS 3D Elevation Program (3DEP)", "license": "U.S. public domain", "service": DEM_SERVICE.rsplit("/", 1)[0], "copyright": meta.get("copyrightText")},
            {"layer": "imagery", "text": "Imagery: USGS The National Map Orthoimagery (USDA NAIP)", "license": "U.S. public domain", "service": IMAGERY_SERVICE.rsplit("/", 1)[0]},
        ],
        "approximations": [
            "Terrain is bare earth (3DEP DEM, NAVD88), resampled bilinearly to a ~2 m grid; building heights come from the separate NH GRANIT nDSM.",
            "Buildings are rigid and sit on the lowest ground under their footprint, so on slopes the uphill side is partly embedded.",
            "Imagery is the National Map's cached orthoimagery (refreshed June 2024) and shows conditions at capture time and includes building roofs and tree crowns that the 3D layers also draw.",
            "Vertical datum is NAVD88 orthometric height; the scene stores heights relative to baseElevation.",
        ],
    }, indent=2) + "\n")
    print("Wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


def building_ground(dem, bounds, cols, rows, origin, geo):
    data = (CAMPUS / "dartmouth-campus-styled.glb").read_bytes()
    json_length = struct.unpack_from("<I", data, 12)[0]
    gltf = json.loads(data[20:20 + json_length])
    binary = memoryview(data)[20 + json_length + 8:]
    nodes = gltf["nodes"]
    parent = {c: i for i, n in enumerate(nodes) for c in n.get("children", [])}
    def root(i):
        while i in parent:
            i = parent[i]
        return nodes[i]["name"]
    def array(index, dtype, width):
        acc = gltf["accessors"][index]
        view = gltf["bufferViews"][acc["bufferView"]]
        return np.frombuffer(binary, dtype=dtype, count=acc["count"] * width, offset=view.get("byteOffset", 0) + acc.get("byteOffset", 0)).reshape(-1, width)
    index_types = {5121: "<u1", 5123: "<u2", 5125: "<u4"}
    transform = rasterio.transform.from_bounds(bounds["west"], bounds["south"], bounds["east"], bounds["north"], cols - 1, rows - 1)
    shapes = {}
    for i, node in enumerate(nodes):
        if "mesh" not in node:
            continue
        name = root(i)
        if not name.startswith("part::building__"):
            continue
        for primitive in gltf["meshes"][node["mesh"]]["primitives"]:
            p = array(primitive["attributes"]["POSITION"], "<f4", 3)
            lon = origin["longitude"] + p[:, 0] * geo["longitudePerMeter"]
            lat = origin["latitude"] - p[:, 2] * geo["latitudePerMeter"]
            acc = gltf["accessors"][primitive["indices"]]
            tris = array(primitive["indices"], index_types[acc["componentType"]], 1).reshape(-1, 3)
            shapes.setdefault(name, []).extend({"type": "Polygon", "coordinates": [[[float(lon[a]), float(lat[a])], [float(lon[b]), float(lat[b])], [float(lon[c]), float(lat[c])], [float(lon[a]), float(lat[a])]]]} for a, b, c in tris)
    out = {}
    for name, polygons in shapes.items():
        # the DEM's pixel centers are the lattice; shift by half a cell so rasterize samples them
        mask = rasterize(((poly, 1) for poly in polygons), out_shape=(rows - 1, cols - 1), transform=transform, all_touched=True, dtype="u1").astype(bool)
        mask = np.pad(mask, ((0, 1), (0, 1))) | np.pad(mask, ((1, 0), (1, 0)))
        values = dem[mask]
        if not len(values):
            continue
        out[name] = {"min": round(float(values.min()), 2), "median": round(float(np.median(values)), 2), "max": round(float(values.max()), 2)}
    print(f"Ground elevations for {len(out)} buildings")
    return out


if __name__ == "__main__":
    main()
