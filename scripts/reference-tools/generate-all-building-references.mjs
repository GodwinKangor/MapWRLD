import { access, mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { spawn } from "node:child_process";

const root = process.cwd();
const modelDir = path.join(root, "public", "models", "dartmouth-energy-twin");
const manifestPath = path.join(modelDir, "renders", "parts-manifest.json");
const reportDir = path.join(modelDir, "reports");
const referenceScript = path.join(root, "scripts", "reference-tools", "generate-building-references.mjs");

const options = parseArgs(process.argv.slice(2));
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const buildings = selectBuildings(manifest.buildings ?? [], options);
const selected = [];

for (const building of buildings) {
  const referenceManifest = path.join(modelDir, "renders", building.folder, "references", "references-manifest.json");
  const exists = await fileExists(referenceManifest);
  if (exists && options.skipExisting && !options.force) continue;
  selected.push({ building, referenceManifest, exists });
}

const limited = selected.slice(options.offset, options.limit === null ? undefined : options.offset + options.limit);
const report = {
  generatedAt: new Date().toISOString(),
  dryRun: options.dryRun,
  options,
  totalBuildings: manifest.buildings?.length ?? 0,
  matchedBuildings: buildings.length,
  queuedBuildings: selected.length,
  processedBuildings: limited.length,
  results: [],
};

console.log(`Matched ${buildings.length} buildings.`);
console.log(`Queued ${selected.length} buildings after skip/force filters.`);
console.log(`${options.dryRun ? "Would process" : "Processing"} ${limited.length} buildings.`);

if (!options.dryRun) {
  await loadLocalEnv();
  const key = process.env.GOOGLE_MAPPLATFORM_APIKEY ?? process.env.GOOGLE_MAPS_API_KEY;
  if (!key) {
    console.error("Missing GOOGLE_MAPPLATFORM_APIKEY or GOOGLE_MAPS_API_KEY.");
    process.exit(1);
  }
}

for (const [index, item] of limited.entries()) {
  const label = `${index + 1}/${limited.length} ${item.building.name}`;
  if (options.dryRun) {
    console.log(`[plan] ${label}`);
    report.results.push(resultFor(item, "planned"));
    continue;
  }

  console.log(`[run] ${label}`);
  const startedAt = Date.now();
  const child = await runNode(referenceScript, [item.building.name]);
  const elapsedMs = Date.now() - startedAt;
  if (child.code === 0) {
    console.log(`[ok] ${item.building.name}`);
    report.results.push({
      ...resultFor(item, "generated"),
      elapsedMs,
      stdoutTail: tail(child.stdout),
    });
    continue;
  }

  console.warn(`[failed] ${item.building.name}`);
  report.results.push({
    ...resultFor(item, "failed"),
    elapsedMs,
    exitCode: child.code,
    stdoutTail: tail(child.stdout),
    stderrTail: tail(child.stderr),
  });

  if (options.stopOnFailure) break;
}

await mkdir(reportDir, { recursive: true });
const reportName = options.dryRun ? "all-building-references-plan.json" : "all-building-references-report.json";
const reportPath = path.join(reportDir, reportName);
await writeFile(reportPath, `${JSON.stringify(report, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, reportPath)}`);

function parseArgs(args) {
  const parsed = {
    dryRun: false,
    force: false,
    skipExisting: true,
    stopOnFailure: false,
    limit: 10,
    offset: 0,
    only: [],
    match: [],
  };

  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--dry-run" || arg === "--plan-only") parsed.dryRun = true;
    else if (arg === "--force") parsed.force = true;
    else if (arg === "--include-existing") parsed.skipExisting = false;
    else if (arg === "--stop-on-failure") parsed.stopOnFailure = true;
    else if (arg === "--all") parsed.limit = null;
    else if (arg === "--limit") parsed.limit = parsePositiveInteger(args[++index], "--limit");
    else if (arg.startsWith("--limit=")) parsed.limit = parsePositiveInteger(arg.slice("--limit=".length), "--limit");
    else if (arg === "--offset") parsed.offset = parseNonNegativeInteger(args[++index], "--offset");
    else if (arg.startsWith("--offset=")) parsed.offset = parseNonNegativeInteger(arg.slice("--offset=".length), "--offset");
    else if (arg === "--only") parsed.only.push(args[++index]);
    else if (arg.startsWith("--only=")) parsed.only.push(arg.slice("--only=".length));
    else if (arg === "--match") parsed.match.push(args[++index]);
    else if (arg.startsWith("--match=")) parsed.match.push(arg.slice("--match=".length));
    else if (!arg.startsWith("-")) parsed.match.push(arg);
    else throw new Error(`Unknown argument: ${arg}`);
  }

  return parsed;
}

function selectBuildings(buildings, options) {
  let selected = buildings;
  if (options.only.length) {
    const exactNames = new Set(options.only.map((value) => normalize(value)));
    selected = selected.filter((building) => exactNames.has(normalize(building.name)) || exactNames.has(normalize(building.folder)));
  }
  if (options.match.length) {
    const needles = options.match.map((value) => normalize(value));
    selected = selected.filter((building) => {
      const haystack = normalize(`${building.name} ${building.folder}`);
      return needles.some((needle) => haystack.includes(needle));
    });
  }
  return selected;
}

function resultFor(item, status) {
  return {
    status,
    building: item.building.name,
    folder: item.building.folder,
    existedBeforeRun: item.exists,
    referenceManifest: path.relative(root, item.referenceManifest),
  };
}

function runNode(script, args) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [script, ...args], {
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
      const value = trimmed.slice(equals + 1).trim().replace(/^['"]|['"]$/g, "");
      if (name && process.env[name] === undefined) process.env[name] = value;
    }
  } catch {
    // Environment file is optional when variables are already exported.
  }
}

function tail(value) {
  return value.trim().split(/\r?\n/).slice(-12);
}

function normalize(value) {
  return String(value ?? "").toLowerCase();
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
