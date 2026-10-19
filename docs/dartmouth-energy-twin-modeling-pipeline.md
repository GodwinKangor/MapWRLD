# Dartmouth Energy Twin Modeling Pipeline

This feature adds a code-driven Blender pipeline for iterating on named campus buildings from references instead of hand-modeling every asset.

## Current Scope

- Work from `public/models/dartmouth-energy-twin/dartmouth-energy-twin.blend`.
- Export individual building parts to GLB/FBX folders under `public/models/dartmouth-energy-twin/renders/buildings`.
- Store named exterior references beside each building under `references/`.
- Enforce modeling rules with `scripts/blender/blender-audit-model-laws.py` before preview/export handoff.

## Rules We Are Enforcing

- Windows and doors must be integrated wall faces with edge loops, not floating panels.
- Window and door counts must match the approved reference plan for each named exterior wall.
- Roof and tower details must use approved roof/tower references.
- Roof/tower/detail objects must be supported; no floating or unsupported overlaps.
- Geometry should avoid loose vertices/edges and n-gons where possible.
- Preview renders must be inspected before a building is considered ready.

## Modeling Modules

Reusable Blender helpers live in `scripts/blender/blender_modules/`.

- `major_wall_detail_module.py` builds quad wall grids with integrated window/door cells and tracks other reference-backed facade features.
- `reference_module.py` compiles selected references into scaled elevation boards and JSON for model scripts.
- `window_module.py` and `door_module.py` create opening plans that become wall faces.
- `roof_module.py` creates flat, gable/prism, and hip/prism roof masses from approved roof references and stores satellite-derived roof zone metadata.
- `chimney_tower_module.py` creates supported chimneys, cupolas, and tiered towers.
- `staircase_module.py` creates exterior stairs tied to references.
- `symmetry_module.py` checks mirrored facade counts before geometry is generated.
- `inspect_module.py` reports topology, bounds, metadata, and quad-cleanliness issues.

Every generated detail should store `mwrld_detail_for`, `mwrld_module`, `mwrld_reference`, and `mwrld_wall_id` when it belongs to a named exterior wall. This keeps each mesh traceable back to the wall/roof/tower reference used for modeling.

Before modeling details for a building, generate its scaled reference boards:

```sh
npm run model:dartmouth:reference-sheets -- dartmouth-hall
```

The output goes to:

- `references/elevation-sheets/scaled-reference-board.svg/json` for oblique photo evidence with overlays.
- `references/elevation-sheets/orthographic-elevations.svg/json` for straight modeling diagrams.

Use the orthographic SVG/JSON for model-module inputs such as front/rear/left/right/roof grouping, wall width, estimated height, approved/blocked status, source image, window count, door count, opening placement, and primitive hints.

Roof panels must include satellite-derived `roofZones` before detailed roof modeling. Each zone needs an `id`, `kind`, `primitive`, normalized satellite bounds, `visibleElevations`, status, and source image. The compiler derives `roofElevationPlans` for front, rear, left-side, and right-side from those same zones, so the roof module does not invent a front/side/rear profile separately from the roof satellite. Roof panels should also include `roofElevationProfiles`: diagrammatic front/rear/side silhouettes that show triangular prism pediments/gables, hip roof masses, rear strips, and support pads as they should read in 3D.

Primitive hints translate references into starter geometry families: `quad_grid_wall`, `recessed_rectangular_face_opening`, `hip_prism_roof`, `gable_prism_roof`, `flat_roof_slab`, `tiered_box_stack`, `rectangular_chimney_shaft_with_cap`, `triangular_pediment_prism`, `thin_spire_cylinder_or_cone`, and similar module-ready shapes.

Primitive hints must include reliability metadata: `status`, `confidence`, `evidence`, and `requiresReview`. Only verified/required primitives with `requiresReview: false` should be used directly by model modules. Allowed, unclassified, low-confidence, or reference-missing primitives must stay in `reviewPrimitives` or `ruleDerivedPrimitives` until the specific wall/roof/tower reference is inspected.

Wall panels also include `openingLayout`: one record per planned window/door with `id`, `kind`, `xMeters`, `zMeters`, `widthMeters`, `heightMeters`, and `centerFraction`. The SVG overlays those openings as blue window rectangles and orange door rectangles, so placement can be inspected before geometry is generated. These positions come from approved modeling rules such as `doorPositions`; if exact measured positions are not available, they remain rule-derived starter positions and should be corrected after reference inspection.

Wall panels may also include `majorWallFeatures` for facade details that are not windows, doors, roofs, chimneys, towers, stairs, or platforms. Examples include entry surrounds, flat entry cap trim, plaque panels, pilasters, belt courses, cornices, vents, and decorative trim. The SVG overlays these as purple rectangles, and unverified features are reported as `major-wall-feature-needs-review`.

Keep the feature taxonomy strict: entry stairs and landings belong in `stairFeatures` and the `staircase_module`; entry surrounds and flat cap trim belong in `majorWallFeatures`; triangular roof/front-gable pediments belong to the roof module. Do not label an entry stair/platform as a pediment, and do not attach the front roof pediment to the cupola/tower stack.

The orthographic compiler groups references as `front`, `rear`, `left-side`, `right-side`, `roof`, and `addition`. Use explicit `elevationRoles` in `modeling-rules.json` when a building has ambiguous wing names or oblique photos. Count proofs must keep windows and doors separate, for example `windows 3 rows x 6 = 18` and `doors rows 1 = 1`.

For angled photos, the compiler does not pretend the source pixels are perpendicular. A real pixel warp requires facade control points in `modeling-rules.json` for `top-left`, `top-right`, `bottom-right`, and `bottom-left`. Without those, the orthographic board is generated from approved wall dimensions, `windowRows`, `doorPositions`, and symmetry/count inference. Use `countMethod: "observed-plus-symmetry-inference"` when hidden openings are inferred from repeated facade rhythm.

Opening layouts must pass `layoutIssues: []` before model modules consume them. Door/window overlaps are reported as `opening-overlap` issues, and the modeler should adjust `windowSillMeters`, `windowRows`, `doorPositions`, or explicit `openingLayout` records before generating mesh edge loops. Door records must include a verified `positionStatus`; default or unverified door placements are reported as `door-position-needs-review`.

For repeated facades, `windowRows` may use explicit column slots with `windowGridColumns`, such as a seven-column rhythm where the center ground slot is reserved for a door. This keeps symmetry from inventing the wrong grid just because the total count can be multiplied another way.

## Integrated Facade Pipeline

Windows/doors-as-real-wall-openings and satellite-derived roofs were originally built as two separate one-off scripts, one hardcoded to Dartmouth Hall and one to Baker Library. They have been merged into a single generic driver, `scripts/blender/blender-build-building-integrated.py`, backed by shared logic in `scripts/blender/blender_modules/integrated_facade_module.py`:

```sh
npm run model:dartmouth:build-integrated -- dartmouth-hall
npm run model:dartmouth:build-integrated -- baker-library
npm run model:dartmouth:build-integrated:all
```

The driver works off each building's own `references/modeling-rules.json` and `references/elevation-sheets/orthographic-elevations.json` rather than per-building Python:

- Wall openings come from `windowsAndDoors.wallOpeningPlans` (or the richer per-opening `openingLayout` on an elevation panel, when available).
- The roof cap is copied from the building's own source footprint polygons by default (shape-accurate for any plan, not just rectangles). Set `roof.type` to `"gable"` or `"hip"` in `modeling-rules.json` for a pitched primitive instead.
- A building with no `modeling-rules.json` yet still gets a plain closed shell -- pass its name explicitly (not `all`) to build it before rules exist.
- `scripts/blender/blender-build-building-integrated.py -- <blend> all` only processes buildings that already have a `modeling-rules.json`, so it never flattens the untouched OSM extrusions for buildings nobody has curated yet.

One-of-a-kind architecture that cannot be inferred from data -- Dartmouth Hall's cupola, Baker Library's clock tower -- lives in `scripts/blender/blender_modules/landmark_features_module.py` as small named "feature packs." A building opts in by setting `roof.landmarkFeaturePack` in its own `modeling-rules.json` (e.g. `"dartmouth_hall_cupola"`); everything else about the driver stays identical across buildings. Wall-id naming is the same story: the default is `{side}-{index}` (e.g. `west-03`), and a building can opt into a named-wing strategy (`wallNaming` in `modeling-rules.json`) the way Dartmouth Hall does for its curated wing-level reference data.

`scripts/blender/blender-apply-building-details.py` (recipe-driven boxy massing from `building-detail-recipes.json`) remains the lighter-weight path for ordinary buildings that have not been through elevation-sheet/wall-reference curation yet; the integrated pipeline is for buildings with real per-wall reference data behind them.

## Automated Wall-Opening Extraction

Hand-authoring `windowsAndDoors.wallOpeningPlans` per wall does not scale --
Dartmouth Hall's `modeling-rules.json` alone is over a thousand lines of
transcribed measurements, and manual counts drift into guesswork
(`countMethod: "observed-plus-symmetry-inference"`) on anything but the
clearest photo. `scripts/blender/extract-wall-openings.mjs` automates the
counting/grid step with a vision-capable Claude model:

```sh
npm run model:dartmouth:extract-openings -- --building baker-library --dry-run
npm run model:dartmouth:extract-openings -- --building baker-library
npm run model:dartmouth:extract-openings -- --all --limit 10
```

Requires `ANTHROPIC_API_KEY` in `.env.local`. Always run `--dry-run` first --
it exercises reference-manifest loading, wall correlation, and prompt
construction with zero API calls, and prints exactly which walls would be
written.

How it works:

- A wall's real width is already known from `references-manifest.json`
  (`walls[].lengthMeters`, derived from the OSM footprint), so the model is
  given that as ground truth and only has to judge floors, window grid
  columns/rows, and door position as a 0-1 fraction -- never absolute scale.
  That output shape is the same compact `windowRows`/`windowGridColumns`/
  `doorPositions` grid `reference_module.py`'s `opening_layout_for_plan`
  already expands into full per-opening geometry, and the same shape humans
  already hand-author.
- Walls the model can't confidently read (`quality: "unusable"`, or
  confidence below `--min-confidence`, default 0.55) are **not written** --
  they're listed as `needs-review` instead of silently guessed.
- `references-manifest.json`'s wall ids (`wall-01`..`wall-NN`, assigned by
  the reference-photo generator, numbered once around the whole perimeter)
  are a different id space from the ids the geometry builder assigns at
  build time (`south-04`, `west-01`, via `assign_generic_wall_ids`, numbered
  per cardinal side). The script correlates the two automatically using
  `scripts/blender/blender-list-wall-ids.py` (a read-only helper that
  imports the builder's own wall-id function, so results always match a
  real build) and matches by real wall length within each cardinal side --
  real walls consistently match to within centimeters between the two
  geometry sources. Buildings whose mesh has been re-detailed since its
  reference photos were captured (long facades broken into many small
  notch segments) will have some walls that no longer correlate; those
  surface as `needs-review` rather than a wrong guess.
- Buildings using a custom `wallNaming` strategy (Dartmouth Hall's curated
  wing splits) are skipped -- that curation isn't a good automation target
  and still needs manual authoring.
- After writing a building's walls, the script automatically re-runs
  `generate-reference-elevation-sheets.py` for that building. This matters:
  without a recompiled `orthographic-elevations.json`,
  `blender-build-building-integrated.py` silently falls back to a dumb
  evenly-spaced/fixed-floor-height formula and ignores `windowRows`/
  `doorPositions` entirely, so skipping this step would make the extracted
  data have no effect. Pass `--no-recompile` to skip it.
- Writing is a merge, not a replace: existing keys on a wall's plan (e.g. a
  hand-added `majorWallFeatures` array) are preserved. Walls that already
  have a plan are skipped unless `--force`.

Known pre-existing issue this fixes going forward: Baker Library's current
`modeling-rules.json` has several walls sharing an identical, explicitly
un-verified placeholder count (`"windows": 15, "doors": 1"`, "generic side
rhythm ported from the old per-side hardcoded Baker layout"), and its
`"reference": "wall-02"`-style values are bare ids rather than real paths,
so `reference_module.py` can't actually resolve the image. The extraction
script always writes full, correct `references/walls/wall-XX.jpg` paths.
Existing curated/placeholder data is not rewritten unless re-run with
`--force`.

Not automated yet: roof zones, tower features, and `majorWallFeatures`
(trim, plaques, belt courses) -- still hand-authored. Also not built: a
render-and-compare step that checks the finished building against its
reference photos after the fact.

## Dartmouth Hall Progress

Dartmouth Hall now has:

- Per-wall reference rules and expected opening counts.
- A front roof/gable pediment tied to the west/front and roof references, separate from entry stairs/platforms.
- A taller cupola/tower stack with tiered plinths, lantern openings, posts, rails, cap, spire, and weathervane.
- Satellite-derived roof detail placeholders for dormers/roof boxes and chimneys.
- Updated GLB/FBX exports and render previews in its building folder.

Known limitation: the roof zones are currently manually picked from the satellite reference. The next pass should refine each zone into exact hip/valley plane geometry and separate individual dormer/roof-box instances.

## Main Commands

```sh
npm run model:dartmouth:references -- dartmouth-hall
npm run model:dartmouth:reference-sheets -- dartmouth-hall
npm run model:dartmouth:references:all -- --dry-run --limit 20
npm run model:dartmouth:references:all -- --limit 20
npm run model:dartmouth:build-integrated -- dartmouth-hall
npm run model:dartmouth:audit-laws -- dartmouth-hall --strict
npm run model:dartmouth:export-parts -- --only dartmouth-hall --force-export
npm run model:dartmouth:render-building-preview -- dartmouth-hall
```

The combined Dartmouth Hall pipeline is:

```sh
npm run model:dartmouth:dartmouth-hall:pipeline
```

On this Mac, Blender may need to run outside the sandbox because background startup can crash during Metal GPU detection.

## Campus Reference Batches

Use `model:dartmouth:references:all` to generate exterior reference sets for buildings that do not already have `references/references-manifest.json`.

Each building reference folder should contain:

- `north.jpg`, `east.jpg`, `south.jpg`, and `west.jpg` from Google Street View where available.
- `roof-satellite.jpg` from Google Maps satellite.
- `walls/wall-XX.jpg` for every detected major exterior footprint edge with a matching manifest entry.
- `references-manifest.json` linking each named wall/face to its source image, camera metadata, roof source, and approval status.

Important: batch-generated wall images start as `qualityStatus: "needs-review"`. Do not use a wall for procedural windows, doors, chimneys, tower details, or roof decisions until the specific wall/roof/tower reference is inspected and approved for that building.

Useful batch commands:

```sh
npm run model:dartmouth:references:all -- --dry-run --limit 25
npm run model:dartmouth:references:all -- --limit 25
npm run model:dartmouth:references:all -- --limit 25 --offset 25
npm run model:dartmouth:references:all -- --match "wheelock" --limit 10
npm run model:dartmouth:references:all -- --all
```
