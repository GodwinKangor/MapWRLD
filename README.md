# Dartmouth Energy Twin

> Visualizing the invisible infrastructure powering Dartmouth College.

Dartmouth Energy Twin is an interactive 3D digital twin for exploring Dartmouth College's campus, buildings, and future energy systems. The project is evolving from a place-discovery map into a campus infrastructure visualization tool focused on sustainability, building intelligence, and immersive spatial context.

## Vision

Most campus maps show where buildings are. Dartmouth Energy Twin aims to show how the campus works.

The long-term product will combine a realistic 3D campus, clickable smart buildings, underground energy infrastructure, animated energy flows, and dashboards that explain how Dartmouth's built environment uses and transforms energy.

## Current MVP

The current app establishes the interactive 3D campus foundation:

- CesiumJS-powered 3D map centered on Dartmouth College
- Clickable building and entrance markers
- Smooth camera fly-to animation
- Building profile side panel
- Street View entrance preview when a Google Maps key is configured
- Bundled Dartmouth building data with Supabase fallback support
- Search and category filtering
- Time-of-day and seasonal atmosphere controls
- Responsive interface

## Product Direction

The project is moving toward an energy-focused digital twin with these major layers:

- Smart building metadata
- Underground district energy network visualization
- Animated heating and energy flow paths
- Renewable energy and carbon metrics
- Building-level energy profiles
- Campus analytics dashboard
- Time, weather, and seasonal simulation
- AI assistant for campus energy questions

## Technology Stack

### Frontend
- Next.js
- React
- TypeScript
- Tailwind-compatible CSS structure

### 3D & GIS
- CesiumJS
- Cesium World Terrain
- Cesium Ion imagery
- OpenStreetMap fallback imagery

### Data & Backend
- Supabase
- PostgreSQL
- Supabase Storage
- Next.js API routes

### External Imagery
- Google Street View Static API

### Deployment
- Vercel

## Environment Variables

Create `.env.local` with the values needed for the features you want to run:

```env
NEXT_PUBLIC_CESIUM_ION_TOKEN=
NEXT_PUBLIC_SUPABASE_URL=
NEXT_PUBLIC_SUPABASE_ANON_KEY=
GOOGLE_MAPPLATFORM_APIKEY=
```

`NEXT_PUBLIC_CESIUM_ION_TOKEN` is required for the 3D map. Supabase variables are optional during local development because the app falls back to bundled building data. The Google Maps key is optional and only powers Street View entrance previews.

## Local Development

```bash
npm install
npm run dev
```

Open http://localhost:3000.

The modeling reference atlas is available at:

```text
http://localhost:3000/reference-atlas
```

It gives modelers front, side, and back Street View reference slots for each tracked campus building.

To generate local orientation images for every tracked building, run:

```bash
npm run reference:images
```

The images are written to `public/reference-atlas/images/` and are ignored by Git so the repository does not balloon. The atlas uses these local images first, then falls back to live Street View when a local image is missing.

For actual modeling references across every OSM building inside the Dartmouth rectangle, generate facade candidates instead:

```bash
npm run reference:open:dartmouth-hall
npm run reference:open:test
npm run reference:open
npm run reference:wikimedia:dartmouth-hall
npm run reference:wikimedia:test
npm run reference:wikimedia
npm run reference:facades:test
npm run reference:facades
```

Use the open-source generator first. It searches named OSM buildings against free/open image providers such as Wikimedia Commons, Openverse-indexed media, and the Library of Congress, then rejects obvious non-modeling images such as maps, aerials, interiors, logos, low-resolution files, narrow crops, construction scenes, and metadata-obstructed photos. Saved candidates include provider, source link, license metadata, checker notes, and manual-review flags.

The Wikimedia-only generator is still available when you want a narrower source pass. It is useful for quick debugging because the results are usually easy to inspect and attribute.

The Street View facade generator is a fallback. It pulls building footprints from OpenStreetMap, selects the major walls, then saves tighter wall-facing candidates like `facade-01.jpg`, `facade-02.jpg`, etc. Use the test commands first because Street View can make many paid API requests.

The checker is intentionally conservative: it discards photos whose metadata suggests blocked walls, trees, vehicles, crowds, scaffolding, snow, night/low-light views, partial crops, or close-up details. Final approval still requires a human or a vision API to confirm that the actual pixels show the wall end-to-end without foreground obstruction.

If an OSM building name is wrong or incomplete, add the correction in:

```text
scripts/campus-building-names.mjs
```

The open-source, Wikimedia, and Street View facade generators all use this shared naming helper before writing atlas manifests.

When the free images are useful but each one has small blocked areas, open:

```text
http://localhost:3000/reference-compositor
```

The compositor reads the same generated manifest, stacks multiple candidate images for a building, and lets a modeler adjust visibility, opacity, scale, rotation, position, and blend mode. Export the result as a PNG reference sheet after aligning the clearest visible wall parts. This is a free/manual path for combining partial references before spending money on vision review or new image capture.

## Supabase Setup

Run this migration in the Supabase SQL editor:

```text
supabase/migrations/202607010001_mapwrld_core.sql
```

Then add the Supabase project URL and anon key to `.env.local`. The app reads building data through `/api/buildings`, caches responses for five minutes, and automatically falls back to bundled data if Supabase is unavailable.

## Model Import Workflow

The app is prepared for a future custom Dartmouth campus model at:

```text
public/models/dartmouth-campus/dartmouth-campus.glb
```

Use this workflow when exporting from Maya:

- Model and export in meters.
- Keep the campus centered around the manifest origin in `public/models/dartmouth-campus/model-manifest.json`.
- Export as binary glTF (`.glb`) for web delivery.
- Keep geometry modular enough to optimize or replace buildings later.
- Reduce unnecessary bevels, hidden faces, duplicate objects, and high-density trees before export.
- Use baked/simple materials first; add detailed materials only after performance is acceptable.
- Place the exported file at `public/models/dartmouth-campus/dartmouth-campus.glb`.
- Change `status` in `model-manifest.json` from `pending` to `ready` after the file is in place.

Until the GLB is ready, the app keeps using Cesium terrain, imagery, OSM buildings, and the energy overlays as the working fallback scene.

For the full GeoJSON -> Blender -> Maya -> GLB pipeline, use:

```text
public/models/dartmouth-campus/README.md
```

## Roadmap

### Phase 1: Campus Foundation
- Establish the 3D Dartmouth scene
- Add terrain, buildings, entrances, and navigation
- Support building search and profile panels

### Phase 2: Smart Campus
- Expand building metadata
- Add accessibility, hours, photos, and categorized building information
- Move content fully into Supabase

### Phase 3: Energy Network
- Add underground mode
- Model district heating and utility paths
- Animate energy flow through campus infrastructure
- Add layer controls for energy systems

### Phase 4: Analytics Dashboard
- Show building-level energy profiles
- Add campus-wide carbon and demand metrics
- Introduce mock datasets before real integrations

### Phase 5: Simulation Engine
- Add day/night, seasonal, and weather scenarios
- Visualize demand changes over time
- Show renewable energy and decarbonization scenarios

### Phase 6: Intelligent Digital Twin
- Add an AI campus energy assistant
- Support natural-language energy and building queries
- Explore real-time data integrations
- Expand into planning, education, and operations use cases

## Portfolio Value

This project demonstrates:

- Digital twin product design
- GIS and 3D web visualization
- CesiumJS integration
- React and Next.js application architecture
- Supabase-backed content workflows
- Sustainability and infrastructure storytelling
- Interactive UI design for spatial data

## Mission

Making Dartmouth's invisible infrastructure visible through immersive digital experiences.
