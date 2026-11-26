// Real-world surroundings: Google Photorealistic 3D Tiles streamed around the campus, placed in the
// scene's local frame and cut away inside the campus rectangle, where our own model is the truth.
// The tiles are photogrammetry (one continuous mesh, no per-building objects), so they are context
// only: never picked, never tinted by evidence. Off by default, since every tile is a billed request.

import * as THREE from "three";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";
import { TilesRenderer } from "3d-tiles-renderer";
import { CesiumIonAuthPlugin, GLTFExtensionsPlugin, GoogleCloudAuthPlugin } from "3d-tiles-renderer/plugins";
import type { CampusFrame } from "./frame";

/** Cesium ion's hosted copy of Google Photorealistic 3D Tiles. */
const ION_GOOGLE_ASSET = "2275207";
/**
 * Ellipsoid height minus NAVD88 elevation at Hanover, NH (GEOID18 is about -28.5 m here). The
 * tiles use ellipsoid heights and the campus terrain uses NAVD88, so this lines the two up.
 */
export const GEOID_UNDULATION = -28.5;
const MIB = 1024 * 1024;

export type WorldCredentials = { googleKey?: string; ionToken?: string };
/** errorTarget: screen-space error in pixels before a tile refines (higher = coarser, fewer requests). */
export type TileBudget = { errorTarget: number; cacheMB: number; downloads: number };
export type WorldStatus = { state: "loading" | "ready" | "error"; message?: string; attributions: string[] };

/** Browser-visible credentials, in the order gods-eye-view tries them: a Google key, then ion. */
export function worldCredentials(): WorldCredentials | null {
  // literal process.env reads so Next inlines them at build time
  const googleKey = process.env.NEXT_PUBLIC_GOOGLE_MAPS_3D_KEY?.trim();
  const ionToken = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN?.trim();
  return googleKey || ionToken ? { googleKey, ionToken } : null;
}

export class WorldContext {
  readonly tiles: TilesRenderer;
  private readonly dracoLoader = new DRACOLoader().setDecoderPath("/draco/");
  // shared by every tile material: the campus cut-out and a light multiplier for time of day
  private readonly uniforms = {
    campusMin: { value: new THREE.Vector2() },
    campusMax: { value: new THREE.Vector2() },
    campusTint: { value: new THREE.Color(1, 1, 1) },
  };
  private attributions = "";
  private failed = false;

  constructor(
    frame: CampusFrame,
    credentials: WorldCredentials,
    private readonly budget: TileBudget,
    private readonly onChange: () => void,
    private readonly onStatus: (status: WorldStatus) => void,
  ) {
    const tiles = new TilesRenderer();
    if (credentials.googleKey) tiles.registerPlugin(new GoogleCloudAuthPlugin({ apiToken: credentials.googleKey, autoRefreshToken: true }));
    else tiles.registerPlugin(new CesiumIonAuthPlugin({ apiToken: credentials.ionToken!, assetId: ION_GOOGLE_ASSET, autoRefreshToken: true }));
    tiles.registerPlugin(new GLTFExtensionsPlugin({ dracoLoader: this.dracoLoader }));
    this.tiles = tiles;
    this.applyBudget();

    tiles.group.name = "world-context";
    tiles.group.matrixAutoUpdate = false;
    tiles.group.matrix.copy(campusFromEcef(tiles, frame));
    tiles.group.matrixWorldNeedsUpdate = true;
    this.uniforms.campusMin.value.set(frame.minX, frame.minZ);
    this.uniforms.campusMax.value.set(frame.maxX, frame.maxZ);

    tiles.addEventListener("load-root-tileset", this.onRoot);
    tiles.addEventListener("load-model", this.onModel);
    tiles.addEventListener("needs-update", this.onChange);
    tiles.addEventListener("tiles-load-end", this.onLoadEnd);
    tiles.addEventListener("load-error", this.onError);
    this.onStatus({ state: "loading", attributions: [] });
  }

  get group() {
    return this.tiles.group;
  }

  /** call once per rendered frame, before drawing */
  update(camera: THREE.PerspectiveCamera, renderer: THREE.WebGLRenderer) {
    if (this.failed) return;
    this.tiles.setCamera(camera);
    this.tiles.setResolutionFromRenderer(camera, renderer);
    this.tiles.update();
    this.reportAttributions();
  }

  /** tiles are photos with baked daylight; darken them at night to sit with the lit campus */
  setLight(color: THREE.Color, intensity: number) {
    this.uniforms.campusTint.value.copy(color).multiplyScalar(intensity);
  }

  dispose() {
    const tiles = this.tiles;
    tiles.removeEventListener("load-root-tileset", this.onRoot);
    tiles.removeEventListener("load-model", this.onModel);
    tiles.removeEventListener("needs-update", this.onChange);
    tiles.removeEventListener("tiles-load-end", this.onLoadEnd);
    tiles.removeEventListener("load-error", this.onError);
    tiles.group.removeFromParent();
    tiles.dispose();
    this.dracoLoader.dispose();
  }

  // the device budget; re-applied once the root loads, since the auth plugins set their own errorTarget
  private applyBudget() {
    const { tiles, budget } = this;
    tiles.errorTarget = budget.errorTarget;
    tiles.lruCache.maxBytesSize = budget.cacheMB * MIB;
    tiles.lruCache.minBytesSize = Math.round(budget.cacheMB * 0.75) * MIB;
    tiles.downloadQueue.maxJobsPerOrigin = budget.downloads;
  }

  private readonly onRoot = () => {
    this.applyBudget();
    this.onChange();
  };

  private readonly onModel = ({ scene }: { scene: THREE.Object3D }) => {
    scene.traverse((object) => {
      const mesh = object as THREE.Mesh;
      if (!mesh.isMesh) return;
      mesh.raycast = () => {}; // context only: clicks go through to the campus
      for (const material of Array.isArray(mesh.material) ? mesh.material : [mesh.material]) this.patchMaterial(material);
    });
    this.onChange();
  };

  private readonly onLoadEnd = () => {
    if (!this.failed) this.onStatus({ state: "ready", attributions: this.attributionList() });
    this.onChange();
  };

  private readonly onError = ({ tile, error }: { tile: unknown; error: Error }) => {
    // a single tile failing is routine; the root failing means auth or quota, so stop asking
    if (tile !== null && tile !== this.tiles.root) return;
    this.failed = true;
    console.warn("Real-world surroundings unavailable", error);
    this.onStatus({ state: "error", message: error?.message || "The 3D tiles could not load", attributions: [] });
  };

  private patchMaterial(material: THREE.Material) {
    const uniforms = this.uniforms;
    material.onBeforeCompile = (shader) => {
      Object.assign(shader.uniforms, uniforms);
      shader.vertexShader = shader.vertexShader
        .replace("#include <common>", "#include <common>\nvarying vec3 vCampusWorld;")
        .replace("#include <project_vertex>", "#include <project_vertex>\nvCampusWorld = (modelMatrix * vec4(transformed, 1.0)).xyz;");
      shader.fragmentShader = shader.fragmentShader
        .replace("#include <common>", "#include <common>\nvarying vec3 vCampusWorld;\nuniform vec2 campusMin;\nuniform vec2 campusMax;\nuniform vec3 campusTint;")
        .replace("#include <clipping_planes_fragment>", "#include <clipping_planes_fragment>\nif (all(greaterThan(vCampusWorld.xz, campusMin)) && all(lessThan(vCampusWorld.xz, campusMax))) discard;")
        .replace("#include <color_fragment>", "#include <color_fragment>\ndiffuseColor.rgb *= campusTint;");
    };
    material.customProgramCacheKey = () => "campus-world-context";
    material.needsUpdate = true;
  }

  private attributionList() {
    return this.tiles.getAttributions()
      .filter((item) => item.type === "string" || item.type === "html")
      .map((item) => String(item.value).replace(/<[^>]*>/g, "").trim())
      .filter((text, index, all) => text && all.indexOf(text) === index);
  }

  private reportAttributions() {
    const list = this.attributionList();
    const joined = list.join(" | ");
    if (joined === this.attributions) return;
    this.attributions = joined;
    this.onStatus({ state: this.failed ? "error" : "ready", attributions: list });
  }
}

/**
 * ECEF -> campus frame: into east/north/up at the campus origin (scene y = 0 is baseElevation
 * NAVD88), then east/north/up -> x east, y up, z south.
 */
function campusFromEcef(tiles: TilesRenderer, frame: CampusFrame) {
  const { origin } = frame.meta.frame;
  const height = frame.meta.grid.baseElevation + GEOID_UNDULATION;
  const enu = tiles.ellipsoid.getEastNorthUpFrame(
    THREE.MathUtils.degToRad(origin.latitude), THREE.MathUtils.degToRad(origin.longitude), height, new THREE.Matrix4(),
  );
  return new THREE.Matrix4().makeRotationX(-Math.PI / 2).multiply(enu.invert());
}
