// Stylized trees from campus-trees.json (canopy-height treetops), drawn as one GPU-instanced
// glTF: three low-poly tree forms, each instanced thousands of times in a single draw call.

type Vector3 = { x: number; y: number; z: number };
type Cartographic = { longitude: number; latitude: number; height: number };
export type TreeModel = { show: boolean; destroy: () => void };

export type TreeCesiumApi = {
  Cartesian3: { fromDegrees: (longitude: number, latitude: number, height?: number) => Vector3 };
  Cartographic: { fromDegrees: (longitude: number, latitude: number) => Cartographic };
  Transforms: { eastNorthUpToFixedFrame: (origin: Vector3) => unknown };
  Model: { fromGltfAsync: (options: unknown) => Promise<TreeModel> };
  Axis: { X: unknown; Y: unknown };
  sampleTerrainMostDetailed: (provider: unknown, positions: Cartographic[]) => Promise<Cartographic[]>;
};

type TreeViewer = {
  terrainProvider: unknown;
  scene: { primitives: { add: (primitive: unknown) => unknown }; requestRender: () => void };
};

type TreeFile = { trees: [number, number, number, number, 0 | 1][] };

const TREES_URL = "/models/dartmouth-campus/campus-trees.json";
const TRUNK: RGB = [0.36, 0.26, 0.18];
type RGB = [number, number, number];
// broadleaf A, broadleaf B, conifer foliage shades (GTA-style saturated greens)
const FOLIAGE: RGB[][] = [
  [[0.33, 0.55, 0.24], [0.29, 0.5, 0.21], [0.38, 0.6, 0.27]],
  [[0.45, 0.58, 0.22], [0.4, 0.53, 0.2], [0.5, 0.63, 0.26]],
  [[0.16, 0.36, 0.22], [0.13, 0.31, 0.19], [0.19, 0.4, 0.25]],
];

export async function loadCampusTrees(viewer: TreeViewer, Cesium: TreeCesiumApi, isCancelled: () => boolean): Promise<TreeModel | null> {
  const response = await fetch(TREES_URL);
  if (!response.ok || isCancelled()) return null;
  const { trees } = await response.json() as TreeFile;
  if (!trees.length) return null;

  const ground = await Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, trees.map(([lon, lat]) => Cesium.Cartographic.fromDegrees(lon, lat)));
  if (isCancelled()) return null;

  const originLon = trees.reduce((sum, tree) => sum + tree[0], 0) / trees.length;
  const originLat = trees.reduce((sum, tree) => sum + tree[1], 0) / trees.length;
  const metersPerLat = 111_320;
  const metersPerLon = 111_320 * Math.cos((originLat * Math.PI) / 180);

  // glTF frame (Y-up): x = east, y = up, z = south, relative to an ENU frame at the origin
  const groups: { t: number[]; s: number[]; r: number[] }[] = [0, 1, 2].map(() => ({ t: [], s: [], r: [] }));
  trees.forEach(([lon, lat, height, crown, conifer], index) => {
    const terrain = ground[index].height;
    if (!Number.isFinite(terrain)) return;
    const variant = conifer ? 2 : hash(lon, lat) < 0.5 ? 0 : 1;
    const yaw = hash(lat, lon) * Math.PI * 2;
    const group = groups[variant];
    group.t.push((lon - originLon) * metersPerLon, terrain - 0.4, -(lat - originLat) * metersPerLat);
    group.s.push(crown, height, crown);
    group.r.push(0, Math.sin(yaw / 2), 0, Math.cos(yaw / 2));
  });

  const glb = buildInstancedGlb([broadleafMesh(FOLIAGE[0]), broadleafMesh(FOLIAGE[1]), coniferMesh(FOLIAGE[2])], groups);
  const model = await Cesium.Model.fromGltfAsync({
    gltf: glb,
    modelMatrix: Cesium.Transforms.eastNorthUpToFixedFrame(Cesium.Cartesian3.fromDegrees(originLon, originLat, 0)),
    // same axes as the campus GLB: Y-up, and keep +X east (Cesium's glTF default forward axis would turn the layout 90 degrees)
    upAxis: Cesium.Axis.Y,
    forwardAxis: Cesium.Axis.X,
    allowPicking: false,
  });
  if (isCancelled()) { model.destroy(); return null; }
  viewer.scene.primitives.add(model);
  viewer.scene.requestRender();
  return model;
}

function hash(a: number, b: number) {
  const x = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

// ---- unit tree meshes: height 1 (scaled by tree height), crown radius 1 (scaled by crown radius)

type Mesh = { positions: number[]; normals: number[]; colors: number[] };

function addTriangle(mesh: Mesh, a: number[], b: number[], c: number[], color: RGB) {
  const u = [b[0] - a[0], b[1] - a[1], b[2] - a[2]];
  const v = [c[0] - a[0], c[1] - a[1], c[2] - a[2]];
  const n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
  const length = Math.hypot(n[0], n[1], n[2]) || 1;
  for (const p of [a, b, c]) {
    mesh.positions.push(p[0], p[1], p[2]);
    mesh.normals.push(n[0] / length, n[1] / length, n[2] / length);
    mesh.colors.push(...color, 1);
  }
}

function ring(sides: number, radius: number, y: number, twist = 0) {
  return Array.from({ length: sides }, (_, i) => {
    const angle = (i / sides) * Math.PI * 2 + twist;
    return [Math.cos(angle) * radius, y, Math.sin(angle) * radius];
  });
}

function addPrism(mesh: Mesh, sides: number, radius: number, y0: number, y1: number, color: RGB) {
  const bottom = ring(sides, radius, y0);
  const top = ring(sides, radius * 0.8, y1);
  for (let i = 0; i < sides; i += 1) {
    const j = (i + 1) % sides;
    addTriangle(mesh, bottom[i], top[i], bottom[j], color);
    addTriangle(mesh, bottom[j], top[i], top[j], color);
  }
}

function addCone(mesh: Mesh, sides: number, radius: number, y0: number, apex: number, shades: RGB[], twist: number) {
  const base = ring(sides, radius, y0, twist);
  const tip = [0, apex, 0];
  const center = [0, y0, 0];
  for (let i = 0; i < sides; i += 1) {
    const j = (i + 1) % sides;
    addTriangle(mesh, base[i], tip, base[j], shades[i % shades.length]);
    addTriangle(mesh, base[j], center, base[i], shades[1]);
  }
}

// a faceted blob: two offset rings between a bottom and top cap
function broadleafMesh(shades: RGB[]): Mesh {
  const mesh: Mesh = { positions: [], normals: [], colors: [] };
  addPrism(mesh, 5, 0.09, 0, 0.42, TRUNK);
  const sides = 7;
  const bottom = [0, 0.3, 0];
  const top = [0, 1, 0];
  const lower = ring(sides, 0.95, 0.52);
  const upper = ring(sides, 0.8, 0.8, Math.PI / sides);
  for (let i = 0; i < sides; i += 1) {
    const j = (i + 1) % sides;
    const shade = shades[i % shades.length];
    addTriangle(mesh, lower[j], bottom, lower[i], shades[1]);
    addTriangle(mesh, lower[i], upper[i], lower[j], shade);
    addTriangle(mesh, lower[j], upper[i], upper[j], shades[(i + 1) % shades.length]);
    addTriangle(mesh, upper[i], top, upper[j], shades[2]);
  }
  return mesh;
}

function coniferMesh(shades: RGB[]): Mesh {
  const mesh: Mesh = { positions: [], normals: [], colors: [] };
  addPrism(mesh, 5, 0.08, 0, 0.25, TRUNK);
  addCone(mesh, 7, 0.95, 0.18, 0.72, shades, 0);
  addCone(mesh, 7, 0.68, 0.48, 1, shades, Math.PI / 7);
  return mesh;
}

// ---- GLB assembly with EXT_mesh_gpu_instancing

function buildInstancedGlb(meshes: Mesh[], groups: { t: number[]; s: number[]; r: number[] }[]) {
  const chunks: ArrayBuffer[] = [];
  const bufferViews: object[] = [];
  const accessors: object[] = [];
  let offset = 0;
  const push = (data: Float32Array, type: "VEC3" | "VEC4", target?: number, bounds = false) => {
    chunks.push(data.buffer as ArrayBuffer);
    bufferViews.push({ buffer: 0, byteOffset: offset, byteLength: data.byteLength, ...(target ? { target } : {}) });
    offset += data.byteLength;
    const width = type === "VEC3" ? 3 : 4;
    const accessor: Record<string, unknown> = { bufferView: bufferViews.length - 1, componentType: 5126, count: data.length / width, type };
    if (bounds) {
      const min = [Infinity, Infinity, Infinity];
      const max = [-Infinity, -Infinity, -Infinity];
      for (let i = 0; i < data.length; i += 3) for (let k = 0; k < 3; k += 1) { min[k] = Math.min(min[k], data[i + k]); max[k] = Math.max(max[k], data[i + k]); }
      Object.assign(accessor, { min, max });
    }
    accessors.push(accessor);
    return accessors.length - 1;
  };

  const gltfMeshes = meshes.map((mesh) => ({
    primitives: [{
      attributes: {
        POSITION: push(new Float32Array(mesh.positions), "VEC3", 34962, true),
        NORMAL: push(new Float32Array(mesh.normals), "VEC3", 34962),
        COLOR_0: push(new Float32Array(mesh.colors), "VEC4", 34962),
      },
      material: 0,
    }],
  }));
  const nodes = groups.map((group, index) => group.t.length ? {
    mesh: index,
    extensions: {
      EXT_mesh_gpu_instancing: {
        attributes: {
          TRANSLATION: push(new Float32Array(group.t), "VEC3"),
          SCALE: push(new Float32Array(group.s), "VEC3"),
          ROTATION: push(new Float32Array(group.r), "VEC4"),
        },
      },
    },
  } : null).filter(Boolean);

  const json = {
    asset: { version: "2.0", generator: "MapWRLD campus trees" },
    extensionsUsed: ["EXT_mesh_gpu_instancing"],
    extensionsRequired: ["EXT_mesh_gpu_instancing"],
    scene: 0,
    scenes: [{ nodes: nodes.map((_, index) => index) }],
    nodes,
    meshes: gltfMeshes,
    materials: [{ name: "tree", pbrMetallicRoughness: { baseColorFactor: [1, 1, 1, 1], metallicFactor: 0, roughnessFactor: 1 } }],
    accessors,
    bufferViews,
    buffers: [{ byteLength: offset }],
  };

  const jsonBytes = new TextEncoder().encode(JSON.stringify(json));
  const jsonLength = Math.ceil(jsonBytes.length / 4) * 4;
  const binLength = Math.ceil(offset / 4) * 4;
  const glb = new Uint8Array(12 + 8 + jsonLength + 8 + binLength);
  const view = new DataView(glb.buffer);
  view.setUint32(0, 0x46546c67, true);
  view.setUint32(4, 2, true);
  view.setUint32(8, glb.length, true);
  view.setUint32(12, jsonLength, true);
  view.setUint32(16, 0x4e4f534a, true);
  glb.set(jsonBytes, 20);
  glb.fill(0x20, 20 + jsonBytes.length, 20 + jsonLength);
  view.setUint32(20 + jsonLength, binLength, true);
  view.setUint32(24 + jsonLength, 0x004e4942, true);
  let cursor = 28 + jsonLength;
  for (const chunk of chunks) { glb.set(new Uint8Array(chunk), cursor); cursor += chunk.byteLength; }
  return glb;
}
