import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const sourceManifestPath = path.join(root, "public", "reference-atlas", "images", "manifest.json");
const outputRoot = path.join(root, "public", "reference-atlas", "guides");
const guideManifestPath = path.join(outputRoot, "guide-manifest.json");
const defaultHeightMeters = Number(getArg("--height") ?? 18);

await mkdir(outputRoot, { recursive: true });

const manifest = JSON.parse(await readFile(sourceManifestPath, "utf8"));
const guideManifest = {
  generatedAt: new Date().toISOString(),
  source: "OpenStreetMap footprint face plans",
  note: "Tree-free geometry guides only. These are not photo-accurate facade references and must not be used to invent windows, doors, materials, or trim.",
  buildings: [],
};

for (const building of manifest.buildings ?? []) {
  if (!Array.isArray(building.facePlan) || !building.facePlan.length) continue;
  const buildingDir = path.join(outputRoot, building.id);
  await mkdir(buildingDir, { recursive: true });

  const record = {
    id: building.id,
    name: building.name,
    guides: {},
  };

  for (const face of building.facePlan) {
    const fileName = `${face.id}.svg`;
    const guide = buildGuideSvg(building, face);
    await writeFile(path.join(buildingDir, fileName), guide);
    record.guides[face.id] = {
      label: face.label,
      path: `/reference-atlas/guides/${building.id}/${fileName}`,
      wallLengthMeters: face.lengthMeters,
      assumedHeightMeters: defaultHeightMeters,
      bearing: face.bearing,
      targetHeading: face.targetHeading,
      candidateCameras: face.candidateCameras ?? [],
      status: "geometry-guide-only",
      warnings: [
        "No trees by construction",
        "Footprint gives wall length and bearing only",
        "Do not invent facade details from this guide",
      ],
    };
  }

  guideManifest.buildings.push(record);
}

await writeFile(guideManifestPath, `${JSON.stringify(guideManifest, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, guideManifestPath)} with ${guideManifest.buildings.length} buildings.`);

function buildGuideSvg(building, face) {
  const width = 1800;
  const height = 1100;
  const margin = 140;
  const wallWidth = width - margin * 2;
  const wallHeight = Math.max(240, Math.min(520, wallWidth * (defaultHeightMeters / Math.max(face.lengthMeters, 1))));
  const wallX = margin;
  const wallY = 315;
  const tickCount = Math.max(2, Math.ceil(face.lengthMeters / 10));
  const scale = wallWidth / face.lengthMeters;
  const ticks = Array.from({ length: tickCount + 1 }, (_, index) => {
    const meters = Math.min(index * 10, face.lengthMeters);
    const x = wallX + meters * scale;
    return `
      <line x1="${x.toFixed(1)}" y1="${wallY + wallHeight}" x2="${x.toFixed(1)}" y2="${wallY + wallHeight + 24}" stroke="#16231c" stroke-width="2"/>
      <text x="${x.toFixed(1)}" y="${wallY + wallHeight + 52}" text-anchor="middle" class="tick">${Math.round(meters)}m</text>
    `;
  }).join("");
  const cameras = (face.candidateCameras ?? []).slice(0, 5).map((camera, index) => {
    const x = wallX + wallWidth * (camera.lookup?.faceFraction ?? 0.5);
    const y = wallY - 68 - index * 34;
    return `
      <circle cx="${x.toFixed(1)}" cy="${y}" r="10" fill="#286348"/>
      <text x="${x + 18}" y="${y + 5}" class="small">camera ${index + 1}: score ${camera.score}, ${camera.distanceToFaceMeters}m, heading ${camera.heading} deg</text>
    `;
  }).join("");

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}" xmlns="http://www.w3.org/2000/svg">
  <style>
    .title { font: 700 44px Arial, sans-serif; fill: #16231c; }
    .meta { font: 400 24px Arial, sans-serif; fill: #4f5f55; }
    .label { font: 700 22px Arial, sans-serif; fill: #16231c; }
    .small { font: 400 18px Arial, sans-serif; fill: #4f5f55; }
    .tick { font: 400 16px Arial, sans-serif; fill: #4f5f55; }
  </style>
  <rect width="100%" height="100%" fill="#f4f1e8"/>
  <text x="80" y="80" class="title">${escapeXml(building.name)} / ${escapeXml(face.label)}</text>
  <text x="80" y="122" class="meta">Tree-free footprint guide. Use for dimensions and camera planning only.</text>
  <text x="80" y="164" class="meta">Wall length ${Math.round(face.lengthMeters)}m · bearing ${Math.round(face.bearing)} deg · target heading ${Math.round(face.targetHeading)} deg · assumed height ${defaultHeightMeters}m</text>
  <rect x="${wallX}" y="${wallY}" width="${wallWidth}" height="${wallHeight}" fill="#ffffff" stroke="#16231c" stroke-width="5"/>
  <line x1="${wallX}" y1="${wallY + wallHeight}" x2="${wallX + wallWidth}" y2="${wallY + wallHeight}" stroke="#16231c" stroke-width="7"/>
  ${ticks}
  <text x="${wallX}" y="${wallY - 34}" class="label">Left end</text>
  <text x="${wallX + wallWidth}" y="${wallY - 34}" text-anchor="end" class="label">Right end</text>
  ${cameras}
  <rect x="80" y="${height - 210}" width="${width - 160}" height="118" fill="#fff8db" stroke="#d6b85d" stroke-width="2"/>
  <text x="112" y="${height - 164}" class="label">Accuracy rule</text>
  <text x="112" y="${height - 126}" class="small">This guide can replace tree-obscured photos only for footprint dimensions, wall length, and camera setup.</text>
  <text x="112" y="${height - 92}" class="small">Exact windows, doors, materials, trim, and roof details must come from approved no-tree photos or field capture.</text>
</svg>
`;
}

function getArg(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return null;
  return process.argv[index + 1] ?? null;
}

function escapeXml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
