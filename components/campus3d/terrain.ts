// Terrain: the pre-built bare-earth DEM as one textured grid mesh, plus dark skirts down the
// four edges so the campus reads as a self-contained slab (nothing exists past the boundary).

import * as THREE from "three";
import type { CampusFrame } from "./frame";

export function buildTerrain(frame: CampusFrame, stride: number, texture: THREE.Texture) {
  const { cols, rows } = frame.meta.grid;
  const columns = sampleIndices(cols, stride);
  const rowIndices = sampleIndices(rows, stride);
  const w = columns.length;
  const h = rowIndices.length;
  const positions = new Float32Array(w * h * 3);
  const uvs = new Float32Array(w * h * 2);
  const spanX = frame.maxX - frame.minX;
  const spanZ = frame.maxZ - frame.minZ;
  rowIndices.forEach((row, j) => {
    columns.forEach((col, i) => {
      const k = j * w + i;
      const u = col / (cols - 1);
      const v = row / (rows - 1);
      positions.set([frame.minX + u * spanX, frame.heights[row * cols + col], frame.minZ + v * spanZ], k * 3);
      uvs.set([u, 1 - v], k * 2); // canvas textures are flipped: v = 1 is the north edge
    });
  });
  const indices = new Uint32Array((w - 1) * (h - 1) * 6);
  let n = 0;
  for (let j = 0; j < h - 1; j += 1) {
    for (let i = 0; i < w - 1; i += 1) {
      const a = j * w + i;
      const b = a + 1;
      const c = a + w;
      const d = c + 1;
      indices.set([a, c, b, b, c, d], n);
      n += 6;
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("uv", new THREE.BufferAttribute(uvs, 2));
  geometry.setIndex(new THREE.BufferAttribute(indices, 1));
  geometry.computeVertexNormals();
  geometry.computeBoundingSphere();
  const terrain = new THREE.Mesh(geometry, new THREE.MeshLambertMaterial({ map: texture }));
  terrain.name = "campus-terrain";

  // skirts: walls from the terrain edge down below the lowest ground
  const floor = frame.meta.grid.minElevation - frame.meta.grid.baseElevation - 30;
  const skirt: number[] = [];
  const edge = (points: [number, number, number][]) => {
    for (let i = 0; i < points.length - 1; i += 1) {
      const [x1, y1, z1] = points[i];
      const [x2, y2, z2] = points[i + 1];
      skirt.push(x1, y1, z1, x1, floor, z1, x2, y2, z2, x2, y2, z2, x1, floor, z1, x2, floor, z2);
    }
  };
  const at = (i: number, j: number): [number, number, number] => {
    const k = (j * w + i) * 3;
    return [positions[k], positions[k + 1], positions[k + 2]];
  };
  edge(columns.map((_, i) => at(i, 0)));                       // north
  edge(columns.map((_, i) => at(w - 1 - i, h - 1)));           // south
  edge(rowIndices.map((_, j) => at(0, h - 1 - j)));            // west
  edge(rowIndices.map((_, j) => at(w - 1, j)));                // east
  const skirtGeometry = new THREE.BufferGeometry();
  skirtGeometry.setAttribute("position", new THREE.Float32BufferAttribute(skirt, 3));
  skirtGeometry.computeVertexNormals();
  const walls = new THREE.Mesh(skirtGeometry, new THREE.MeshLambertMaterial({ color: "#1b2820", side: THREE.DoubleSide }));
  walls.name = "campus-terrain-skirt";

  const group = new THREE.Group();
  group.add(terrain, walls);
  return { group, terrain, triangles: indices.length / 3 };
}

function sampleIndices(count: number, stride: number) {
  const indices: number[] = [];
  for (let i = 0; i < count - 1; i += stride) indices.push(i);
  indices.push(count - 1); // always keep the boundary row/column
  return indices;
}
