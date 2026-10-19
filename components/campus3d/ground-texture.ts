// Paints the ground layers (imagery, lawns and fields, paths, roads, energy network, boundary)
// into one canvas that textures the terrain mesh. Draping is exact because the canvas and the
// terrain share the campus rectangle, and every layer costs zero extra draw calls.

import { ELECTRIC_CONNECTIONS, ENERGY_GRAPH, HEATING_CONNECTIONS, HEATING_TRUNK_COUNT, type LonLat } from "@/data/campus-layers";
import type { CampusFrame } from "./frame";

export type CampusField = {
  osmId: string;
  name: string;
  kind: string;
  axisRadians: number;
  lengthMeters: number;
  outer: LonLat[];
  holes: LonLat[][];
  markings: LonLat[][];
};

export type CampusRoad = { osmId: string; highway: string; coordinates: LonLat[] };

export type GroundLayers = { fields: boolean; roads: boolean; energyNetwork: boolean; heating: boolean; electric: boolean; boundary: boolean };

// width in meters and fill color per OSM highway class; anything unlisted is drawn as a service road
const ROAD_STYLES: Record<string, { width: number; color: string; path?: boolean }> = {
  primary: { width: 12, color: "#2e3338" },
  secondary: { width: 10, color: "#33383d" },
  tertiary: { width: 9, color: "#363b40" },
  residential: { width: 7, color: "#3f4549" },
  unclassified: { width: 7, color: "#3f4549" },
  service: { width: 4.5, color: "#4d5154" },
  track: { width: 3, color: "#7a6b54", path: true },
  footway: { width: 2.2, color: "#dbd1b8", path: true },
  path: { width: 2, color: "#ccbd99", path: true },
  pedestrian: { width: 4, color: "#e0d6bd", path: true },
  cycleway: { width: 2.2, color: "#9ec7a8", path: true },
  steps: { width: 2, color: "#bdb39e", path: true },
};

// mowing stripes (light, dark, stripe width in meters) and flat fills for other surfaces
const STRIPED: Record<string, { even: string; odd: string; meters: number }> = {
  lawn: { even: "#86b85f", odd: "#78a853", meters: 8 },
  park: { even: "#7cb058", odd: "#6fa04d", meters: 8 },
  pitch: { even: "#55a84a", odd: "#46923d", meters: 5.5 },
};
const FILLS: Record<string, string> = {
  diamond: "#5ca14a",
  court: "#3d8c7d",
  hardcourt: "#9c8f85",
  track: "#ba5440",
  playground: "#c9a86b",
};
const DRAW_ORDER = ["lawn", "park", "pitch", "diamond", "court", "hardcourt", "track", "playground"];

export class GroundPainter {
  readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly pixelsPerMeter: number;

  constructor(private readonly frame: CampusFrame, private readonly imagery: CanvasImageSource, width: number, height: number) {
    this.canvas = document.createElement("canvas");
    this.canvas.width = width;
    this.canvas.height = height;
    this.ctx = this.canvas.getContext("2d")!;
    this.pixelsPerMeter = width / (frame.maxX - frame.minX);
  }

  paint(layers: GroundLayers, fields: CampusField[], roads: CampusRoad[], season = "Fall") {
    const { ctx, canvas } = this;
    ctx.save();
    ctx.filter = "saturate(0.92) brightness(0.97)";
    ctx.drawImage(this.imagery, 0, 0, canvas.width, canvas.height);
    ctx.restore();
    if (layers.fields) this.paintFields(fields);
    if (season === "Winter") {
      // the imagery is an autumn capture; a light snow wash under the plowed roads and paths
      ctx.fillStyle = "rgba(236, 241, 246, 0.45)";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }
    if (layers.roads) {
      this.paintRoads(roads.filter((road) => (ROAD_STYLES[road.highway] ?? ROAD_STYLES.service).path));
      this.paintRoads(roads.filter((road) => !(ROAD_STYLES[road.highway] ?? ROAD_STYLES.service).path));
    }
    if (layers.energyNetwork) this.paintEnergy(layers);
    if (layers.boundary) {
      ctx.strokeStyle = "#c7ff66";
      ctx.lineWidth = Math.max(4, 3 * this.pixelsPerMeter);
      ctx.strokeRect(0, 0, canvas.width, canvas.height);
    }
  }

  private px([longitude, latitude]: LonLat): [number, number] {
    const [u, v] = this.frame.uv(this.frame.x(longitude), this.frame.z(latitude));
    return [u * this.canvas.width, v * this.canvas.height];
  }

  private trace(ring: LonLat[]) {
    ring.forEach((point, index) => {
      const [x, y] = this.px(point);
      if (index === 0) this.ctx.moveTo(x, y); else this.ctx.lineTo(x, y);
    });
    this.ctx.closePath();
  }

  private paintFields(fields: CampusField[]) {
    const { ctx } = this;
    const ordered = [...fields].sort((a, b) => DRAW_ORDER.indexOf(a.kind) - DRAW_ORDER.indexOf(b.kind));
    for (const field of ordered) {
      if (field.outer.length < 3) continue;
      ctx.save();
      ctx.beginPath();
      this.trace(field.outer);
      field.holes.forEach((hole) => this.trace(hole));
      const stripes = STRIPED[field.kind];
      if (stripes) {
        ctx.clip("evenodd");
        const [cx, cy] = this.px(centroid(field.outer));
        const reach = (field.lengthMeters + 40) * this.pixelsPerMeter;
        const band = stripes.meters * this.pixelsPerMeter;
        ctx.translate(cx, cy);
        ctx.rotate(-field.axisRadians); // world angle is counter-clockwise from east; canvas y points south
        for (let x = -reach, i = 0; x < reach; x += band, i += 1) {
          ctx.fillStyle = i % 2 ? stripes.odd : stripes.even;
          ctx.fillRect(x, -reach, band + 0.5, 2 * reach);
        }
      } else if (FILLS[field.kind]) {
        ctx.fillStyle = FILLS[field.kind];
        ctx.fill("evenodd");
      }
      ctx.restore();
    }
    ctx.save();
    ctx.strokeStyle = "rgba(248, 248, 238, 0.95)";
    ctx.lineWidth = Math.max(1.2, 0.5 * this.pixelsPerMeter);
    ctx.lineJoin = "miter";
    for (const field of fields) {
      for (const line of field.markings) {
        if (line.length < 2) continue;
        ctx.beginPath();
        line.forEach((point, index) => { const [x, y] = this.px(point); if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  private paintRoads(roads: CampusRoad[]) {
    const { ctx } = this;
    ctx.save();
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    for (const road of roads) {
      const style = ROAD_STYLES[road.highway] ?? ROAD_STYLES.service;
      if (road.coordinates.length < 2) continue;
      ctx.strokeStyle = style.color;
      ctx.lineWidth = Math.max(1, style.width * this.pixelsPerMeter);
      ctx.beginPath();
      road.coordinates.forEach((point, index) => { const [x, y] = this.px(point); if (index) ctx.lineTo(x, y); else ctx.moveTo(x, y); });
      ctx.stroke();
    }
    ctx.restore();
  }

  private paintEnergy(layers: GroundLayers) {
    const { ctx } = this;
    const m = this.pixelsPerMeter;
    const segment = ([a, b]: [LonLat, LonLat], width: number, color: string) => {
      const [x1, y1] = this.px(a);
      const [x2, y2] = this.px(b);
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.lineTo(x2, y2);
      ctx.stroke();
    };
    ctx.save();
    ctx.lineCap = "round";
    if (layers.electric) ELECTRIC_CONNECTIONS.forEach((link) => segment(link, 2.5 * m, "rgba(82, 184, 255, 0.9)"));
    if (layers.heating) {
      HEATING_CONNECTIONS.forEach((link, index) => segment(link, (index < HEATING_TRUNK_COUNT ? 5 : 3.5) * m, index < HEATING_TRUNK_COUNT ? "rgba(245, 89, 43, 0.92)" : "rgba(199, 255, 102, 0.88)"));
      Object.entries(ENERGY_GRAPH).forEach(([name, point]) => {
        const [x, y] = this.px(point);
        ctx.fillStyle = "rgba(245, 89, 43, 0.97)";
        ctx.strokeStyle = "rgba(250, 255, 184, 0.97)";
        ctx.lineWidth = 1.5 * m;
        ctx.beginPath();
        ctx.arc(x, y, (name === "hub" ? 7 : 5) * m, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      });
    }
    ctx.restore();
  }
}

function centroid(ring: LonLat[]): LonLat {
  const sum = ring.reduce((acc, [x, y]) => [acc[0] + x, acc[1] + y], [0, 0]);
  return [sum[0] / ring.length, sum[1] / ring.length];
}
