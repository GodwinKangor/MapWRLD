// Canopy-height trees (campus-trees.json) as three instanced low-poly forms: two broadleaf
// color variants and a conifer, one draw call each. Per-instance colors carry the season.

import * as THREE from "three";
import type { CampusFrame } from "./frame";

type TreeRecord = [number, number, number, number, 0 | 1]; // lon, lat, height m, crown radius m, conifer
type RGB = [number, number, number];
export type Season = "Spring" | "Summer" | "Fall" | "Winter";

const TRUNK: RGB = [0.36, 0.26, 0.18];
const FOLIAGE: RGB[][] = [
  [[0.33, 0.55, 0.24], [0.29, 0.5, 0.21], [0.38, 0.6, 0.27]],
  [[0.45, 0.58, 0.22], [0.4, 0.53, 0.2], [0.5, 0.63, 0.26]],
  [[0.16, 0.36, 0.22], [0.13, 0.31, 0.19], [0.19, 0.4, 0.25]],
];
// multiplied into the vertex colors per instance; conifers keep their needles
const SEASON_TINTS: Record<Season, { broadleaf: string[]; conifer: string }> = {
  Spring: { broadleaf: ["#c8f0a8", "#d8f5b5", "#bfe89c"], conifer: "#ffffff" },
  Summer: { broadleaf: ["#ffffff", "#f2f7ee", "#e8f0e2"], conifer: "#ffffff" },
  Fall: { broadleaf: ["#ffb347", "#ff8c42", "#e8c547", "#d9643a", "#ffffff"], conifer: "#f2f2f2" },
  Winter: { broadleaf: ["#8c7a6b", "#9a8a7c", "#7f7064"], conifer: "#c9d6cf" },
};

export class CampusTrees {
  readonly group = new THREE.Group();
  private readonly meshes: THREE.InstancedMesh[] = [];
  private readonly variants: number[][] = [[], [], []]; // tree record index per instance, per form

  constructor(private readonly trees: TreeRecord[], frame: CampusFrame) {
    this.group.name = "campus-trees";
    const geometries = [broadleaf(FOLIAGE[0]), broadleaf(FOLIAGE[1]), conifer(FOLIAGE[2])];
    trees.forEach(([lon, lat, , , isConifer], index) => {
      this.variants[isConifer ? 2 : hash(lon, lat) < 0.5 ? 0 : 1].push(index);
    });
    const material = new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true });
    const matrix = new THREE.Matrix4();
    const rotation = new THREE.Quaternion();
    const up = new THREE.Vector3(0, 1, 0);
    geometries.forEach((geometry, form) => {
      const ids = this.variants[form];
      const mesh = new THREE.InstancedMesh(geometry, form === 0 ? material : material, ids.length);
      ids.forEach((treeIndex, instance) => {
        const [lon, lat, height, crown] = trees[treeIndex];
        const [x, z] = frame.toLocal([lon, lat]);
        rotation.setFromAxisAngle(up, hash(lat, lon) * Math.PI * 2);
        matrix.compose(new THREE.Vector3(x, frame.ground(x, z) - 0.4, z), rotation, new THREE.Vector3(crown, height, crown));
        mesh.setMatrixAt(instance, matrix);
      });
      mesh.instanceMatrix.needsUpdate = true;
      mesh.computeBoundingSphere();
      mesh.frustumCulled = true;
      this.meshes.push(mesh);
      this.group.add(mesh);
    });
    this.setSeason("Fall");
  }

  get count() {
    return this.trees.length;
  }

  setSeason(season: Season) {
    const tints = SEASON_TINTS[season];
    const color = new THREE.Color();
    this.meshes.forEach((mesh, form) => {
      this.variants[form].forEach((treeIndex, instance) => {
        const [lon, lat] = this.trees[treeIndex];
        const options = form === 2 ? [tints.conifer] : tints.broadleaf;
        color.set(options[Math.floor(hash(lon * 3.1, lat * 1.7) * options.length) % options.length]);
        mesh.setColorAt(instance, color);
      });
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    });
  }

  dispose() {
    this.meshes.forEach((mesh) => { mesh.geometry.dispose(); mesh.dispose(); });
    (this.meshes[0]?.material as THREE.Material | undefined)?.dispose();
  }
}

function hash(a: number, b: number) {
  const x = Math.sin(a * 12.9898 + b * 78.233) * 43758.5453;
  return x - Math.floor(x);
}

// ---- unit tree meshes: height 1 (scaled by tree height), crown radius 1 (scaled by crown radius)

type Builder = { positions: number[]; colors: number[] };

function triangle(mesh: Builder, a: number[], b: number[], c: number[], color: RGB) {
  for (const p of [a, b, c]) { mesh.positions.push(p[0], p[1], p[2]); mesh.colors.push(...color); }
}

function ring(sides: number, radius: number, y: number, twist = 0) {
  return Array.from({ length: sides }, (_, i) => {
    const angle = (i / sides) * Math.PI * 2 + twist;
    return [Math.cos(angle) * radius, y, Math.sin(angle) * radius];
  });
}

function trunk(mesh: Builder, radius: number, height: number) {
  const bottom = ring(5, radius, 0);
  const top = ring(5, radius * 0.8, height);
  for (let i = 0; i < 5; i += 1) {
    const j = (i + 1) % 5;
    triangle(mesh, bottom[i], top[i], bottom[j], TRUNK);
    triangle(mesh, bottom[j], top[i], top[j], TRUNK);
  }
}

function build(mesh: Builder) {
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(mesh.positions, 3));
  geometry.setAttribute("color", new THREE.Float32BufferAttribute(mesh.colors, 3));
  geometry.computeVertexNormals();
  return geometry;
}

function broadleaf(shades: RGB[]) {
  const mesh: Builder = { positions: [], colors: [] };
  trunk(mesh, 0.09, 0.42);
  const sides = 7;
  const bottom = [0, 0.3, 0];
  const top = [0, 1, 0];
  const lower = ring(sides, 0.95, 0.52);
  const upper = ring(sides, 0.8, 0.8, Math.PI / sides);
  for (let i = 0; i < sides; i += 1) {
    const j = (i + 1) % sides;
    triangle(mesh, lower[j], bottom, lower[i], shades[1]);
    triangle(mesh, lower[i], upper[i], lower[j], shades[i % shades.length]);
    triangle(mesh, lower[j], upper[i], upper[j], shades[(i + 1) % shades.length]);
    triangle(mesh, upper[i], top, upper[j], shades[2]);
  }
  return build(mesh);
}

function conifer(shades: RGB[]) {
  const mesh: Builder = { positions: [], colors: [] };
  trunk(mesh, 0.08, 0.25);
  const cone = (radius: number, y0: number, apex: number, twist: number) => {
    const base = ring(7, radius, y0, twist);
    for (let i = 0; i < 7; i += 1) {
      const j = (i + 1) % 7;
      triangle(mesh, base[i], [0, apex, 0], base[j], shades[i % shades.length]);
      triangle(mesh, base[j], [0, y0, 0], base[i], shades[1]);
    }
  };
  cone(0.95, 0.18, 0.72, 0);
  cone(0.68, 0.48, 1, Math.PI / 7);
  return build(mesh);
}
