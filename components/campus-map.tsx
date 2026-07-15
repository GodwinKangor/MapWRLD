"use client";

import type { Building } from "@/data/buildings";
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
  };
  time: number;
};

type CampusModelManifest = {
  campusModel: string;
  status: "pending" | "ready";
  units: string;
  origin: {
    longitude: number;
    latitude: number;
    heightMeters: number;
  };
  fallback: string;
};

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
  clock: { currentTime: unknown };
  entities: { add: (options: unknown) => { energyTwinId?: string }; removeAll: () => void };
  imageryLayers: { addImageryProvider: (provider: unknown) => unknown; remove: (layer: unknown) => boolean };
  resolutionScale: number;
  scene: {
    canvas: HTMLCanvasElement;
    globe: { enableLighting: boolean; show: boolean };
    maximumRenderTimeChange?: number;
    primitives: { add: (primitive: unknown) => unknown; remove: (primitive: unknown) => boolean };
    requestRenderMode?: boolean;
    screenSpaceCameraController: {
      maximumZoomDistance: number;
      minimumZoomDistance: number;
    };
    clampToHeightMostDetailed: (positions: unknown[]) => Promise<unknown[]>;
  };
  destroy: () => void;
};

type CesiumApi = {
  Ion: { defaultAccessToken: string };
  Viewer: new (element: HTMLElement, options: unknown) => CesiumViewer;
  Terrain: { fromWorldTerrain: (options?: unknown) => unknown };
  ImageryLayer: new (provider: unknown) => unknown;
  IonImageryProvider: { fromAssetId: (assetId: number) => Promise<unknown> };
  OpenStreetMapImageryProvider: new (options: { url: string }) => unknown;
  createOsmBuildingsAsync: () => Promise<unknown>;
  Cartesian3: {
    fromDegrees: (longitude: number, latitude: number, height?: number) => unknown;
    fromDegreesArray: (coordinates: number[]) => unknown[];
  };
  BoundingSphere: new (center: unknown, radius: number) => unknown;
  HeadingPitchRange: new (heading: number, pitch: number, range: number) => unknown;
  Color: { new (red: number, green: number, blue: number, alpha?: number): unknown; WHITE: unknown; BLACK: unknown };
  Rectangle: { fromDegrees: (west: number, south: number, east: number, north: number) => unknown };
  VerticalOrigin: { BOTTOM: unknown };
  HorizontalOrigin: { CENTER: unknown };
  HeightReference: { CLAMP_TO_GROUND: unknown; CLAMP_TO_3D_TILE: unknown };
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
const MASK_BOUNDS = {
  west: -72.62,
  south: 43.48,
  east: -71.98,
  north: 43.92,
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
  steepestPitch: -70,
};
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

export function CampusMap({ buildings, selected, onSelect, layers, time }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<CesiumViewer | null>(null);
  const clickHandlerRef = useRef<{ destroy: () => void } | null>(null);
  const cameraLimitsCleanupRef = useRef<(() => void) | null>(null);
  const flightRef = useRef(0);
  const onSelectRef = useRef(onSelect);
  const buildingsRef = useRef(buildings);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);
  useEffect(() => { buildingsRef.current = buildings; }, [buildings]);

  useEffect(() => {
    let cancelled = false;
    const token = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN;
    if (!token) { setStatus("error"); return; }

    loadCesium().then(async (Cesium) => {
      if (cancelled || !containerRef.current) return;
      Cesium.Ion.defaultAccessToken = token;
      const visibleBaseLayer = new Cesium.ImageryLayer(
        new Cesium.OpenStreetMapImageryProvider({ url: "https://tile.openstreetmap.org/" }),
      );
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
        terrain: Cesium.Terrain.fromWorldTerrain({ requestVertexNormals: true }),
        requestRenderMode: true,
        maximumRenderTimeChange: 0.5,
        useBrowserRecommendedResolution: true,
      });
      viewerRef.current = viewer;
      viewer.resolutionScale = 0.88;
      viewer.scene.requestRenderMode = true;
      viewer.scene.maximumRenderTimeChange = 0.5;
      // Keep satellite imagery legible. The app's atmosphere layer handles
      // day/night; Cesium globe lighting can black out imagery at local night.
      viewer.scene.globe.enableLighting = false;
      cameraLimitsCleanupRef.current = installCampusCameraLimits(viewer, Cesium);

      addBuildingMarkers(viewer, Cesium, buildingsRef.current, undefined, layers);
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

      // The base globe is usable immediately. Dartmouth's OSM geometry streams
      // in without holding the interface behind the loading screen.
      void loadEnhancedGeometry(viewer, Cesium, () => cancelled);
      void prepareCampusModelSlot(viewer, Cesium, () => cancelled);
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
    };
  }, []);

  useEffect(() => {
    const viewer = viewerRef.current;
    const Cesium = window.Cesium;
    if (!viewer || !Cesium) return;
    viewer.entities.removeAll();
    addBuildingMarkers(viewer, Cesium, buildings, selected?.id, layers);
  }, [buildings, layers, selected?.id]);

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

  return (
    <section className={`campus-map cesium-campus ${selected ? "has-selection" : ""}`} aria-label="Interactive 3D map of Dartmouth College">
      <div ref={containerRef} className="cesium-container" />
      {status === "loading" && <div className="map-loading"><span /><strong>Building Dartmouth in 3D</strong><small>Loading terrain and campus geometry…</small></div>}
      {status === "error" && <div className="map-loading map-error"><DoorOpen size={26} /><strong>The 3D map couldn’t load</strong><small>Check NEXT_PUBLIC_CESIUM_ION_TOKEN and restart the dev server.</small></div>}
      <div className="map-vignette" />
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
    destination: Cesium.Cartesian3.fromDegrees(DARTMOUTH_HOME.longitude, DARTMOUTH_HOME.latitude - 0.0005, DARTMOUTH_HOME.height),
    orientation: { heading: Cesium.Math.toRadians(1), pitch: Cesium.Math.toRadians(-70), roll: 0 },
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

function installCampusCameraLimits(viewer: CesiumViewer, Cesium: CesiumApi) {
  viewer.scene.screenSpaceCameraController.minimumZoomDistance = CAMERA_LIMITS.minHeight;
  viewer.scene.screenSpaceCameraController.maximumZoomDistance = CAMERA_LIMITS.maxHeight;
  viewer.camera.percentageChanged = 0.01;
  (viewer.scene as unknown as { cameraEventWaitTime?: number }).cameraEventWaitTime = 75;

  let clamping = false;
  const clampCamera = () => {
    if (clamping) return;
    const position = viewer.camera.positionCartographic;
    const longitude = Cesium.Math.toDegrees(position.longitude);
    const latitude = Cesium.Math.toDegrees(position.latitude);
    const height = position.height;
    const pitch = Cesium.Math.toDegrees(viewer.camera.pitch);
    const clampedLongitude = clamp(longitude, CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.east);
    const clampedLatitude = clamp(latitude, CAMPUS_BOUNDS.south, CAMPUS_BOUNDS.north);
    const clampedHeight = clamp(height, CAMERA_LIMITS.minHeight, CAMERA_LIMITS.maxHeight);
    const clampedPitch = clamp(pitch, CAMERA_LIMITS.steepestPitch, CAMERA_LIMITS.shallowestPitch);

    if (
      clampedLongitude === longitude &&
      clampedLatitude === latitude &&
      clampedHeight === height &&
      clampedPitch === pitch
    ) return;

    clamping = true;
    viewer.camera.setView({
      destination: Cesium.Cartesian3.fromDegrees(clampedLongitude, clampedLatitude, clampedHeight),
      orientation: {
        heading: viewer.camera.heading,
        pitch: Cesium.Math.toRadians(clampedPitch),
        roll: 0,
      },
    });
    window.setTimeout(() => { clamping = false; }, 0);
  };

  viewer.camera.moveEnd?.addEventListener(clampCamera);
  return () => viewer.camera.moveEnd?.removeEventListener(clampCamera);
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
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
  try {
    const response = await fetch(CAMPUS_MODEL_MANIFEST, { cache: "no-store" });
    if (!response.ok || isCancelled()) return;
    const manifest = await response.json() as CampusModelManifest;
    if (manifest.status !== "ready") {
      console.info("Campus model placeholder active:", manifest.fallback);
      return;
    }
    // Future drop-in point: load manifest.campusModel as a Cesium model once the
    // optimized GLB is exported from Maya and the manifest status is set ready.
    console.info("Campus model ready for loading", {
      model: manifest.campusModel,
      origin: Cesium.Cartesian3.fromDegrees(
        manifest.origin.longitude,
        manifest.origin.latitude,
        manifest.origin.heightMeters,
      ),
      viewerReady: Boolean(viewer.scene),
    });
  } catch (error) {
    console.warn("Campus model manifest unavailable; keeping fallback geometry.", error);
  }
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
    viewer.imageryLayers.addImageryProvider(provider);
    viewer.imageryLayers.remove(fallbackLayer);
  } catch (error) {
    console.warn("Satellite imagery unavailable; keeping the OpenStreetMap base layer.", error);
  }
}

function addBuildingMarkers(viewer: CesiumViewer, Cesium: CesiumApi, buildings: Building[], selectedId?: string, layers?: Props["layers"]) {
  if (layers?.boundary ?? true) addCampusMask(viewer, Cesium);
  if (layers?.energyNetwork ?? true) {
    if (layers?.heating ?? true) addHeatingGraph(viewer, Cesium);
    if (layers?.electric ?? true) addElectricGraph(viewer, Cesium);
  }
  if (layers?.carbon ?? false) addCarbonLayer(viewer, Cesium, buildings);
  if (layers?.futureWork ?? false) addFutureWorkLayer(viewer, Cesium);
  buildings.forEach((building) => {
    const entrances = building.entrances ?? [building.entrance];
    entrances.forEach((entrance) => {
      if (entrance.kind === "accessible" && layers?.accessibility === false) return;
      const isPrimary = entrance.kind === "main";
      const isSelected = building.id === selectedId;
      const entity = viewer.entities.add({
      position: Cesium.Cartesian3.fromDegrees(entrance.coordinates[0], entrance.coordinates[1], 8),
      billboard: {
        image: createDoorIcon(entrance.kind),
        width: isPrimary ? (isSelected ? 42 : 34) : (isSelected ? 31 : 24),
        height: isPrimary ? (isSelected ? 50 : 41) : (isSelected ? 37 : 29),
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        horizontalOrigin: Cesium.HorizontalOrigin.CENTER,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: 900,
      },
      label: {
        show: isSelected,
        text: isPrimary ? building.name : entrance.label,
        font: isPrimary ? "600 13px Manrope, sans-serif" : "600 10px Manrope, sans-serif",
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 4,
        pixelOffset: { x: 0, y: -62 },
        showBackground: true,
        backgroundColor: { red: 0.05, green: 0.14, blue: 0.09, alpha: 0.82 },
        backgroundPadding: { x: 9, y: 6 },
        disableDepthTestDistance: 900,
      },
    });
    entity.energyTwinId = building.id;
    });
  });
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
  const mutedMaterial = new Cesium.Color(0.13, 0.145, 0.14, 0.72);
  const maskStrips = [
    [MASK_BOUNDS.west, CAMPUS_BOUNDS.north, MASK_BOUNDS.east, MASK_BOUNDS.north],
    [MASK_BOUNDS.west, MASK_BOUNDS.south, MASK_BOUNDS.east, CAMPUS_BOUNDS.south],
    [MASK_BOUNDS.west, CAMPUS_BOUNDS.south, CAMPUS_BOUNDS.west, CAMPUS_BOUNDS.north],
    [CAMPUS_BOUNDS.east, CAMPUS_BOUNDS.south, MASK_BOUNDS.east, CAMPUS_BOUNDS.north],
  ];

  maskStrips.forEach(([west, south, east, north]) => {
    viewer.entities.add({
      allowPicking: false,
      rectangle: {
        coordinates: Cesium.Rectangle.fromDegrees(west, south, east, north),
        material: mutedMaterial,
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
