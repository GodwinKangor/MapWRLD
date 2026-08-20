# Dartmouth Energy Twin Modeling Pipeline

This feature adds a code-driven Blender pipeline for iterating on named campus buildings from references instead of hand-modeling every asset.

## Current Scope

- Work from `public/models/dartmouth-energy-twin/dartmouth-energy-twin.blend`.
- Export individual building parts to GLB/FBX folders under `public/models/dartmouth-energy-twin/renders/buildings`.
- Store named exterior references beside each building under `references/`.
- Enforce modeling rules with `scripts/blender-audit-model-laws.py` before preview/export handoff.

## Rules We Are Enforcing

- Windows and doors must be integrated wall faces with edge loops, not floating panels.
- Window and door counts must match the approved reference plan for each named exterior wall.
- Roof and tower details must use approved roof/tower references.
- Roof/tower/detail objects must be supported; no floating or unsupported overlaps.
- Geometry should avoid loose vertices/edges and n-gons where possible.
- Preview renders must be inspected before a building is considered ready.

## Dartmouth Hall Progress

Dartmouth Hall now has:

- Per-wall reference rules and expected opening counts.
- A front pediment tied to the west/front reference.
- A taller cupola/tower stack with tiered plinths, lantern openings, posts, rails, cap, spire, and weathervane.
- Satellite-derived roof detail placeholders for dormers/roof boxes and chimneys.
- Updated GLB/FBX exports and render previews in its building folder.

Known limitation: the roof is still a simplified hip-roof pass with attached roof details. The next pass should split it into the true smaller hip/valley roof planes visible in the satellite reference.

## Main Commands

```sh
npm run model:dartmouth:references -- dartmouth-hall
npm run model:dartmouth:build-dartmouth-hall-integrated
npm run model:dartmouth:audit-laws -- dartmouth-hall --strict
npm run model:dartmouth:export-parts -- --only dartmouth-hall --force-export
npm run model:dartmouth:render-building-preview -- dartmouth-hall
```

The combined Dartmouth Hall pipeline is:

```sh
npm run model:dartmouth:dartmouth-hall:pipeline
```

On this Mac, Blender may need to run outside the sandbox because background startup can crash during Metal GPU detection.
