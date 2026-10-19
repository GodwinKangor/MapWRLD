// Screen-space billboards for every marker (door pins, public-record badges, carbon dots,
// future-work points) in one instanced draw call. Icons live in a canvas atlas; sizes are CSS
// pixels. Picking uses the same layout on the CPU, so it matches what is drawn.

import * as THREE from "three";

export type MarkerIcon =
  | "door-main" | "door-accessible" | "door-exit"
  | `badge:${string}` | `badge-selected:${string}`
  | "carbon-high" | "carbon-medium" | "carbon-low" | "future";

export type MarkerSpec = {
  buildingId?: string;
  icon: MarkerIcon;
  position: THREE.Vector3;
  width: number;
  height: number;
  anchor: [number, number];        // 0..1 within the icon that sits on the position (0.5,0 = bottom center)
  offset?: [number, number];       // extra CSS pixels (x right, y up)
  maxDistance?: number;            // hide beyond this camera distance (m)
};

const CELL = 96;
const COLUMNS = 8;

export class MarkerLayer {
  readonly mesh: THREE.Mesh<THREE.InstancedBufferGeometry, THREE.ShaderMaterial>;
  private specs: MarkerSpec[] = [];
  private readonly atlas: THREE.CanvasTexture;
  private readonly cells = new Map<MarkerIcon, number>();
  private readonly atlasCanvas: HTMLCanvasElement;
  private capacity = 0;

  constructor() {
    this.atlasCanvas = document.createElement("canvas");
    this.atlasCanvas.width = CELL * COLUMNS;
    this.atlasCanvas.height = CELL * COLUMNS;
    this.atlas = new THREE.CanvasTexture(this.atlasCanvas);
    this.atlas.colorSpace = THREE.SRGBColorSpace;
    this.atlas.generateMipmaps = false;
    this.atlas.minFilter = THREE.LinearFilter;
    const geometry = new THREE.InstancedBufferGeometry();
    geometry.setAttribute("position", new THREE.Float32BufferAttribute([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0], 3));
    geometry.setIndex([0, 1, 2, 0, 2, 3]);
    const material = new THREE.ShaderMaterial({
      uniforms: { atlas: { value: this.atlas }, resolution: { value: new THREE.Vector2(1, 1) } },
      vertexShader: `
        attribute vec3 center;
        attribute vec4 sizeAnchor;   // width, height (px), anchor x, anchor y
        attribute vec3 offsetLimit;  // offset x, offset y (px), max distance (m)
        attribute vec4 uvRect;
        uniform vec2 resolution;
        varying vec2 vUv;
        void main() {
          vec4 viewPosition = modelViewMatrix * vec4(center, 1.0);
          vec4 clip = projectionMatrix * viewPosition;
          vec2 pixels = (position.xy - sizeAnchor.zw) * sizeAnchor.xy + offsetLimit.xy;
          clip.xy += pixels * 2.0 / resolution * clip.w;
          // beyond the marker's distance limit, or behind the camera: collapse off screen
          if (-viewPosition.z > offsetLimit.z || viewPosition.z > 0.0) clip = vec4(2.0, 2.0, 2.0, 1.0);
          gl_Position = clip;
          vUv = uvRect.xy + position.xy * uvRect.zw;
        }`,
      fragmentShader: `
        uniform sampler2D atlas;
        varying vec2 vUv;
        void main() {
          vec4 color = texture2D(atlas, vUv);
          if (color.a < 0.04) discard;
          gl_FragColor = color;
          #include <colorspace_fragment>
        }`,
      transparent: true,
      depthTest: false,
      depthWrite: false,
    });
    this.mesh = new THREE.Mesh(geometry, material);
    this.mesh.name = "campus-markers";
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 10;
  }

  setResolution(width: number, height: number) {
    this.mesh.material.uniforms.resolution.value.set(width, height);
  }

  /** replace the whole set (layer or filter changes) */
  setMarkers(specs: MarkerSpec[]) {
    this.specs = specs;
    specs.forEach((spec) => this.cell(spec.icon));
    const geometry = this.mesh.geometry;
    if (specs.length > this.capacity) {
      this.capacity = Math.max(64, Math.ceil(specs.length * 1.25));
      geometry.setAttribute("center", new THREE.InstancedBufferAttribute(new Float32Array(this.capacity * 3), 3).setUsage(THREE.DynamicDrawUsage));
      geometry.setAttribute("sizeAnchor", new THREE.InstancedBufferAttribute(new Float32Array(this.capacity * 4), 4).setUsage(THREE.DynamicDrawUsage));
      geometry.setAttribute("offsetLimit", new THREE.InstancedBufferAttribute(new Float32Array(this.capacity * 3), 3).setUsage(THREE.DynamicDrawUsage));
      geometry.setAttribute("uvRect", new THREE.InstancedBufferAttribute(new Float32Array(this.capacity * 4), 4).setUsage(THREE.DynamicDrawUsage));
    }
    specs.forEach((spec, index) => this.write(index, spec));
    geometry.instanceCount = specs.length;
    this.flag();
  }

  /** restyle the markers of specific buildings in place (selection), without touching the rest */
  update(buildingIds: Set<string>, restyle: (spec: MarkerSpec) => MarkerSpec) {
    let changed = false;
    this.specs.forEach((spec, index) => {
      if (!spec.buildingId || !buildingIds.has(spec.buildingId)) return;
      const next = restyle(spec);
      this.cell(next.icon);
      this.specs[index] = next;
      this.write(index, next);
      changed = true;
    });
    if (changed) this.flag();
    return changed;
  }

  /** topmost marker under a CSS-pixel point, using the same layout as the shader */
  pick(x: number, y: number, camera: THREE.Camera, width: number, height: number) {
    const projected = new THREE.Vector3();
    const view = new THREE.Vector3();
    for (let index = this.specs.length - 1; index >= 0; index -= 1) {
      const spec = this.specs[index];
      view.copy(spec.position).applyMatrix4(camera.matrixWorldInverse);
      if (view.z > 0 || -view.z > (spec.maxDistance ?? Infinity)) continue;
      projected.copy(spec.position).project(camera);
      const sx = (projected.x + 1) / 2 * width + (spec.offset?.[0] ?? 0);
      const sy = (1 - projected.y) / 2 * height - (spec.offset?.[1] ?? 0);
      const left = sx - spec.anchor[0] * spec.width;
      const bottom = sy + spec.anchor[1] * spec.height;
      if (x >= left && x <= left + spec.width && y <= bottom && y >= bottom - spec.height) return spec;
    }
    return undefined;
  }

  get markers() {
    return this.specs;
  }

  dispose() {
    this.mesh.geometry.dispose();
    this.mesh.material.dispose();
    this.atlas.dispose();
  }

  private flag() {
    for (const name of ["center", "sizeAnchor", "offsetLimit", "uvRect"]) {
      const attribute = this.mesh.geometry.getAttribute(name) as THREE.InstancedBufferAttribute | undefined;
      if (attribute) attribute.needsUpdate = true;
    }
  }

  private write(index: number, spec: MarkerSpec) {
    const geometry = this.mesh.geometry;
    (geometry.getAttribute("center") as THREE.InstancedBufferAttribute).setXYZ(index, spec.position.x, spec.position.y, spec.position.z);
    (geometry.getAttribute("sizeAnchor") as THREE.InstancedBufferAttribute).setXYZW(index, spec.width, spec.height, spec.anchor[0], spec.anchor[1]);
    (geometry.getAttribute("offsetLimit") as THREE.InstancedBufferAttribute).setXYZ(index, spec.offset?.[0] ?? 0, spec.offset?.[1] ?? 0, spec.maxDistance ?? 1e9);
    const cell = this.cells.get(spec.icon)!;
    const u = (cell % COLUMNS) / COLUMNS;
    const v = 1 - (Math.floor(cell / COLUMNS) + 1) / COLUMNS; // canvas textures are flipped: row 0 is the top
    (geometry.getAttribute("uvRect") as THREE.InstancedBufferAttribute).setXYZW(index, u, v, 1 / COLUMNS, 1 / COLUMNS);
  }

  private cell(icon: MarkerIcon) {
    let cell = this.cells.get(icon);
    if (cell !== undefined) return cell;
    cell = this.cells.size;
    if (cell >= COLUMNS * COLUMNS) throw new Error("Marker atlas is full");
    this.cells.set(icon, cell);
    const ctx = this.atlasCanvas.getContext("2d")!;
    ctx.save();
    ctx.translate((cell % COLUMNS) * CELL, Math.floor(cell / COLUMNS) * CELL);
    drawIcon(ctx, icon);
    ctx.restore();
    this.atlas.needsUpdate = true;
    return cell;
  }
}

function drawIcon(ctx: CanvasRenderingContext2D, icon: MarkerIcon) {
  const s = CELL / 100;
  ctx.scale(s, s);
  if (icon.startsWith("door-")) {
    const fill = icon === "door-accessible" ? "#8ee6ff" : icon === "door-exit" ? "#ffffff" : "#d9ff77";
    // pin occupies the full cell: 84 x 100 artwork centered horizontally
    ctx.translate(8, 0);
    ctx.fillStyle = fill;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 6;
    ctx.fill(new Path2D("M42 2C20 2 4 19 4 40c0 29 38 58 38 58s38-29 38-58C80 19 64 2 42 2Z"));
    ctx.stroke(new Path2D("M42 2C20 2 4 19 4 40c0 29 38 58 38 58s38-29 38-58C80 19 64 2 42 2Z"));
    ctx.strokeStyle = "#163f2e";
    ctx.lineWidth = 5;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.stroke(new Path2D("M29 60V25l29-6v41M29 60h29M47 43h2"));
    return;
  }
  if (icon.startsWith("badge")) {
    const selected = icon.startsWith("badge-selected:");
    const color = icon.slice(icon.indexOf(":") + 1);
    ctx.beginPath();
    ctx.arc(50, 50, 40, 0, Math.PI * 2);
    ctx.fillStyle = color;
    ctx.fill();
    ctx.lineWidth = selected ? 13 : 9;
    ctx.strokeStyle = selected ? "#d9ff77" : "#ffffff";
    ctx.stroke();
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = 5;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.stroke(new Path2D("M36 30h20l10 10v28H36Z M56 30v10h10 M42 51h18 M42 60h13"));
    return;
  }
  const dot = { "carbon-high": "#f5381f", "carbon-medium": "#ffb82e", "carbon-low": "#57db70", future: "#db73ff" }[icon as "future"];
  ctx.beginPath();
  ctx.arc(50, 50, 36, 0, Math.PI * 2);
  ctx.fillStyle = dot;
  ctx.globalAlpha = icon === "future" ? 0.95 : 0.8;
  ctx.fill();
  ctx.globalAlpha = 1;
  ctx.lineWidth = 8;
  ctx.strokeStyle = "#ffffff";
  ctx.stroke();
}
