import { readFile } from "node:fs/promises";
import path from "node:path";
import { buildings as staticBuildings, type Building } from "@/data/buildings";

const OSM_NAMES_PATH = path.join(
  process.cwd(),
  "public",
  "models",
  "dartmouth-energy-twin",
  "reports",
  "osm-campus-names.json",
);

// These OSM ways are the same physical buildings as the 6 hand-authored
// entries in data/buildings.ts (Baker-Berry is two connected buildings) --
// excluded so the generated placeholders don't duplicate them on the map.
const CURATED_OSM_IDS: Record<string, string> = {
  "way/295888783": "baker-berry", // Baker Library
  "way/295888784": "baker-berry", // Berry Library
  "way/262924499": "hopkins", // Hopkins Center for the Arts
  "way/261796580": "collis", // Collis Student Center
  "way/262912597": "foco", // Class of 1953 Commons
  "way/48784540": "dartmouth-hall", // Dartmouth Hall
  "way/262950856": "life-sciences", // Class of 1978 Life Sciences Center
};

// the OSM ways (and campus-model buildings) behind each hand-authored entry, for 3D picking
const curatedOsmIds = (id: string) => Object.entries(CURATED_OSM_IDS).filter(([, curated]) => curated === id).map(([osmId]) => osmId);

const CATEGORY_BY_BUILDING_TAG: Record<string, string> = {
  university: "Study",
  school: "Study",
  college: "Study",
  dormitory: "Residential",
  apartments: "Residential",
  fraternity: "Residential",
  house: "Residential",
  semidetached_house: "Residential",
  cabin: "Residential",
  church: "History",
  chapel: "History",
  retail: "Campus life",
  commercial: "Campus life",
  office: "Campus life",
};
const DEFAULT_CATEGORY = "Campus building";

type OsmBuildingRecord = {
  osmId: string;
  wayId: number;
  name: string;
  tags?: Record<string, string>;
  centroid?: { longitude: number; latitude: number };
};

type CampusBounds = { west: number; south: number; east: number; north: number };

let cachedPlaceholders: Building[] | null = null;

export async function getAllBuildings(): Promise<Building[]> {
  return [...staticBuildings.map((building) => ({ ...building, osmIds: curatedOsmIds(building.id) })), ...(await getPlaceholderBuildings())];
}

async function getPlaceholderBuildings(): Promise<Building[]> {
  if (cachedPlaceholders) return cachedPlaceholders;
  try {
    const raw = await readFile(OSM_NAMES_PATH, "utf8");
    const parsed = JSON.parse(raw) as { bounds?: CampusBounds; buildings?: OsmBuildingRecord[] };
    // The map world is the campus rectangle; ways that only clip its edge stay outside it.
    const inside = (record: OsmBuildingRecord) => !parsed.bounds || (
      record.centroid!.longitude >= parsed.bounds.west && record.centroid!.longitude <= parsed.bounds.east &&
      record.centroid!.latitude >= parsed.bounds.south && record.centroid!.latitude <= parsed.bounds.north
    );
    cachedPlaceholders = (parsed.buildings ?? [])
      .filter((record) => !CURATED_OSM_IDS[record.osmId] && record.centroid && inside(record))
      .map(toPlaceholderBuilding);
  } catch (error) {
    console.error("Could not load osm-campus-names.json for placeholder buildings.", error);
    cachedPlaceholders = [];
  }
  return cachedPlaceholders;
}

function toPlaceholderBuilding(record: OsmBuildingRecord): Building {
  const centroid = record.centroid!;
  const category = CATEGORY_BY_BUILDING_TAG[record.tags?.building ?? ""] ?? DEFAULT_CATEGORY;
  const coordinates: [number, number] = [centroid.longitude, centroid.latitude];
  const entrance = {
    id: "centroid",
    coordinates,
    approach: coordinates,
    heading: 0,
    label: "Building location (approximate)",
    kind: "main" as const,
  };

  return {
    id: `${slugify(record.name)}-${record.wayId}`,
    osmIds: [record.osmId],
    name: record.name,
    shortCode: shortCodeFor(record.name),
    category,
    subtitle: "Campus building",
    description: "Part of the Dartmouth campus. A detailed energy and building profile hasn't been captured yet.",
    coordinates,
    entrance,
    open: true,
    hours: "Hours not tracked",
    imageClass: "placeholder",
    features: [],
    gallery: [],
    energy: {
      useType: category,
      system: "Not yet assessed",
      demandKw: 0,
      annualMwh: 0,
      emissions: "Medium",
      retrofit: "Not yet assessed",
      score: 0,
    },
    assetStatus: {
      modelStatus: "Queued",
      meterStatus: "Missing",
      dataQuality: "Draft",
      priority: "Low",
      lastInspection: "Not yet scheduled",
      nextStep: "Generate references and model this building",
    },
  };
}

function slugify(value: string): string {
  return (
    value
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "building"
  );
}

function shortCodeFor(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((word) => word[0]?.toUpperCase())
      .join("") || "OSM"
  );
}
