# Cesium view vs standalone campus scene

Measured 2026-10-19 with `scripts/perf/compare-renderers.mjs` against a local production build
(`next build && next start`). Raw numbers: `renderer-comparison-2026-10-19.json`.

## Conditions

- Apple M2, macOS 26.2, headless Chromium (Chrome for Testing build 1248) using the Metal ANGLE backend, 1500×950 viewport.
- 3 runs per renderer, each in a fresh browser context (empty HTTP cache). Medians below.
- Same app shell and the same default layers in both: boundary, energy network (heat + electric),
  accessibility, fields, roads, trees, public records, all 719 building markers.
- Same views: the home overview, then each renderer's "Ground campus view" button.
- Draw calls and triangles are counted by wrapping the WebGL draw functions, so both renderers are
  measured the same way; frames with no draws (idle, on-demand rendering) are excluded.
- Frame intervals are measured with a separate `requestAnimationFrame` loop during the same scripted
  90-step pan drag; values above 33 ms mean the main thread missed at least one 60 Hz frame.

## Results

| Metric | Cesium (`/`) | Standalone (`/preview`) |
|---|---|---|
| Load to ready | 8,051 ms (runs: 8,051 / 21,117 / 5,084) | 1,006 ms (982 / 1,031 / 1,006) |
| Network requests until ready + 4 s | 1,728 | 32 |
| Transferred (bodies + headers) | 11.9 MB | 5.3 MB |
| Draw calls per frame, overview | 1,155 | 7 |
| Draw calls per frame, ground view | 403 | 7 |
| Triangles per frame, overview | 1.39 M | 0.56 M |
| Triangles per frame, ground view | 1.42 M | 0.56 M |
| Frame interval during drag, p50 / p95 | 16.7 / 50.0 ms | 16.7 / 16.7 ms |
| Drag frames over 33 ms | 70 | 0 |
| JS heap after the views | 172 MB | 42 MB |

## Caveats

- "Ready" is not the same event: Cesium is ready when its campus model is grounded (roads, trees
  and imagery refinement may still be streaming); the standalone scene is ready only after every
  layer has loaded. This favors Cesium.
- Cesium's requests go to Cesium ion over the internet (terrain, imagery tiles, workers); the
  standalone scene's assets came from localhost here. On Vercel they come from the CDN.
- One machine and a headless browser; absolute numbers will differ on other hardware, but the
  draw-call, request and triangle counts are deterministic.
- Memory is the JS heap only (`performance.memory`); GPU memory is not exposed to the page. The
  standalone scene reports its GPU resources in `window.__campusScene.metrics` (7 geometries,
  3 textures at medium quality).

## Deployed (Vercel CDN)

Standalone scene at https://dartmouth-energy-twin.vercel.app, same harness and machine, 3 cold runs
(`--targets three --three-path /`; raw: `standalone-vercel-2026-10-19.json`):

| Metric | Value |
|---|---|
| Load to ready | 1,615 ms |
| Requests / transferred | 31 / 4.1 MB (CDN compression) |
| Draw calls, triangles per frame | 7, 0.56 M (overview and ground) |
| Drag frame interval p50 / p95, frames over 33 ms | 16.7 / 16.8 ms, 0 |
| JS heap | 44 MB |
