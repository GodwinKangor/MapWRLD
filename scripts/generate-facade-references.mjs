import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { getCampusBuildingName } from "./campus-building-names.mjs";

const CAMPUS_BOUNDS = {
  west: -72.2972,
  south: 43.6961,
  east: -72.2785,
  north: 43.7108,
};
const root = process.cwd();
const outputRoot = path.join(root, "public", "reference-atlas", "images");
const manifestPath = path.join(outputRoot, "manifest.json");
const requestLimit = Number(getArg("--limit") ?? 0);

await loadLocalEnv();
const key = process.env.GOOGLE_MAPPLATFORM_APIKEY ?? process.env.GOOGLE_MAPS_API_KEY;

if (!key) {
  console.error("Missing GOOGLE_MAPPLATFORM_APIKEY or GOOGLE_MAPS_API_KEY in the environment.");
  process.exit(1);
}

await mkdir(outputRoot, { recursive: true });

const osm = await fetchCampusBuildings();
const buildings = extractBuildingFootprints(osm)
  .sort((a, b) => a.name.localeCompare(b.name))
  .slice(0, requestLimit || undefined);

const manifest = {
  generatedAt: new Date().toISOString(),
  source: "OpenStreetMap footprints + Google Street View Static API",
  mode: "facade",
  bounds: CAMPUS_BOUNDS,
  buildings: [],
};

console.log(`Preparing facade references for ${buildings.length} buildings.`);

for (const building of buildings) {
  const buildingDir = path.join(outputRoot, building.id);
  await mkdir(buildingDir, { recursive: true });
  const facades = pickFacadeEdges(building.coordinates);
  const record = {
    id: building.id,
    name: building.name,
    osmId: building.osmId,
    category: "OSM building",
    shortCode: makeShortCode(building.name),
    views: {},
  };

  for (const [index, facade] of facades.entries()) {
    const metadata = await getStreetViewMetadata(facade.midpoint.latitude, facade.midpoint.longitude);
    const viewId = `facade-${String(index + 1).padStart(2, "0")}`;
    if (!metadata?.pano_id || !metadata.location) {
      console.warn(`No panorama for ${building.name} ${viewId}`);
      continue;
    }

    const distance = distanceInMeters(
      metadata.location.lat,
      metadata.location.lng,
      facade.midpoint.latitude,
      facade.midpoint.longitude,
    );
    if (distance > 95) {
      console.warn(`Skipping ${building.name} ${viewId}; panorama is ${Math.round(distance)}m from wall.`);
      continue;
    }

    const heading = bearingInDegrees(
      metadata.location.lat,
      metadata.location.lng,
      facade.midpoint.latitude,
      facade.midpoint.longitude,
    );
    const fov = facadeFov(facade.lengthMeters, distance);
    const fileName = `${viewId}.jpg`;
    const imageResponse = await fetchStreetViewImage(metadata.pano_id, heading, fov);
    if (!imageResponse.ok || !imageResponse.body) {
      console.warn(`Missing ${building.name} ${viewId}: ${imageResponse.status}`);
      continue;
    }

    const bytes = Buffer.from(await imageResponse.arrayBuffer());
    await writeFile(path.join(buildingDir, fileName), bytes);
    record.views[viewId] = {
      label: `Facade ${index + 1}`,
      path: `/reference-atlas/images/${building.id}/${fileName}`,
      heading: Math.round(heading),
      fov,
      wallLengthMeters: Math.round(facade.lengthMeters),
      panoramaDistanceMeters: Math.round(distance),
    };
    console.log(`Saved ${building.name} ${viewId}`);
  }

  manifest.buildings.push(record);
}

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, manifestPath)}`);

async function fetchCampusBuildings() {
  const query = `
    [out:json][timeout:60];
    (
      way["building"](${CAMPUS_BOUNDS.south},${CAMPUS_BOUNDS.west},${CAMPUS_BOUNDS.north},${CAMPUS_BOUNDS.east});
    );
    out body;
    >;
    out skel qt;
  `;
  const endpoints = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
  ];

  for (const endpoint of endpoints) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "User-Agent": "DartmouthEnergyTwin/0.1",
      },
      body: new URLSearchParams({ data: query.trim() }),
    });
    if (response.ok) return response.json();
    console.warn(`${endpoint} returned ${response.status}`);
  }

  throw new Error("All Overpass endpoints rejected the campus building query.");
}

function extractBuildingFootprints(osm) {
  const nodes = new Map();
  const ways = [];
  for (const element of osm.elements ?? []) {
    if (element.type === "node") nodes.set(element.id, { latitude: element.lat, longitude: element.lon });
    if (element.type === "way" && element.tags?.building) ways.push(element);
  }

  return ways.flatMap((way) => {
    const coordinates = (way.nodes ?? []).map((id) => nodes.get(id)).filter(Boolean);
    if (coordinates.length < 4) return [];
    const closed = sameCoordinate(coordinates[0], coordinates[coordinates.length - 1])
      ? coordinates
      : [...coordinates, coordinates[0]];
    const naming = getCampusBuildingName(way.tags, way.id);
    return [{
      id: slugify(`${naming.name}-${way.id}`),
      osmId: `way/${way.id}`,
      name: naming.name,
      rawName: naming.rawName,
      nameSource: naming.hasRealName ? "osm-name" : naming.isAddressOnly ? "address" : "generated",
      coordinates: closed,
    }];
  });
}

function pickFacadeEdges(coordinates) {
  const edges = [];
  for (let index = 0; index < coordinates.length - 1; index += 1) {
    const start = coordinates[index];
    const end = coordinates[index + 1];
    const lengthMeters = distanceInMeters(start.latitude, start.longitude, end.latitude, end.longitude);
    if (lengthMeters < 4) continue;
    edges.push({
      lengthMeters,
      bearing: bearingInDegrees(start.latitude, start.longitude, end.latitude, end.longitude),
      midpoint: {
        latitude: (start.latitude + end.latitude) / 2,
        longitude: (start.longitude + end.longitude) / 2,
      },
    });
  }

  const picked = [];
  for (const edge of edges.sort((a, b) => b.lengthMeters - a.lengthMeters)) {
    if (picked.length >= 4) break;
    const tooSimilar = picked.some((item) => angleDelta(item.bearing, edge.bearing) < 22);
    if (!tooSimilar) picked.push(edge);
  }
  return picked.length ? picked : edges.slice(0, 4);
}

function facadeFov(wallLengthMeters, distanceMeters) {
  if (!distanceMeters) return 55;
  const degrees = 2 * Math.atan((wallLengthMeters / 2) / distanceMeters) * 180 / Math.PI;
  return Math.round(clamp(degrees + 18, 38, 100));
}

async function getStreetViewMetadata(latitude, longitude) {
  const params = new URLSearchParams({
    location: `${latitude},${longitude}`,
    radius: "80",
    source: "outdoor",
    key: key.trim(),
  });
  const response = await fetch(`https://maps.googleapis.com/maps/api/streetview/metadata?${params}`, {
    cache: "no-store",
  });
  if (!response.ok) return null;
  return response.json();
}

function fetchStreetViewImage(pano, heading, fov) {
  const params = new URLSearchParams({
    size: "640x640",
    pano,
    heading: String(Math.round(heading)),
    pitch: "3",
    fov: String(fov),
    return_error_code: "true",
    key: key.trim(),
  });
  return fetch(`https://maps.googleapis.com/maps/api/streetview?${params}`, {
    cache: "no-store",
  });
}

function getArg(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return null;
  return process.argv[index + 1] ?? null;
}

function makeShortCode(name) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("") || "OSM";
}

function slugify(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

function sameCoordinate(a, b) {
  return a?.latitude === b?.latitude && a?.longitude === b?.longitude;
}

function bearingInDegrees(fromLat, fromLng, toLat, toLng) {
  const phi1 = toRadians(fromLat);
  const phi2 = toRadians(toLat);
  const lambda = toRadians(toLng - fromLng);
  const y = Math.sin(lambda) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(lambda);
  return normalizeHeading(Math.atan2(y, x) * 180 / Math.PI);
}

function distanceInMeters(fromLat, fromLng, toLat, toLng) {
  const earthRadius = 6_371_000;
  const deltaPhi = toRadians(toLat - fromLat);
  const deltaLambda = toRadians(toLng - fromLng);
  const phi1 = toRadians(fromLat);
  const phi2 = toRadians(toLat);
  const a = Math.sin(deltaPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(deltaLambda / 2) ** 2;
  return earthRadius * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function angleDelta(a, b) {
  const delta = Math.abs(normalizeHeading(a) - normalizeHeading(b));
  return Math.min(delta, 360 - delta);
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function toRadians(value) {
  return value * Math.PI / 180;
}

function normalizeHeading(value) {
  return (value % 360 + 360) % 360;
}

async function loadLocalEnv() {
  const envPath = path.join(root, ".env.local");
  try {
    const contents = await readFile(envPath, "utf8");
    for (const line of contents.split(/\r?\n/)) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const equals = trimmed.indexOf("=");
      if (equals === -1) continue;
      const name = trimmed.slice(0, equals).trim();
      const value = trimmed.slice(equals + 1).trim().replace(/^['"]|['"]$/g, "");
      if (name && process.env[name] === undefined) process.env[name] = value;
    }
  } catch {
    // .env.local is optional; the script also accepts exported shell variables.
  }
}
