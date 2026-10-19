"use client";

import { installCampusControls, type CameraCesiumApi } from "./campus-camera";
import { loadCampusTrees, type TreeCesiumApi, type TreeModel } from "./campus-trees";
import { applyCampusGround, sampleCampusGround, type GroundedModel, type TerrainCesiumApi } from "./campus-terrain";
import type { Building, Entrance } from "@/data/buildings";
import { primaryTechnology, technologyColors, type EnergyTechnology } from "@/data/energy-evidence";
import { DoorOpen, LocateFixed, Minus, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Props = {
  buildings: Building[];
  selected: Building | null;
  onSelect: (building: Building) => void;
  layers: {
    accessibility: boolean;
    boundary: boolean;
    carbon: boolean;
    electric: boolean;
    energyNetwork: boolean;
    futureWork: boolean;
    heating: boolean;
    evidence: boolean;
    roads: boolean;
    fields: boolean;
    trees: boolean;
  };
  evidenceTechnology: EnergyTechnology | "all";
  time: number;
};

type CampusModelManifest = {
  campusModel: string;
  evidenceModel?: string;
  terrainAnchors: string;
  georeference: { longitudePerMeter: number; latitudePerMeter: number };
  status: "pending" | "ready";
  units: string;
  origin: {
    longitude: number;
    latitude: number;
    heightMeters: number;
  };
  fallback: string;
};

type CampusModel = Omit<GroundedModel, "getNode"> & {
  getNode: (name: string) => { matrix: unknown; show: boolean } | undefined;
  color?: unknown;
  colorBlendMode?: unknown;
  colorBlendAmount?: number;
};
type CampusPlacement = { modelMatrix: unknown; placements: Awaited<ReturnType<typeof sampleCampusGround>>; evidenceUrl?: string };
type RoadPrimitive = { show: boolean };
type CampusField = {
  osmId: string;
  name: string;
  kind: string;
  axisRadians: number;
  lengthMeters: number;
  outer: [number, number][];
  holes: [number, number][][];
  markings: [number, number][][];
};
type CampusRoad = { osmId: string; part: number; name: string; highway: string; coordinates: [number, number][] };
type TwinOverlay = { model: CampusModel; roots: string[]; highlighted: Set<string> };
type MarkerEntity = { energyTwinId?: string; billboard?: { image: unknown }; label?: unknown };

type CesiumViewer = {
  camera: {
    flyTo: (options: unknown) => void;
    flyToBoundingSphere: (sphere: unknown, options: unknown) => void;
    heading: number;
    moveEnd?: {
      addEventListener: (listener: () => void) => void;
      removeEventListener: (listener: () => void) => void;
    };
    pitch: number;
    percentageChanged?: number;
    positionCartographic: { longitude: number; latitude: number; height: number };
    setView: (options: unknown) => void;
    zoomIn: (amount: number) => void;
    zoomOut: (amount: number) => void;
  };
  clock: { currentTime: unknown; shouldAnimate: boolean };
  entities: { add: (options: unknown) => MarkerEntity; getById: (id: string) => MarkerEntity | undefined; removeAll: () => void; suspendEvents: () => void; resumeEvents: () => void };
  imageryLayers: { add: (layer: unknown) => void; remove: (layer: unknown) => boolean };
  terrainProvider: unknown;
  resolutionScale: number;
  scene: {
    canvas: HTMLCanvasElement;
    globe: { cartographicLimitRectangle?: unknown; enableLighting: boolean; depthTestAgainstTerrain: boolean; show: boolean };
    maximumRenderTimeChange?: number;
    primitives: { add: (primitive: unknown) => unknown; remove: (primitive: unknown) => boolean };
    requestRenderMode?: boolean;
    requestRender: () => void;
    screenSpaceCameraController: {
      maximumZoomDistance: number;
      minimumZoomDistance: number;
    };
    clampToHeightMostDetailed: (positions: unknown[]) => Promise<unknown[]>;
  };
  destroy: () => void;
};

type CesiumApi = TerrainCesiumApi & {
  Model: { fromGltfAsync: (options: unknown) => Promise<CampusModel> };
  Transforms: { eastNorthUpToFixedFrame: (origin: unknown) => unknown };
  Axis: { X: unknown; Y: unknown };
  Ion: { defaultAccessToken: string };
  Viewer: new (element: HTMLElement, options: unknown) => CesiumViewer;
  createWorldTerrainAsync: (options?: unknown) => Promise<unknown>;
  ImageryLayer: new (provider: unknown, options?: { rectangle?: unknown }) => unknown;
  GroundPrimitive: new (options: unknown) => RoadPrimitive;
  GeometryInstance: new (options: unknown) => unknown;
  CorridorGeometry: new (options: unknown) => unknown;
  PolygonGeometry: new (options: unknown) => unknown;
  PolygonHierarchy: new (positions: unknown[], holes?: unknown[]) => unknown;
  MaterialAppearance: new (options: unknown) => unknown;
  Material: { fromType: (type: string, uniforms?: Record<string, unknown>) => unknown };
  ColorGeometryInstanceAttribute: { fromColor: (color: unknown) => unknown };
  PerInstanceColorAppearance: new (options: unknown) => unknown;
  ClassificationType: { TERRAIN: unknown };
  CornerType: { ROUNDED: unknown; MITERED: unknown };
  IonImageryProvider: { fromAssetId: (assetId: number) => Promise<unknown> };
  OpenStreetMapImageryProvider: new (options: { url: string }) => unknown;
  createOsmBuildingsAsync: () => Promise<unknown>;
  Cartesian3: {
    fromDegrees: (longitude: number, latitude: number, height?: number) => unknown;
    fromDegreesArray: (coordinates: number[]) => unknown[];
  };
  BoundingSphere: new (center: unknown, radius: number) => unknown;
  HeadingPitchRange: new (heading: number, pitch: number, range: number) => unknown;
  Color: { new (red: number, green: number, blue: number, alpha?: number): unknown; WHITE: unknown; BLACK: unknown; fromCssColorString: (color: string) => unknown };
  ColorBlendMode: { MIX: unknown };
  Rectangle: { fromDegrees: (west: number, south: number, east: number, north: number) => unknown };
  VerticalOrigin: { BOTTOM: unknown; CENTER: unknown };
  HorizontalOrigin: { CENTER: unknown };
  HeightReference: { NONE: unknown; CLAMP_TO_GROUND: unknown; CLAMP_TO_3D_TILE: unknown };
  DistanceDisplayCondition: new (near: number, far: number) => unknown;
  Math: { toDegrees: (radians: number) => number; toRadians: (degrees: number) => number };
  JulianDate: { fromDate: (date: Date) => unknown };
  ScreenSpaceEventHandler: new (canvas: HTMLCanvasElement) => { setInputAction: (action: (event: { position: unknown }) => void, type: unknown) => void; destroy: () => void };
  ScreenSpaceEventType: { LEFT_CLICK: unknown };
};

declare global { interface Window { Cesium?: CesiumApi } }

const DARTMOUTH_HOME = { longitude: -72.2884, latitude: 43.7037, height: 2450 };
const CAMPUS_BOUNDS = {
  west: -72.2972,
  south: 43.6961,
  east: -72.2785,
  north: 43.7108,
};
const CAMPUS_EDGE_HEIGHT = {
  bottom: 36,
  top: 162,
};
// Saved for a later campus-shaped mask pass. The live MVP uses the rectangular
// frame so the boundary reads like the reference map while modeling continues.
const FUTURE_CAMPUS_POLYGON = [
  -72.2973, 43.7018,
  -72.2957, 43.7042,
  -72.2926, 43.7068,
  -72.2876, 43.7081,
  -72.2822, 43.7101,
  -72.2791, 43.7096,
  -72.2788, 43.7063,
  -72.2801, 43.7032,
  -72.2795, 43.7006,
  -72.2811, 43.6983,
  -72.2832, 43.6965,
  -72.2871, 43.6968,
  -72.2895, 43.6984,
  -72.2923, 43.6991,
  -72.2967, 43.6995,
  -72.2973, 43.7018,
];
const CAMERA_LIMITS = {
  minHeight: 58,
  maxHeight: 3200,
  shallowestPitch: -8,
};
// typical campus ground (ellipsoid height, m), used when the cursor is over the void outside the campus
const CAMPUS_GROUND_HEIGHT = 168;
const ENERGY_GRAPH = {
  hub: [-72.2873, 43.7006],
  westHub: [-72.2902, 43.7027],
  northHub: [-72.2889, 43.7049],
  eastHub: [-72.2866, 43.7038],
} satisfies Record<string, [number, number]>;
const HEATING_CONNECTIONS: Array<[[number, number], [number, number]]> = [
  [ENERGY_GRAPH.hub, ENERGY_GRAPH.westHub],
  [ENERGY_GRAPH.westHub, ENERGY_GRAPH.northHub],
  [ENERGY_GRAPH.northHub, ENERGY_GRAPH.eastHub],
  [ENERGY_GRAPH.eastHub, ENERGY_GRAPH.hub],
  [ENERGY_GRAPH.northHub, [-72.28913, 43.70535]],
  [ENERGY_GRAPH.westHub, [-72.2899353, 43.7027887]],
  [ENERGY_GRAPH.westHub, [-72.29044, 43.70456]],
  [ENERGY_GRAPH.hub, [-72.28858, 43.70187]],
  [ENERGY_GRAPH.eastHub, [-72.28658, 43.70371]],
  [ENERGY_GRAPH.eastHub, [-72.28578, 43.70887]],
];
const ELECTRIC_CONNECTIONS: Array<[[number, number], [number, number]]> = [
  [[-72.2909, 43.7001], [-72.2886, 43.7016]],
  [[-72.2886, 43.7016], [-72.2869, 43.7038]],
  [[-72.2869, 43.7038], [-72.2858, 43.7089]],
  [[-72.2886, 43.7016], [-72.2902, 43.7046]],
];
const FUTURE_WORK = [
  { label: "Low-temp heat loop study", coordinates: [-72.2873, 43.7006] as [number, number] },
  { label: "Lab airflow optimization", coordinates: [-72.28578, 43.70887] as [number, number] },
  { label: "Dining heat recovery review", coordinates: [-72.29044, 43.70456] as [number, number] },
];
const CAMPUS_MODEL_MANIFEST = "/models/dartmouth-campus/model-manifest.json";
const CAMPUS_ROADS = "/models/dartmouth-campus/campus-roads.json";
const CAMPUS_FIELDS = "/models/dartmouth-campus/campus-fields.json";
// Mowing stripes (light, dark) and the stripe width they aim for. Lawns and turf pitches get
// stripes aligned to each area's long axis; other surfaces are flat fills.
const MOWING = {
  lawn: { even: "#86B85F", odd: "#78A853", stripeMeters: 8 },
  pitch: { even: "#55A84A", odd: "#46923D", stripeMeters: 5.5 },
};
// stylized ground fills; "base" areas (lawns, parks) draw first so sports surfaces on them stay visible
const FIELD_STYLES: Record<string, { color: [number, number, number]; layer: "base" | "sport" }> = {
  lawn: { color: [0.5, 0.7, 0.35], layer: "base" },
  park: { color: [0.44, 0.65, 0.31], layer: "base" },
  pitch: { color: [0.31, 0.62, 0.27], layer: "sport" },
  diamond: { color: [0.36, 0.63, 0.29], layer: "sport" },
  court: { color: [0.24, 0.55, 0.49], layer: "sport" },
  hardcourt: { color: [0.61, 0.56, 0.52], layer: "sport" },
  track: { color: [0.73, 0.33, 0.25], layer: "sport" },
  playground: { color: [0.79, 0.66, 0.42], layer: "sport" },
};
// Generated placeholder buildings only show their pin once the camera is this close (meters), like map icons in a game.
const PLACEHOLDER_PIN_MAX_DISTANCE = 1400;
// width in meters and fill color per OSM highway class; anything unlisted is drawn as a service road
const ROAD_STYLES: Record<string, { width: number; color: [number, number, number]; path?: boolean }> = {
  primary: { width: 12, color: [0.18, 0.2, 0.22] },
  secondary: { width: 10, color: [0.2, 0.22, 0.24] },
  tertiary: { width: 9, color: [0.21, 0.23, 0.25] },
  residential: { width: 7, color: [0.25, 0.27, 0.29] },
  unclassified: { width: 7, color: [0.25, 0.27, 0.29] },
  service: { width: 4.5, color: [0.3, 0.32, 0.33] },
  track: { width: 3, color: [0.48, 0.42, 0.33], path: true },
  footway: { width: 2.2, color: [0.86, 0.82, 0.72], path: true },
  path: { width: 2, color: [0.8, 0.74, 0.6], path: true },
  pedestrian: { width: 4, color: [0.88, 0.84, 0.74], path: true },
  cycleway: { width: 2.2, color: [0.62, 0.78, 0.66], path: true },
  steps: { width: 2, color: [0.74, 0.7, 0.62], path: true },
};

export function CampusMap({ buildings, selected, onSelect, layers, evidenceTechnology, time }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<CesiumViewer | null>(null);
  const campusModelRef = useRef<CampusModel | null>(null);
  const campusPlacementRef = useRef<CampusPlacement | null>(null);
  const overlayRef = useRef<Promise<TwinOverlay | null> | null>(null);
  const roadsRef = useRef<RoadPrimitive[]>([]);
  const fieldsRef = useRef<RoadPrimitive[]>([]);
  const treesRef = useRef<TreeModel | null>(null);
  // Terrain height under each marker, sampled once so pins don't re-clamp to the ground on every tile load.
  const groundRef = useRef<Map<string, number>>(new Map());
  const [groundVersion, setGroundVersion] = useState(0);
  const [modelReady, setModelReady] = useState(false);
  const [modelStatus, setModelStatus] = useState("Loading campus model…");
  const [modelVisible, setModelVisible] = useState(true);
  const clickHandlerRef = useRef<{ destroy: () => void } | null>(null);
  const cameraLimitsCleanupRef = useRef<(() => void) | null>(null);
  const flightRef = useRef(0);
  const onSelectRef = useRef(onSelect);
  const buildingsRef = useRef(buildings);
  const selectedRef = useRef(selected);
  const previousSelectionRef = useRef<Building | null>(null);
  const layersRef = useRef(layers);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);
  useEffect(() => { buildingsRef.current = buildings; }, [buildings]);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  useEffect(() => {
    layersRef.current = layers;
    roadsRef.current.forEach((primitive) => { primitive.show = layers.roads; });
    fieldsRef.current.forEach((primitive) => { primitive.show = layers.fields; });
    if (treesRef.current) treesRef.current.show = layers.trees;
    viewerRef.current?.scene.requestRender();
  }, [layers]);

  useEffect(() => {
    let cancelled = false;
    const token = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN;
    if (!token) { setStatus("error"); return; }

    loadCesium().then(async (Cesium) => {
      if (cancelled || !containerRef.current) return;
      Cesium.Ion.defaultAccessToken = token;
      const visibleBaseLayer = new Cesium.ImageryLayer(
        new Cesium.OpenStreetMapImageryProvider({ url: "https://tile.openstreetmap.org/" }),
        { rectangle: campusRectangle(Cesium) },
      );
      const terrainProvider = await Cesium.createWorldTerrainAsync({ requestVertexNormals: true });
      if (cancelled || !containerRef.current) return;
      const viewer = new Cesium.Viewer(containerRef.current, {
        animation: false,
        baseLayer: visibleBaseLayer,
        baseLayerPicker: false,
        fullscreenButton: false,
        geocoder: false,
        homeButton: false,
        infoBox: false,
        navigationHelpButton: false,
        sceneModePicker: false,
        selectionIndicator: false,
        timeline: false,
        terrainProvider,
        requestRenderMode: true,
        maximumRenderTimeChange: Infinity,
        scene3DOnly: true,
        useBrowserRecommendedResolution: true,
      });
      viewerRef.current = viewer;
      viewer.resolutionScale = 0.88;
      viewer.scene.requestRenderMode = true;
      viewer.scene.maximumRenderTimeChange = Infinity;
      viewer.clock.shouldAnimate = false;
      // Keep satellite imagery legible. The app's atmosphere layer handles
      // day/night; Cesium globe lighting can black out imagery at local night.
      viewer.scene.globe.enableLighting = false;
      viewer.scene.globe.depthTestAgainstTerrain = true;
      restrictGlobeToCampus(viewer, Cesium);
      cameraLimitsCleanupRef.current = installCampusControls(viewer as unknown as Parameters<typeof installCampusControls>[0], Cesium as unknown as CameraCesiumApi, {
        bounds: CAMPUS_BOUNDS,
        groundHeight: CAMPUS_GROUND_HEIGHT,
        minZoom: CAMERA_LIMITS.minHeight,
        maxZoom: CAMERA_LIMITS.maxHeight,
        shallowestPitch: CAMERA_LIMITS.shallowestPitch,
      });

      void loadCampusGround(viewer, Cesium, () => cancelled).then(({ fields, roads }) => {
        fieldsRef.current = fields;
        roadsRef.current = roads;
        fields.forEach((primitive) => { primitive.show = layersRef.current.fields; });
        roads.forEach((primitive) => { primitive.show = layersRef.current.roads; });
        viewer.scene.requestRender();
      });
      void loadCampusTrees(viewer, Cesium as unknown as TreeCesiumApi, () => cancelled).then((trees) => {
        treesRef.current = trees;
        if (trees) trees.show = layersRef.current.trees;
        viewer.scene.requestRender();
      }).catch((error) => console.warn("Campus trees unavailable", error));
      flyHome(viewer, Cesium);

      const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      handler.setInputAction((event) => {
        const picked = (viewer.scene as unknown as { pick: (position: unknown) => { id?: { energyTwinId?: string } } }).pick(event.position);
        const id = picked?.id?.energyTwinId;
        const building = buildingsRef.current.find((item) => item.id === id);
        if (building) onSelectRef.current(building);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      clickHandlerRef.current = handler;
      setStatus("ready");

      // Upgrade the reliable OSM fallback to satellite imagery when this token
      // has permission for Cesium's Bing Maps Aerial asset (ID 2).
      void loadAerialImagery(viewer, Cesium, visibleBaseLayer, () => cancelled);

      // Keep the working scene physically constrained to the Dartmouth tile.
      // Global OSM building tiles are intentionally off in this mode because
      // they keep rendering buildings outside the campus rectangle.
      void prepareCampusModelSlot(viewer, Cesium, () => cancelled).then((loaded) => {
        if (cancelled) return;
        if (!loaded) { setModelStatus("Campus model unavailable"); return; }
        campusModelRef.current = loaded.model;
        campusPlacementRef.current = loaded.placement;
        setModelReady(true);
        setModelStatus("Campus model grounded");
      }).catch((error) => {
        console.error("Campus model failed to load", error);
        if (!cancelled) setModelStatus("Campus model failed to load");
      });
    }).catch((error) => {
      console.error("Cesium failed to initialize", error);
      if (!cancelled) setStatus("error");
    });

    return () => {
      cancelled = true;
      cameraLimitsCleanupRef.current?.();
      cameraLimitsCleanupRef.current = null;
      clickHandlerRef.current?.destroy();
      clickHandlerRef.current = null;
      viewerRef.current?.destroy();
      viewerRef.current = null;
      campusModelRef.current = null;
      campusPlacementRef.current = null;
      overlayRef.current = null;
      roadsRef.current = [];
      fieldsRef.current = [];
      treesRef.current = null;
      previousSelectionRef.current = null;
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    if (!viewer || !Cesium || status !== "ready") return;
    viewer.entities.suspendEvents();
    viewer.entities.removeAll();
    addBuildingMarkers(viewer, Cesium, buildings, groundRef.current, selectedRef.current?.id, layers, evidenceTechnology);
    viewer.entities.resumeEvents();
    viewer.scene.requestRender();
    // Roads use their own primitive visibility toggle; selection is updated below.
  }, [buildings, layers.accessibility, layers.boundary, layers.carbon, layers.electric, layers.energyNetwork, layers.futureWork, layers.heating, layers.evidence, evidenceTechnology, groundVersion, status]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    if (!viewer || !Cesium || status !== "ready") return;
    viewer.entities.suspendEvents();
    for (const building of [previousSelectionRef.current, selected]) {
      if (!building) continue;
      const isSelected = building.id === selected?.id;
      for (const entrance of building.entrances ?? [building.entrance]) {
        const entity = viewer.entities.getById(`building:${building.id}:${entrance.id}`);
        if (!entity) continue;
        const appearance = buildingMarkerAppearance(Cesium, building, entrance, groundRef.current, isSelected);
        entity.billboard = appearance.billboard;
        entity.label = appearance.label;
      }
      const evidenceEntity = viewer.entities.getById(`evidence:${building.id}`);
      if (evidenceEntity?.billboard && building.evidence) {
        const lead = evidenceTechnology === "all" ? primaryTechnology(building.evidence) : evidenceTechnology;
        evidenceEntity.billboard.image = createEvidenceIcon(lead ? technologyColors[lead] : "#f2a33a", isSelected);
      }
    }
    previousSelectionRef.current = selected;
    viewer.entities.resumeEvents();
    viewer.scene.requestRender();
  }, [selected?.id, status]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    if (!viewer || !Cesium || status !== "ready") return;
    const missing = [...new Set(buildings.flatMap((building) => (building.entrances ?? [building.entrance]).map((entrance) => groundKey(entrance.coordinates))))]
      .filter((key) => !groundRef.current.has(key));
    if (!missing.length) return;
    let cancelled = false;
    const positions = missing.map((key) => { const [longitude, latitude] = key.split(",").map(Number); return Cesium.Cartographic.fromDegrees(longitude, latitude); });
    Cesium.sampleTerrainMostDetailed(viewer.terrainProvider, positions).then((sampled) => {
      if (cancelled) return;
      sampled.forEach((position, index) => { if (Number.isFinite(position.height)) groundRef.current.set(missing[index], position.height); });
      setGroundVersion((version) => version + 1);
    }).catch((error) => console.warn("Marker ground heights unavailable; pins stay clamped to terrain", error));
    return () => { cancelled = true; };
  }, [buildings, status]);

  // Tint the campus model's buildings that have public-record evidence for the chosen technology.
  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    const main = campusModelRef.current;
    const placement = campusPlacementRef.current;
    if (!viewer || !Cesium || !main || !placement || !modelReady) return;
    const roots = new Set(layers.evidence ? evidenceTwinRoots(buildings, evidenceTechnology) : []);
    if (!roots.size && !overlayRef.current) return;
    let stale = false;
    overlayRef.current ??= createTwinOverlay(viewer, Cesium, placement);
    void overlayRef.current.then((overlay) => {
      if (stale || !overlay) return;
      for (const root of overlay.highlighted) if (!roots.has(root)) {
        main.getNode(root)!.show = true;
        overlay.model.getNode(root)!.show = false;
      }
      for (const root of roots) if (!overlay.highlighted.has(root)) {
        const node = main.getNode(root);
        if (!node || !overlay.model.getNode(root)) { roots.delete(root); continue; }
        node.show = false;
        overlay.model.getNode(root)!.show = true;
      }
      overlay.highlighted = roots;
      overlay.model.color = Cesium.Color.fromCssColorString(evidenceTechnology === "all" ? "#f2a33a" : technologyColors[evidenceTechnology]);
      overlay.model.show = modelVisible && roots.size > 0;
      viewer.scene.requestRender();
    }).catch((error) => console.warn("Evidence highlight unavailable", error));
    return () => { stale = true; };
  }, [buildings, layers.evidence, evidenceTechnology, modelReady, modelVisible]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    if (!viewer || !Cesium || !selected) return;
    const flightId = ++flightRef.current;
    void flyToEntrance(viewer, Cesium, selected, flightId, flightRef);
    return () => { flightRef.current += 1; };
  }, [selected]);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    if (!viewer || !Cesium) return;
    const date = new Date();
    date.setHours(time, 0, 0, 0);
    viewer.clock.currentTime = Cesium.JulianDate.fromDate(date);
    viewer.scene.requestRender();
  }, [time]);

  const zoom = (direction: "in" | "out") => {
    const camera = viewerRef.current?.camera;
    if (!camera) return;
    direction === "in" ? camera.zoomIn(220) : camera.zoomOut(360);
  };

  const reset = () => {
    if (viewerRef.current && window.Cesium) flyHome(viewerRef.current, window.Cesium);
  };

  const groundView = () => {
    if (viewerRef.current && window.Cesium) flyGroundView(viewerRef.current, window.Cesium);
  };

  const updateModelPreview = (visible: boolean) => {
    setModelVisible(visible);
    if (campusModelRef.current) campusModelRef.current.show = visible;
    viewerRef.current?.scene.requestRender();
  };

  return (
    <section className={`campus-map cesium-campus ${selected ? "has-selection" : ""}`} aria-label="Interactive 3D map of Dartmouth College">
      <div ref={containerRef} className="cesium-container" />
      {status === "loading" && <div className="map-loading"><span /><strong>Building Dartmouth in 3D</strong><small>Loading terrain and campus geometry…</small></div>}
      {status === "error" && <div className="map-loading map-error"><DoorOpen size={26} /><strong>The 3D map couldn’t load</strong><small>Check NEXT_PUBLIC_CESIUM_ION_TOKEN and restart the dev server.</small></div>}
      <div className="map-vignette" />
      {status === "ready" && <div className="campus-model-preview">
        <small role="status">{modelStatus}</small>
        <label><input type="checkbox" checked={modelVisible} disabled={modelStatus !== "Campus model grounded"}
          onChange={(event) => updateModelPreview(event.target.checked)} /> Show campus model</label>

      </div>}
      <div className="map-controls">
        <button onClick={() => zoom("in")} aria-label="Zoom in"><Plus size={18} /></button>
        <button onClick={() => zoom("out")} aria-label="Zoom out"><Minus size={18} /></button>
        <button onClick={reset} aria-label="Reset Dartmouth view"><LocateFixed size={18} /></button>
        <button onClick={groundView} aria-label="Ground campus view"><DoorOpen size={18} /></button>
      </div>
      <span className="north">N <i /></span>
    </section>
  );
}

function flyHome(viewer: CesiumViewer, Cesium: CesiumApi) {
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(DARTMOUTH_HOME.longitude, DARTMOUTH_HOME.latitude - 0.00035, 2320),
    orientation: { heading: Cesium.Math.toRadians(1), pitch: Cesium.Math.toRadians(-76), roll: 0 },
    duration: 1.8,
  });
}

function flyGroundView(viewer: CesiumViewer, Cesium: CesiumApi) {
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(-72.2897, 43.7007, 210),
    orientation: { heading: Cesium.Math.toRadians(4), pitch: Cesium.Math.toRadians(-28), roll: 0 },
    duration: 1.8,
  });
}

function restrictGlobeToCampus(viewer: CesiumViewer, Cesium: CesiumApi) {
  viewer.scene.globe.cartographicLimitRectangle = Cesium.Rectangle.fromDegrees(
    CAMPUS_BOUNDS.west,
    CAMPUS_BOUNDS.south,
    CAMPUS_BOUNDS.east,
    CAMPUS_BOUNDS.north,
  );
  const scene = viewer.scene as unknown as {
    backgroundColor?: unknown;
    skyAtmosphere?: { show: boolean };
  };
  scene.backgroundColor = new Cesium.Color(0.06, 0.075, 0.065, 1);
  if (scene.skyAtmosphere) scene.skyAtmosphere.show = false;
  // The campus rectangle is the whole world: no sky, celestial bodies, haze, or horizon fog to draw.
  const world = viewer.scene as unknown as {
    skyBox?: { show: boolean };
    sun?: { show: boolean };
    moon?: { show: boolean };
    fog?: { enabled: boolean };
    globe: { showGroundAtmosphere?: boolean };
  };
  if (world.skyBox) world.skyBox.show = false;
  if (world.sun) world.sun.show = false;
  if (world.moon) world.moon.show = false;
  if (world.fog) world.fog.enabled = false;
  world.globe.showGroundAtmosphere = false;
}

function campusRectangle(Cesium: CesiumApi) {
  return Cesium.Rectangle.fromDegrees(CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.south, CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.north);
}

function insideCampus(longitude: number, latitude: number) {
  return longitude >= CAMPUS_BOUNDS.west && longitude <= CAMPUS_BOUNDS.east && latitude >= CAMPUS_BOUNDS.south && latitude <= CAMPUS_BOUNDS.north;
}

// Fields and roads are draped on the terrain (the GLB's road objects are edge-only centerlines
// with no faces). Ground primitives draw in the order they are added: lawns/parks, sports
// surfaces, paths, then vehicle roads, so crossings and courts on lawns read correctly.
async function loadCampusGround(viewer: CesiumViewer, Cesium: CesiumApi, isCancelled: () => boolean): Promise<{ fields: RoadPrimitive[]; roads: RoadPrimitive[] }> {
  const load = async <T,>(url: string, key: string): Promise<T[]> => {
    try {
      const response = await fetch(url);
      return response.ok ? ((await response.json()) as Record<string, T[]>)[key] ?? [] : [];
    } catch (error) {
      console.warn(`Campus ${key} unavailable`, error);
      return [];
    }
  };
  const [fields, roads] = await Promise.all([load<CampusField>(CAMPUS_FIELDS, "fields"), load<CampusRoad>(CAMPUS_ROADS, "roads")]);
  if (isCancelled()) return { fields: [], roads: [] };
  const color = (rgb: [number, number, number]) => ({ color: Cesium.ColorGeometryInstanceAttribute.fromColor(new Cesium.Color(...rgb, 1)) });
  const ring = (points: [number, number][]) => Cesium.Cartesian3.fromDegreesArray(points.flat());

  // Striped areas share one material per stripe count, so stripe counts are bucketed (powers of two)
  // to keep stripes near their target width without a primitive per field.
  const striped = new Map<string, { mowing: typeof MOWING.lawn; repeat: number; instances: unknown[] }>();
  const sportFills: unknown[] = [];
  const markings: unknown[] = [];
  for (const field of fields) {
    const style = FIELD_STYLES[field.kind];
    if (!style || field.outer.length < 3) continue;
    const mowingKind = field.kind === "pitch" ? "pitch" : style.layer === "base" ? "lawn" : null;
    const geometry = new Cesium.PolygonGeometry({
      polygonHierarchy: new Cesium.PolygonHierarchy(ring(field.outer), field.holes.map((hole) => new Cesium.PolygonHierarchy(ring(hole)))),
      ...(mowingKind ? { stRotation: field.axisRadians } : {}),
    });
    if (mowingKind) {
      const mowing = MOWING[mowingKind];
      const ideal = Math.max(1, field.lengthMeters / (2 * mowing.stripeMeters));
      const repeat = 2 ** Math.round(Math.log2(ideal));
      const key = `${mowingKind}:${repeat}`;
      if (!striped.has(key)) striped.set(key, { mowing, repeat, instances: [] });
      striped.get(key)!.instances.push(new Cesium.GeometryInstance({ id: field.osmId, geometry }));
    } else {
      sportFills.push(new Cesium.GeometryInstance({ id: field.osmId, geometry, attributes: color(style.color) }));
    }
    field.markings.forEach((line, index) => {
      if (line.length < 2) return;
      markings.push(new Cesium.GeometryInstance({
        id: `${field.osmId}#line${index}`,
        geometry: new Cesium.CorridorGeometry({ positions: ring(line), width: 0.5, cornerType: Cesium.CornerType.MITERED }),
        attributes: color([0.97, 0.97, 0.93]),
      }));
    });
  }

  const roadBatches: Record<"paths" | "roads", unknown[]> = { paths: [], roads: [] };
  for (const road of roads) {
    const coordinates = road.coordinates.filter((point, index, all) => index === 0 || point[0] !== all[index - 1][0] || point[1] !== all[index - 1][1]);
    if (coordinates.length < 2) continue;
    const style = ROAD_STYLES[road.highway] ?? ROAD_STYLES.service;
    roadBatches[style.path ? "paths" : "roads"].push(new Cesium.GeometryInstance({
      id: `${road.osmId}#${road.part}`,
      geometry: new Cesium.CorridorGeometry({ positions: ring(coordinates), width: style.width, cornerType: Cesium.CornerType.ROUNDED }),
      attributes: color(style.color),
    }));
  }

  const add = (instances: unknown[], appearance?: unknown) => viewer.scene.primitives.add(new Cesium.GroundPrimitive({
    geometryInstances: instances,
    appearance: appearance ?? new Cesium.PerInstanceColorAppearance({ flat: true, translucent: false }),
    classificationType: Cesium.ClassificationType.TERRAIN,
    allowPicking: false,
    asynchronous: true,
  })) as RoadPrimitive;
  const stripes = ({ mowing, repeat }: { mowing: typeof MOWING.lawn; repeat: number }) => new Cesium.MaterialAppearance({
    flat: true,
    translucent: false,
    // vertical stripes alternate along s, which stRotation turns onto the field's long axis
    material: Cesium.Material.fromType("Stripe", {
      evenColor: Cesium.Color.fromCssColorString(mowing.even),
      oddColor: Cesium.Color.fromCssColorString(mowing.odd),
      repeat,
      horizontal: false,
    }),
  });
  const stripeGroups = [...striped.values()].sort((a, b) => (a.mowing === b.mowing ? 0 : a.mowing === MOWING.lawn ? -1 : 1));
  return {
    // lawns, then pitches, then other sports surfaces, then the white lines on top
    fields: [
      ...stripeGroups.map((group) => add(group.instances, stripes(group))),
      ...(sportFills.length ? [add(sportFills)] : []),
      ...(markings.length ? [add(markings)] : []),
    ],
    roads: [roadBatches.paths, roadBatches.roads].filter((batch) => batch.length).map((batch) => add(batch)),
  };
}

async function flyToEntrance(
  viewer: CesiumViewer,
  Cesium: CesiumApi,
  building: Building,
  flightId: number,
  flightRef: React.MutableRefObject<number>,
) {
  // Hanover has limited photogrammetry coverage. Target a doorway-height point
  // just above Dartmouth's local ground elevation instead of clamping to a roof.
  const entranceTarget = Cesium.Cartesian3.fromDegrees(
    building.entrance.coordinates[0],
    building.entrance.coordinates[1],
    168,
  );
  if (flightRef.current !== flightId) return;

  const target = new Cesium.BoundingSphere(entranceTarget, 3);
  const heading = Cesium.Math.toRadians(building.entrance.heading);
  viewer.camera.flyToBoundingSphere(target, {
    offset: new Cesium.HeadingPitchRange(heading, Cesium.Math.toRadians(-30), 180),
    duration: 1.55,
    complete: () => {
      if (flightRef.current !== flightId) return;
      viewer.camera.flyToBoundingSphere(target, {
        offset: new Cesium.HeadingPitchRange(heading, Cesium.Math.toRadians(-14), 72),
        duration: 1.25,
      });
    },
  });
}

async function loadEnhancedGeometry(viewer: CesiumViewer, Cesium: CesiumApi, isCancelled: () => boolean) {
  try {
    const osmBuildings = await Cesium.createOsmBuildingsAsync();
    if (!isCancelled()) viewer.scene.primitives.add(osmBuildings);
  } catch (error) {
    console.warn("Dartmouth 3D buildings could not be loaded", error);
  }
}

async function prepareCampusModelSlot(viewer: CesiumViewer, Cesium: CesiumApi, isCancelled: () => boolean) {
  const response = await fetch(CAMPUS_MODEL_MANIFEST, { cache: "no-store" });
  if (!response.ok || isCancelled()) return;
  const manifest = await response.json() as CampusModelManifest;
  if (manifest.status !== "ready") {
    console.info("Campus model placeholder active:", manifest.fallback);
    return;
  }
  if (isCancelled()) return;
  const modelMatrix = Cesium.Transforms.eastNorthUpToFixedFrame(Cesium.Cartesian3.fromDegrees(
    manifest.origin.longitude, manifest.origin.latitude, manifest.origin.heightMeters,
  ));
  const placements = await sampleCampusGround(
    Cesium, viewer.terrainProvider, modelMatrix, manifest.terrainAnchors,
    { ...manifest.origin, ...manifest.georeference }, isCancelled,
  );
  if (isCancelled()) return;
  const model = await Cesium.Model.fromGltfAsync({
    url: manifest.campusModel,
    modelMatrix,
    show: false,
    // Blender exports east/up/south; preserve east when rotating Y-up to Z-up.
    upAxis: Cesium.Axis.Y,
    forwardAxis: Cesium.Axis.X,
    minimumPixelSize: 0,
  });
  if (isCancelled()) { model.destroy(); return; }
  const placement: CampusPlacement = { modelMatrix, placements, evidenceUrl: manifest.evidenceModel };
  return await new Promise<{ model: CampusModel; placement: CampusPlacement }>((resolve, reject) => {
    const ground = () => {
      if (isCancelled()) { resolve({ model, placement }); return; }
      try {
        applyCampusGround(model, placements);
        for (const anchor of placements) {
          if (insideCampus(Cesium.Math.toDegrees(anchor.longitude), Cesium.Math.toDegrees(anchor.latitude))) continue;
          const node = model.getNode(anchor.node);
          if (node) node.show = false;
        }
        model.show = true;
        viewer.scene.requestRender();
        resolve({ model, placement });
      } catch (error) {
        viewer.scene.primitives.remove(model);
        reject(error);
      }
    };
    if (!model.ready) {
      const removeListener = model.readyEvent.addEventListener(() => { removeListener(); ground(); });
    }
    viewer.scene.primitives.add(model);
    if (model.ready) ground();
    viewer.scene.requestRender();
  });
}

function evidenceTwinRoots(buildings: Building[], technology: EnergyTechnology | "all") {
  return buildings
    .filter((building) => building.evidence && (technology === "all" || building.evidence.technologies.some(({ id }) => id === technology)))
    .flatMap((building) => building.evidence!.twinObjects.map((name) => `part::${name}`));
}

// This compact GLB contains only the buildings in the evidence index, preserving
// their terrain and height transforms. No full-campus duplicate is instantiated.
async function createTwinOverlay(viewer: CesiumViewer, Cesium: CesiumApi, placement: CampusPlacement): Promise<TwinOverlay | null> {
  if (!placement.evidenceUrl) return null;
  const response = await fetch(placement.evidenceUrl);
  if (!response.ok) return null;
  const bytes = new Uint8Array(await response.arrayBuffer());
  const roots = glbSceneRoots(bytes);
  const model = await Cesium.Model.fromGltfAsync({
    gltf: bytes,
    modelMatrix: placement.modelMatrix,
    show: false,
    upAxis: Cesium.Axis.Y,
    forwardAxis: Cesium.Axis.X,
    minimumPixelSize: 0,
    colorBlendMode: Cesium.ColorBlendMode.MIX,
    colorBlendAmount: 0.72,
  });
  viewer.scene.primitives.add(model);
  if (!model.ready) await new Promise<void>((resolve) => { const remove = model.readyEvent.addEventListener(() => { remove(); resolve(); }); });
  const rootSet = new Set(roots);
  applyCampusGround(model, placement.placements.filter((position) => rootSet.has(position.node)));
  for (const root of roots) { const node = model.getNode(root); if (node) node.show = false; }
  return { model, roots, highlighted: new Set() };
}

// Cesium can't enumerate model nodes, so read the scene's root node names from the GLB JSON chunk.
function glbSceneRoots(bytes: Uint8Array) {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const jsonLength = view.getUint32(12, true);
  const gltf = JSON.parse(new TextDecoder().decode(bytes.subarray(20, 20 + jsonLength))) as { nodes: { name?: string }[]; scenes: { nodes: number[] }[]; scene?: number };
  return gltf.scenes[gltf.scene ?? 0].nodes.map((index) => gltf.nodes[index].name).filter((name): name is string => Boolean(name));
}

function addEvidenceMarkers(viewer: CesiumViewer, Cesium: CesiumApi, buildings: Building[], ground: Map<string, number>, technology: EnergyTechnology | "all", selectedId?: string) {
  buildings.forEach((building) => {
    const evidence = building.evidence;
    if (!evidence) return;
    const matches = technology === "all" || evidence.technologies.some(({ id }) => id === technology);
    if (!matches) return;
    const lead = technology === "all" ? primaryTechnology(evidence) : technology;
    const size = Math.round(Math.max(24, Math.min(38, 18 + Math.sqrt(evidence.candidateCount) * 3)));
    const small = isPlaceholder(building);
    const entity = viewer.entities.add({
      id: `evidence:${building.id}`,
      ...markerPosition(Cesium, ground, building.entrance.coordinates),
      billboard: {
        image: createEvidenceIcon(lead ? technologyColors[lead] : "#f2a33a", building.id === selectedId),
        width: size,
        height: size,
        verticalOrigin: Cesium.VerticalOrigin.CENTER,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        heightReference: groundReference(Cesium, ground, building.entrance.coordinates),
        // sit at the top-right of the door pin so both stay clickable
        pixelOffset: small ? { x: 11, y: -24 } : { x: 17, y: -42 },
        disableDepthTestDistance: 900,
      },
    });
    entity.energyTwinId = building.id;
  });
}

function createEvidenceIcon(color: string, selected: boolean) {
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 48 48"><circle cx="24" cy="24" r="19" fill="${color}" stroke="${selected ? "#d9ff77" : "white"}" stroke-width="${selected ? 7 : 5}"/><path d="M17 15h10l5 5v13H17Z M27 15v5h5 M20 25h9 M20 29h7" fill="none" stroke="white" stroke-width="2.6" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

async function loadAerialImagery(
  viewer: CesiumViewer,
  Cesium: CesiumApi,
  fallbackLayer: unknown,
  isCancelled: () => boolean,
) {
  try {
    const provider = await Cesium.IonImageryProvider.fromAssetId(2);
    if (isCancelled()) return;
    viewer.imageryLayers.add(new Cesium.ImageryLayer(provider, { rectangle: campusRectangle(Cesium) }));
    viewer.imageryLayers.remove(fallbackLayer);
  } catch (error) {
    console.warn("Satellite imagery unavailable; keeping the OpenStreetMap base layer.", error);
  }
}

function addBuildingMarkers(viewer: CesiumViewer, Cesium: CesiumApi, buildings: Building[], ground: Map<string, number>, selectedId?: string, layers?: Props["layers"], evidenceTechnology: EnergyTechnology | "all" = "all") {
  if (layers?.boundary ?? true) addCampusMask(viewer, Cesium);
  if (layers?.energyNetwork ?? true) {
    if (layers?.heating ?? true) addHeatingGraph(viewer, Cesium);
    if (layers?.electric ?? true) addElectricGraph(viewer, Cesium);
  }
  if (layers?.carbon ?? false) addCarbonLayer(viewer, Cesium, buildings);
  if (layers?.futureWork ?? false) addFutureWorkLayer(viewer, Cesium);
  buildings.forEach((building) => {
    const isSelected = building.id === selectedId;
    // generated placeholders get a small pin that only appears up close; curated buildings keep the full pin
    const entrances = building.entrances ?? [building.entrance];
    entrances.forEach((entrance) => {
      if (entrance.kind === "accessible" && layers?.accessibility === false) return;
      const entity = viewer.entities.add({
        id: `building:${building.id}:${entrance.id}`,
        ...markerPosition(Cesium, ground, entrance.coordinates),
        ...buildingMarkerAppearance(Cesium, building, entrance, ground, isSelected),
      });
      entity.energyTwinId = building.id;
    });
  });
  if (layers?.evidence ?? true) addEvidenceMarkers(viewer, Cesium, buildings, ground, evidenceTechnology, selectedId);
}

function buildingMarkerAppearance(Cesium: CesiumApi, building: Building, entrance: Entrance, ground: Map<string, number>, isSelected: boolean) {
  const small = isPlaceholder(building) && !isSelected;
  const isPrimary = entrance.kind === "main";
  const [width, height] = small ? [18, 22] : isPrimary ? (isSelected ? [42, 50] : [34, 41]) : (isSelected ? [31, 37] : [24, 29]);
  return {
        billboard: {
          image: doorIcon(entrance.kind),
          width,
          height,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
          horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
          heightReference: groundReference(Cesium, ground, entrance.coordinates),
          disableDepthTestDistance: 900,
          distanceDisplayCondition: small ? new Cesium.DistanceDisplayCondition(0, PLACEHOLDER_PIN_MAX_DISTANCE) : undefined,
        },
        // only the selected building carries labels; hidden labels still cost layout and texture space
        label: isSelected ? {
          text: isPrimary ? building.name : entrance.label,
          font: isPrimary ? "600 13px Manrope, sans-serif" : "600 10px Manrope, sans-serif",
          heightReference: groundReference(Cesium, ground, entrance.coordinates),
          fillColor: Cesium.Color.WHITE,
          outlineColor: Cesium.Color.BLACK,
          outlineWidth: 4,
          pixelOffset: { x: 0, y: -62 },
          showBackground: true,
          backgroundColor: { red: 0.05, green: 0.14, blue: 0.09, alpha: 0.82 },
          backgroundPadding: { x: 9, y: 6 },
          disableDepthTestDistance: 900,
        } : undefined,
  };
}

function isPlaceholder(building: Building) {
  return building.imageClass === "placeholder";
}

function groundKey([longitude, latitude]: [number, number]) {
  return `${longitude.toFixed(6)},${latitude.toFixed(6)}`;
}

// Fixed absolute height when the terrain has been sampled; otherwise fall back to per-frame clamping.
function markerPosition(Cesium: CesiumApi, ground: Map<string, number>, coordinates: [number, number]) {
  const height = ground.get(groundKey(coordinates));
  return { position: Cesium.Cartesian3.fromDegrees(coordinates[0], coordinates[1], height === undefined ? 8 : height + 1) };
}

function groundReference(Cesium: CesiumApi, ground: Map<string, number>, coordinates: [number, number]) {
  return ground.has(groundKey(coordinates)) ? Cesium.HeightReference.NONE : Cesium.HeightReference.CLAMP_TO_GROUND;
}

function addHeatingGraph(viewer: CesiumViewer, Cesium: CesiumApi) {
  const trunkMaterial = new Cesium.Color(0.96, 0.35, 0.17, 0.88);
  const branchMaterial = new Cesium.Color(0.78, 1, 0.4, 0.82);

  HEATING_CONNECTIONS.forEach(([start, end], index) => {
    viewer.entities.add({
      allowPicking: false,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([start[0], start[1], end[0], end[1]]),
        width: index < 4 ? 6 : 4,
        material: index < 4 ? trunkMaterial : branchMaterial,
        clampToGround: true,
      },
    });
  });

  Object.entries(ENERGY_GRAPH).forEach(([name, coordinates]) => {
    viewer.entities.add({
      allowPicking: false,
      position: Cesium.Cartesian3.fromDegrees(coordinates[0], coordinates[1], 12),
      point: {
        pixelSize: name === "hub" ? 15 : 11,
        color: new Cesium.Color(0.96, 0.35, 0.17, 0.95),
        outlineColor: new Cesium.Color(0.98, 1, 0.72, 0.95),
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: 900,
      },
    });
  });
}

function addElectricGraph(viewer: CesiumViewer, Cesium: CesiumApi) {
  const electricMaterial = new Cesium.Color(0.32, 0.72, 1, 0.82);
  ELECTRIC_CONNECTIONS.forEach(([start, end]) => {
    viewer.entities.add({
      allowPicking: false,
      polyline: {
        positions: Cesium.Cartesian3.fromDegreesArray([start[0], start[1], end[0], end[1]]),
        width: 3,
        material: electricMaterial,
        clampToGround: true,
      },
    });
  });
}

function addCarbonLayer(viewer: CesiumViewer, Cesium: CesiumApi, buildings: Building[]) {
  buildings.forEach((building) => {
    const color = building.energy.emissions === "High"
      ? new Cesium.Color(0.96, 0.22, 0.12, 0.72)
      : building.energy.emissions === "Medium"
        ? new Cesium.Color(1, 0.72, 0.18, 0.68)
        : new Cesium.Color(0.34, 0.86, 0.44, 0.68);
    viewer.entities.add({
      allowPicking: false,
      position: Cesium.Cartesian3.fromDegrees(building.coordinates[0], building.coordinates[1], 16),
      point: {
        pixelSize: Math.max(14, Math.min(34, building.energy.demandKw / 38)),
        color,
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: 900,
      },
    });
  });
}

function addFutureWorkLayer(viewer: CesiumViewer, Cesium: CesiumApi) {
  FUTURE_WORK.forEach((item) => {
    viewer.entities.add({
      allowPicking: false,
      position: Cesium.Cartesian3.fromDegrees(item.coordinates[0], item.coordinates[1], 18),
      label: {
        text: item.label,
        font: "600 11px Manrope, sans-serif",
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 4,
        pixelOffset: { x: 0, y: -42 },
        showBackground: true,
        backgroundColor: { red: 0.34, green: 0.12, blue: 0.42, alpha: 0.86 },
        backgroundPadding: { x: 8, y: 5 },
        disableDepthTestDistance: 900,
      },
      point: {
        pixelSize: 12,
        color: new Cesium.Color(0.86, 0.45, 1, 0.92),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: 900,
      },
    });
  });
}

function addCampusMask(viewer: CesiumViewer, Cesium: CesiumApi) {
  const liftedEdgeMaterial = new Cesium.Color(0.08, 0.095, 0.085, 0.92);
  const campusEdges = [
    [CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.south, CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.south],
    [CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.south, CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.north],
    [CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.north, CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.north],
    [CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.north, CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.south],
  ];

  campusEdges.forEach(([startLongitude, startLatitude, endLongitude, endLatitude]) => {
    viewer.entities.add({
      allowPicking: false,
      wall: {
        positions: Cesium.Cartesian3.fromDegreesArray([
          startLongitude, startLatitude,
          endLongitude, endLatitude,
        ]),
        minimumHeights: [CAMPUS_EDGE_HEIGHT.bottom, CAMPUS_EDGE_HEIGHT.bottom],
        maximumHeights: [CAMPUS_EDGE_HEIGHT.top, CAMPUS_EDGE_HEIGHT.top],
        material: liftedEdgeMaterial,
      },
    });
  });

  viewer.entities.add({
    allowPicking: false,
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray([
        CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.south,
        CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.south,
        CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.north,
        CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.north,
        CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.south,
      ]),
      width: 3,
      material: new Cesium.Color(0.78, 1, 0.4, 0.95),
      clampToGround: true,
    },
  });
}

const doorIcons = new Map<string, string>();
function doorIcon(kind: "main" | "accessible" | "exit") {
  if (!doorIcons.has(kind)) doorIcons.set(kind, createDoorIcon(kind));
  return doorIcons.get(kind)!;
}

function createDoorIcon(kind: "main" | "accessible" | "exit") {
  const fill = kind === "accessible" ? "#8ee6ff" : kind === "exit" ? "#ffffff" : "#d9ff77";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="84" height="100" viewBox="0 0 84 100"><path d="M42 2C20 2 4 19 4 40c0 29 38 58 38 58s38-29 38-58C80 19 64 2 42 2Z" fill="${fill}" stroke="white" stroke-width="6"/><path d="M29 60V25l29-6v41M29 60h29M47 43h2" fill="none" stroke="#163f2e" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function loadCesium(): Promise<CesiumApi> {
  if (window.Cesium) return Promise.resolve(window.Cesium);
  return new Promise((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>("script[data-energy-twin-cesium]");
    if (existing) {
      existing.addEventListener("load", () => window.Cesium ? resolve(window.Cesium) : reject(new Error("Cesium unavailable")), { once: true });
      existing.addEventListener("error", () => reject(new Error("Cesium script failed")), { once: true });
      return;
    }
    const stylesheet = document.createElement("link");
    stylesheet.rel = "stylesheet";
    stylesheet.href = "https://cesium.com/downloads/cesiumjs/releases/1.129/Build/Cesium/Widgets/widgets.css";
    document.head.appendChild(stylesheet);
    const script = document.createElement("script");
    script.src = "https://cesium.com/downloads/cesiumjs/releases/1.129/Build/Cesium/Cesium.js";
    script.async = true;
    script.dataset.energyTwinCesium = "true";
    script.onload = () => window.Cesium ? resolve(window.Cesium) : reject(new Error("Cesium unavailable"));
    script.onerror = () => reject(new Error("Cesium script failed"));
    document.head.appendChild(script);
  });
}
