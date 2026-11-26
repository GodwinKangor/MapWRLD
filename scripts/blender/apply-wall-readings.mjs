// Apply hand-read (or reviewed) wall-photo readings to a building's modeling-rules.json.
//
// The readings use the reference photo ids (wall-01, wall-02 ... from references-manifest.json)
// and the same compact grid shape extract-wall-openings.mjs writes: floors, windowGridColumns,
// windowRows (bottom-to-top lists of 1-indexed column slots), doorPositions (0 = left edge of the
// photo facing the wall, 1 = right edge). Photo ids are matched to the builder's wall ids
// (south-03, west-01 ...) with extract-wall-openings.mjs --dry-run, which makes no API calls.
//
//   node scripts/blender/apply-wall-readings.mjs --building rollins-chapel --readings readings.json
//
// readings.json:
//   { "reader": "...", "walls": { "wall-01": { quality, confidence, floors, windowGridColumns,
//     windowRows, doorPositions, notes }, ... }, "roof": { type, riseMeters, ... } }
// Walls with quality "unusable" are skipped. Existing hand-authored keys on a wall plan are kept.

import { execFileSync } from "node:child_process";
import { readFile, readdir, writeFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => (value.startsWith("--") ? [...pairs, [value.slice(2), all[index + 1]]] : pairs), []));
if (!args.building || !args.readings) throw new Error("Usage: --building <slug> --readings <file.json>");

const buildingsDir = path.join(root, "public/models/dartmouth-energy-twin/renders/buildings");
const folder = (await readdir(buildingsDir)).find((name) => name.startsWith(`building__${args.building}__`));
if (!folder) throw new Error(`No building folder for ${args.building}`);
const referencesDir = path.join(buildingsDir, folder, "references");
const readings = JSON.parse(await readFile(args.readings, "utf8"));
const manifest = JSON.parse(await readFile(path.join(referencesDir, "references-manifest.json"), "utf8"));

// photo wall id -> builder wall id, from the existing correlation (no API calls)
const dryRun = execFileSync("node", ["scripts/blender/extract-wall-openings.mjs", "--building", args.building, "--dry-run", "--force"], { cwd: root, encoding: "utf8" });
const meshIdFor = {};
for (const match of dryRun.matchAll(/\[plan\] (\S+) <- (wall-\d+)/g)) meshIdFor[match[2]] = match[1];

const rulesPath = path.join(referencesDir, "modeling-rules.json");
let rules;
try { rules = JSON.parse(await readFile(rulesPath, "utf8")); }
catch { rules = { building: folder, displayName: manifest.displayName, rulesVersion: 1, scope: "exterior-only" }; }
rules.windowsAndDoors ??= {};
rules.windowsAndDoors.wallOpeningPlans ??= {};
const plans = rules.windowsAndDoors.wallOpeningPlans;
// Once a building has been built its walls are split into opening segments and no longer match
// by length; fall back to the photo -> wall mapping recorded by an earlier apply.
for (const [meshId, plan] of Object.entries(plans)) {
  const photo = /walls\/(wall-\d+)\.jpg$/.exec(plan.reference ?? "")?.[1];
  if (photo && !meshIdFor[photo]) meshIdFor[photo] = meshId;
}
const readAt = new Date().toISOString();
const report = { written: [], skipped: [] };

for (const [photoId, reading] of Object.entries(readings.walls ?? {})) {
  const meshId = meshIdFor[photoId];
  if (!meshId) { report.skipped.push(`${photoId}: no matching model wall`); continue; }
  if (reading.quality === "unusable") { report.skipped.push(`${photoId} -> ${meshId}: unusable photo (${reading.notes ?? ""})`); continue; }
  const windows = (reading.windowRows ?? []).reduce((sum, row) => sum + (Array.isArray(row) ? row.length : Number(row)), 0);
  const doors = (reading.doorPositions ?? []).length;
  plans[meshId] = {
    ...(plans[meshId] ?? {}),
    reference: `references/walls/${photoId}.jpg`,
    windows,
    doors,
    floors: reading.floors ?? (reading.windowRows?.length || 1),
    windowGridColumns: reading.windowGridColumns,
    windowRows: reading.windowRows ?? [],
    doorPositions: reading.doorPositions ?? [],
    // optional opening sizes the layout expander understands (tall arched windows, wide doors, ...)
    ...Object.fromEntries(["windowSillMeters", "floorHeightMeters", "windowWidthMeters", "windowHeightMeters", "doorWidthMeters", "doorHeightMeters"]
      .filter((key) => reading[key] !== undefined).map((key) => [key, reading[key]])),
    doorPositionStatus: "visually-read",
    countMethod: "visual-inspection",
    confidence: reading.confidence,
    quality: reading.quality,
    notes: reading.notes,
    reader: readings.reader ?? "manual reading",
    readAt,
  };
  report.written.push(`${photoId} -> ${meshId}: ${windows} windows, ${doors} doors`);
}
if (readings.roof) {
  const roofPath = manifest.roof?.path ?? "references/roof-satellite.jpg";
  rules.roof = { ...(rules.roof ?? {}), referenceSource: roofPath, ...readings.roof };
}

// Wall height: the measured (lidar nDSM) building height, or a reading override. The lidar value
// is a median over the whole footprint, so for pitched roofs it sits about halfway up the roof;
// take half the roof rise off to get the eave height the walls should reach.
const heights = JSON.parse(await readFile(path.join(root, "public/models/dartmouth-campus/building-heights.json"), "utf8"));
const measured = heights.buildings.find((record) => record.osmId === manifest.osmId);
const targetHeight = readings.heightMeters ?? measured?.heightMeters;
if (targetHeight) {
  const roof = rules.roof ?? {};
  const pitched = roof.type && roof.type !== "flat";
  const wall = !pitched ? targetHeight
    : roof.riseMeters ? targetHeight - roof.riseMeters / 2
    : targetHeight / (1 + Number(roof.heightRatio ?? 0.16) / 2);
  rules.heightMeters = Math.round(targetHeight * 100) / 100;
  rules.wallHeightMeters = Math.round(Math.max(3, wall) * 100) / 100;
  rules.heightSource = readings.heightMeters ? "reading override" : `${measured.method} (${measured.sourceUrl ?? "building-heights.json"})`;
}
await writeFile(rulesPath, `${JSON.stringify(rules, null, 2)}\n`);
console.log(`${folder}\n  ${report.written.join("\n  ")}`);
if (report.skipped.length) console.log(`  skipped:\n    ${report.skipped.join("\n    ")}`);

// elevation sheets must be recompiled or the builder ignores windowRows/doorPositions
const sheetArgs = ["scripts/blender/generate-reference-elevation-sheets.py", folder.split("__")[1]];
if (rules.wallHeightMeters) sheetArgs.push("--height", String(rules.wallHeightMeters));
execFileSync("python3", sheetArgs, { cwd: root, stdio: "inherit" });
