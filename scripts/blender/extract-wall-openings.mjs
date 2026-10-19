// Automates the most token-heavy, error-prone step of the 3D builder
// pipeline: hand-transcribing window/door counts and grid positions from
// reference photos into modeling-rules.json's wallOpeningPlans.
//
// A wall's real width in meters is already known (references-manifest.json,
// derived from the OSM footprint), so the vision model never has to guess
// absolute scale -- only the count/grid/relative-position facts a photo can
// actually support. That output shape is deliberately the same compact
// windowRows/windowGridColumns/doorPositions grid a human already
// hand-authors, since reference_module.py's opening_layout_for_plan()
// already expands it into full per-opening geometry using the wall's real
// measured width and the mesh's real (build-time) height.
//
// Extracted photo wall ids (references-manifest.json's wall-01..wall-NN,
// assigned by the reference-photo generator) live in a different id space
// than the ids the geometry builder actually assigns at build time
// (south-04, west-01, via assign_generic_wall_ids in
// integrated_facade_module.py, based on real mesh edge geometry). This
// script correlates the two by real wall length + cardinal side, using
// scripts/blender/blender-list-wall-ids.py (which reuses the builder's own
// wall-id function, so the ids it reports are guaranteed to match a real
// build) rather than guessing.

import { access, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";
import Anthropic from "@anthropic-ai/sdk";

const root = process.cwd();
const modelDir = path.join(root, "public", "models", "dartmouth-energy-twin");
const manifestPath = path.join(modelDir, "renders", "parts-manifest.json");
const blendPath = path.join(modelDir, "dartmouth-energy-twin.blend");
const blenderBinary = process.env.BLENDER_BINARY || "/Applications/Blender.app/Contents/MacOS/Blender";
const wallListScript = path.join(root, "scripts", "blender", "blender-list-wall-ids.py");
const elevationSheetsScript = path.join(root, "scripts", "blender", "generate-reference-elevation-sheets.py");

const DEFAULT_MODEL = "claude-sonnet-5";
const TOOL_NAME = "report_wall_openings";
const WALL_LIST_START_MARKER = "===WALL_LIST_JSON_START===";
const WALL_LIST_END_MARKER = "===WALL_LIST_JSON_END===";

async function main() {
  const options = parseArgs(process.argv.slice(2));
  await loadLocalEnv();

  const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
  const matched = selectBuildings(manifest.buildings ?? [], options);
  const limited = options.building
    ? matched
    : matched.slice(options.offset, options.limit === null ? undefined : options.offset + options.limit);

  if (!limited.length) throw new Error("No buildings matched.");

  let client = null;
  if (!options.dryRun) {
    const apiKey = process.env.ANTHROPIC_API_KEY;
    if (!apiKey) throw new Error("Missing ANTHROPIC_API_KEY. Set it in .env.local, or pass --dry-run to test wiring without spending API calls.");
    client = new Anthropic({ apiKey });
  }

  console.log(`Matched ${matched.length} building(s). Processing ${limited.length}.`);

  const results = [];
  for (const [index, building] of limited.entries()) {
    console.log(`\n=== ${index + 1}/${limited.length} ${building.name} ===`);
    results.push(await processBuilding(building, options, client));
  }

  console.log("\n--- summary ---");
  for (const result of results) {
    console.log(
      `${result.building}: written=${result.written.length} skipped=${result.skipped.length} needsReview=${result.needsReview.length}`,
    );
    for (const item of result.needsReview) {
      console.log(`  needs-review: ${item.wallId ?? item.source ?? "?"} -- ${item.reason ?? item.extracted?.quality ?? "low confidence"}`);
    }
  }
}

async function processBuilding(building, options, client) {
  const referenceDir = path.join(modelDir, "renders", building.folder, "references");
  const referencesManifestFile = path.join(referenceDir, "references-manifest.json");
  const rulesFile = path.join(referenceDir, "modeling-rules.json");
  const result = { building: building.name, written: [], skipped: [], needsReview: [] };

  if (!(await fileExists(referencesManifestFile))) {
    console.log("[skip] no references-manifest.json yet -- run the facade reference generator first");
    result.skipped.push({ reason: "no-references-manifest" });
    return result;
  }

  const referencesManifest = JSON.parse(await readFile(referencesManifestFile, "utf8"));
  const majorWalls = (referencesManifest.walls ?? []).filter(
    (wall) => wall.reference?.status === "saved" && wall.reference?.qualityStatus !== "rejected",
  );
  if (!majorWalls.length) {
    console.log("[skip] no saved, non-rejected wall references");
    result.skipped.push({ reason: "no-usable-wall-references" });
    return result;
  }

  let rules = (await fileExists(rulesFile)) ? JSON.parse(await readFile(rulesFile, "utf8")) : null;
  if (rules?.wallNaming) {
    console.log(`[skip] custom wallNaming ("${rules.wallNaming}") -- curated wing splits need manual correlation`);
    result.skipped.push({ reason: "custom-wall-naming", wallNaming: rules.wallNaming });
    return result;
  }

  const meshBuilding = await listMeshWalls(building.name);
  if (!meshBuilding) {
    console.log("[skip] could not read mesh wall geometry from the .blend");
    result.skipped.push({ reason: "mesh-wall-list-failed" });
    return result;
  }

  const { matched, unmatched } = correlateWalls(majorWalls, meshBuilding);
  for (const manifestWall of unmatched) {
    console.log(`[needs-review] ${manifestWall.id}: no mesh wall found within length tolerance`);
    result.needsReview.push({ source: manifestWall.id, reason: "no-mesh-wall-correlation" });
  }

  rules ??= {
    building: building.name,
    displayName: referencesManifest.displayName ?? building.name,
    rulesVersion: 1,
    scope: "exterior-only",
    windowsAndDoors: { wallOpeningPlans: {} },
  };
  rules.windowsAndDoors ??= {};
  rules.windowsAndDoors.wallOpeningPlans ??= {};

  let changed = false;
  for (const { manifestWall, meshWall, lengthDeltaMeters } of matched) {
    const existing = rules.windowsAndDoors.wallOpeningPlans[meshWall.wallId];
    if (existing && !options.force) {
      console.log(`[skip] ${meshWall.wallId} already has a plan (pass --force to overwrite)`);
      result.skipped.push({ wallId: meshWall.wallId, reason: "already-has-plan" });
      continue;
    }

    if (options.dryRun) {
      console.log(
        `[plan] ${meshWall.wallId} <- ${manifestWall.id} (${manifestWall.reference.path}), ` +
          `length ${meshWall.lengthMeters}m vs ${manifestWall.lengthMeters}m (delta ${lengthDeltaMeters}m)`,
      );
      result.written.push({ wallId: meshWall.wallId, source: manifestWall.id, planned: true });
      continue;
    }

    // manifestWall.reference.path is relative to the building's own
    // references/ folder and is itself prefixed with "references/" (the
    // same quirk reference_module.py works around with removeprefix), so
    // it resolves against referenceDir, not the repo root.
    const imagePath = path.join(referenceDir, manifestWall.reference.path.replace(/^references\//, ""));
    let extracted;
    try {
      extracted = await extractWallOpenings(client, options.model, imagePath, manifestWall.lengthMeters);
    } catch (error) {
      console.warn(`[error] ${meshWall.wallId}: ${error.message}`);
      result.needsReview.push({ wallId: meshWall.wallId, source: manifestWall.id, reason: "extraction-error", error: error.message });
      continue;
    }

    if (!extracted || extracted.quality === "unusable" || extracted.confidence < options.minConfidence) {
      console.log(
        `[needs-review] ${meshWall.wallId}: ${extracted ? `${extracted.quality} (confidence ${extracted.confidence})` : "no tool response"}`,
      );
      result.needsReview.push({ wallId: meshWall.wallId, source: manifestWall.id, extracted });
      continue;
    }

    rules.windowsAndDoors.wallOpeningPlans[meshWall.wallId] = {
      ...(existing ?? {}),
      reference: manifestWall.reference.path,
      windows: extracted.windows,
      doors: extracted.doors,
      floors: extracted.floors,
      windowGridColumns: extracted.windowGridColumns,
      windowRows: extracted.windowRows,
      doorPositions: extracted.doorPositions,
      doorPositionStatus: "vision-extracted",
      countMethod: "vision-extracted",
      confidence: extracted.confidence,
      quality: extracted.quality,
      notes: extracted.notes,
      visionModel: options.model,
      extractedAt: new Date().toISOString(),
    };
    changed = true;
    console.log(`[ok] ${meshWall.wallId} <- ${manifestWall.id}: windows=${extracted.windows} doors=${extracted.doors} confidence=${extracted.confidence}`);
    result.written.push({ wallId: meshWall.wallId, source: manifestWall.id, windows: extracted.windows, doors: extracted.doors, confidence: extracted.confidence });
  }

  if (changed) {
    await writeFile(rulesFile, `${JSON.stringify(rules, null, 2)}\n`);
    console.log(`Wrote ${path.relative(root, rulesFile)}`);
    if (!options.noRecompile) {
      console.log("Recompiling elevation sheets so the new wallOpeningPlans data actually takes effect...");
      const recompile = await runPython(elevationSheetsScript, [building.name]);
      if (recompile.code !== 0) {
        console.warn(`[warn] elevation-sheet recompile failed (exit ${recompile.code}) -- run npm run model:dartmouth:reference-sheets -- ${building.name} manually before building.`);
      }
    }
  }

  return result;
}

async function extractWallOpenings(client, model, imagePath, wallLengthMeters) {
  const imageBuffer = await readFile(imagePath);
  const mediaType = mediaTypeFor(imagePath);
  const prompt = [
    `This photo shows one exterior wall of a building. The wall is measured at exactly ${wallLengthMeters.toFixed(1)} meters wide in real life, from real footprint survey data -- use that as your only scale reference, never guess an absolute width from the photo.`,
    "Read the facade and report, via the report_wall_openings tool:",
    "- how many full floors/stories of windows are visible on this wall",
    "- windowGridColumns: pick a column count that fits the widest floor's window rhythm",
    "- windowRows: one array per floor (bottom to top), each containing the 1-indexed column slots (out of windowGridColumns) that have a window on that floor",
    "- doors: how many ground-floor doors, and doorPositions: each door's position as a fraction from 0 (left edge of the photo facing the wall) to 1 (right edge)",
    "- windows and doors are always counted separately, never combined",
    "If trees, vehicles, cropping, or extreme angle make the wall too unclear to confidently read the grid, set quality to \"unusable\" -- still fill in your best-effort numbers (they will be discarded), and explain the obstruction in notes.",
  ].join("\n");

  const response = await client.messages.create({
    model,
    max_tokens: 1024,
    tools: [wallOpeningsTool()],
    tool_choice: { type: "tool", name: TOOL_NAME },
    messages: [
      {
        role: "user",
        content: [
          { type: "image", source: { type: "base64", media_type: mediaType, data: imageBuffer.toString("base64") } },
          { type: "text", text: prompt },
        ],
      },
    ],
  });

  const toolUse = response.content.find((block) => block.type === "tool_use");
  return toolUse ? toolUse.input : null;
}

function wallOpeningsTool() {
  return {
    name: TOOL_NAME,
    description: "Report the window/door grid layout observed on one building wall photo.",
    input_schema: {
      type: "object",
      properties: {
        quality: { type: "string", enum: ["clear", "partially-occluded", "unusable"] },
        confidence: { type: "number", minimum: 0, maximum: 1 },
        floors: { type: "integer", minimum: 1 },
        windows: { type: "integer", minimum: 0 },
        doors: { type: "integer", minimum: 0 },
        windowGridColumns: { type: "integer", minimum: 1 },
        windowRows: {
          type: "array",
          description: "One entry per floor bottom-to-top; each entry lists the 1-indexed column slots (out of windowGridColumns) with a window on that floor.",
          items: { type: "array", items: { type: "integer", minimum: 1 } },
        },
        doorPositions: {
          type: "array",
          description: "One 0-1 fraction per door, left edge of the photo = 0.",
          items: { type: "number", minimum: 0, maximum: 1 },
        },
        notes: { type: "string", description: "Short evidence/reasoning, including any occlusion or uncertainty caveats." },
      },
      required: ["quality", "confidence", "floors", "windows", "doors", "windowGridColumns", "windowRows", "doorPositions", "notes"],
    },
  };
}

async function listMeshWalls(buildingName) {
  const idMatch = buildingName.match(/(\d+)$/);
  const query = idMatch ? idMatch[1] : buildingName;
  const { code, stdout, stderr } = await runBlender(wallListScript, [blendPath, query]);
  if (code !== 0) {
    console.warn(`[warn] blender-list-wall-ids.py failed: ${tail(stderr)}`);
    return null;
  }
  const start = stdout.indexOf(WALL_LIST_START_MARKER);
  const end = stdout.indexOf(WALL_LIST_END_MARKER);
  if (start === -1 || end === -1) {
    console.warn("[warn] could not find wall-list JSON markers in Blender output");
    return null;
  }
  const payload = stdout.slice(start + WALL_LIST_START_MARKER.length, end).trim();
  const parsed = JSON.parse(payload);
  return parsed.buildings?.[0] ?? null;
}

const CARDINALS = [
  ["north", 0],
  ["east", 90],
  ["south", 180],
  ["west", 270],
];

function nearestCardinal(bearing) {
  let best = CARDINALS[0][0];
  let bestDelta = Infinity;
  for (const [name, target] of CARDINALS) {
    const delta = angleDelta(bearing, target);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = name;
    }
  }
  return best;
}

function angleDelta(a, b) {
  const diff = Math.abs(a - b) % 360;
  return diff > 180 ? 360 - diff : diff;
}

// Greedy, longest-wall-first match within each cardinal bucket: real walls
// almost always have near-identical lengths between the OSM-footprint-derived
// manifest and the current Blender mesh (e.g. observed 45.22m vs 45.23m for
// the same physical wall on Baker Library), so length is a strong signal --
// far more reliable than trying to recreate positional ordering, since the
// two generators number walls in unrelated ways (manifest: perimeter-wide
// sequence over "major" edges only; mesh: per-side reading order over every
// edge). Walls without a confident match are left for manual review rather
// than guessed.
function correlateWalls(manifestWalls, meshBuilding) {
  const meshWalls = meshBuilding.walls ?? [];
  const usedMeshWallIds = new Set();
  const matched = [];
  const unmatched = [];

  const sorted = [...manifestWalls].sort((a, b) => b.lengthMeters - a.lengthMeters);
  for (const manifestWall of sorted) {
    const bearing = manifestWall.outwardBearing ?? manifestWall.bearing ?? 0;
    const cardinal = nearestCardinal(bearing);
    let best = null;
    let bestDiff = Infinity;
    for (const meshWall of meshWalls) {
      if (meshWall.side !== cardinal || usedMeshWallIds.has(meshWall.wallId)) continue;
      const diff = Math.abs(meshWall.lengthMeters - manifestWall.lengthMeters);
      const tolerance = Math.max(2, manifestWall.lengthMeters * 0.15);
      if (diff <= tolerance && diff < bestDiff) {
        best = meshWall;
        bestDiff = diff;
      }
    }
    if (best) {
      usedMeshWallIds.add(best.wallId);
      matched.push({ manifestWall, meshWall: best, lengthDeltaMeters: Number(bestDiff.toFixed(2)) });
    } else {
      unmatched.push(manifestWall);
    }
  }
  return { matched, unmatched };
}

function runBlender(scriptPath, args) {
  return new Promise((resolve) => {
    const child = spawn(blenderBinary, ["--background", "--factory-startup", "--python", scriptPath, "--", ...args], {
      cwd: root,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      stdout += chunk.toString();
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function runPython(scriptPath, args) {
  return new Promise((resolve) => {
    const child = spawn("python3", [scriptPath, ...args], {
      cwd: root,
      env: process.env,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => {
      const text = chunk.toString();
      stdout += text;
      process.stdout.write(text);
    });
    child.stderr.on("data", (chunk) => {
      const text = chunk.toString();
      stderr += text;
      process.stderr.write(text);
    });
    child.on("close", (code) => resolve({ code, stdout, stderr }));
  });
}

function mediaTypeFor(filePath) {
  const ext = path.extname(filePath).toLowerCase();
  if (ext === ".png") return "image/png";
  if (ext === ".webp") return "image/webp";
  return "image/jpeg";
}

function parseArgs(args) {
  const parsed = {
    dryRun: false,
    force: false,
    limit: 5,
    offset: 0,
    building: null,
    minConfidence: 0.55,
    model: DEFAULT_MODEL,
    noRecompile: false,
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--dry-run") parsed.dryRun = true;
    else if (arg === "--force") parsed.force = true;
    else if (arg === "--all") parsed.limit = null;
    else if (arg === "--limit") parsed.limit = parsePositiveInteger(args[++index], "--limit");
    else if (arg.startsWith("--limit=")) parsed.limit = parsePositiveInteger(arg.slice("--limit=".length), "--limit");
    else if (arg === "--offset") parsed.offset = parseNonNegativeInteger(args[++index], "--offset");
    else if (arg.startsWith("--offset=")) parsed.offset = parseNonNegativeInteger(arg.slice("--offset=".length), "--offset");
    else if (arg === "--building") parsed.building = args[++index];
    else if (arg.startsWith("--building=")) parsed.building = arg.slice("--building=".length);
    else if (arg === "--min-confidence") parsed.minConfidence = Number.parseFloat(args[++index]);
    else if (arg.startsWith("--min-confidence=")) parsed.minConfidence = Number.parseFloat(arg.slice("--min-confidence=".length));
    else if (arg === "--model") parsed.model = args[++index];
    else if (arg.startsWith("--model=")) parsed.model = arg.slice("--model=".length);
    else if (arg === "--no-recompile") parsed.noRecompile = true;
    else if (!arg.startsWith("-")) parsed.building = arg;
    else throw new Error(`Unknown argument: ${arg}`);
  }

  return parsed;
}

function selectBuildings(buildings, options) {
  if (!options.building) return buildings;
  const needle = options.building.toLowerCase();
  const matches = buildings.filter((building) => building.name.toLowerCase().includes(needle) || building.folder.toLowerCase().includes(needle));
  if (!matches.length) throw new Error(`No building matched "${options.building}".`);
  if (matches.length > 1) {
    throw new Error(`"${options.building}" matched ${matches.length} buildings: ${matches.map((m) => m.name).join(", ")}. Be more specific.`);
  }
  return matches;
}

async function fileExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
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
      const value = trimmed
        .slice(equals + 1)
        .trim()
        .replace(/^['"]|['"]$/g, "");
      if (name && process.env[name] === undefined) process.env[name] = value;
    }
  } catch {
    // Environment file is optional when variables are already exported.
  }
}

function tail(value) {
  return value.trim().split(/\r?\n/).slice(-12).join("\n");
}

function parsePositiveInteger(value, name) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 1) throw new Error(`${name} must be a positive integer.`);
  return parsed;
}

function parseNonNegativeInteger(value, name) {
  const parsed = Number.parseInt(value, 10);
  if (!Number.isInteger(parsed) || parsed < 0) throw new Error(`${name} must be a non-negative integer.`);
  return parsed;
}

await main();
