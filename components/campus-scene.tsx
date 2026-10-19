"use client";

import { DoorOpen, LocateFixed, Minus, Plus } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import type { Building } from "@/data/buildings";
import type { EnergyTechnology } from "@/data/energy-evidence";
import { CampusEngine, type CameraState, type Quality, type SceneLayers, type SceneStatus } from "./campus3d/engine";
import type { Season } from "./campus3d/trees";

type Props = {
  buildings: Building[];        // what search/filters show as markers
  allBuildings: Building[];     // everything clickable in 3D
  selected: Building | null;
  onSelect: (building: Building) => void;
  layers: SceneLayers;
  evidenceTechnology: EnergyTechnology | "all";
  time: number;
  season: string;
};

const QUALITY_KEY = "campus-scene-quality";
const MINIMAP_IMAGE = "/models/dartmouth-campus/terrain/campus-imagery-2048.jpg";
const ATTRIBUTION = [
  "Imagery: USGS The National Map / USDA NAIP",
  "Elevation: USGS 3DEP",
  "Buildings, roads & fields: © OpenStreetMap contributors (ODbL)",
  "Heights: NH GRANIT nDSM",
  "Trees: Meta & WRI canopy height (CC BY 4.0)",
];

export function CampusScene({ buildings, allBuildings, selected, onSelect, layers, evidenceTechnology, time, season }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const engineRef = useRef<CampusEngine | null>(null);
  const minimapRef = useRef<HTMLCanvasElement>(null);
  const minimapImage = useRef<HTMLImageElement | null>(null);
  const lastCamera = useRef<CameraState | null>(null);
  const onSelectRef = useRef(onSelect);
  const allRef = useRef(allBuildings);
  const [status, setStatus] = useState<SceneStatus>({ phase: "loading", message: "Preparing the campus", progress: 0 });
  const [modelVisible, setModelVisible] = useState(true);
  const [quality, setQuality] = useState<Quality | "auto">("auto");
  const [attempt, setAttempt] = useState(0);
  const [showCredits, setShowCredits] = useState(false);
  // latest props for the engine's initial state without re-creating it on every change
  const latest = useRef({ buildings, allBuildings, layers, evidenceTechnology, time, season, selected, modelVisible });
  latest.current = { buildings, allBuildings, layers, evidenceTechnology, time, season, selected, modelVisible };

  useEffect(() => { onSelectRef.current = onSelect; }, [onSelect]);
  useEffect(() => { allRef.current = allBuildings; }, [allBuildings]);
  useEffect(() => {
    try { const saved = window.localStorage.getItem(QUALITY_KEY) as Quality | "auto" | null; if (saved) setQuality(saved); } catch { /* storage unavailable */ }
  }, []);

  const drawMinimap = useCallback((camera: CameraState | null) => {
    const canvas = minimapRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (minimapImage.current?.complete) ctx.drawImage(minimapImage.current, 0, 0, canvas.width, canvas.height);
    else { ctx.fillStyle = "#24382d"; ctx.fillRect(0, 0, canvas.width, canvas.height); }
    if (!camera) return;
    const [u, v] = camera.frame.uv(camera.x, camera.z);
    const x = Math.min(1, Math.max(0, u)) * canvas.width;
    const y = Math.min(1, Math.max(0, v)) * canvas.height;
    const spread = Math.PI / 4.5;
    const reach = Math.max(14, Math.min(canvas.width * 0.6, camera.distance / (camera.frame.maxX - camera.frame.minX) * canvas.width));
    ctx.fillStyle = "rgba(217, 255, 119, 0.28)";
    ctx.beginPath();
    ctx.moveTo(x, y);
    // heading is clockwise from north; minimap y points south
    ctx.arc(x, y, reach, camera.heading - Math.PI / 2 - spread, camera.heading - Math.PI / 2 + spread);
    ctx.closePath();
    ctx.fill();
    ctx.fillStyle = "#d9ff77";
    ctx.strokeStyle = "#163f2e";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.arc(x, y, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }, []);

  useEffect(() => {
    const image = new Image();
    image.onload = () => drawMinimap(lastCamera.current);
    image.src = MINIMAP_IMAGE;
    minimapImage.current = image;
  }, [drawMinimap]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const resolved: Quality = quality === "auto" ? autoQuality() : quality;
    const initial = latest.current;
    const engine = new CampusEngine(container, {
      onSelect: (id) => {
        const building = allRef.current.find((item) => item.id === id);
        if (building) onSelectRef.current(building);
      },
      onStatus: setStatus,
      onCamera: (camera) => { lastCamera.current = camera; drawMinimap(camera); },
    }, initial.layers, resolved);
    engineRef.current = engine;
    engine.setBuildings(initial.buildings, initial.allBuildings);
    engine.setEvidenceTechnology(initial.evidenceTechnology);
    engine.setTime(initial.time);
    engine.setSeason(toSeason(initial.season));
    engine.setModelVisible(initial.modelVisible);
    void engine.load().then(() => { if (latest.current.selected) engine.setSelected(latest.current.selected.id); });
    (window as unknown as { __campusScene?: CampusEngine }).__campusScene = engine;
    return () => {
      engine.dispose();
      engineRef.current = null;
      setStatus({ phase: "loading", message: "Preparing the campus", progress: 0 });
    };
  }, [quality, attempt, drawMinimap]);

  useEffect(() => { engineRef.current?.setBuildings(buildings, allBuildings); }, [buildings, allBuildings]);
  useEffect(() => { engineRef.current?.setSelected(selected?.id ?? null); }, [selected?.id]);
  useEffect(() => { engineRef.current?.setLayers(layers); }, [layers]);
  useEffect(() => { engineRef.current?.setEvidenceTechnology(evidenceTechnology); }, [evidenceTechnology]);
  useEffect(() => { engineRef.current?.setTime(time); }, [time]);
  useEffect(() => { engineRef.current?.setSeason(toSeason(season)); }, [season]);
  useEffect(() => { engineRef.current?.setModelVisible(modelVisible); }, [modelVisible]);

  const changeQuality = (next: Quality | "auto") => {
    setQuality(next);
    try { window.localStorage.setItem(QUALITY_KEY, next); } catch { /* storage unavailable */ }
  };

  const onMinimapClick = (event: React.MouseEvent<HTMLCanvasElement>) => {
    const camera = lastCamera.current;
    if (!camera) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const u = (event.clientX - rect.left) / rect.width;
    const v = (event.clientY - rect.top) / rect.height;
    const { frame } = camera;
    engineRef.current?.lookAtLocal(frame.minX + u * (frame.maxX - frame.minX), frame.minZ + v * (frame.maxZ - frame.minZ));
  };

  return (
    <section className={`campus-map campus-scene ${selected ? "has-selection" : ""}`} aria-label="Interactive 3D map of Dartmouth College">
      <div ref={containerRef} className="campus-scene-container" />
      {status.phase === "loading" && (
        <div className="map-loading" role="status">
          <span />
          <strong>Building Dartmouth in 3D</strong>
          <small>{status.message}…</small>
          <i className="scene-progress"><b style={{ width: `${Math.round(status.progress * 100)}%` }} /></i>
        </div>
      )}
      {status.phase === "error" && (
        <div className="map-loading map-error" role="alert">
          <DoorOpen size={26} />
          <strong>The campus scene couldn’t load</strong>
          <small>{status.message}</small>
          <button className="scene-retry" onClick={() => setAttempt((value) => value + 1)}>Try again</button>
        </div>
      )}
      <div className="map-vignette" />
      {status.phase === "ready" && (
        <div className="campus-model-preview">
          <small role="status">Campus scene ready</small>
          <label><input type="checkbox" checked={modelVisible} onChange={(event) => setModelVisible(event.target.checked)} /> Show campus model</label>
          <label className="quality-select">Quality
            <select value={quality} onChange={(event) => changeQuality(event.target.value as Quality | "auto")}>
              <option value="auto">Auto</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
            </select>
          </label>
        </div>
      )}
      <canvas ref={minimapRef} className="campus-minimap" width={150} height={118} onClick={onMinimapClick} aria-label="Campus overview map; click to move the view" />
      <div className="map-controls">
        <button onClick={() => engineRef.current?.zoom("in")} aria-label="Zoom in"><Plus size={18} /></button>
        <button onClick={() => engineRef.current?.zoom("out")} aria-label="Zoom out"><Minus size={18} /></button>
        <button onClick={() => engineRef.current?.home()} aria-label="Reset Dartmouth view"><LocateFixed size={18} /></button>
        <button onClick={() => engineRef.current?.groundView()} aria-label="Ground campus view"><DoorOpen size={18} /></button>
      </div>
      <span className="north">N <i /></span>
      <button className="scene-credits-toggle" onClick={() => setShowCredits((value) => !value)} aria-expanded={showCredits}>
        Data sources
      </button>
      {showCredits && <ul className="scene-credits">{ATTRIBUTION.map((line) => <li key={line}>{line}</li>)}</ul>}
    </section>
  );
}

function toSeason(season: string): Season {
  return (["Spring", "Summer", "Fall", "Winter"].includes(season) ? season : "Fall") as Season;
}

function autoQuality(): Quality {
  const coarse = window.matchMedia?.("(pointer: coarse)").matches;
  const small = Math.min(window.innerWidth, window.innerHeight) < 700;
  const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
  if (coarse || small || (memory !== undefined && memory <= 4)) return "low";
  return "medium";
}
