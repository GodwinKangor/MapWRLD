// Fetches OSM highway centerlines for the campus rectangle and clips them to it.
// The Blender road objects are edge-only centerlines, which glTF export drops, so
// the map drapes these lines onto the terrain instead of using model geometry.
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const namesPath = path.join(root, "public", "models", "dartmouth-energy-twin", "reports", "osm-campus-names.json");
const outPath = path.join(root, "public", "models", "dartmouth-campus", "campus-roads.json");
const { bounds } = JSON.parse(await readFile(namesPath, "utf8"));

const osm = await fetchQuery(`
  [out:json][timeout:60];
  way["highway"](${bounds.south},${bounds.west},${bounds.north},${bounds.east});
  out body;
  >;
  out skel qt;
`);
const nodes = new Map();
for (const element of osm.elements ?? []) if (element.type === "node") nodes.set(element.id, [element.lon, element.lat]);

const roads = [];
for (const element of osm.elements ?? []) {
  if (element.type !== "way" || !element.tags?.highway) continue;
  const line = (element.nodes ?? []).map((id) => nodes.get(id)).filter(Boolean);
  for (const [index, part] of clipLine(line, bounds).entries()) {
    roads.push({
      osmId: `way/${element.id}`,
      part: index,
      name: element.tags.name ?? "",
      highway: element.tags.highway,
      coordinates: part.map(([lon, lat]) => [round(lon), round(lat)]),
    });
  }
}

await mkdir(path.dirname(outPath), { recursive: true });
await writeFile(outPath, `${JSON.stringify({ generatedAt: new Date().toISOString(), source: "OpenStreetMap Overpass API", bounds, roads })}\n`);
console.log(`Wrote ${roads.length} road segments to ${path.relative(root, outPath)}`);

// Split a polyline into the pieces inside the rectangle (Liang-Barsky per segment).
function clipLine(points, box) {
  const parts = [];
  let current = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const clipped = clipSegment(points[i], points[i + 1], box);
    if (!clipped) { if (current.length > 1) parts.push(current); current = []; continue; }
    const [a, b, exits] = clipped;
    if (!current.length) current.push(a);
    current.push(b);
    if (exits) { parts.push(current); current = []; }
  }
  if (current.length > 1) parts.push(current);
  return parts.filter((part) => part.length > 1);
}

function clipSegment([x0, y0], [x1, y1], box) {
  const dx = x1 - x0;
  const dy = y1 - y0;
  let t0 = 0;
  let t1 = 1;
  for (const [p, q] of [[-dx, x0 - box.west], [dx, box.east - x0], [-dy, y0 - box.south], [dy, box.north - y0]]) {
    if (p === 0) { if (q < 0) return null; continue; }
    const t = q / p;
    if (p < 0) t0 = Math.max(t0, t); else t1 = Math.min(t1, t);
    if (t0 > t1) return null;
  }
  return [[x0 + t0 * dx, y0 + t0 * dy], [x0 + t1 * dx, y0 + t1 * dy], t1 < 1];
}

function round(value) {
  return Math.round(value * 1e7) / 1e7;
}

async function fetchQuery(query) {
  const endpoints = ["https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter"];
  let lastError;
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "MapWRLD campus road fetch" },
        body: new URLSearchParams({ data: query }),
      });
      if (response.ok) return await response.json();
      lastError = new Error(`${endpoint} returned ${response.status}`);
    } catch (error) {
      lastError = error;
    }
  }
  throw lastError;
}
