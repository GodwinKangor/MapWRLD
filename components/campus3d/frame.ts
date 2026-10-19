// The campus scene's coordinate frame and terrain sampling.
// Local meters: x east, y up (elevation - baseElevation), z south, from the campus GLB's
// calibrated origin. Longitude/latitude map linearly onto x/z, matching the GLB export.

import type { LonLat } from "@/data/campus-layers";

export const ASSET_ROOT = "/models/dartmouth-campus";

export type TerrainMeta = {
  bounds: { west: number; south: number; east: number; north: number };
  frame: { origin: { longitude: number; latitude: number }; georeference: { longitudePerMeter: number; latitudePerMeter: number } };
  grid: { cols: number; rows: number; baseElevation: number; minElevation: number; maxElevation: number };
  imagery: { file: string; mobileFile: string; width: number; height: number };
  files: Record<string, string>;
  attribution: { layer: string; text: string; license: string }[];
  approximations: string[];
};

export class CampusFrame {
  readonly heights: Float32Array; // meters above baseElevation, row 0 = north
  readonly minX: number;
  readonly maxX: number;
  readonly minZ: number;
  readonly maxZ: number;

  constructor(readonly meta: TerrainMeta, encoded: Uint16Array) {
    this.heights = new Float32Array(encoded.length);
    for (let i = 0; i < encoded.length; i += 1) this.heights[i] = encoded[i] / 100;
    const { west, east, north, south } = meta.bounds;
    this.minX = this.x(west);
    this.maxX = this.x(east);
    this.minZ = this.z(north);
    this.maxZ = this.z(south);
  }

  x(longitude: number) {
    return (longitude - this.meta.frame.origin.longitude) / this.meta.frame.georeference.longitudePerMeter;
  }

  z(latitude: number) {
    return (this.meta.frame.origin.latitude - latitude) / this.meta.frame.georeference.latitudePerMeter;
  }

  toLocal([longitude, latitude]: LonLat): [number, number] {
    return [this.x(longitude), this.z(latitude)];
  }

  toLonLat(x: number, z: number): LonLat {
    const { origin, georeference } = this.meta.frame;
    return [origin.longitude + x * georeference.longitudePerMeter, origin.latitude - z * georeference.latitudePerMeter];
  }

  /** elevation (NAVD88 m) to scene y */
  y(elevation: number) {
    return elevation - this.meta.grid.baseElevation;
  }

  /** bilinear terrain height (scene y) at local x/z, clamped to the campus edge */
  ground(x: number, z: number) {
    const { cols, rows } = this.meta.grid;
    const u = clamp((x - this.minX) / (this.maxX - this.minX), 0, 1) * (cols - 1);
    const v = clamp((z - this.minZ) / (this.maxZ - this.minZ), 0, 1) * (rows - 1);
    const c0 = Math.min(cols - 2, Math.floor(u));
    const r0 = Math.min(rows - 2, Math.floor(v));
    const fu = u - c0;
    const fv = v - r0;
    const h = this.heights;
    const i = r0 * cols + c0;
    return (h[i] * (1 - fu) + h[i + 1] * fu) * (1 - fv) + (h[i + cols] * (1 - fu) + h[i + cols + 1] * fu) * fv;
  }

  inside(x: number, z: number) {
    return x >= this.minX && x <= this.maxX && z >= this.minZ && z <= this.maxZ;
  }

  clampX(x: number) {
    return clamp(x, this.minX, this.maxX);
  }

  clampZ(z: number) {
    return clamp(z, this.minZ, this.maxZ);
  }

  /** texture coordinates over the campus rectangle (u east, v south) */
  uv(x: number, z: number): [number, number] {
    return [(x - this.minX) / (this.maxX - this.minX), (z - this.minZ) / (this.maxZ - this.minZ)];
  }
}

export function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

export async function loadFrame(signal: AbortSignal) {
  const meta = await fetchJson<TerrainMeta>(`${ASSET_ROOT}/terrain/campus-terrain.json`, signal);
  const response = await fetch(versioned(`${ASSET_ROOT}/terrain/campus-terrain.bin`, meta, "campus-terrain.bin"), { signal });
  if (!response.ok) throw new Error(`Terrain heights unavailable (${response.status})`);
  return new CampusFrame(meta, new Uint16Array(await response.arrayBuffer()));
}

export async function fetchJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { signal });
  if (!response.ok) throw new Error(`${url} returned ${response.status}`);
  return await response.json() as T;
}

/** cache-busting query from the build-time content hash, so long-lived caching stays safe */
export function versioned(url: string, meta: TerrainMeta, file: string) {
  const hash = meta.files[file];
  return hash ? `${url}?v=${hash}` : url;
}
