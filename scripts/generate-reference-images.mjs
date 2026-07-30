import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const VIEWS = [
  { id: "front", offset: 0 },
  { id: "left", offset: -90 },
  { id: "right", offset: 90 },
  { id: "back", offset: 180 },
];

const root = process.cwd();
const outputRoot = path.join(root, "public", "reference-atlas", "images");
const manifestPath = path.join(outputRoot, "manifest.json");
await loadLocalEnv();
const key = process.env.GOOGLE_MAPPLATFORM_APIKEY ?? process.env.GOOGLE_MAPS_API_KEY;

if (!key) {
  console.error("Missing GOOGLE_MAPPLATFORM_APIKEY or GOOGLE_MAPS_API_KEY in the environment.");
  process.exit(1);
}

const buildings = JSON.parse(
  await readFile(path.join(root, "scripts", "reference-buildings.json"), "utf8"),
);
const manifest = {
  generatedAt: new Date().toISOString(),
  source: "Google Street View Static API",
  buildings: [],
};

await mkdir(outputRoot, { recursive: true });

for (const building of buildings) {
  const buildingDir = path.join(outputRoot, building.id);
  await mkdir(buildingDir, { recursive: true });
  const { latitude, longitude } = building.entrance;
  const metadata = await getStreetViewMetadata(latitude, longitude);
  const record = {
    id: building.id,
    name: building.name,
    views: {},
  };

  if (!metadata?.pano_id || !metadata.location) {
    console.warn(`No Street View panorama found for ${building.name}`);
    manifest.buildings.push(record);
    continue;
  }

  const distance = distanceInMeters(metadata.location.lat, metadata.location.lng, latitude, longitude);
  if (distance > 120) {
    console.warn(`Skipping ${building.name}; panorama is ${Math.round(distance)}m from entrance.`);
    manifest.buildings.push(record);
    continue;
  }

  const baseHeading = bearingInDegrees(metadata.location.lat, metadata.location.lng, latitude, longitude);

  for (const view of VIEWS) {
    const heading = normalizeHeading(baseHeading + view.offset);
    const fileName = `${view.id}.jpg`;
    const outputPath = path.join(buildingDir, fileName);
    const imageResponse = await fetchStreetViewImage(metadata.pano_id, heading);

    if (!imageResponse.ok || !imageResponse.body) {
      console.warn(`Missing ${view.id} image for ${building.name}: ${imageResponse.status}`);
      continue;
    }

    const bytes = Buffer.from(await imageResponse.arrayBuffer());
    await writeFile(outputPath, bytes);
    record.views[view.id] = {
      path: `/reference-atlas/images/${building.id}/${fileName}`,
      heading: Math.round(heading),
      panoramaDistanceMeters: Math.round(distance),
    };
    console.log(`Saved ${building.name} ${view.id}`);
  }

  manifest.buildings.push(record);
}

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, manifestPath)}`);

async function getStreetViewMetadata(latitude, longitude) {
  const params = new URLSearchParams({
    location: `${latitude},${longitude}`,
    radius: "100",
    source: "outdoor",
    key: key.trim(),
  });
  const response = await fetch(`https://maps.googleapis.com/maps/api/streetview/metadata?${params}`, {
    cache: "no-store",
  });
  if (!response.ok) return null;
  return response.json();
}

function fetchStreetViewImage(pano, heading) {
  const params = new URLSearchParams({
    size: "640x640",
    pano,
    heading: String(Math.round(heading)),
    pitch: "4",
    fov: "82",
    return_error_code: "true",
    key: key.trim(),
  });
  return fetch(`https://maps.googleapis.com/maps/api/streetview?${params}`, {
    cache: "no-store",
  });
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
