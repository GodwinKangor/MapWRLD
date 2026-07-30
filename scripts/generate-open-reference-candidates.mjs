import { access, mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { getCampusBuildingName } from "./campus-building-names.mjs";

const CAMPUS_BOUNDS = {
  west: -72.2972,
  south: 43.6961,
  east: -72.2785,
  north: 43.7108,
};
const PROVIDERS = ["wikimedia", "openverse", "loc"];
const GENERIC_NAME_TOKENS = new Set([
  "dartmouth",
  "college",
  "building",
  "buildings",
  "hall",
  "center",
  "centre",
  "house",
  "school",
  "library",
]);
const OBSTRUCTION_WORDS = [
  "blocked",
  "blocking",
  "obscured",
  "obstructed",
  "covered",
  "hidden",
  "behind tree",
  "behind trees",
  "tree in front",
  "trees in front",
  "foliage",
  "bush",
  "bushes",
  "ivy covered",
  "scaffold",
  "scaffolding",
  "fence",
  "fenced",
  "construction",
  "renovation",
  "vehicle",
  "vehicles",
  "car",
  "cars",
  "truck",
  "bus",
  "crowd",
  "crowded",
  "people",
  "snow",
  "night",
  "low light",
  "closeup",
  "close-up",
  "detail",
  "partial",
  "corner",
  "entrance only",
  "doorway",
];
const root = process.cwd();
const outputRoot = path.join(root, "public", "reference-atlas", "images");
const manifestPath = path.join(outputRoot, "manifest.json");
const requestLimit = Number(getArg("--limit") ?? 0);
const only = getArg("--only")?.toLowerCase() ?? "";

await mkdir(outputRoot, { recursive: true });

const buildings = await getSearchBuildings();
const manifest = {
  generatedAt: new Date().toISOString(),
  source: "Open/free image providers + OpenStreetMap building names",
  mode: "open-candidates",
  bounds: CAMPUS_BOUNDS,
  providers: PROVIDERS,
  checker: {
    status: "metadata-first",
    note: "Rejects obvious bad references before saving. Final approval still requires confirming the full wall is visible end-to-end and unobscured.",
  },
  buildings: [],
};

console.log(`Searching open reference candidates for ${buildings.length} buildings.`);

for (const building of buildings) {
  const buildingDir = path.join(outputRoot, building.id);
  await mkdir(buildingDir, { recursive: true });

  const record = {
    id: building.id,
    name: building.name,
    osmId: building.osmId,
    category: "Open reference candidates",
    shortCode: makeShortCode(building.name),
    views: {},
    rejected: [],
  };

  const candidates = await collectCandidates(building.name);
  for (const candidate of candidates) {
    const check = checkReferenceCandidate(candidate, building.name);
    if (check.status === "invalid") {
      record.rejected.push({
        provider: candidate.provider,
        title: candidate.title,
        sourceUrl: candidate.sourceUrl,
        reasons: check.reasons,
      });
      continue;
    }

    const next = Object.keys(record.views).length + 1;
    const viewId = `${check.viewGuess}-${String(next).padStart(2, "0")}`;
    const extension = extensionFromUrl(candidate.imageUrl) ?? "jpg";
    const fileName = `${viewId}-${slugify(candidate.title).slice(0, 72) || "reference"}.${extension}`;
    const filePath = path.join(buildingDir, fileName);
    const download = await downloadImage(candidate.imageUrl, filePath);

    if (!download.ok) {
      record.rejected.push({
        provider: candidate.provider,
        title: candidate.title,
        sourceUrl: candidate.sourceUrl,
        reasons: [download.reason],
      });
      continue;
    }

    record.views[viewId] = {
      label: check.label,
      path: `/reference-atlas/images/${building.id}/${fileName}`,
      source: candidate.providerLabel,
      sourceUrl: candidate.sourceUrl,
      title: candidate.title,
      author: candidate.creator,
      license: candidate.license,
      licenseUrl: candidate.licenseUrl,
      width: candidate.width,
      height: candidate.height,
      viewGuess: check.viewGuess,
      qualityStatus: check.status,
      qualityScore: check.score,
      reasons: check.reasons,
      flags: check.flags,
    };
    console.log(`${download.reused ? "Reused" : "Saved"} ${building.name}: ${candidate.providerLabel} / ${candidate.title}`);
  }

  manifest.buildings.push(record);
}

async function downloadImage(url, filePath) {
  if (await fileExists(filePath)) return { ok: true, reused: true };

  for (let attempt = 1; attempt <= 3; attempt += 1) {
    const imageResponse = await fetch(url, {
      headers: { "User-Agent": "DartmouthEnergyTwin/0.1 (modeling reference atlas; educational non-commercial use)" },
    });
    if (imageResponse.ok && imageResponse.body) {
      await writeFile(filePath, Buffer.from(await imageResponse.arrayBuffer()));
      await sleep(300);
      return { ok: true, reused: false };
    }
    if (imageResponse.status !== 429 || attempt === 3) {
      return { ok: false, reason: `Image download returned ${imageResponse.status}` };
    }
    await sleep(1200 * attempt);
  }

  return { ok: false, reason: "Image download failed" };
}

async function fileExists(filePath) {
  try {
    await access(filePath);
    return true;
  } catch {
    return false;
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(`Wrote ${path.relative(root, manifestPath)}`);

async function collectCandidates(buildingName) {
  const providerResults = await Promise.allSettled([
    searchWikimedia(buildingName),
    searchOpenverse(buildingName),
    searchLibraryOfCongress(buildingName),
  ]);
  return dedupeCandidates(providerResults.flatMap((result) => result.status === "fulfilled" ? result.value : []));
}

async function searchWikimedia(buildingName) {
  const searches = searchPhrases(buildingName).map(async (search) => {
    const params = new URLSearchParams({
      action: "query",
      format: "json",
      generator: "search",
      gsrnamespace: "6",
      gsrlimit: "10",
      gsrsearch: search,
      prop: "imageinfo",
      iiprop: "url|size|mime|extmetadata",
      origin: "*",
    });
    const response = await fetch(`https://commons.wikimedia.org/w/api.php?${params}`, {
      headers: { "User-Agent": "DartmouthEnergyTwin/0.1 (modeling reference atlas)" },
    });
    if (!response.ok) return [];
    const payload = await response.json();
    return Object.values(payload.query?.pages ?? {}).map((page) => {
      const info = page.imageinfo?.[0];
      if (!info?.url) return null;
      const metadata = info.extmetadata ?? {};
      return {
        provider: "wikimedia",
        providerLabel: "Wikimedia Commons",
        title: page.title?.replace(/^File:/, "") ?? "Untitled",
        imageUrl: info.url,
        sourceUrl: info.descriptionurl,
        width: info.width,
        height: info.height,
        mime: info.mime,
        creator: stripHtml(metadata.Artist?.value ?? ""),
        license: stripHtml(metadata.LicenseShortName?.value ?? metadata.UsageTerms?.value ?? ""),
        licenseUrl: metadata.LicenseUrl?.value,
        text: `${page.title ?? ""} ${stripHtml(metadata.ImageDescription?.value ?? "")} ${stripHtml(metadata.ObjectName?.value ?? "")}`,
      };
    }).filter(Boolean);
  });
  return dedupeCandidates((await Promise.all(searches)).flat());
}

async function searchOpenverse(buildingName) {
  const searches = searchPhrases(buildingName).map(async (search) => {
    const params = new URLSearchParams({
      q: search,
      page_size: "10",
      license_type: "all-cc",
      extension: "jpg,png",
      size: "large",
    });
    const response = await fetch(`https://api.openverse.org/v1/images/?${params}`, {
      headers: { "User-Agent": "DartmouthEnergyTwin/0.1 (modeling reference atlas)" },
    });
    if (!response.ok) return [];
    const payload = await response.json();
    return (payload.results ?? []).map((item) => ({
      provider: "openverse",
      providerLabel: `Openverse / ${item.provider ?? item.source ?? "open media"}`,
      title: item.title ?? "Untitled",
      imageUrl: item.url,
      sourceUrl: item.foreign_landing_url ?? item.detail_url,
      width: item.width,
      height: item.height,
      mime: item.filetype ? `image/${item.filetype}` : "image",
      creator: item.creator ?? "",
      license: item.license ? `${item.license}${item.license_version ? ` ${item.license_version}` : ""}` : "",
      licenseUrl: item.license_url,
      text: `${item.title ?? ""} ${(item.tags ?? []).map((tag) => tag.name ?? tag).join(" ")}`,
    })).filter((item) => item.imageUrl && item.sourceUrl);
  });
  return dedupeCandidates((await Promise.all(searches)).flat());
}

async function searchLibraryOfCongress(buildingName) {
  const searches = searchPhrases(buildingName).map(async (search) => {
    const params = new URLSearchParams({
      fo: "json",
      at: "results",
      c: "10",
      q: search,
      fa: "original-format:photo|online-format:image",
    });
    const response = await fetch(`https://www.loc.gov/search/?${params}`, {
      headers: { "User-Agent": "DartmouthEnergyTwin/0.1 (modeling reference atlas)" },
    });
    if (!response.ok) return [];
    const payload = await response.json();
    return (payload.results ?? []).flatMap((item) => {
      const imageUrl = pickLocImage(item);
      if (!imageUrl) return [];
      return [{
        provider: "loc",
        providerLabel: "Library of Congress",
        title: item.title ?? "Untitled",
        imageUrl,
        sourceUrl: item.url,
        width: item.image_width,
        height: item.image_height,
        mime: "image/jpeg",
        creator: Array.isArray(item.contributor) ? item.contributor.join(", ") : "",
        license: "Check LOC rights advisory",
        licenseUrl: item.url,
        text: `${item.title ?? ""} ${item.description?.join?.(" ") ?? ""} ${item.subject?.join?.(" ") ?? ""} ${item.rights_advisory ?? ""}`,
      }];
    });
  });
  return dedupeCandidates((await Promise.all(searches)).flat());
}

function pickLocImage(item) {
  if (Array.isArray(item.image_url) && item.image_url.length) return item.image_url.at(-1);
  if (Array.isArray(item.resources)) {
    for (const resource of item.resources) {
      if (Array.isArray(resource.image_url) && resource.image_url.length) return resource.image_url.at(-1);
    }
  }
  return null;
}

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
  return (osm.elements ?? [])
    .filter((element) => element.type === "way" && element.tags?.building)
    .map((way) => {
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

function checkReferenceCandidate(candidate, buildingName) {
  const text = `${candidate.title} ${candidate.text ?? ""}`.toLowerCase();
  const reasons = [];
  const flags = [];
  let score = 0;

  if (!candidate.mime?.startsWith("image")) reasons.push("Not an image file");
  if ((candidate.width ?? 0) < 900 || (candidate.height ?? 0) < 450) reasons.push("Resolution too low for modeling details");

  const aspectRatio = (candidate.width ?? 0) / (candidate.height || 1);
  if (aspectRatio < 1.15) reasons.push("Not wide enough to show a full facade");
  if (aspectRatio > 5.2) flags.push("Very wide panorama; may be distorted");
  if (aspectRatio >= 1.6 && aspectRatio <= 4.2) score += 2;
  if ((candidate.width ?? 0) >= 1600) score += 2;

  const badWords = [
    "aerial", "air view", "bird", "map", "plan", "floorplan", "diagram", "interior", "room",
    "portrait", "people", "team", "logo", "seal", "plaque", "sign", "snow sculpture", "postcard",
    "construction", "burning", "fire",
  ];
  for (const word of [...badWords, ...OBSTRUCTION_WORDS]) {
    if (hasKeyword(text, word)) reasons.push(`Rejected by metadata keyword: ${word}`);
  }

  for (const word of ["facade", "façade", "front", "elevation", "exterior", "building", "hall", "library", "center"]) {
    if (text.includes(word)) score += 1;
  }

  const normalizedName = normalizeText(buildingName);
  const normalizedText = normalizeText(text);
  const nameTokens = normalizedName.split(/\W+/).filter((token) => token.length > 2);
  const specificTokens = nameTokens.filter((token) => !GENERIC_NAME_TOKENS.has(token));
  const matchedSpecificTokens = specificTokens.filter((token) => normalizedText.includes(token)).length;
  const hasExactName = normalizedText.includes(normalizedName);

  if (hasExactName) score += 3;
  else if (specificTokens.length && matchedSpecificTokens >= Math.min(2, specificTokens.length)) score += 2;
  else reasons.push("Image metadata does not match the building name closely enough");

  const viewGuess = guessView(text);
  const status = reasons.length ? "invalid" : score >= 5 ? "candidate" : "needs-review";

  if (status !== "invalid") {
    flags.push("Manual obstruction check required");
    flags.push("Approve only if the wall is visible from end to end");
  }

  return {
    status,
    score,
    reasons,
    flags,
    viewGuess,
    label: viewGuess === "candidate" ? "Candidate" : titleCase(viewGuess),
  };
}

function guessView(text) {
  if (text.includes("back") || text.includes("rear")) return "back";
  if (text.includes("left") || text.includes("right") || text.includes("side")) return "side";
  if (text.includes("front") || text.includes("facade") || text.includes("façade") || text.includes("elevation")) return "front";
  return "candidate";
}

function dedupeCandidates(candidates) {
  const seen = new Set();
  return candidates.filter((candidate) => {
    const key = candidate.sourceUrl || candidate.imageUrl;
    if (!key || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function searchPhrases(buildingName) {
  return [
    `${buildingName} Dartmouth College`,
    `${buildingName} Dartmouth`,
    `${buildingName} building`,
    `${buildingName} exterior`,
    `${buildingName} facade`,
  ];
}

function extensionFromUrl(url) {
  const extension = new URL(url).pathname.split(".").pop()?.toLowerCase();
  if (!extension || extension.length > 5) return null;
  return extension === "jpeg" ? "jpg" : extension;
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

function normalizeText(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function hasKeyword(text, keyword) {
  const escaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\\ /g, "\\s+");
  return new RegExp(`(^|[^a-z0-9])${escaped}($|[^a-z0-9])`, "i").test(text);
}
