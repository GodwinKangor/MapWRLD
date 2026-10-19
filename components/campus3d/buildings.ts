// All campus buildings as one merged, vertex-colored mesh (one draw call instead of ~1,400).
// Each vertex carries its building's index; a 1-pixel-tall state texture holds per-building
// highlight colors, so evidence tinting and selection never touch the base colors and update
// by writing a few texels instead of rebuilding geometry or loading a second model.

import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { CampusFrame } from "./frame";

export type BuildingGround = Record<string, { min: number; median: number; max: number }>;

export class CampusBuildings {
  readonly mesh: THREE.Mesh<THREE.BufferGeometry, THREE.MeshLambertMaterial>;
  readonly roots: string[];                 // GLB root node name per building index ("part::building__…")
  readonly osmIds: (string | undefined)[];  // OSM id per building index
  readonly centers: THREE.Vector3[];        // footprint center at roof height, for camera targets
  private readonly indexByRoot = new Map<string, number>();
  private readonly indexByOsm = new Map<string, number>();
  private readonly state: Uint8Array;
  private readonly stateTexture: THREE.DataTexture;

  private constructor(geometry: THREE.BufferGeometry, roots: string[], osmIds: (string | undefined)[], centers: THREE.Vector3[]) {
    this.roots = roots;
    this.osmIds = osmIds;
    this.centers = centers;
    roots.forEach((root, index) => this.indexByRoot.set(root, index));
    osmIds.forEach((osm, index) => { if (osm) this.indexByOsm.set(osm, index); });
    this.state = new Uint8Array(Math.max(1, roots.length) * 4);
    this.stateTexture = new THREE.DataTexture(this.state, Math.max(1, roots.length), 1, THREE.RGBAFormat);
    this.stateTexture.needsUpdate = true;
    const stateTexture = this.stateTexture;
    const material = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide });
    material.onBeforeCompile = (shader) => {
      shader.uniforms.buildingState = { value: stateTexture };
      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", "#include <common>\nattribute float buildingIndex;\nuniform sampler2D buildingState;\nvarying vec4 vBuildingState;")
        .replace("#include <begin_vertex>", "#include <begin_vertex>\nvBuildingState = texelFetch(buildingState, ivec2(int(buildingIndex + 0.5), 0), 0);");
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <common>", "#include <common>\nvarying vec4 vBuildingState;")
        .replace("#include <color_fragment>", "#include <color_fragment>\ndiffuseColor.rgb = mix(diffuseColor.rgb, vBuildingState.rgb, vBuildingState.a);");
    };
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.name = "campus-buildings";
  }

  static async load(url: string, frame: CampusFrame, ground: BuildingGround, signal: AbortSignal) {
    const response = await fetch(url, { signal });
    if (!response.ok) throw new Error(`Campus model unavailable (${response.status})`);
    const gltf = await new GLTFLoader().parseAsync(await response.arrayBuffer(), "");
    if (signal.aborted) throw new DOMException("aborted", "AbortError");
    gltf.scene.updateMatrixWorld(true);

    const roots: string[] = [];
    const osmIds: (string | undefined)[] = [];
    const centers: THREE.Vector3[] = [];
    const parts: THREE.BufferGeometry[] = [];
    const box = new THREE.Box3();
    for (const root of gltf.scene.children) {
      // GLTFLoader strips ":" from node names; the original is kept in userData.name
      const name = (root.userData?.name as string | undefined) ?? root.name;
      if (!name.startsWith("part::building__")) continue; // road parts are empty centerlines
      box.setFromObject(root);
      if (box.isEmpty()) continue;
      const center = box.getCenter(new THREE.Vector3());
      if (!frame.inside(center.x, center.z)) continue; // the map world is the campus rectangle
      const elevation = ground[name];
      // sit on the lowest ground under the footprint; fall back to the terrain at the center
      const lift = (elevation ? frame.y(elevation.min) : frame.ground(center.x, center.z)) - box.min.y - 0.1;
      const index = roots.length;
      root.traverse((object) => {
        const mesh = object as THREE.Mesh;
        if (!mesh.isMesh) return;
        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
        const source = mesh.geometry;
        const groups = source.groups.length ? source.groups : [{ start: 0, count: (source.index ?? source.attributes.position).count, materialIndex: 0 }];
        for (const group of groups) {
          const material = materials[group.materialIndex ?? 0] as THREE.MeshStandardMaterial;
          parts.push(bakePart(source, group.start, group.count, mesh.matrixWorld, lift, material, index));
        }
      });
      roots.push(name);
      osmIds.push((root.userData?.osmId as string | undefined) ?? osmFromName(name));
      centers.push(new THREE.Vector3(center.x, box.max.y + lift, center.z));
    }
    disposeObject(gltf.scene);
    const merged = mergeGeometries(parts, false);
    parts.forEach((part) => part.dispose());
    if (!merged) throw new Error("Campus model has no building geometry");
    merged.computeBoundingSphere();
    merged.computeBoundingBox();
    return new CampusBuildings(merged, roots, osmIds, centers);
  }

  indexOfRoot(root: string) {
    return this.indexByRoot.get(root);
  }

  indexOfOsm(osmId: string) {
    return this.indexByOsm.get(osmId);
  }

  /** building index under a ray hit on the merged mesh */
  indexFromHit(hit: THREE.Intersection) {
    const vertex = hit.face?.a;
    return vertex === undefined ? undefined : Math.round(this.mesh.geometry.getAttribute("buildingIndex").getX(vertex));
  }

  /** replace all highlight states at once: index -> [color, amount 0..1] */
  setStates(states: Map<number, [THREE.Color, number]>) {
    this.state.fill(0);
    const scratch = new THREE.Color();
    for (const [index, [color, amount]] of states) {
      scratch.copy(color); // linear working space, matching the shader's diffuse color
      this.state.set([scratch.r * 255, scratch.g * 255, scratch.b * 255, amount * 255].map(Math.round), index * 4);
    }
    this.stateTexture.needsUpdate = true;
  }

  dispose() {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
    this.stateTexture.dispose();
  }
}

function osmFromName(name: string) {
  const match = /__way_(\d+)$/.exec(name);
  return match ? `way/${match[1]}` : undefined;
}

// one material group of a GLB mesh -> world-space, grounded, indexed geometry with baked color
function bakePart(source: THREE.BufferGeometry, start: number, count: number, matrix: THREE.Matrix4, lift: number, material: THREE.MeshStandardMaterial, buildingIndex: number) {
  const position = source.getAttribute("position");
  const normal = source.getAttribute("normal");
  const color = source.getAttribute("color");
  const sourceIndex = source.index;
  const used = new Map<number, number>();
  const indices: number[] = [];
  for (let i = start; i < start + count; i += 1) {
    const vertex = sourceIndex ? sourceIndex.getX(i) : i;
    let mapped = used.get(vertex);
    if (mapped === undefined) { mapped = used.size; used.set(vertex, mapped); }
    indices.push(mapped);
  }
  const n = used.size;
  const positions = new Float32Array(n * 3);
  const normals = new Float32Array(n * 3);
  const colors = new Float32Array(n * 3);
  const base = material?.color ?? new THREE.Color(0.8, 0.8, 0.8);
  const normalMatrix = new THREE.Matrix3().getNormalMatrix(matrix);
  const p = new THREE.Vector3();
  const q = new THREE.Vector3();
  for (const [vertex, i] of used) {
    p.fromBufferAttribute(position, vertex).applyMatrix4(matrix);
    positions.set([p.x, p.y + lift, p.z], i * 3);
    if (normal) q.fromBufferAttribute(normal, vertex).applyMatrix3(normalMatrix).normalize(); else q.set(0, 1, 0);
    normals.set([q.x, q.y, q.z], i * 3);
    const r = color ? color.getX(vertex) : 1;
    const g = color ? color.getY(vertex) : 1;
    const b = color ? color.getZ(vertex) : 1;
    colors.set([base.r * r, base.g * g, base.b * b], i * 3);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
  geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3));
  geometry.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  geometry.setAttribute("buildingIndex", new THREE.BufferAttribute(new Float32Array(n).fill(buildingIndex), 1));
  geometry.setIndex(n > 65535 ? new THREE.Uint32BufferAttribute(indices, 1) : new THREE.Uint16BufferAttribute(indices, 1));
  return geometry;
}

export function disposeObject(root: THREE.Object3D) {
  root.traverse((object) => {
    const mesh = object as THREE.Mesh;
    if (!mesh.isMesh) return;
    mesh.geometry?.dispose();
    (Array.isArray(mesh.material) ? mesh.material : [mesh.material]).forEach((material) => material?.dispose());
  });
}
