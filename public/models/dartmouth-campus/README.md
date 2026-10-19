# Dartmouth Campus Model Drop-In

Place the optimized campus model here as:

```text
dartmouth-campus.glb
```

The app reads `model-manifest.json` and loads the `campusModel` GLB (the styled copy) into the standalone Three.js scene, which merges every building into one batched mesh and grounds it on the pre-built terrain (`terrain/`).

## Combined campus preview

Run `npm run model:dartmouth:combine` after exporting updated building parts.
Building GLB/FBX filenames use their display names (for example, `McNutt Hall.glb`).
The [building index](../dartmouth-energy-twin/renders/buildings/README.md) lists
all exported buildings alphabetically. Folder names, OSM IDs, and scene-node
names remain stable; metadata and manifests contain the readable file paths.
This combines the existing GLBs under `dartmouth-energy-twin/renders`, keeping
one export per category/OSM ID (newest modification time wins). It preserves
the detailed meshes within each selected export, their transforms, and materials.
It never imports the old Blender scene or modifies source GLBs.
`assembly-report.json` records every included source and its SHA-256 hash.
The same command builds `dartmouth-evidence.glb`, containing only the buildings
referenced by `data/energy-evidence.json`. The standalone scene no longer loads it:
evidence highlighting is a per-building state on the single campus mesh. Mesh buffers, materials, height
adjustments and terrain parent names are preserved. Rebuild after regenerating
the evidence index so newly matched buildings can be highlighted.

### Reference-based building colors

Run `python3 scripts/blender/style-campus-glb.py` after assembling the campus.
This writes styled versions of both the campus and compact evidence GLBs and
updates the manifest. `data/building-reference-colors.json` stores approximate
sRGB wall, roof and existing trim-material colors selected by visual review of
the saved reference images. Only observed colors with aligned footprint identities
are applied. Obstructed views, uncertain building identities and unrelated search
results are withheld; other massing models use a neutral illustrative fallback.
`building-color-report.json` records each decision and source-image checksum.
Styling adds vertex colors or material overrides without changing geometry,
height corrections, terrain placement, or the original part exports.
The Public records layer applies a separate evidence tint; switch it off when
comparing the base material colors with the photos.
The combiner supports the current static, untextured exports and rejects
unsupported features such as skins, animations, and texture references.

### Sourced placeholder heights

`building-heights.json` records height candidates, provenance, raster statistics,
footprint alignment, and review flags for each OSM building. Regenerate it with:

```bash
python3 -m pip install requests numpy Pillow
python3 scripts/reference-tools/collect-building-heights.py --footprints assets/height-data/building-footprints.geojson
npm run model:dartmouth:combine
python3 -m unittest discover -s scripts/tests -p 'test_building_heights.py'
```

Sources are OSM-reported height, or NH GRANIT's 2-meter LiDAR-derived normalized
surface model from collections available January 2020. Missing usable measurements
can fall back to OSM floor counts at an explicitly estimated 3.2 meters per floor.
The collector takes median raster heights at least one meter inside footprints,
excludes courtyards, and rejects sparse, implausible or highly variable surfaces.
Trees, rooftop equipment and construction since the LiDAR survey remain reasons
for manual review. NH GRANIT / University of New Hampshire must be credited.
The input footprints, raster, request metadata and checksum are cached in
`assets/height-data/`; the raster is fetched only if the cache is missing.

The combiner changes only simple 20-meter fallback models whose source footprints
align within two meters. Detailed geometry and existing nondefault heights are
preserved. Heights are applied on separate child nodes so terrain placement cannot
overwrite them, with the base and all horizontal coordinates held fixed.
`assembly-report.json` records applied heights and the reason for each skipped
building. Source GLB/FBX exports and the Blender scene remain unchanged; rebuild
the combined web model to reproduce the adjusted campus preview.

The combiner also generates `terrain-anchors.json` (each part's footprint center and
base height); it was used by the former Cesium view and is kept for tooling.
The standalone scene grounds buildings from `terrain/building-ground.json`, which
`scripts/terrain/build-campus-terrain.py` computes from each building's footprint and
the USGS 3DEP bare-earth DEM: every building sits on the lowest ground under its
footprint. Re-run that script after rebuilding or restyling the campus GLB.

The geographic origin and angular scale are calibrated from source GeoJSON
footprints, independently of the camera's home position. `georeference-report.json`
records the reference points and fit residuals. Recalibrate after changing the
source coordinate frame with
`python3 scripts/reference-tools/calibrate-campus-georeference.py /path/to/buildings.geojson`.
The fit uses a consensus of matching footprints rather than moving each building
to its assigned OSM ID, because some historical nearest-neighbor name assignments
do not match the geometry. The entire source layout is preserved.

Buildings remain rigid, so their edges may intersect sloping terrain; this does
not deform them to follow every terrain point. The GLB's road objects are
edge-only centerlines (no faces), so glTF export leaves them empty. The map
instead drapes roads onto the terrain from `campus-roads.json`, which holds OSM
highway lines clipped to the campus rectangle. Widths are in meters per highway
class. Refresh it with `node scripts/reference-tools/fetch-dartmouth-osm-roads.mjs`.

The campus rectangle is the whole map world. Terrain, imagery, buildings, markers
and roads all stop at its edge, and the sky box, sun, moon, ground atmosphere
and fog are off. Buildings whose OSM centroid lies outside the rectangle are left
out of the data and hidden in the model.

## Building Colors And Trees

The map loads `dartmouth-campus-styled.glb`, a recoloured copy of the assembled
`dartmouth-campus.glb`. `scripts/blender/style-campus-glb.py` gives every bare
building mesh vertex colours. Faces pointing up become roof and the rest
become wall, using a palette chosen by OSM building type (academic, residential,
athletic, civic, commercial, utility) with ±5% variation per building. The
named materials on Baker Library and Dartmouth Hall get real colours. Re-run it
after re-assembling the campus GLB; it also points `campusModel` in the manifest
at the styled copy.

Trees come from `campus-trees.json`. `scripts/reference-tools/fetch-campus-trees.py`
reads the campus window of Meta & WRI's 1 m High Resolution Canopy Height Map
(CC BY 4.0) over HTTP and finds treetops of at least 3 m. It drops any that fall
inside a building (footprints projected from the campus GLB) or on a vehicle road,
and records each tree's height and crown size. It needs `pip install rasterio numpy scipy`.
The map draws all trees as one GPU-instanced model of three low-poly forms
(`components/campus-trees.ts`).

## GeoJSON To Web Model Workflow

Use this path when starting from Overpass Turbo or another GIS source.

### 1. Export GeoJSON From Overpass Turbo

1. Run the Dartmouth rectangle query in Overpass Turbo.
2. Click `Export`.
3. Choose `GeoJSON`.
4. Save the file as:

```text
dartmouth-campus.geojson
```

Keep the export focused on the campus rectangle. Exporting too much Hanover/river/highway context makes Blender and Maya heavier than needed.

### 2. Import GeoJSON Into Blender

Blender does not import GeoJSON natively in the default install, so use one of these paths:

- Recommended: install the BlenderGIS add-on, then use `GIS > Import > GeoJSON`.
- Manual fallback: convert GeoJSON to DXF, OBJ, or SVG first, then import that into Blender.

Suggested BlenderGIS settings:

- Coordinate system: use the source data CRS if prompted, usually `EPSG:4326`.
- Projection: reproject to a local metric projection if available.
- Units: meters.
- Keep origin near the Dartmouth campus center, not at world zero thousands of miles away.

### 3. Clean The Imported Geometry In Blender

After import:

1. Separate major asset types into collections:
   - `buildings`
   - `roads`
   - `paths`
   - `fields`
   - `water`
   - `trees`
2. Delete geometry outside the Dartmouth rectangle.
3. Simplify curves and outlines where possible.
4. Convert building footprints to meshes.
5. Extrude placeholder buildings only enough for orientation.
6. Remove duplicate vertices and tiny fragments.
7. Apply scale and transforms.
8. Keep object names readable, for example `baker_berry`, `life_sciences`, `soccer_field`.

For the first web version, avoid detailed trees, bevels, interiors, or high-density street furniture. The goal is a clean campus massing model that runs smoothly.

### 4. Blender Export For Maya

If you want to continue modeling in Maya:

1. Select only the cleaned campus geometry.
2. Export as `FBX`.
3. Use meters.
4. Disable animation.
5. Disable cameras and lights unless you specifically need them.
6. Keep materials simple.

Suggested file name:

```text
dartmouth-campus-base.fbx
```

### 5. Maya Cleanup And Export

In Maya:

1. Import the FBX.
2. Check scale against a known campus feature.
3. Freeze transforms only after the model is positioned correctly.
4. Delete construction history.
5. Keep the campus centered around the origin listed in `model-manifest.json`.
6. Group objects by area or system:
   - `campus_buildings`
   - `energy_assets`
   - `fields`
   - `roads_paths`
   - `terrain_reference`
7. Export selected geometry as `FBX export`.

Maya FBX export settings:

- File type: `FBX export`
- Units: meters
- Animation: off
- Cameras: off
- Lights: off
- Smoothing groups: on
- Tangents/binormals: on if materials need them
- Embed media: off unless textures are intentionally included

### 6. Convert To GLB For The App

The app wants a binary glTF file:

```text
dartmouth-campus.glb
```

Recommended path:

1. Import the final Maya FBX into Blender.
2. Inspect scale, materials, and orientation.
3. Export from Blender as `glTF 2.0`.
4. Choose `Format: glTF Binary (.glb)`.
5. Disable animation.
6. Export only selected objects if the scene has references.

Place the final file here:

```text
public/models/dartmouth-campus/dartmouth-campus.glb
```

Then update `model-manifest.json`:

```json
"status": "ready"
```

Keep it as:

```json
"status": "pending"
```

until the GLB exists and has been checked in the app.

## Quick Quality Checklist

Before using the model in the app, confirm:

- Scale is in meters.
- Campus is centered around the manifest origin.
- The Life Sciences building and athletic fields are included.
- Geometry outside the Dartmouth rectangle is deleted or simplified.
- No hidden duplicate imported layers remain.
- Materials are simple and web-friendly.
- File size is reasonable for browser loading.
- Building names are clear enough to replace pieces later.
