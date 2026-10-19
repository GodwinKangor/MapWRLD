// Fetches OSM sports fields, tracks, lawns and parks for the campus rectangle, clipped to it,
// and derives each area's orientation (minimum bounding rectangle) plus sport line markings.
// The map drapes these onto the terrain under the roads (see loadCampusGround in campus-map.tsx).
import { mkdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";

const root = process.cwd();
const namesPath = path.join(root, "public", "models", "dartmouth-energy-twin", "reports", "osm-campus-names.json");
const outPath = path.join(root, "public", "models", "dartmouth-campus", "campus-fields.json");
const { bounds } = JSON.parse(await readFile(namesPath, "utf8"));
const box = `${bounds.south},${bounds.west},${bounds.north},${bounds.east}`;

const osm = await fetchQuery(`
  [out:json][timeout:90];
  (
    way["leisure"~"^(pitch|track|park|garden|recreation_ground|golf_course|playground)$"](${box});
    relation["leisure"~"^(pitch|track|park|garden|recreation_ground|golf_course)$"](${box});
    way["landuse"~"^(grass|recreation_ground|meadow|village_green)$"](${box});
    relation["landuse"~"^(grass|recreation_ground|meadow|village_green)$"](${box});
  );
  out geom;
`);

const fields = [];
for (const element of osm.elements ?? []) {
  const tags = element.tags ?? {};
  const kind = classify(tags);
  if (!kind) continue;
  let outers = [];
  let inners = [];
  if (element.type === "way") {
    if (!isClosed(element.geometry)) continue; // a running track drawn as a centerline, not an area
    outers = [element.geometry.map(({ lon, lat }) => [lon, lat])];
  } else {
    outers = assembleRings(element.members.filter((m) => m.type === "way" && m.role !== "inner"));
    inners = assembleRings(element.members.filter((m) => m.type === "way" && m.role === "inner"));
  }
  for (const outer of outers) {
    const clipped = clipPolygon(outer, bounds);
    if (clipped.length < 3) continue;
    const holes = inners.filter((ring) => insideRing(ring[0], outer)).map((ring) => clipPolygon(ring, bounds)).filter((ring) => ring.length >= 3);
    const frame = orientedRectangle(clipped);
    fields.push({
      osmId: `${element.type}/${element.id}`,
      name: tags.name ?? "",
      kind,
      sport: tags.sport ?? "",
      surface: tags.surface ?? "",
      // long axis, counter-clockwise from east, and the rectangle's size in meters
      axisRadians: Math.round(frame.angle * 1e4) / 1e4,
      lengthMeters: Math.round(frame.length * 10) / 10,
      widthMeters: Math.round(frame.width * 10) / 10,
      outer: clipped.map(roundPoint),
      holes: holes.map((ring) => ring.map(roundPoint)),
      markings: markingsFor(kind, tags.sport ?? "", frame, clipped, holes).map((line) => line.map(roundPoint)),
    });
  }
}

// largest first, so small areas (courts on a lawn, a pitch inside a park) draw on top
fields.sort((a, b) => area(b.outer) - area(a.outer));
await mkdir(path.dirname(outPath), { recursive: true });
await writeFile(outPath, `${JSON.stringify({ generatedAt: new Date().toISOString(), source: "OpenStreetMap Overpass API", bounds, fields })}\n`);
const counts = fields.reduce((all, field) => ({ ...all, [field.kind]: (all[field.kind] ?? 0) + 1 }), {});
console.log(`Wrote ${fields.length} field areas ${JSON.stringify(counts)} to ${path.relative(root, outPath)}`);

function classify(tags) {
  const leisure = tags.leisure;
  const sport = tags.sport ?? "";
  if (leisure === "track" || /athletics|running/.test(sport)) return "track";
  if (leisure === "pitch") {
    if (/tennis|pickleball/.test(sport)) return "court";
    if (/basketball|volleyball|handball/.test(sport) || /asphalt|concrete/.test(tags.surface ?? "")) return "hardcourt";
    if (/baseball|softball/.test(sport)) return "diamond";
    return "pitch";
  }
  if (leisure === "golf_course") return "lawn";
  if (leisure === "playground") return "playground";
  if (["park", "garden", "recreation_ground"].includes(leisure)) return "park";
  if (["grass", "meadow", "village_green", "recreation_ground"].includes(tags.landuse)) return "lawn";
  return null;
}

function isClosed(geometry) {
  if (!geometry || geometry.length < 4) return false;
  const first = geometry[0];
  const last = geometry[geometry.length - 1];
  return first.lon === last.lon && first.lat === last.lat;
}

// join relation member ways end-to-end into closed rings
function assembleRings(members) {
  const pieces = members.map((m) => (m.geometry ?? []).map(({ lon, lat }) => [lon, lat])).filter((p) => p.length > 1);
  const rings = [];
  const same = (a, b) => a[0] === b[0] && a[1] === b[1];
  while (pieces.length) {
    let ring = pieces.shift();
    let extended = true;
    while (!same(ring[0], ring[ring.length - 1]) && extended) {
      extended = false;
      for (let i = 0; i < pieces.length; i += 1) {
        const piece = pieces[i];
        const end = ring[ring.length - 1];
        if (same(piece[0], end)) ring = ring.concat(piece.slice(1));
        else if (same(piece[piece.length - 1], end)) ring = ring.concat(piece.slice(0, -1).reverse());
        else continue;
        pieces.splice(i, 1);
        extended = true;
        break;
      }
    }
    if (ring.length >= 4 && same(ring[0], ring[ring.length - 1])) rings.push(ring);
  }
  return rings;
}

// Sutherland-Hodgman against the campus rectangle; returns an open ring
function clipPolygon(ring, b) {
  let points = same(ring[0], ring[ring.length - 1]) ? ring.slice(0, -1) : ring.slice();
  const edges = [
    [(p) => p[0] >= b.west, (p, q) => cross(p, q, 0, b.west)],
    [(p) => p[0] <= b.east, (p, q) => cross(p, q, 0, b.east)],
    [(p) => p[1] >= b.south, (p, q) => cross(p, q, 1, b.south)],
    [(p) => p[1] <= b.north, (p, q) => cross(p, q, 1, b.north)],
  ];
  for (const [inside, intersect] of edges) {
    const input = points;
    points = [];
    for (let i = 0; i < input.length; i += 1) {
      const current = input[i];
      const previous = input[(i + input.length - 1) % input.length];
      if (inside(current)) {
        if (!inside(previous)) points.push(intersect(previous, current));
        points.push(current);
      } else if (inside(previous)) {
        points.push(intersect(previous, current));
      }
    }
    if (!points.length) break;
  }
  return points;
  function same(p, q) { return p[0] === q[0] && p[1] === q[1]; }
  function cross(p, q, axis, value) {
    const t = (value - p[axis]) / (q[axis] - p[axis]);
    return axis === 0 ? [value, p[1] + t * (q[1] - p[1])] : [p[0] + t * (q[0] - p[0]), value];
  }
}

function insideRing([x, y], ring) {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

function area(ring) {
  let sum = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    sum += x1 * y2 - x2 * y1;
  }
  return Math.abs(sum) / 2;
}

// ---- orientation: minimum-area bounding rectangle in local meters (rotating calipers over the hull)

function orientedRectangle(ring) {
  const lon0 = ring.reduce((sum, p) => sum + p[0], 0) / ring.length;
  const lat0 = ring.reduce((sum, p) => sum + p[1], 0) / ring.length;
  const mx = 111_320 * Math.cos((lat0 * Math.PI) / 180);
  const my = 110_574;
  const points = ring.map(([lon, lat]) => [(lon - lon0) * mx, (lat - lat0) * my]);
  const hull = convexHull(points);
  let best = null;
  for (let i = 0; i < hull.length; i += 1) {
    const [x1, y1] = hull[i];
    const [x2, y2] = hull[(i + 1) % hull.length];
    const angle = Math.atan2(y2 - y1, x2 - x1);
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    let minU = Infinity, maxU = -Infinity, minV = Infinity, maxV = -Infinity;
    for (const [x, y] of hull) {
      const u = x * cos + y * sin;
      const v = -x * sin + y * cos;
      minU = Math.min(minU, u); maxU = Math.max(maxU, u); minV = Math.min(minV, v); maxV = Math.max(maxV, v);
    }
    const area = (maxU - minU) * (maxV - minV);
    if (!best || area < best.area) best = { area, angle, minU, maxU, minV, maxV };
  }
  let { angle } = best;
  let length = best.maxU - best.minU;
  let width = best.maxV - best.minV;
  const cu = (best.minU + best.maxU) / 2;
  const cv = (best.minV + best.maxV) / 2;
  const cx = cu * Math.cos(angle) - cv * Math.sin(angle);
  const cy = cu * Math.sin(angle) + cv * Math.cos(angle);
  if (width > length) { [length, width] = [width, length]; angle += Math.PI / 2; }
  angle = ((angle % Math.PI) + Math.PI) % Math.PI; // a field's axis has no direction
  // field-local (u along the length, v across it, meters from the center) -> lon/lat
  const toLonLat = ([u, v]) => {
    const x = cx + u * Math.cos(angle) - v * Math.sin(angle);
    const y = cy + u * Math.sin(angle) + v * Math.cos(angle);
    return [lon0 + x / mx, lat0 + y / my];
  };
  return { angle, length, width, toLonLat };
}

function convexHull(points) {
  const sorted = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const half = (list) => {
    const out = [];
    for (const p of list) {
      while (out.length >= 2 && cross(out[out.length - 2], out[out.length - 1], p) <= 0) out.pop();
      out.push(p);
    }
    out.pop();
    return out;
  };
  return [...half(sorted), ...half([...sorted].reverse())];
}

// ---- line markings, laid out in field-local meters and scaled down for undersized fields

function markingsFor(kind, sport, frame, outer, holes) {
  const { length: L, width: W, toLonLat } = frame;
  const lines = [];
  const line = (...points) => lines.push(points.map(toLonLat));
  const rect = (u0, v0, u1, v1) => line([u0, v0], [u1, v0], [u1, v1], [u0, v1], [u0, v0]);
  const circle = (u, v, r, segments = 28) => line(...Array.from({ length: segments + 1 }, (_, i) => [u + r * Math.cos((i / segments) * 2 * Math.PI), v + r * Math.sin((i / segments) * 2 * Math.PI)]));

  if (kind === "track") {
    // the area's own edges: outer lane line and infield curb
    return [outer, ...holes].map((ring) => [...ring, ring[0]]);
  }
  if (kind === "pitch" && L >= 40) {
    const inset = 1.5;
    const hl = L / 2 - inset;
    const hw = W / 2 - inset;
    rect(-hl, -hw, hl, hw);
    if (/american_football/.test(sport)) {
      const zone = Math.min(9.14, hl * 0.09);
      line([-hl + zone, -hw], [-hl + zone, hw]);
      line([hl - zone, -hw], [hl - zone, hw]);
      const spacing = (2 * (hl - zone)) / 20; // 5-yard lines across the 100-yard field
      for (let i = 1; i < 20; i += 1) line([-hl + zone + i * spacing, -hw], [-hl + zone + i * spacing, hw]);
      return lines;
    }
    const s = Math.min(1, (2 * hl) / 105);
    line([0, -hw], [0, hw]);
    circle(0, 0, 9.15 * s);
    for (const end of [-1, 1]) {
      const goal = end * hl;
      const box = (depth, half) => line([goal, -half], [goal - end * depth, -half], [goal - end * depth, half], [goal, half]);
      box(16.5 * s, Math.min(20.16 * s, hw - 1));
      box(5.5 * s, Math.min(9.16 * s, hw - 2));
    }
    return lines;
  }
  if (kind === "court") {
    // OSM often maps a bank of courts as one area: split it into side-by-side courts
    const courtLength = 23.77;
    const courtWidth = 10.97;
    const alongLength = L >= 30 && W < 30;          // one row of courts lying along the long side
    const lengthAxis = alongLength && W >= 14 && L < 45;
    const count = lengthAxis ? 1 : Math.max(1, Math.round((alongLength ? L : W) / 18.3));
    const cell = (lengthAxis ? W : alongLength ? L : W) / count;
    for (let i = 0; i < count; i += 1) {
      const offset = -((count - 1) / 2) * cell + i * cell;
      // court-local (along, across) -> field-local (u, v)
      const place = lengthAxis || !alongLength ? (a, c) => [a, c + offset] : (a, c) => [c + offset, a];
      const hl = Math.min(courtLength / 2, (lengthAxis || !alongLength ? L : W) / 2 - 0.3);
      const hw = Math.min(courtWidth / 2, cell / 2 - 0.3);
      if (hl <= 2 || hw <= 2) continue;
      const singles = hw * (8.23 / 10.97);
      const service = hl * (6.4 / 11.885);
      const add = (...points) => lines.push(points.map((p) => toLonLat(place(...p))));
      add([-hl, -hw], [hl, -hw], [hl, hw], [-hl, hw], [-hl, -hw]);
      add([-hl, -singles], [hl, -singles]);
      add([-hl, singles], [hl, singles]);
      add([0, -hw], [0, hw]);
      add([-service, -singles], [-service, singles]);
      add([service, -singles], [service, singles]);
      add([-service, 0], [service, 0]);
    }
    return lines;
  }
  if (kind === "hardcourt" && /basketball/.test(sport)) {
    const hl = Math.min(14, L / 2 - 1);
    const hw = Math.min(7.5, W / 2 - 1);
    if (hl > 4 && hw > 3) {
      rect(-hl, -hw, hl, hw);
      line([0, -hw], [0, hw]);
      circle(0, 0, 1.8, 20);
      for (const end of [-1, 1]) rect(end * hl, -2.45, end * (hl - 5.8), 2.45);
    }
    return lines;
  }
  return lines;
}

function roundPoint([lon, lat]) {
  return [Math.round(lon * 1e7) / 1e7, Math.round(lat * 1e7) / 1e7];
}

async function fetchQuery(query) {
  const endpoints = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter", "https://overpass.kumi.systems/api/interpreter"];
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    for (const endpoint of endpoints) {
      try {
        const response = await fetch(endpoint, {
          method: "POST",
          headers: { "Content-Type": "application/x-www-form-urlencoded", "User-Agent": "MapWRLD campus field fetch" },
          body: new URLSearchParams({ data: query }),
          signal: AbortSignal.timeout(120_000),
        });
        if (response.ok) {
          // mirrors can lag the main server; say which one answered so a short result is explainable
          console.log("Overpass data from", endpoint);
          return await response.json();
        }
        lastError = new Error(`${endpoint} returned ${response.status}`);
      } catch (error) {
        lastError = error;
      }
      console.warn("Overpass attempt failed:", endpoint, lastError?.message);
    }
  }
  throw lastError;
}
