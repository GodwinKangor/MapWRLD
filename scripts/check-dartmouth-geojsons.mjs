import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const modelDir = path.join(root, "public", "models", "dartmouth-energy-twin");
const reportsDir = path.join(modelDir, "reports");

const sources = {
  buildings: "/Users/godwinkangor/Downloads/darrtmouth buildings.geojson",
  roads: "/Users/godwinkangor/Downloads/roads and paths.geojson",
  sports: "/Users/godwinkangor/Downloads/sports and field.geojson",
};

const osmPath = path.join(reportsDir, "osm-campus-names.json");
const manifestPath = path.join(modelDir, "renders", "parts-manifest.json");
const reportPath = path.join(reportsDir, "geojson-crosscheck.json");

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function osmIdFromFeature(feature) {
  return feature.properties?.["@id"] || "";
}

function osmIdFromExportName(name) {
  const match = name.match(/(way|relation|node)_(\d+)/);
  return match ? `${match[1]}/${match[2]}` : "";
}

function geoLabel(properties = {}) {
  const address = [properties["addr:housenumber"], properties["addr:street"]].filter(Boolean).join(" ");
  return (
    properties.name ||
    properties["addr:housename"] ||
    address ||
    properties.highway ||
    properties.leisure ||
    properties.building ||
    ""
  );
}

function actualGeoLabel(properties = {}) {
  const address = [properties["addr:housenumber"], properties["addr:street"]].filter(Boolean).join(" ");
  return properties.name || properties["addr:housename"] || address || "";
}

function summarizeLayer(name, geojson) {
  const features = geojson.features || [];
  return {
    source: sources[name],
    features: features.length,
    named: features.filter((feature) => feature.properties?.name).length,
    addressed: features.filter(
      (feature) => feature.properties?.["addr:housenumber"] || feature.properties?.["addr:street"],
    ).length,
  };
}

function compareLayer(name, geojson, osmItems, manifestItems) {
  const osmById = new Map(osmItems.map((item) => [item.osmId, item]));
  const manifestIds = new Set(manifestItems.map((item) => osmIdFromExportName(item.name)).filter(Boolean));
  const missingFromFetchedOsm = [];
  const missingFromManifest = [];
  const meaningfulLabelDifferences = [];
  const genericLabelDifferences = [];

  for (const feature of geojson.features || []) {
    const id = osmIdFromFeature(feature);
    const fetched = osmById.get(id);
    if (!fetched) {
      missingFromFetchedOsm.push(id);
    }
    if (!manifestIds.has(id)) {
      missingFromManifest.push(id);
    }

    const label = geoLabel(feature.properties);
    if (fetched && label && fetched.name !== label) {
      const diff = {
        id,
        geojson: label,
        fetched: fetched.name,
      };
      if (actualGeoLabel(feature.properties)) {
        meaningfulLabelDifferences.push(diff);
      } else {
        genericLabelDifferences.push(diff);
      }
    }
  }

  return {
    missingFromFetchedOsm,
    missingFromManifest,
    meaningfulLabelDifferences,
    genericLabelDifferences,
  };
}

const geojson = Object.fromEntries(Object.entries(sources).map(([name, filePath]) => [name, readJson(filePath)]));
const osm = readJson(osmPath);
const manifest = readJson(manifestPath);

const report = {
  generatedAt: new Date().toISOString(),
  layers: {
    buildings: summarizeLayer("buildings", geojson.buildings),
    roads: summarizeLayer("roads", geojson.roads),
    sports: summarizeLayer("sports", geojson.sports),
  },
  comparisons: {
    buildings: compareLayer("buildings", geojson.buildings, osm.buildings, manifest.buildings),
    roads: compareLayer("roads", geojson.roads, osm.roads, manifest.roads),
  },
  sportsLayer: {
    note: "Sports and field features are checked as a separate reference layer; they are not part of the current buildings/roads export contract.",
    featureIds: (geojson.sports.features || []).map(osmIdFromFeature).filter(Boolean),
  },
};

fs.mkdirSync(reportsDir, { recursive: true });
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);

console.log(`Wrote ${path.relative(root, reportPath)}`);
console.log(`Buildings missing from manifest: ${report.comparisons.buildings.missingFromManifest.length}`);
console.log(`Roads missing from manifest: ${report.comparisons.roads.missingFromManifest.length}`);
console.log(`Meaningful building label differences: ${report.comparisons.buildings.meaningfulLabelDifferences.length}`);
console.log(`Meaningful road label differences: ${report.comparisons.roads.meaningfulLabelDifferences.length}`);
console.log(`Generic building label differences: ${report.comparisons.buildings.genericLabelDifferences.length}`);
console.log(`Generic road label differences: ${report.comparisons.roads.genericLabelDifferences.length}`);
