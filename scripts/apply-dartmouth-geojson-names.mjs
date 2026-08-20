import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(__dirname, "..");
const modelDir = path.join(root, "public", "models", "dartmouth-energy-twin");
const reportsDir = path.join(modelDir, "reports");
const osmPath = path.join(reportsDir, "osm-campus-names.json");
const reportPath = path.join(reportsDir, "geojson-name-overrides.json");

const sources = {
  buildings: "/Users/godwinkangor/Downloads/darrtmouth buildings.geojson",
  roads: "/Users/godwinkangor/Downloads/roads and paths.geojson",
};

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function actualLabel(properties = {}) {
  const address = [properties["addr:housenumber"], properties["addr:street"]].filter(Boolean).join(" ");
  return properties.name || properties["addr:housename"] || address || "";
}

const osm = readJson(osmPath);
const overrides = [];

for (const [layer, filePath] of Object.entries(sources)) {
  const geojson = readJson(filePath);
  const items = osm[layer] || [];
  const byId = new Map(items.map((item) => [item.osmId, item]));

  for (const feature of geojson.features || []) {
    const id = feature.properties?.["@id"];
    const label = actualLabel(feature.properties);
    const item = byId.get(id);
    if (!id || !label || !item || item.name === label) {
      continue;
    }

    overrides.push({
      layer,
      osmId: id,
      from: item.name,
      to: label,
      source: filePath,
    });

    item.name = label;
    item.rawName = feature.properties.name || label;
    item.hasRealName = Boolean(feature.properties.name || feature.properties["addr:housename"]);
    item.isAddressOnly = !item.hasRealName;
    item.tags = {
      ...item.tags,
      ...feature.properties,
    };
  }
}

fs.writeFileSync(osmPath, `${JSON.stringify(osm, null, 2)}\n`);
fs.writeFileSync(reportPath, `${JSON.stringify({ generatedAt: new Date().toISOString(), overrides }, null, 2)}\n`);

console.log(`Updated ${path.relative(root, osmPath)}`);
console.log(`Wrote ${path.relative(root, reportPath)}`);
console.log(`Overrides applied: ${overrides.length}`);
for (const override of overrides) {
  console.log(`${override.osmId}: ${override.from} -> ${override.to}`);
}
