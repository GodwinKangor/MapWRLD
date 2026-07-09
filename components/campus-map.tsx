"use client";

import type { Building } from "@/data/buildings";
import { DoorOpen, LocateFixed, Minus, Plus } from "lucide-react";
import { useEffect, useRef, useState } from "react";

type Props = {
  buildings: Building[];
  selected: Building | null;
  onSelect: (building: Building) => void;
  time: number;
};

type CesiumViewer = {
  camera: {
    flyTo: (options: unknown) => void;
    flyToBoundingSphere: (sphere: unknown, options: unknown) => void;
    zoomIn: (amount: number) => void;
    zoomOut: (amount: number) => void;
  };
  clock: { currentTime: unknown };
  entities: { add: (options: unknown) => { energyTwinId?: string }; removeAll: () => void };
  imageryLayers: { addImageryProvider: (provider: unknown) => unknown; remove: (layer: unknown) => boolean };
  scene: {
    canvas: HTMLCanvasElement;
    globe: { enableLighting: boolean; show: boolean };
    primitives: { add: (primitive: unknown) => unknown; remove: (primitive: unknown) => boolean };
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
  Cartesian3: { fromDegrees: (longitude: number, latitude: number, height?: number) => unknown };
  BoundingSphere: new (center: unknown, radius: number) => unknown;
  HeadingPitchRange: new (heading: number, pitch: number, range: number) => unknown;
  Color: { WHITE: unknown; BLACK: unknown };
  VerticalOrigin: { BOTTOM: unknown };
  HorizontalOrigin: { CENTER: unknown };
  HeightReference: { CLAMP_TO_GROUND: unknown; CLAMP_TO_3D_TILE: unknown };
  Math: { toRadians: (degrees: number) => number };
  JulianDate: { fromDate: (date: Date) => unknown };
  ScreenSpaceEventHandler: new (canvas: HTMLCanvasElement) => { setInputAction: (action: (event: { position: unknown }) => void, type: unknown) => void; destroy: () => void };
  ScreenSpaceEventType: { LEFT_CLICK: unknown };
};

declare global { interface Window { Cesium?: CesiumApi } }

const DARTMOUTH_HOME = { longitude: -72.2895, latitude: 43.7044, height: 1050 };

export function CampusMap({ buildings, selected, onSelect, time }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const viewerRef = useRef<CesiumViewer | null>(null);
  const clickHandlerRef = useRef<{ destroy: () => void } | null>(null);
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
      });
      viewerRef.current = viewer;
      // Keep satellite imagery legible. The app's atmosphere layer handles
      // day/night; Cesium globe lighting can black out imagery at local night.
      viewer.scene.globe.enableLighting = false;

      addBuildingMarkers(viewer, Cesium, buildingsRef.current);
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
    }).catch((error) => {
      console.error("Cesium failed to initialize", error);
      if (!cancelled) setStatus("error");
    });

    return () => {
      cancelled = true;
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
    addBuildingMarkers(viewer, Cesium, buildings, selected?.id);
  }, [buildings, selected?.id]);

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
    direction === "in" ? camera.zoomIn(180) : camera.zoomOut(180);
  };

  const reset = () => {
    if (viewerRef.current && window.Cesium) flyHome(viewerRef.current, window.Cesium);
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
      </div>
      <span className="north">N <i /></span>
    </section>
  );
}

function flyHome(viewer: CesiumViewer, Cesium: CesiumApi) {
  viewer.camera.flyTo({
    destination: Cesium.Cartesian3.fromDegrees(DARTMOUTH_HOME.longitude, DARTMOUTH_HOME.latitude - 0.0032, 690),
    orientation: { heading: 0, pitch: Cesium.Math.toRadians(-38), roll: 0 },
    duration: 1.8,
  });
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

function addBuildingMarkers(viewer: CesiumViewer, Cesium: CesiumApi, buildings: Building[], selectedId?: string) {
  buildings.forEach((building) => {
    const entrances = building.entrances ?? [building.entrance];
    entrances.forEach((entrance) => {
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
