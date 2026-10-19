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
const SEARCH_LIMIT_PER_BUILDING = 8;
const root = process.cwd();
const outputRoot = path.join(root, "public", "reference-atlas", "images");
const manifestPath = path.join(outputRoot, "manifest.json");
const requestLimit = Number(getArg("--limit") ?? 0);
const only = getArg("--only")?.toLowerCase() ?? "";
const dryRun = process.argv.includes("--dry-run");

await mkdir(outputRoot, { recursive: true });

const buildings = await getSearchBuildings();

const manifest = {
  generatedAt: new Date().toISOString(),
  source: "Wikimedia Commons API + OpenStreetMap building names",
  mode: "wikimedia-candidates",
  bounds: CAMPUS_BOUNDS,
  checker: {
    status: "metadata-first",
    note: "The checker rejects obvious non-modeling images using metadata and image dimensions. Obstruction and full-wall quality still need human approval or a vision API.",
  },
  buildings: [],
};

console.log(`Searching Wikimedia candidates for ${buildings.length} buildings.`);

for (const building of buildings) {
  const buildingDir = path.join(outputRoot, building.id);
  await mkdir(buildingDir, { recursive: true });

  const candidates = await searchCommons(building.name);
  const record = {
    id: building.id,
    name: building.name,
    osmId: building.osmId,
    category: "Wikimedia candidates",
    shortCode: makeShortCode(building.name),
    views: {},
    rejected: [],
  };

  for (const candidate of candidates) {
    const check = checkReferenceCandidate(candidate, building.name);
    const viewId = `${check.viewGuess}-${String(Object.keys(record.views).length + 1).padStart(2, "0")}`;
    const fileName = `${viewId}.jpg`;

    if (check.status === "invalid") {
      record.rejected.push({
        title: candidate.title,
        sourceUrl: candidate.descriptionUrl,
        reasons: check.reasons,
      });
      continue;
    }

    if (!dryRun) {
      const response = await fetch(candidate.url, {
        headers: { "User-Agent": "DartmouthEnergyTwin/0.1 (modeling reference atlas)" },
      });
      if (!response.ok || !response.body) {
        record.rejected.push({
          title: candidate.title,
          sourceUrl: candidate.descriptionUrl,
          reasons: [`Image download returned ${response.status}`],
        });
        continue;
      }
      await writeFile(path.join(buildingDir, fileName), Buffer.from(await response.arrayBuffer()));
    }

    record.views[viewId] = {
      label: check.label,
      path: `/reference-atlas/images/${building.id}/${fileName}`,
      source: "Wikimedia Commons",
      sourceUrl: candidate.descriptionUrl,
      title: candidate.title,
      author: candidate.author,
      license: candidate.license,
      width: candidate.width,
      height: candidate.height,
      viewGuess: check.viewGuess,
      qualityStatus: check.status,
      qualityScore: check.score,
      reasons: check.reasons,
      flags: check.flags,
    };
    console.log(`${dryRun ? "Found" : "Saved"} ${building.name}: ${candidate.title}`);
  }

  manifest.buildings.push(record);
}

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, manifestPath)}`);

async function getSearchBuildings() {
  if (only) {
    return [{
      id: slugify(only),
      osmId: null,
      name: titleCase(only),
      searchable: true,
    }];
  }
  const osm = await fetchCampusBuildings();
  return extractBuildingFootprints(osm)
    .filter((building) => building.searchable)
    .sort((a, b) => scoreBuildingName(b.name) - scoreBuildingName(a.name) || a.name.localeCompare(b.name))
    .slice(0, requestLimit || undefined);
}

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
  const response = await fetch("https://overpass-api.de/api/interpreter", {
    method: "POST",
    headers: {
      "Accept": "application/json, text/plain, */*",
      "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
      "User-Agent": "DartmouthEnergyTwin/0.1",
    },
    body: new URLSearchParams({ data: query.trim() }),
  });
  if (!response.ok) throw new Error(`Overpass returned ${response.status}`);
  return response.json();
}

function extractBuildingFootprints(osm) {
  const ways = [];
  for (const element of osm.elements ?? []) {
    if (element.type === "way" && element.tags?.building) ways.push(element);
  }

  return ways.map((way) => {
    const naming = getCampusBuildingName(way.tags, way.id);
    return {
      id: slugify(`${naming.name}-${way.id}`),
      osmId: `way/${way.id}`,
      name: naming.name,
      rawName: naming.rawName,
      searchable: naming.hasRealName && !naming.isGenerated,
    };
  });
}

async function searchCommons(buildingName) {
  const search = `${buildingName} Dartmouth College building`;
  const params = new URLSearchParams({
    action: "query",
    format: "json",
    generator: "search",
    gsrnamespace: "6",
    gsrlimit: String(SEARCH_LIMIT_PER_BUILDING),
    gsrsearch: search,
    prop: "imageinfo",
    iiprop: "url|size|mime|extmetadata",
    origin: "*",
  });
  const response = await fetch(`https://commons.wikimedia.org/w/api.php?${params}`, {
    headers: { "User-Agent": "DartmouthEnergyTwin/0.1 (modeling reference atlas)" },
  });
  if (!response.ok) {
    console.warn(`Wikimedia returned ${response.status} for ${buildingName}`);
    return [];
  }
  const payload = await response.json();
  return Object.values(payload.query?.pages ?? {})
    .map((page) => mapCommonsCandidate(page))
    .filter(Boolean);
}

function mapCommonsCandidate(page) {
  const info = page.imageinfo?.[0];
  if (!info?.url) return null;
  const metadata = info.extmetadata ?? {};
  return {
    title: page.title?.replace(/^File:/, "") ?? "Untitled",
    url: info.url,
    descriptionUrl: info.descriptionurl,
    mime: info.mime,
    width: info.width,
    height: info.height,
    description: stripHtml(metadata.ImageDescription?.value ?? ""),
    objectName: stripHtml(metadata.ObjectName?.value ?? ""),
    author: stripHtml(metadata.Artist?.value ?? ""),
    license: stripHtml(metadata.LicenseShortName?.value ?? metadata.UsageTerms?.value ?? ""),
  };
}

function checkReferenceCandidate(candidate, buildingName) {
  const text = `${candidate.title} ${candidate.description} ${candidate.objectName}`.toLowerCase();
  const reasons = [];
  const flags = [];
  let score = 0;

  if (!candidate.mime?.startsWith("image/")) reasons.push("Not an image file");
  if ((candidate.width ?? 0) < 900 || (candidate.height ?? 0) < 450) reasons.push("Resolution too low for modeling details");

  const aspectRatio = candidate.width / candidate.height;
  if (aspectRatio < 1.15) reasons.push("Not wide enough to show a full facade");
  if (aspectRatio > 5.2) flags.push("Very wide panorama; may be distorted");
  if (aspectRatio >= 1.6 && aspectRatio <= 4.2) score += 2;
  if ((candidate.width ?? 0) >= 1600) score += 2;

  const badWords = [
    "aerial", "air view", "bird", "map", "plan", "floorplan", "diagram", "interior", "room",
    "portrait", "people", "team", "logo", "seal", "plaque", "sign", "snow sculpture", "postcard",
    "blocked", "blocking", "obscured", "obstructed", "covered", "hidden", "behind tree",
    "behind trees", "tree", "trees", "tree in front", "trees in front", "branch",
    "branches", "leaf", "leaves", "foliage", "greenery", "vegetation", "canopy",
    "shrub", "shrubs", "bush", "bushes", "ivy covered", "scaffold", "scaffolding", "fence", "fenced", "construction",
    "renovation", "vehicle", "vehicles", "car", "cars", "truck", "bus", "crowd",
    "crowded", "snow", "night", "low light", "closeup", "close-up", "detail",
    "partial", "corner", "entrance only", "doorway", "burning", "fire",
  ];
  for (const word of badWords) {
    if (hasKeyword(text, word)) reasons.push(`Rejected by metadata keyword: ${word}`);
  }

  const goodWords = ["facade", "front", "elevation", "exterior", "building", "hall", "library", "center"];
  for (const word of goodWords) {
    if (text.includes(word)) score += 1;
  }

  const nameTokens = buildingName.toLowerCase().split(/\W+/).filter((token) => token.length > 2);
  const matchedTokens = nameTokens.filter((token) => text.includes(token)).length;
  if (matchedTokens >= Math.min(2, nameTokens.length)) score += 2;
  if (matchedTokens === 0) reasons.push("Image metadata does not match the building name");

  const viewGuess = guessView(text);
  const status = reasons.length ? "invalid" : score >= 5 ? "candidate" : "needs-review";
  const label = viewGuess === "candidate" ? "Candidate" : titleCase(viewGuess);

  if (status !== "invalid") {
    flags.push("Manual obstruction check required");
    flags.push("Approve only if the wall is visible from end to end");
  }

  return { status, score, reasons, flags, viewGuess, label };
}

function guessView(text) {
  if (text.includes("back") || text.includes("rear")) return "back";
  if (text.includes("left") || text.includes("west side") || text.includes("east side")) return "side";
  if (text.includes("right") || text.includes("side")) return "side";
  if (text.includes("front") || text.includes("facade") || text.includes("façade") || text.includes("elevation")) return "front";
  return "candidate";
}

function scoreBuildingName(name) {
  if (/building \d+/i.test(name)) return 0;
  if (/^\d+\s/.test(name)) return 1;
  return name.split(/\s+/).length + 2;
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

function stripHtml(value) {
  return String(value).replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function titleCase(value) {
  return value.replace(/[-_]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function hasKeyword(text, keyword) {
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\ /g, "\\s+");
  return new RegExp(`(^|[^a-z0-9])${escaped}($|[^a-z0-9])`, "i").test(text);
}
