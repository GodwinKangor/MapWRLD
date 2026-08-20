import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const query = process.argv[2] ?? "baker-library";
const wallIds = process.argv.slice(3);
const modelDir = path.join(root, "public", "models", "dartmouth-energy-twin");
const partsManifestPath = path.join(modelDir, "renders", "parts-manifest.json");

await loadLocalEnv();
const key = process.env.GOOGLE_MAPPLATFORM_APIKEY ?? process.env.GOOGLE_MAPS_API_KEY;
if (!key) {
  console.error("Missing GOOGLE_MAPPLATFORM_APIKEY or GOOGLE_MAPS_API_KEY.");
  process.exit(1);
}

const partsManifest = JSON.parse(await readFile(partsManifestPath, "utf8"));
const building = findManifestBuilding(query, partsManifest.buildings);
const referenceDir = path.join(modelDir, "renders", building.folder, "references");
const referenceManifestPath = path.join(referenceDir, "references-manifest.json");
const referenceManifest = JSON.parse(await readFile(referenceManifestPath, "utf8"));
const candidateDir = path.join(referenceDir, "walls", "candidates");
await mkdir(candidateDir, { recursive: true });

const selectedWalls = referenceManifest.walls.filter((wall) => !wallIds.length || wallIds.includes(wall.id));
for (const wall of selectedWalls) {
  for (const [index, candidate] of (wall.candidateCameras ?? []).entries()) {
    const fileName = `${wall.id}-candidate-${String(index + 1).padStart(2, "0")}.jpg`;
    const response = await fetchStreetViewImage(candidate.panoId, candidate.heading, candidate.fov);
    if (!response.ok || !response.body) {
      console.warn(`Failed ${wall.id} candidate ${index + 1}: ${response.status}`);
      continue;
    }
    await writeFile(path.join(candidateDir, fileName), Buffer.from(await response.arrayBuffer()));
    console.log(`Saved ${path.relative(root, path.join(candidateDir, fileName))}`);
  }
}

function findManifestBuilding(value, buildings) {
  const normalized = value.toLowerCase();
  const match = buildings.find((item) => item.name.toLowerCase().includes(normalized) || item.folder.toLowerCase().includes(normalized));
  if (!match) throw new Error(`No exported building matched ${value}`);
  return match;
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
