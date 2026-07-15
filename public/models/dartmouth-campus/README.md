# Dartmouth Campus Model Drop-In

Place the optimized campus model here as:

```text
dartmouth-campus.glb
```

The app reads `model-manifest.json` for the expected path, units, and origin. Until the GLB exists, the Cesium terrain, imagery, and OSM building fallback stay active.

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
