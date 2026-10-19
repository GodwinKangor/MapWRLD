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
const shotsPerFace = Number(getArg("--shots-per-face") ?? 1);
const planOnly = process.argv.includes("--plan-only");

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
  const facades = assignModelingViewSlots(pickFacadeEdges(building.coordinates), building.coordinates);
  const record = {
    id: building.id,
    name: building.name,
    osmId: building.osmId,
    rawName: building.rawName,
    category: "OSM building",
    shortCode: makeShortCode(building.name),
    referenceGoal: "Capture each major building face from corner to corner with no trees, vehicles, or foreground obstruction.",
    facePlan: facades.map((facade) => ({
      id: facade.id,
      viewSlot: facade.viewSlot,
      label: facade.label,
      lengthMeters: Math.round(facade.lengthMeters),
      bearing: Math.round(facade.bearing),
      outwardBearing: Math.round(facade.outwardBearing),
      targetHeading: Math.round(facade.outwardBearing),
      midpoint: {
        longitude: Number(facade.midpoint.longitude.toFixed(7)),
        latitude: Number(facade.midpoint.latitude.toFixed(7)),
      },
      endpoints: {
        start: {
          longitude: Number(facade.start.longitude.toFixed(7)),
          latitude: Number(facade.start.latitude.toFixed(7)),
        },
        end: {
          longitude: Number(facade.end.longitude.toFixed(7)),
          latitude: Number(facade.end.latitude.toFixed(7)),
        },
      },
      candidateCameras: [],
    })),
    views: {},
  };

  for (const [index, facade] of facades.entries()) {
    const candidates = await findStreetViewCandidates(facade);
    record.facePlan[index].candidateCameras = candidates.map(serializeCandidate);

    if (!candidates.length) {
      console.warn(`No usable camera candidate for ${building.name} ${facade.id}`);
      continue;
    }

    if (planOnly) {
      console.log(`Planned ${building.name} ${facade.id}: ${candidates.length} camera candidates`);
      continue;
    }

    for (const [shotIndex, candidate] of candidates.slice(0, shotsPerFace || 1).entries()) {
      const viewId = `${facade.viewSlot}${shotsPerFace > 1 ? `-${String(shotIndex + 1).padStart(2, "0")}` : ""}`;
      const fileName = `${viewId}.jpg`;
      const imageResponse = await fetchStreetViewImage(candidate.panoId, candidate.heading, candidate.fov);
      if (!imageResponse.ok || !imageResponse.body) {
        console.warn(`Missing ${building.name} ${viewId}: ${imageResponse.status}`);
        continue;
      }

      const bytes = Buffer.from(await imageResponse.arrayBuffer());
      await writeFile(path.join(buildingDir, fileName), bytes);
      record.views[viewId] = {
        label: `${facade.label}${shotsPerFace > 1 ? ` Shot ${shotIndex + 1}` : ""}`,
        path: `/reference-atlas/images/${building.id}/${fileName}`,
        viewSlot: facade.viewSlot,
        faceId: facade.id,
        heading: Math.round(candidate.heading),
        faceBearing: Math.round(facade.bearing),
        outwardBearing: Math.round(facade.outwardBearing),
        fov: candidate.fov,
        wallLengthMeters: Math.round(facade.lengthMeters),
        panoramaDistanceMeters: Math.round(candidate.distanceToFace),
        qualityStatus: "needs-review",
        qualityScore: candidate.score,
        candidateCamera: serializeCandidate(candidate),
        flags: [
          "Reject if trees are visible",
          "If only a small area is blocked, mark as cleanup-candidate and remove only the obstruction from the original pixels",
          "Do not generate a replacement building face from scratch",
          "Approve only if the full face is visible corner to corner",
        ],
      };
      console.log(`Saved ${building.name} ${viewId}`);
    }
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
      id: `face-${String(index + 1).padStart(2, "0")}`,
      label: `Face ${index + 1}`,
      lengthMeters,
      bearing: bearingInDegrees(start.latitude, start.longitude, end.latitude, end.longitude),
      start,
      end,
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

function assignModelingViewSlots(facades, coordinates) {
  const centroid = footprintCentroid(coordinates);
  const withOutward = facades.map((facade) => ({
    ...facade,
    outwardBearing: bearingInDegrees(
      centroid.latitude,
      centroid.longitude,
      facade.midpoint.latitude,
      facade.midpoint.longitude,
    ),
  }));
  const slots = [
    { id: "front", label: "Front", targetBearing: 180 },
    { id: "right", label: "Right Side", targetBearing: 90 },
    { id: "back", label: "Back", targetBearing: 0 },
    { id: "left", label: "Left Side", targetBearing: 270 },
  ];
  const assigned = [];
  const available = [...withOutward];

  for (const slot of slots) {
    if (!available.length) break;
    available.sort((a, b) => {
      const angleScore = angleDelta(a.outwardBearing, slot.targetBearing) - angleDelta(b.outwardBearing, slot.targetBearing);
      return angleScore || b.lengthMeters - a.lengthMeters;
    });
    const facade = available.shift();
    assigned.push({
      ...facade,
      viewSlot: slot.id,
      label: slot.label,
    });
  }

  return assigned;
}

function footprintCentroid(coordinates) {
  const open = sameCoordinate(coordinates[0], coordinates[coordinates.length - 1])
    ? coordinates.slice(0, -1)
    : coordinates;
  return {
    latitude: open.reduce((sum, coordinate) => sum + coordinate.latitude, 0) / open.length,
    longitude: open.reduce((sum, coordinate) => sum + coordinate.longitude, 0) / open.length,
  };
}

async function findStreetViewCandidates(facade) {
  const lookups = candidateLookupPoints(facade);
  const candidates = [];
  const seen = new Set();

  for (const lookup of lookups) {
    const metadata = await getStreetViewMetadata(lookup.latitude, lookup.longitude);
    if (!metadata?.pano_id || !metadata.location) continue;

    const distanceToFace = distanceInMeters(
      metadata.location.lat,
      metadata.location.lng,
      facade.midpoint.latitude,
      facade.midpoint.longitude,
    );
    if (distanceToFace > 130 || distanceToFace < 8) continue;

    const heading = bearingInDegrees(
      metadata.location.lat,
      metadata.location.lng,
      facade.midpoint.latitude,
      facade.midpoint.longitude,
    );
    const fov = facadeFov(facade.lengthMeters, distanceToFace);
    if (fov > 116) continue;

    const faceNormalDelta = Math.min(
      angleDelta(heading, normalizeHeading(facade.bearing + 90)),
      angleDelta(heading, normalizeHeading(facade.bearing - 90)),
    );
    const key = `${metadata.pano_id}:${Math.round(heading / 5) * 5}`;
    if (seen.has(key)) continue;
    seen.add(key);

    candidates.push({
      panoId: metadata.pano_id,
      lookup,
      camera: {
        latitude: metadata.location.lat,
        longitude: metadata.location.lng,
      },
      heading,
      fov,
      distanceToFace,
      faceNormalDelta,
      score: scoreCandidate({ distanceToFace, faceNormalDelta, fov }),
    });
  }

  return candidates.sort((a, b) => b.score - a.score);
}

function candidateLookupPoints(facade) {
  const points = [];
  const normals = [normalizeHeading(facade.bearing + 90), normalizeHeading(facade.bearing - 90)];
  const fractions = coverageFractionsBfs();
  const offsets = [18, 30, 45, 65];

  for (const fraction of fractions) {
    const alongPoint = interpolateCoordinate(facade.start, facade.end, fraction);
    for (const normal of normals) {
      for (const offsetMeters of offsets) {
        points.push({
          ...offsetCoordinate(alongPoint.latitude, alongPoint.longitude, normal, offsetMeters),
          normal,
          offsetMeters,
          faceFraction: fraction,
        });
      }
    }
  }

  return points;
}

function coverageFractionsBfs() {
  const fractions = [];
  const queue = [[0.05, 0.95]];
  const seen = new Set();

  while (queue.length && fractions.length < 17) {
    const [start, end] = queue.shift();
    const midpoint = Number(((start + end) / 2).toFixed(3));
    const key = midpoint.toFixed(3);
    if (!seen.has(key)) {
      seen.add(key);
      fractions.push(midpoint);
    }

    if (end - start < 0.12) continue;
    queue.push([start, midpoint], [midpoint, end]);
  }

  return fractions;
}

function scoreCandidate({ distanceToFace, faceNormalDelta, fov }) {
  const distanceScore = 100 - Math.min(Math.abs(distanceToFace - 36) * 1.7, 80);
  const angleScore = 100 - Math.min(faceNormalDelta * 2.4, 85);
  const fovScore = 100 - Math.max(fov - 72, 0) * 1.8;
  return Math.round(distanceScore * 0.42 + angleScore * 0.38 + fovScore * 0.2);
}

function serializeCandidate(candidate) {
  return {
    score: candidate.score,
    panoId: candidate.panoId,
    heading: Math.round(candidate.heading),
    fov: candidate.fov,
    distanceToFaceMeters: Math.round(candidate.distanceToFace),
    faceNormalDelta: Math.round(candidate.faceNormalDelta),
    camera: {
      longitude: Number(candidate.camera.longitude.toFixed(7)),
      latitude: Number(candidate.camera.latitude.toFixed(7)),
    },
    lookup: {
      longitude: Number(candidate.lookup.longitude.toFixed(7)),
      latitude: Number(candidate.lookup.latitude.toFixed(7)),
      offsetMeters: candidate.lookup.offsetMeters,
      faceFraction: candidate.lookup.faceFraction,
      normal: Math.round(candidate.lookup.normal),
    },
  };
}

function facadeFov(wallLengthMeters, distanceMeters) {
  if (!distanceMeters) return 55;
  const degrees = 2 * Math.atan((wallLengthMeters / 2) / distanceMeters) * 180 / Math.PI;
  return Math.round(clamp(degrees + 24, 45, 120));
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

function interpolateCoordinate(start, end, fraction) {
  return {
    latitude: start.latitude + (end.latitude - start.latitude) * fraction,
    longitude: start.longitude + (end.longitude - start.longitude) * fraction,
  };
}

function offsetCoordinate(latitude, longitude, heading, distanceMeters) {
  const earthRadius = 6_371_000;
  const angularDistance = distanceMeters / earthRadius;
  const bearing = toRadians(heading);
  const lat1 = toRadians(latitude);
  const lon1 = toRadians(longitude);
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDistance)
    + Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearing),
  );
  const lon2 = lon1 + Math.atan2(
    Math.sin(bearing) * Math.sin(angularDistance) * Math.cos(lat1),
    Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
  );
  return {
    latitude: lat2 * 180 / Math.PI,
    longitude: lon2 * 180 / Math.PI,
  };
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
