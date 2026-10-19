// Verify every asset URL the deployed app requests exists with exact path case (Linux and the
// Vercel CDN are case-sensitive; macOS is not) and is not excluded by .vercelignore.
//   node scripts/check-deploy-assets.mjs
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";

const root = process.cwd();
const pub = path.join(root, "public");
const json = (p) => JSON.parse(readFileSync(path.join(pub, p), "utf8"));
const problems = [];
const checked = new Set();

// exact-case existence, one path segment at a time
function exists(relative) {
  let current = pub;
  for (const segment of relative.split("/").filter(Boolean)) {
    if (!existsSync(current) || !readdirSync(current).includes(segment)) return false;
    current = path.join(current, segment);
  }
  return true;
}

const ignore = readFileSync(path.join(root, ".vercelignore"), "utf8").split("\n").map((l) => l.trim()).filter((l) => l && !l.startsWith("#") && !l.startsWith("!"));
const globToRegex = (glob) => new RegExp("^" + glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, "[^/]*").replace(/\?/g, ".") + "(/.*)?$");
const ignored = (relative) => ignore.some((pattern) => {
  const p = pattern.replace(/\/$/, "");
  const target = `public/${relative}`;
  return p.includes("/") ? globToRegex(p).test(target) : target.split("/").some((part) => globToRegex(p).test(part));
});

function need(url, from) {
  const relative = decodeURI(url.split("?")[0]).replace(/^\//, "");
  if (checked.has(relative)) return;
  checked.add(relative);
  if (!exists(relative)) problems.push(`missing (exact case): /${relative}  <- ${from}`);
  else if (ignored(relative)) problems.push(`excluded by .vercelignore: /${relative}  <- ${from}`);
}

// standalone scene
const manifest = json("models/dartmouth-campus/model-manifest.json");
need("/models/dartmouth-campus/model-manifest.json", "campus scene");
need(manifest.campusModel, "model-manifest campusModel");
const terrain = json("models/dartmouth-campus/terrain/campus-terrain.json");
need("/models/dartmouth-campus/terrain/campus-terrain.json", "campus scene");
for (const file of Object.keys(terrain.files)) need(`/models/dartmouth-campus/terrain/${file}`, "campus-terrain.json files");
for (const file of ["campus-roads.json", "campus-fields.json", "campus-trees.json"]) need(`/models/dartmouth-campus/${file}`, "campus scene");

// /api/buildings reads this from disk (traced into the function by next.config.ts)
need("/models/dartmouth-energy-twin/reports/osm-campus-names.json", "/api/buildings");

// /design-space loads per-building renders listed in the parts manifest
const parts = json("models/dartmouth-energy-twin/renders/parts-manifest.json");
const entries = [...(parts.buildings ?? []), ...(parts.roads ?? [])];
let partFiles = 0;
for (const entry of entries) {
  for (const key of ["glb", "fbx"]) if (entry?.[key]) { need(`/models/dartmouth-energy-twin/renders/${entry[key]}`, `parts-manifest ${key}`); partFiles += 1; }
}

// /reference-atlas and /reference-compositor (generated locally; gitignored)
if (exists("reference-atlas/images/manifest.json")) need("/reference-atlas/images/manifest.json", "/reference-atlas");
else console.warn("note: public/reference-atlas/images/manifest.json is absent; /reference-atlas will show its empty state");

console.log(`Checked ${checked.size} asset paths (${partFiles} design-space part files).`);
if (problems.length) {
  console.error(problems.slice(0, 50).join("\n"));
  console.error(`${problems.length} problem(s).`);
  process.exit(1);
}
console.log("All referenced assets exist with exact case and are included in the deployment.");
