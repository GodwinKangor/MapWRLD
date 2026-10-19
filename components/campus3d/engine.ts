// The standalone campus scene: Three.js, local meters, Dartmouth only. Everything it draws is
// pre-built (terrain, imagery, roads, fields, trees, buildings); nothing samples live terrain.
// Rendering is on demand: a frame is drawn only when the camera, an animation, or data changes.

import * as THREE from "three";
import { MapControls } from "three/examples/jsm/controls/MapControls.js";
import type { Building } from "@/data/buildings";
import { CAMPUS_BOUNDS, DARTMOUTH_HOME, FUTURE_WORK, GROUND_VIEW } from "@/data/campus-layers";
import { primaryTechnology, technologyColors, type EnergyTechnology } from "@/data/energy-evidence";
import { CampusBuildings, type BuildingGround } from "./buildings";
import { ASSET_ROOT, clamp, fetchJson, loadFrame, versioned, type CampusFrame } from "./frame";
import { GroundPainter, type CampusField, type CampusRoad } from "./ground-texture";
import { MarkerLayer, type MarkerSpec } from "./markers";
import { buildTerrain } from "./terrain";
import { CampusTrees, type Season } from "./trees";

export type SceneLayers = {
  accessibility: boolean; boundary: boolean; carbon: boolean; electric: boolean; energyNetwork: boolean;
  futureWork: boolean; heating: boolean; evidence: boolean; roads: boolean; fields: boolean; trees: boolean;
};
export type Quality = "low" | "medium" | "high";
export type SceneStatus = { phase: "loading" | "ready" | "error"; message: string; progress: number };
export type CameraState = { x: number; z: number; heading: number; distance: number; frame: CampusFrame };
export type SceneMetrics = { readyMs?: number; calls: number; triangles: number; geometries: number; textures: number; frames: number; lastFrameMs: number };

type Callbacks = {
  onSelect: (buildingId: string) => void;
  onStatus: (status: SceneStatus) => void;
  onCamera?: (camera: CameraState) => void;
};

const QUALITY: Record<Quality, { pixelRatio: number; terrainStride: number; mobileImagery: boolean; anisotropy: number }> = {
  low: { pixelRatio: 1, terrainStride: 3, mobileImagery: true, anisotropy: 2 },
  medium: { pixelRatio: 1.5, terrainStride: 2, mobileImagery: false, anisotropy: 8 },
  high: { pixelRatio: 2, terrainStride: 1, mobileImagery: false, anisotropy: 16 },
};
const HIGHLIGHT_ALL = "#f2a33a";
const SELECTED = "#d9ff77";
const PLACEHOLDER_PIN_MAX_DISTANCE = 1400;
const CAMERA = { minDistance: 12, maxDistance: 3200, maxPolar: THREE.MathUtils.degToRad(84), eyeClearance: 2.5 };

export class CampusEngine {
  readonly renderer: THREE.WebGLRenderer;
  readonly metrics: SceneMetrics = { calls: 0, triangles: 0, geometries: 0, textures: 0, frames: 0, lastFrameMs: 0 };
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(40, 1, 1, 9000);
  private readonly controls: MapControls;
  private readonly abort = new AbortController();
  private readonly sun = new THREE.DirectionalLight("#fff4e0", 2.2);
  private readonly sky = new THREE.HemisphereLight("#dfe9f2", "#4a5a3c", 1.3);
  private readonly markers = new MarkerLayer();
  private readonly labels: HTMLDivElement;
  private readonly startedAt = performance.now();
  private frame?: CampusFrame;
  private buildings?: CampusBuildings;
  private trees?: CampusTrees;
  private painter?: GroundPainter;
  private groundTexture?: THREE.CanvasTexture;
  private terrainGroup?: THREE.Group;
  private fields: CampusField[] = [];
  private roads: CampusRoad[] = [];
  private markerBuildings: Building[] = [];
  private pickBuildings: Building[] = [];
  private buildingByOsm = new Map<string, Building>();
  private selectedId: string | null = null;
  private layers: SceneLayers;
  private technology: EnergyTechnology | "all" = "all";
  private season: Season = "Fall";
  private hour = 14;
  private modelVisible = true;
  private frameRequested = 0;
  private flight?: { from: [THREE.Vector3, THREE.Vector3]; to: [THREE.Vector3, THREE.Vector3]; start: number; duration: number };
  private width = 1;
  private height = 1;
  private pointerDown?: { x: number; y: number; time: number };
  private readonly resizeObserver: ResizeObserver;
  private disposed = false;

  constructor(private readonly container: HTMLElement, private readonly callbacks: Callbacks, layers: SceneLayers, private readonly quality: Quality) {
    this.layers = layers;
    this.renderer = new THREE.WebGLRenderer({ antialias: quality !== "low", powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, QUALITY[quality].pixelRatio));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.05;
    this.renderer.info.autoReset = true;
    this.renderer.domElement.className = "campus-canvas";
    container.appendChild(this.renderer.domElement);
    this.labels = document.createElement("div");
    this.labels.className = "campus-labels";
    container.appendChild(this.labels);

    this.scene.background = new THREE.Color("#13251c");
    this.scene.add(this.sky, this.sun, this.sun.target, this.markers.mesh);
    this.controls = new MapControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.12;
    this.controls.screenSpacePanning = false;
    this.controls.minDistance = CAMERA.minDistance;
    this.controls.maxDistance = CAMERA.maxDistance;
    this.controls.maxPolarAngle = CAMERA.maxPolar;
    this.controls.zoomToCursor = true;
    this.controls.addEventListener("change", this.onControlsChange);
    this.controls.addEventListener("start", this.cancelFlight);

    const canvas = this.renderer.domElement;
    canvas.addEventListener("pointerdown", this.onPointerDown);
    canvas.addEventListener("pointerup", this.onPointerUp);
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(container);
    this.resize();
    this.applyTime();
  }

  async load() {
    const { signal } = this.abort;
    const status = (message: string, progress: number) => this.callbacks.onStatus({ phase: "loading", message, progress });
    try {
      status("Loading terrain", 0.05);
      const frame = await loadFrame(signal);
      this.frame = frame;
      this.home(false);
      status("Loading imagery, roads and fields", 0.2);
      const settings = QUALITY[this.quality];
      const imageryFile = settings.mobileImagery ? frame.meta.imagery.mobileFile : frame.meta.imagery.file;
      const [imagery, fields, roads] = await Promise.all([
        loadImage(versioned(`${ASSET_ROOT}/terrain/${imageryFile}`, frame.meta, imageryFile), signal),
        fetchJson<{ fields: CampusField[] }>(`${ASSET_ROOT}/campus-fields.json`, signal).then((d) => d.fields).catch(() => []),
        fetchJson<{ roads: CampusRoad[] }>(`${ASSET_ROOT}/campus-roads.json`, signal).then((d) => d.roads).catch(() => []),
      ]);
      this.fields = fields;
      this.roads = roads;
      const textureWidth = settings.mobileImagery ? 2048 : 4000;
      this.painter = new GroundPainter(frame, imagery, textureWidth, Math.round(textureWidth * imagery.height / imagery.width));
      this.paintGround();
      this.groundTexture = new THREE.CanvasTexture(this.painter.canvas);
      this.groundTexture.colorSpace = THREE.SRGBColorSpace;
      this.groundTexture.anisotropy = Math.min(settings.anisotropy, this.renderer.capabilities.getMaxAnisotropy());
      const terrain = buildTerrain(frame, settings.terrainStride, this.groundTexture);
      this.terrainGroup = terrain.group;
      this.scene.add(terrain.group);
      this.invalidate();

      status("Loading trees", 0.45);
      const treeData = await fetchJson<{ trees: [number, number, number, number, 0 | 1][] }>(`${ASSET_ROOT}/campus-trees.json`, signal).catch(() => ({ trees: [] }));
      this.trees = new CampusTrees(treeData.trees, frame);
      this.trees.setSeason(this.season);
      this.trees.group.visible = this.layers.trees;
      this.scene.add(this.trees.group);
      this.invalidate();

      status("Loading campus buildings", 0.6);
      const manifest = await fetchJson<{ campusModel: string }>(`${ASSET_ROOT}/model-manifest.json`, signal);
      const ground = await fetchJson<BuildingGround>(versioned(`${ASSET_ROOT}/terrain/building-ground.json`, frame.meta, "building-ground.json"), signal);
      this.buildings = await CampusBuildings.load(manifest.campusModel, frame, ground, signal);
      this.buildings.mesh.visible = this.modelVisible;
      this.scene.add(this.buildings.mesh);
      this.indexBuildings();
      this.refreshMarkers();
      this.refreshHighlights();
      this.metrics.readyMs = Math.round(performance.now() - this.startedAt);
      this.callbacks.onStatus({ phase: "ready", message: "Campus ready", progress: 1 });
      this.invalidate();
    } catch (error) {
      if ((error as Error).name === "AbortError" || this.disposed) return;
      console.error("Campus scene failed to load", error);
      this.callbacks.onStatus({ phase: "error", message: (error as Error).message || "The campus scene could not load", progress: 0 });
    }
  }

  // ---- data and UI state

  setBuildings(markerBuildings: Building[], pickBuildings: Building[]) {
    this.markerBuildings = markerBuildings;
    this.pickBuildings = pickBuildings;
    this.indexBuildings();
    this.refreshMarkers();
    this.refreshHighlights();
  }

  setSelected(id: string | null) {
    if (id === this.selectedId) return;
    const previous = this.selectedId;
    this.selectedId = id;
    const changed = new Set([previous, id].filter((value): value is string => Boolean(value)));
    // restyle just the two buildings' markers in place
    this.markers.update(changed, (spec) => this.styleMarker(spec));
    this.refreshHighlights();
    const building = id ? this.pickBuildings.find((item) => item.id === id) ?? this.markerBuildings.find((item) => item.id === id) : undefined;
    if (building) this.flyToBuilding(building);
    this.invalidate();
  }

  setLayers(layers: SceneLayers) {
    const previous = this.layers;
    this.layers = layers;
    const groundKeys: (keyof SceneLayers)[] = ["fields", "roads", "energyNetwork", "heating", "electric", "boundary"];
    if (groundKeys.some((key) => previous[key] !== layers[key])) this.paintGround();
    if (this.trees) this.trees.group.visible = layers.trees;
    const markerKeys: (keyof SceneLayers)[] = ["accessibility", "evidence", "carbon", "futureWork"];
    if (markerKeys.some((key) => previous[key] !== layers[key])) this.refreshMarkers();
    if (previous.evidence !== layers.evidence) this.refreshHighlights();
    this.invalidate();
  }

  setEvidenceTechnology(technology: EnergyTechnology | "all") {
    if (technology === this.technology) return;
    this.technology = technology;
    this.refreshMarkers();
    this.refreshHighlights();
    this.invalidate();
  }

  setSeason(season: Season) {
    if (season === this.season) return;
    this.season = season;
    this.trees?.setSeason(season);
    this.paintGround();
    this.invalidate();
  }

  setTime(hour: number) {
    this.hour = hour;
    this.applyTime();
    this.invalidate();
  }

  setModelVisible(visible: boolean) {
    this.modelVisible = visible;
    if (this.buildings) this.buildings.mesh.visible = visible;
    this.invalidate();
  }

  // ---- camera

  home(animate = true) {
    if (!this.frame) return;
    const [x, z] = this.frame.toLocal([DARTMOUTH_HOME.longitude, DARTMOUTH_HOME.latitude]);
    this.look(new THREE.Vector3(x, this.frame.ground(x, z), z), 1, 76, 2250, animate);
  }

  groundView() {
    if (!this.frame) return;
    const [x, z] = this.frame.toLocal([GROUND_VIEW.longitude, GROUND_VIEW.latitude]);
    const forward = new THREE.Vector3(Math.sin(THREE.MathUtils.degToRad(4)), 0, -Math.cos(THREE.MathUtils.degToRad(4)));
    const tx = x + forward.x * 120;
    const tz = z + forward.z * 120;
    this.look(new THREE.Vector3(tx, this.frame.ground(tx, tz), tz), 4, 22, 130, true);
  }

  zoom(direction: "in" | "out") {
    const offset = this.camera.position.clone().sub(this.controls.target);
    const distance = clamp(offset.length() * (direction === "in" ? 0.65 : 1.5), CAMERA.minDistance, CAMERA.maxDistance);
    this.flyTo(this.controls.target.clone(), this.controls.target.clone().add(offset.setLength(distance)), 450);
  }

  /** center the view on a minimap point, keeping the current angle */
  lookAtLocal(x: number, z: number) {
    if (!this.frame) return;
    const target = new THREE.Vector3(this.frame.clampX(x), 0, this.frame.clampZ(z));
    target.y = this.frame.ground(target.x, target.z);
    const offset = this.camera.position.clone().sub(this.controls.target);
    this.flyTo(target, target.clone().add(offset), 700);
  }

  private flyToBuilding(building: Building) {
    if (!this.frame) return;
    const [x, z] = this.frame.toLocal(building.entrance.coordinates);
    const index = this.buildingIndices(building)[0];
    const top = index !== undefined ? this.buildings?.centers[index] : undefined;
    const ground = this.frame.ground(x, z);
    const target = new THREE.Vector3(x, top ? (ground + top.y) / 2 : ground + 6, z);
    this.look(target, building.entrance.heading, 30, 165, true);
  }

  /** camera looking along `heading` (degrees from north) down at `pitch` degrees from `distance` m */
  private look(target: THREE.Vector3, heading: number, pitch: number, distance: number, animate: boolean) {
    const h = THREE.MathUtils.degToRad(heading);
    const p = THREE.MathUtils.degToRad(pitch);
    const forward = new THREE.Vector3(Math.sin(h), 0, -Math.cos(h));
    const position = target.clone().addScaledVector(forward, -Math.cos(p) * distance).add(new THREE.Vector3(0, Math.sin(p) * distance, 0));
    if (animate) this.flyTo(target, position, 1200);
    else {
      this.controls.target.copy(target);
      this.camera.position.copy(position);
      this.controls.update();
      this.invalidate();
    }
  }

  private flyTo(target: THREE.Vector3, position: THREE.Vector3, duration: number) {
    this.flight = { from: [this.controls.target.clone(), this.camera.position.clone()], to: [target, position], start: performance.now(), duration };
    this.invalidate();
  }

  private readonly cancelFlight = () => { this.flight = undefined; };

  private readonly onControlsChange = () => {
    this.constrainCamera();
    this.invalidate();
  };

  // the boundary is a soft wall on what the camera looks at; the eye never dips below the ground
  private constrainCamera() {
    const frame = this.frame;
    if (!frame) return;
    const target = this.controls.target;
    const clampedX = frame.clampX(target.x);
    const clampedZ = frame.clampZ(target.z);
    const shift = new THREE.Vector3(clampedX - target.x, 0, clampedZ - target.z);
    const groundY = frame.ground(clampedX, clampedZ);
    shift.y = groundY - target.y;
    target.add(shift);
    this.camera.position.add(shift);
    const eye = this.camera.position;
    const floor = frame.ground(eye.x, eye.z) + CAMERA.eyeClearance;
    if (eye.y < floor) eye.y = floor;
  }

  // ---- rendering

  invalidate = () => {
    if (this.disposed || this.frameRequested) return;
    this.frameRequested = requestAnimationFrame(this.renderFrame);
  };

  private readonly renderFrame = (now: number) => {
    this.frameRequested = 0;
    const started = performance.now();
    let animating = false;
    if (this.flight) {
      const t = Math.min(1, (now - this.flight.start) / this.flight.duration);
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2;
      this.controls.target.lerpVectors(this.flight.from[0], this.flight.to[0], e);
      this.camera.position.lerpVectors(this.flight.from[1], this.flight.to[1], e);
      if (t >= 1) this.flight = undefined; else animating = true;
    }
    const moved = this.controls.update(); // damping keeps moving after the pointer is released
    this.constrainCamera();
    this.renderer.render(this.scene, this.camera);
    this.placeLabels();
    const info = this.renderer.info;
    Object.assign(this.metrics, {
      calls: info.render.calls, triangles: info.render.triangles, geometries: info.memory.geometries, textures: info.memory.textures,
      frames: this.metrics.frames + 1, lastFrameMs: performance.now() - started,
    });
    if (this.frame) {
      const offset = this.camera.position.clone().sub(this.controls.target);
      this.callbacks.onCamera?.({ x: this.camera.position.x, z: this.camera.position.z, heading: Math.atan2(-offset.x, offset.z), distance: offset.length(), frame: this.frame });
    }
    if (animating || moved) this.invalidate();
  };

  private resize() {
    const { clientWidth, clientHeight } = this.container;
    this.width = Math.max(1, clientWidth);
    this.height = Math.max(1, clientHeight);
    this.renderer.setSize(this.width, this.height, false);
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
    this.markers.setResolution(this.width, this.height);
    this.invalidate();
  }

  private applyTime() {
    // simple solar arc: sunrise 6, sunset 19; dim blue light at night
    const daylight = clamp((this.hour - 6) / 13, 0, 1);
    const isDay = this.hour >= 6 && this.hour <= 19;
    const angle = daylight * Math.PI;
    const elevation = isDay ? Math.max(0.12, Math.sin(angle)) : 0.35;
    this.sun.position.set(Math.cos(angle) * 1000, elevation * 1200, 400);
    // night stays readable: moonlight plus a cool sky, not a black-out
    this.sun.intensity = isDay ? 0.9 + 1.5 * Math.sin(angle) : 0.55;
    this.sun.color.set(isDay ? (Math.sin(angle) < 0.35 ? "#ffcf99" : "#fff4e0") : "#aab8ff");
    this.sky.intensity = isDay ? 1.05 + 0.4 * Math.sin(angle) : 0.85;
    this.sky.color.set(isDay ? "#dfe9f2" : "#7f93c4");
    (this.scene.background as THREE.Color).set(isDay ? "#13251c" : "#070d12");
  }

  private paintGround() {
    if (!this.painter) return;
    this.painter.paint(this.layers, this.fields, this.roads, this.season);
    if (this.groundTexture) this.groundTexture.needsUpdate = true;
  }

  // ---- picking

  private readonly onPointerDown = (event: PointerEvent) => {
    this.pointerDown = { x: event.clientX, y: event.clientY, time: performance.now() };
  };

  private readonly onPointerUp = (event: PointerEvent) => {
    const down = this.pointerDown;
    this.pointerDown = undefined;
    if (!down || Math.hypot(event.clientX - down.x, event.clientY - down.y) > 6 || performance.now() - down.time > 500) return;
    const rect = this.renderer.domElement.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const marker = this.markers.pick(x, y, this.camera, this.width, this.height);
    if (marker?.buildingId) { this.callbacks.onSelect(marker.buildingId); return; }
    if (!this.buildings || !this.modelVisible) return;
    const raycaster = new THREE.Raycaster();
    raycaster.setFromCamera(new THREE.Vector2((x / this.width) * 2 - 1, -(y / this.height) * 2 + 1), this.camera);
    const hit = raycaster.intersectObject(this.buildings.mesh, false)[0];
    const index = hit ? this.buildings.indexFromHit(hit) : undefined;
    const osm = index !== undefined ? this.buildings.osmIds[index] : undefined;
    const building = osm ? this.buildingByOsm.get(osm) : undefined;
    if (building) this.callbacks.onSelect(building.id);
  };

  // ---- buildings, markers, highlights

  private indexBuildings() {
    this.buildingByOsm = new Map();
    for (const building of this.pickBuildings) for (const osm of osmIdsOf(building)) this.buildingByOsm.set(osm, building);
  }

  private buildingIndices(building: Building) {
    if (!this.buildings) return [];
    return osmIdsOf(building).map((osm) => this.buildings!.indexOfOsm(osm)).filter((index): index is number => index !== undefined);
  }

  private evidenceMatches(building: Building) {
    return Boolean(this.layers.evidence && building.evidence && (this.technology === "all" || building.evidence.technologies.some(({ id }) => id === this.technology)));
  }

  private refreshHighlights() {
    if (!this.buildings) return;
    const states = new Map<number, [THREE.Color, number]>();
    const tint = new THREE.Color(this.technology === "all" ? HIGHLIGHT_ALL : technologyColors[this.technology]);
    for (const building of this.pickBuildings) {
      if (!this.evidenceMatches(building)) continue;
      const roots = building.evidence!.twinObjects.map((name) => this.buildings!.indexOfRoot(`part::${name}`));
      for (const index of [...roots, ...this.buildingIndices(building)]) if (index !== undefined) states.set(index, [tint, 0.72]);
    }
    const selected = this.selectedId ? this.pickBuildings.find((item) => item.id === this.selectedId) : undefined;
    if (selected) for (const index of this.buildingIndices(selected)) states.set(index, [new THREE.Color(SELECTED), 0.45]);
    this.buildings.setStates(states);
    this.invalidate();
  }

  private refreshMarkers() {
    const frame = this.frame;
    if (!frame) return;
    const specs: MarkerSpec[] = [];
    const at = (coordinates: [number, number], lift: number) => {
      const [x, z] = frame.toLocal(coordinates);
      return new THREE.Vector3(x, frame.ground(x, z) + lift, z);
    };
    for (const building of this.markerBuildings) {
      const [lon, lat] = building.entrance.coordinates;
      if (lon < CAMPUS_BOUNDS.west || lon > CAMPUS_BOUNDS.east || lat < CAMPUS_BOUNDS.south || lat > CAMPUS_BOUNDS.north) continue;
      for (const entrance of building.entrances ?? [building.entrance]) {
        if (entrance.kind === "accessible" && !this.layers.accessibility) continue;
        specs.push(this.styleMarker({ buildingId: building.id, icon: `door-${entrance.kind}`, position: at(entrance.coordinates, 1), width: 0, height: 0, anchor: [0.5, 0.02] }, building));
      }
      if (building.evidence && this.evidenceMatches(building)) {
        const lead = this.technology === "all" ? primaryTechnology(building.evidence) : this.technology;
        specs.push(this.styleMarker({ buildingId: building.id, icon: `badge:${lead ? technologyColors[lead] : HIGHLIGHT_ALL}`, position: at(building.entrance.coordinates, 1), width: 0, height: 0, anchor: [0.5, 0.5] }, building));
      }
      if (this.layers.carbon) {
        const size = Math.max(14, Math.min(34, building.energy.demandKw / 38));
        specs.push({ buildingId: building.id, icon: `carbon-${building.energy.emissions.toLowerCase() as "high" | "medium" | "low"}`, position: at(building.coordinates, 16), width: size, height: size, anchor: [0.5, 0.5] });
      }
    }
    if (this.layers.futureWork) {
      for (const item of FUTURE_WORK) specs.push({ icon: "future", position: at(item.coordinates, 18), width: 14, height: 14, anchor: [0.5, 0.5] });
    }
    this.markers.setMarkers(specs);
    this.invalidate();
  }

  /** size, icon, and distance limit for a marker given selection and building type */
  private styleMarker(spec: MarkerSpec, known?: Building): MarkerSpec {
    const building = known ?? this.markerBuildings.find((item) => item.id === spec.buildingId);
    if (!building) return spec;
    const selected = building.id === this.selectedId;
    const small = building.imageClass === "placeholder" && !selected;
    if (spec.icon.startsWith("door-")) {
      const main = spec.icon === "door-main";
      const size = small ? 22 : main ? (selected ? 50 : 41) : (selected ? 37 : 29);
      return { ...spec, width: size, height: size, maxDistance: small ? PLACEHOLDER_PIN_MAX_DISTANCE : undefined };
    }
    if (spec.icon.startsWith("badge")) {
      const color = spec.icon.slice(spec.icon.indexOf(":") + 1);
      const size = Math.round(Math.max(24, Math.min(38, 18 + Math.sqrt(building.evidence?.candidateCount ?? 1) * 3)));
      const placeholder = building.imageClass === "placeholder";
      return { ...spec, icon: selected ? `badge-selected:${color}` : `badge:${color}`, width: size, height: size, offset: placeholder ? [11, 24] : [17, 42] };
    }
    return spec;
  }

  private placeLabels() {
    const items: { text: string; position: THREE.Vector3; kind: string }[] = [];
    const frame = this.frame;
    if (!frame) return;
    const selected = this.selectedId ? this.markerBuildings.find((item) => item.id === this.selectedId) ?? this.pickBuildings.find((item) => item.id === this.selectedId) : undefined;
    if (selected) {
      const [x, z] = frame.toLocal(selected.entrance.coordinates);
      items.push({ text: selected.name, position: new THREE.Vector3(x, frame.ground(x, z) + 1, z), kind: "selected" });
    }
    if (this.layers.futureWork) {
      for (const item of FUTURE_WORK) {
        const [x, z] = frame.toLocal(item.coordinates);
        items.push({ text: item.label, position: new THREE.Vector3(x, frame.ground(x, z) + 18, z), kind: "future" });
      }
    }
    while (this.labels.children.length > items.length) this.labels.lastElementChild!.remove();
    items.forEach((item, index) => {
      let element = this.labels.children[index] as HTMLDivElement | undefined;
      if (!element) { element = document.createElement("div"); this.labels.appendChild(element); }
      const projected = item.position.clone().project(this.camera);
      const behind = item.position.clone().applyMatrix4(this.camera.matrixWorldInverse).z > 0;
      element.className = `campus-label ${item.kind}`;
      element.textContent = item.text;
      element.style.display = behind ? "none" : "";
      element.style.transform = `translate(${((projected.x + 1) / 2) * this.width}px, ${((1 - projected.y) / 2) * this.height}px)`;
    });
  }

  dispose() {
    this.disposed = true;
    this.abort.abort();
    if (this.frameRequested) cancelAnimationFrame(this.frameRequested);
    this.resizeObserver.disconnect();
    const canvas = this.renderer.domElement;
    canvas.removeEventListener("pointerdown", this.onPointerDown);
    canvas.removeEventListener("pointerup", this.onPointerUp);
    this.controls.removeEventListener("change", this.onControlsChange);
    this.controls.removeEventListener("start", this.cancelFlight);
    this.controls.dispose();
    this.buildings?.dispose();
    this.trees?.dispose();
    this.markers.dispose();
    this.groundTexture?.dispose();
    this.terrainGroup?.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      mesh.geometry.dispose();
      (mesh.material as THREE.Material).dispose();
    });
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    canvas.remove();
    this.labels.remove();
  }
}

function osmIdsOf(building: Building) {
  if (building.osmIds?.length) return building.osmIds;
  const match = /-(\d+)$/.exec(building.id);
  return match ? [`way/${match[1]}`] : [];
}

function loadImage(url: string, signal: AbortSignal) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    const abort = () => { image.src = ""; reject(new DOMException("aborted", "AbortError")); };
    signal.addEventListener("abort", abort, { once: true });
    image.onload = () => { signal.removeEventListener("abort", abort); resolve(image); };
    image.onerror = () => { signal.removeEventListener("abort", abort); reject(new Error(`Imagery unavailable: ${url}`)); };
    image.src = url;
  });
}
