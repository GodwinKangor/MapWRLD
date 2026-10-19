import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const modelDir = path.join(root, "public", "models", "dartmouth-energy-twin");
const manifestPath = path.join(modelDir, "renders", "parts-manifest.json");
const osmPath = path.join(modelDir, "reports", "osm-campus-names.json");
const buildingGeojsonPath = "/Users/godwinkangor/Downloads/darrtmouth buildings.geojson";

const SIDES = [
  { id: "north", bearing: 0 },
  { id: "east", bearing: 90 },
  { id: "south", bearing: 180 },
  { id: "west", bearing: 270 },
];

await loadLocalEnv();
const key = process.env.GOOGLE_MAPPLATFORM_APIKEY ?? process.env.GOOGLE_MAPS_API_KEY;
if (!key) {
  console.error("Missing GOOGLE_MAPPLATFORM_APIKEY or GOOGLE_MAPS_API_KEY.");
  process.exit(1);
}

const query = process.argv[2] ?? "baker-library";
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const osm = JSON.parse(await readFile(osmPath, "utf8"));
const buildingGeojson = JSON.parse(await readFile(buildingGeojsonPath, "utf8"));
const building = findManifestBuilding(query, manifest.buildings);
const osmId = idFromName(building.name);
const osmRecord = osm.buildings.find((item) => item.osmId === osmId);
const footprint = footprintFor(osmId, buildingGeojson);

if (!osmRecord || !footprint) {
  throw new Error(`Missing OSM record or footprint for ${building.name}`);
}

const referenceDir = path.join(modelDir, "renders", building.folder, "references");
const wallReferenceDir = path.join(referenceDir, "walls");
await mkdir(referenceDir, { recursive: true });
await mkdir(wallReferenceDir, { recursive: true });

const centroid = footprintCentroid(footprint);
const span = footprintSpanMeters(footprint);
const offsetMeters = Math.max(32, Math.min(85, Math.max(span.width, span.height) * 0.72));
const wallPlan = majorExteriorWalls(footprint, centroid);
const references = {
  generatedAt: new Date().toISOString(),
  building: building.name,
  displayName: osmRecord.name,
  osmId,
  output: path.relative(root, referenceDir),
  referencePolicy: [
    "Use Street View/Google photos for windows, doors, facade rhythm, roof edge hints, and tower details.",
    "Use roof satellite/Cesium plan for roof footprint and massing only.",
    "Use named major exterior wall references for procedural facade details.",
    "Do not generate facade details for a wall unless that exact wall has an approved reference.",
  ],
  approvedForModeling: {
    north: false,
    east: false,
    south: false,
    west: false,
    roof: false,
    walls: Object.fromEntries(wallPlan.map((wall) => [wall.id, false])),
  },
  streetView: {},
  walls: [],
  roof: null,
  googlePhotos: [],
  cesiumCameraPlan: cesiumCameraPlan(centroid, span),
};

for (const side of SIDES) {
  const cameraGuess = offsetCoordinate(centroid.latitude, centroid.longitude, side.bearing, offsetMeters);
  const metadata = await getStreetViewMetadata(cameraGuess.latitude, cameraGuess.longitude);
  if (!metadata?.pano_id || !metadata.location) {
    references.streetView[side.id] = { status: "missing", cameraGuess };
    continue;
  }

  const distance = distanceInMeters(metadata.location.lat, metadata.location.lng, centroid.latitude, centroid.longitude);
  if (distance > 150) {
    references.streetView[side.id] = { status: "too-far", distanceMeters: Math.round(distance), cameraGuess };
    continue;
  }

  const heading = bearingInDegrees(metadata.location.lat, metadata.location.lng, centroid.latitude, centroid.longitude);
  const fileName = `${side.id}.jpg`;
  const response = await fetchStreetViewImage(metadata.pano_id, heading, facadeFov(Math.max(span.width, span.height), distance));
  if (!response.ok || !response.body) {
    references.streetView[side.id] = { status: "image-failed", httpStatus: response.status, cameraGuess };
    continue;
  }

  await writeFile(path.join(referenceDir, fileName), Buffer.from(await response.arrayBuffer()));
  references.streetView[side.id] = {
    status: "saved",
    path: `references/${fileName}`,
    source: "Google Street View Static API",
    panoId: metadata.pano_id,
    heading: Math.round(heading),
    fov: facadeFov(Math.max(span.width, span.height), distance),
    distanceMeters: Math.round(distance),
    camera: {
      latitude: Number(metadata.location.lat.toFixed(7)),
      longitude: Number(metadata.location.lng.toFixed(7)),
    },
  };
}

for (const wall of wallPlan) {
  const candidates = await findStreetViewCandidatesForWall(wall);
  const wallRecord = serializeWall(wall, candidates);

  if (!candidates.length) {
    references.walls.push(wallRecord);
    continue;
  }

  const best = candidates[0];
  const fileName = `${wall.id}.jpg`;
  const response = await fetchStreetViewImage(best.panoId, best.heading, best.fov);
  if (!response.ok || !response.body) {
    references.walls.push({
      ...wallRecord,
      reference: { status: "image-failed", httpStatus: response.status },
    });
    continue;
  }

  await writeFile(path.join(wallReferenceDir, fileName), Buffer.from(await response.arrayBuffer()));
  references.walls.push({
    ...wallRecord,
    reference: {
      status: "saved",
      path: `references/walls/${fileName}`,
      source: "Google Street View Static API",
      panoId: best.panoId,
      heading: Math.round(best.heading),
      fov: best.fov,
      distanceMeters: Math.round(best.distanceToWall),
      camera: {
        latitude: Number(best.camera.latitude.toFixed(7)),
        longitude: Number(best.camera.longitude.toFixed(7)),
      },
      qualityStatus: "needs-review",
      flags: [
        "Approve only if this named wall segment is visible enough to model.",
        "Reject or mark partial if trees, neighboring walls, or perspective hide the segment.",
        "Do not use this image to infer a different wall.",
      ],
    },
  });
}

const roofFile = "roof-satellite.jpg";
const roofResponse = await fetchStaticRoofImage(centroid.latitude, centroid.longitude);
if (roofResponse.ok && roofResponse.body) {
  await writeFile(path.join(referenceDir, roofFile), Buffer.from(await roofResponse.arrayBuffer()));
  references.roof = {
    status: "saved",
    path: `references/${roofFile}`,
    source: "Google Maps Static API satellite",
    center: {
      latitude: Number(centroid.latitude.toFixed(7)),
      longitude: Number(centroid.longitude.toFixed(7)),
    },
    note: "Use only for roof footprint, orientation, and block/prism decision unless details are clearly visible.",
  };
} else {
  references.roof = { status: "failed", httpStatus: roofResponse.status };
}

references.googlePhotos = await fetchGooglePlacePhotos(osmRecord.name, centroid, referenceDir);

await writeFile(path.join(referenceDir, "references-manifest.json"), `${JSON.stringify(references, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, path.join(referenceDir, "references-manifest.json"))}`);
for (const side of SIDES) {
  console.log(`${side.id}: ${references.streetView[side.id]?.status}`);
}
console.log(`roof: ${references.roof?.status}`);
console.log(`googlePhotos: ${references.googlePhotos.filter((item) => item.status === "saved").length}`);
console.log(`walls: ${references.walls.filter((item) => item.reference?.status === "saved").length}/${references.walls.length} saved`);

function findManifestBuilding(value, buildings) {
  const normalized = value.toLowerCase();
  const match = buildings.find((item) => item.name.toLowerCase().includes(normalized) || item.folder.toLowerCase().includes(normalized));
  if (!match) throw new Error(`No exported building matched ${value}`);
  return match;
}

function idFromName(name) {
  const match = name.match(/(way|relation|node)_(\d+)/);
  if (!match) return "";
  return `${match[1]}/${match[2]}`;
}

function footprintFor(osmId, geojson) {
  const feature = (geojson.features ?? []).find((item) => item.properties?.["@id"] === osmId);
  const coordinates = feature?.geometry?.coordinates?.[0];
  if (!coordinates) return null;
  return coordinates.map(([longitude, latitude]) => ({ longitude, latitude }));
}

function majorExteriorWalls(coordinates, centroid) {
  const open = sameCoordinate(coordinates[0], coordinates.at(-1)) ? coordinates.slice(0, -1) : coordinates;
  const edges = [];
  let perimeter = 0;
  for (let index = 0; index < open.length; index += 1) {
    const start = open[index];
    const end = open[(index + 1) % open.length];
    const lengthMeters = distanceInMeters(start.latitude, start.longitude, end.latitude, end.longitude);
    perimeter += lengthMeters;
    const bearing = bearingInDegrees(start.latitude, start.longitude, end.latitude, end.longitude);
    const midpoint = {
      latitude: (start.latitude + end.latitude) / 2,
      longitude: (start.longitude + end.longitude) / 2,
    };
    const outwardBearing = bearingInDegrees(centroid.latitude, centroid.longitude, midpoint.latitude, midpoint.longitude);
    const orientation = orientationName(outwardBearing);
    edges.push({
      sourceEdgeIndex: index + 1,
      orientation,
      lengthMeters,
      bearing,
      outwardBearing,
      start,
      end,
      midpoint,
    });
  }
  const minimumMajorLength = Math.max(8, perimeter * 0.032);
  return edges
    .filter((edge) => edge.lengthMeters >= minimumMajorLength)
    .map((edge, index) => ({
      ...edge,
      id: `wall-${String(index + 1).padStart(2, "0")}`,
      name: `${edge.orientation} major exterior wall ${String(index + 1).padStart(2, "0")}`,
    }));
}

function serializeWall(wall, candidates) {
  return {
    id: wall.id,
    name: wall.name,
    sourceEdgeIndex: wall.sourceEdgeIndex,
    orientation: wall.orientation,
    approvedForModeling: false,
    lengthMeters: Number(wall.lengthMeters.toFixed(2)),
    bearing: Math.round(wall.bearing),
    outwardBearing: Math.round(wall.outwardBearing),
    endpoints: {
      start: {
        latitude: Number(wall.start.latitude.toFixed(7)),
        longitude: Number(wall.start.longitude.toFixed(7)),
      },
      end: {
        latitude: Number(wall.end.latitude.toFixed(7)),
        longitude: Number(wall.end.longitude.toFixed(7)),
      },
    },
    midpoint: {
      latitude: Number(wall.midpoint.latitude.toFixed(7)),
      longitude: Number(wall.midpoint.longitude.toFixed(7)),
    },
    reference: candidates.length ? { status: "planned" } : { status: "missing", reason: "No nearby outdoor Street View panorama found for this wall segment." },
    candidateCameras: candidates.slice(0, 4).map(serializeWallCandidate),
  };
}

async function findStreetViewCandidatesForWall(wall) {
  if (wall.lengthMeters < 1.2) return [];
  const candidates = [];
  const seen = new Set();
  const lookups = wallLookupPoints(wall);
  for (const lookup of lookups) {
    const metadata = await getStreetViewMetadata(lookup.latitude, lookup.longitude);
    if (!metadata?.pano_id || !metadata.location) continue;

    const distanceToWall = distanceInMeters(
      metadata.location.lat,
      metadata.location.lng,
      wall.midpoint.latitude,
      wall.midpoint.longitude,
    );
    if (distanceToWall > 145 || distanceToWall < 5) continue;

    const heading = bearingInDegrees(metadata.location.lat, metadata.location.lng, wall.midpoint.latitude, wall.midpoint.longitude);
    const fov = facadeFov(wall.lengthMeters, distanceToWall);
    if (fov > 116) continue;

    const faceNormalDelta = Math.min(
      angleDelta(heading, normalizeHeading(wall.bearing + 90)),
      angleDelta(heading, normalizeHeading(wall.bearing - 90)),
    );
    const key = `${metadata.pano_id}:${Math.round(heading / 4) * 4}`;
    if (seen.has(key)) continue;
    seen.add(key);

    candidates.push({
      panoId: metadata.pano_id,
      camera: {
        latitude: metadata.location.lat,
        longitude: metadata.location.lng,
      },
      lookup,
      heading,
      fov,
      distanceToWall,
      faceNormalDelta,
      score: scoreWallCandidate({ distanceToWall, faceNormalDelta, fov }),
    });
  }
  return candidates.sort((a, b) => b.score - a.score);
}

function wallLookupPoints(wall) {
  const normals = [normalizeHeading(wall.bearing + 90), normalizeHeading(wall.bearing - 90)];
  const fractions = [0.5, 0.25, 0.75, 0.12, 0.88];
  const offsets = [14, 24, 38, 58, 82];
  const points = [];
  for (const fraction of fractions) {
    const along = interpolateCoordinate(wall.start, wall.end, fraction);
    for (const normal of normals) {
      for (const offsetMeters of offsets) {
        points.push({
          ...offsetCoordinate(along.latitude, along.longitude, normal, offsetMeters),
          normal,
          offsetMeters,
          wallFraction: fraction,
        });
      }
    }
  }
  return points;
}

function serializeWallCandidate(candidate) {
  return {
    score: candidate.score,
    panoId: candidate.panoId,
    heading: Math.round(candidate.heading),
    fov: candidate.fov,
    distanceMeters: Math.round(candidate.distanceToWall),
    faceNormalDelta: Math.round(candidate.faceNormalDelta),
    camera: {
      latitude: Number(candidate.camera.latitude.toFixed(7)),
      longitude: Number(candidate.camera.longitude.toFixed(7)),
    },
    lookup: {
      latitude: Number(candidate.lookup.latitude.toFixed(7)),
      longitude: Number(candidate.lookup.longitude.toFixed(7)),
      offsetMeters: candidate.lookup.offsetMeters,
      wallFraction: candidate.lookup.wallFraction,
      normal: Math.round(candidate.lookup.normal),
    },
  };
}

function scoreWallCandidate({ distanceToWall, faceNormalDelta, fov }) {
  const distanceScore = 100 - Math.min(Math.abs(distanceToWall - 32) * 1.6, 82);
  const angleScore = 100 - Math.min(faceNormalDelta * 2.6, 88);
  const fovScore = 100 - Math.max(fov - 68, 0) * 1.7;
  return Math.round(distanceScore * 0.42 + angleScore * 0.4 + fovScore * 0.18);
}

function interpolateCoordinate(start, end, fraction) {
  return {
    latitude: start.latitude + (end.latitude - start.latitude) * fraction,
    longitude: start.longitude + (end.longitude - start.longitude) * fraction,
  };
}

function orientationName(bearing) {
  const directions = [
    ["north", 0],
    ["northeast", 45],
    ["east", 90],
    ["southeast", 135],
    ["south", 180],
    ["southwest", 225],
    ["west", 270],
    ["northwest", 315],
  ];
  directions.sort((a, b) => angleDelta(bearing, a[1]) - angleDelta(bearing, b[1]));
  return directions[0][0];
}

function footprintCentroid(coordinates) {
  const open = sameCoordinate(coordinates[0], coordinates.at(-1)) ? coordinates.slice(0, -1) : coordinates;
  return {
    latitude: open.reduce((sum, coordinate) => sum + coordinate.latitude, 0) / open.length,
    longitude: open.reduce((sum, coordinate) => sum + coordinate.longitude, 0) / open.length,
  };
}

function footprintSpanMeters(coordinates) {
  const latitudes = coordinates.map((coordinate) => coordinate.latitude);
  const longitudes = coordinates.map((coordinate) => coordinate.longitude);
  const south = Math.min(...latitudes);
  const north = Math.max(...latitudes);
  const west = Math.min(...longitudes);
  const east = Math.max(...longitudes);
  const centerLat = (south + north) / 2;
  const centerLng = (west + east) / 2;
  return {
    width: distanceInMeters(centerLat, west, centerLat, east),
    height: distanceInMeters(south, centerLng, north, centerLng),
  };
}

async function getStreetViewMetadata(latitude, longitude) {
  const params = new URLSearchParams({
    location: `${latitude},${longitude}`,
    radius: "85",
    source: "outdoor",
    key: key.trim(),
  });
  const response = await fetch(`https://maps.googleapis.com/maps/api/streetview/metadata?${params}`, { cache: "no-store" });
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
  return fetch(`https://maps.googleapis.com/maps/api/streetview?${params}`, { cache: "no-store" });
}

function fetchStaticRoofImage(latitude, longitude) {
  const params = new URLSearchParams({
    center: `${latitude},${longitude}`,
    zoom: "20",
    size: "640x640",
    maptype: "satellite",
    scale: "2",
    key: key.trim(),
  });
  return fetch(`https://maps.googleapis.com/maps/api/staticmap?${params}`, { cache: "no-store" });
}

async function fetchGooglePlacePhotos(name, centroid, referenceDir) {
  const results = [];
  const findParams = new URLSearchParams({
    query: `${name} Dartmouth College Hanover NH`,
    location: `${centroid.latitude},${centroid.longitude}`,
    radius: "300",
    key: key.trim(),
  });
  const findResponse = await fetch(`https://maps.googleapis.com/maps/api/place/textsearch/json?${findParams}`, { cache: "no-store" });
  if (!findResponse.ok) return [{ status: "place-search-failed", httpStatus: findResponse.status }];
  const findPayload = await findResponse.json();
  const candidate = findPayload.results?.[0];
  if (!candidate?.photos?.length) return [{ status: "no-place-photo", placeStatus: findPayload.status }];

  for (const [index, photo] of candidate.photos.slice(0, 3).entries()) {
    const fileName = `google-photo-${index + 1}.jpg`;
    const photoParams = new URLSearchParams({
      maxwidth: "1200",
      photo_reference: photo.photo_reference,
      key: key.trim(),
    });
    const response = await fetch(`https://maps.googleapis.com/maps/api/place/photo?${photoParams}`, { cache: "no-store", redirect: "follow" });
    if (!response.ok || !response.body) {
      results.push({ status: "photo-failed", httpStatus: response.status });
      continue;
    }
    await writeFile(path.join(referenceDir, fileName), Buffer.from(await response.arrayBuffer()));
    results.push({
      status: "saved",
      path: `references/${fileName}`,
      source: "Google Places Photo API",
      placeName: candidate.name,
      placeId: candidate.place_id,
      width: photo.width,
      height: photo.height,
    });
  }
  return results;
}

function cesiumCameraPlan(centroid, span) {
  const range = Math.max(span.width, span.height, 60);
  return {
    note: "Use in CesiumJS for massing/roof inspection, not exact facade detail extraction.",
    roof: {
      destination: { longitude: centroid.longitude, latitude: centroid.latitude, heightMeters: Math.max(180, range * 3.2) },
      headingDegrees: 0,
      pitchDegrees: -86,
    },
    oblique: SIDES.map((side) => ({
      side: side.id,
      camera: offsetCoordinate(centroid.latitude, centroid.longitude, side.bearing, range * 1.6),
      target: centroid,
      headingDegrees: normalizeHeading(side.bearing + 180),
      pitchDegrees: -28,
    })),
  };
}

function offsetCoordinate(latitude, longitude, bearing, meters) {
  const earthRadius = 6_371_000;
  const angularDistance = meters / earthRadius;
  const bearingRadians = toRadians(bearing);
  const lat1 = toRadians(latitude);
  const lon1 = toRadians(longitude);
  const lat2 = Math.asin(
    Math.sin(lat1) * Math.cos(angularDistance) +
    Math.cos(lat1) * Math.sin(angularDistance) * Math.cos(bearingRadians),
  );
  const lon2 = lon1 + Math.atan2(
    Math.sin(bearingRadians) * Math.sin(angularDistance) * Math.cos(lat1),
    Math.cos(angularDistance) - Math.sin(lat1) * Math.sin(lat2),
  );
  return { latitude: toDegrees(lat2), longitude: toDegrees(lon2) };
}

function facadeFov(wallLengthMeters, distanceMeters) {
  if (!distanceMeters) return 70;
  const degrees = 2 * Math.atan((wallLengthMeters / 2) / distanceMeters) * 180 / Math.PI;
  return Math.round(clamp(degrees + 24, 45, 110));
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

function sameCoordinate(a, b) {
  return a?.latitude === b?.latitude && a?.longitude === b?.longitude;
}

function angleDelta(a, b) {
  const delta = Math.abs(normalizeHeading(a) - normalizeHeading(b));
  return Math.min(delta, 360 - delta);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function normalizeHeading(value) {
  return (value % 360 + 360) % 360;
}

function toRadians(value) {
  return value * Math.PI / 180;
}

function toDegrees(value) {
  return value * 180 / Math.PI;
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
    // Environment file is optional when variables are already exported.
  }
}
