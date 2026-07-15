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
