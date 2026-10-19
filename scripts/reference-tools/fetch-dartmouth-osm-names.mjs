import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { getCampusBuildingName } from "./campus-building-names.mjs";

const CAMPUS_BOUNDS = {
  west: -72.2972,
  south: 43.6961,
  east: -72.2785,
  north: 43.7108,
};

const root = process.cwd();
const outDir = path.join(root, "public", "models", "dartmouth-energy-twin", "reports");
const outPath = path.join(outDir, "osm-campus-names.json");

await mkdir(outDir, { recursive: true });

const osm = await fetchOverpass();
const nodes = new Map();
for (const element of osm.elements ?? []) {
  if (element.type === "node") nodes.set(element.id, element);
}

const buildings = [];
const roads = [];
for (const element of osm.elements ?? []) {
  if (element.type !== "way") continue;
  const points = (element.nodes ?? []).map((nodeId) => nodes.get(nodeId)).filter(Boolean);
  if (points.length === 0) continue;

  if (element.tags?.building) {
    const naming = getCampusBuildingName(element.tags, element.id);
    buildings.push({
      osmId: `way/${element.id}`,
      wayId: element.id,
      name: naming.name,
      rawName: naming.rawName,
      hasRealName: naming.hasRealName,
      isAddressOnly: naming.isAddressOnly,
      tags: element.tags,
      centroid: centroid(points),
    });
  } else if (element.tags?.highway) {
    roads.push({
      osmId: `way/${element.id}`,
      wayId: element.id,
      name: element.tags.name ?? roadFallbackName(element.tags, element.id),
      rawName: element.tags.name ?? "",
      hasRealName: Boolean(element.tags.name),
      tags: element.tags,
      centroid: centroid(points),
    });
  }
}

const payload = {
  generatedAt: new Date().toISOString(),
  source: "OpenStreetMap Overpass API",
  bounds: CAMPUS_BOUNDS,
  buildings,
  roads,
};

await writeFile(outPath, JSON.stringify(payload, null, 2));
console.log(`Wrote ${path.relative(root, outPath)}`);
console.log(`Buildings: ${buildings.length}. Roads: ${roads.length}.`);

async function fetchOverpass() {
  const buildings = await fetchQuery(`
    [out:json][timeout:60];
    way["building"](${CAMPUS_BOUNDS.south},${CAMPUS_BOUNDS.west},${CAMPUS_BOUNDS.north},${CAMPUS_BOUNDS.east});
    out body;
    >;
    out skel qt;
  `);
  const roads = await fetchQuery(`
    [out:json][timeout:60];
    way["highway"](${CAMPUS_BOUNDS.south},${CAMPUS_BOUNDS.west},${CAMPUS_BOUNDS.north},${CAMPUS_BOUNDS.east});
    out body;
    >;
    out skel qt;
  `);
  const byKey = new Map();
  for (const element of [...(buildings.elements ?? []), ...(roads.elements ?? [])]) {
    byKey.set(`${element.type}/${element.id}`, element);
  }
  return { elements: [...byKey.values()] };
}

async function fetchQuery(query) {
  const endpoints = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
  ];
  let lastError;
  for (const endpoint of endpoints) {
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: {
          "Accept": "application/json, text/plain, */*",
          "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
          "User-Agent": "DartmouthEnergyTwin/0.1",
        },
        body: new URLSearchParams({ data: query.trim() }),
      });
      if (!response.ok) throw new Error(`${endpoint} returned ${response.status}`);
      return response.json();
    } catch (error) {
      lastError = error;
      console.warn(error.message);
    }
  }
  throw lastError;
}

function centroid(points) {
  const sum = points.reduce(
    (acc, point) => {
      acc.longitude += point.lon;
      acc.latitude += point.lat;
      return acc;
    },
    { longitude: 0, latitude: 0 },
  );
  return {
    longitude: sum.longitude / points.length,
    latitude: sum.latitude / points.length,
  };
}

function roadFallbackName(tags, wayId) {
  const service = tags.service ? ` ${titleCase(tags.service)}` : "";
  return `${titleCase(tags.highway ?? "road")}${service} ${wayId}`;
}

function titleCase(value) {
  return String(value)
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}
