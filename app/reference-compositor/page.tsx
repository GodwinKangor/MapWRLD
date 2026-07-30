"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Download, Eye, EyeOff, ImageOff, Layers3, RotateCcw } from "lucide-react";

type ManifestView = {
  label?: string;
  path?: string;
  source?: string;
  sourceUrl?: string;
  title?: string;
  qualityStatus?: string;
  qualityScore?: number;
  flags?: string[];
  width?: number;
  height?: number;
};

type ManifestBuilding = {
  id: string;
  name: string;
  shortCode?: string;
  category?: string;
  views?: Record<string, ManifestView>;
};

type ReferenceManifest = {
  buildings?: ManifestBuilding[];
};

type CompositeLayer = {
  id: string;
  label: string;
  path: string;
  source?: string;
  title?: string;
};

type BlendMode = "source-over" | "multiply" | "screen" | "overlay";

type LayerSettings = {
  visible: boolean;
  opacity: number;
  scale: number;
  x: number;
  y: number;
  rotate: number;
  blendMode: BlendMode;
};

const DEFAULT_LAYER: LayerSettings = {
  visible: true,
  opacity: 0.68,
  scale: 1,
  x: 0,
  y: 0,
  rotate: 0,
  blendMode: "source-over",
};

const BLEND_MODES: Array<{ value: BlendMode; label: string }> = [
  { value: "source-over", label: "Normal" },
  { value: "multiply", label: "Multiply" },
  { value: "screen", label: "Screen" },
  { value: "overlay", label: "Overlay" },
];

export default function ReferenceCompositorPage() {
  const [manifest, setManifest] = useState<ReferenceManifest | null>(null);
  const [selectedBuildingId, setSelectedBuildingId] = useState("");
  const [selectedLayerId, setSelectedLayerId] = useState("");
  const [settingsByLayer, setSettingsByLayer] = useState<Record<string, LayerSettings>>({});

  useEffect(() => {
    fetch("/reference-atlas/images/manifest.json", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("No manifest")))
      .then((nextManifest: ReferenceManifest) => {
        setManifest(nextManifest);
        const first = nextManifest.buildings?.find((building) => Object.keys(building.views ?? {}).length);
        if (!first) return;
        setSelectedBuildingId(first.id);
        const firstLayer = getLayers(first)[0];
        if (firstLayer) setSelectedLayerId(firstLayer.id);
      })
      .catch(() => setManifest({ buildings: [] }));
  }, []);

  const buildings = manifest?.buildings ?? [];
  const selectedBuilding = buildings.find((building) => building.id === selectedBuildingId) ?? buildings[0];
  const layers = useMemo(() => selectedBuilding ? getLayers(selectedBuilding) : [], [selectedBuilding]);
  const selectedLayer = layers.find((layer) => layer.id === selectedLayerId) ?? layers[0];
  const selectedSettings = selectedLayer ? getLayerSettings(settingsByLayer, selectedLayer.id) : DEFAULT_LAYER;

  const updateLayer = (layerId: string, patch: Partial<LayerSettings>) => {
    setSettingsByLayer((current) => ({
      ...current,
      [layerId]: { ...getLayerSettings(current, layerId), ...patch },
    }));
  };

  const chooseBuilding = (buildingId: string) => {
    const nextBuilding = buildings.find((building) => building.id === buildingId);
    const nextLayer = nextBuilding ? getLayers(nextBuilding)[0] : null;
    setSelectedBuildingId(buildingId);
    setSelectedLayerId(nextLayer?.id ?? "");
  };

  const resetSelected = () => {
    if (!selectedLayer) return;
    updateLayer(selectedLayer.id, DEFAULT_LAYER);
  };

  const exportComposite = async () => {
    if (!selectedBuilding || !layers.length) return;
    const canvas = document.createElement("canvas");
    canvas.width = 1800;
    canvas.height = 1100;
    const context = canvas.getContext("2d");
    if (!context) return;

    context.fillStyle = "#ece9df";
    context.fillRect(0, 0, canvas.width, canvas.height);
    context.strokeStyle = "rgba(22,35,28,.18)";
    context.lineWidth = 2;
    context.strokeRect(70, 70, canvas.width - 140, canvas.height - 140);

    for (const layer of layers) {
      const settings = getLayerSettings(settingsByLayer, layer.id);
      if (!settings.visible) continue;
      const image = await loadImage(layer.path);
      const baseScale = Math.min((canvas.width * 0.82) / image.naturalWidth, (canvas.height * 0.78) / image.naturalHeight);
      const width = image.naturalWidth * baseScale * settings.scale;
      const height = image.naturalHeight * baseScale * settings.scale;
      context.save();
      context.globalAlpha = settings.opacity;
      context.globalCompositeOperation = settings.blendMode;
      context.translate(canvas.width / 2 + settings.x * 2.4, canvas.height / 2 + settings.y * 2.4);
      context.rotate((settings.rotate * Math.PI) / 180);
      context.drawImage(image, -width / 2, -height / 2, width, height);
      context.restore();
    }

    context.globalCompositeOperation = "source-over";
    context.fillStyle = "#16231c";
    context.font = "700 32px Arial";
    context.fillText(`${selectedBuilding.name} composite reference`, 82, 52);
    context.font = "20px Arial";
    context.fillText("Layered from approved/candidate atlas images. Verify wall continuity before modeling.", 82, canvas.height - 32);

    const link = document.createElement("a");
    link.download = `${selectedBuilding.id}-facade-composite.png`;
    link.href = canvas.toDataURL("image/png");
    link.click();
  };

  return (
    <main className="compositor-page">
      <aside className="compositor-sidebar">
        <Link href="/reference-atlas" className="atlas-back"><ArrowLeft size={17} /> Reference Atlas</Link>
        <div className="atlas-title">
          <span className="eyebrow">FREE REFERENCE COMPOSITOR</span>
          <h1>Facade Composite Workbench</h1>
        </div>

        <div className="compositor-building-list">
          {buildings.filter((building) => getLayers(building).length).map((building) => (
            <button
              className={building.id === selectedBuilding?.id ? "active" : ""}
              key={building.id}
              onClick={() => chooseBuilding(building.id)}
            >
              <span>{building.shortCode ?? makeShortCode(building.name)}</span>
              <strong>{building.name}</strong>
              <small>{getLayers(building).length} reference images</small>
            </button>
          ))}
        </div>
      </aside>

      <section className="compositor-workspace">
        <header className="atlas-header">
          <div>
            <span className="eyebrow">{selectedBuilding?.category ?? "Composite"}</span>
            <h2>{selectedBuilding?.name ?? "No references yet"}</h2>
            <p>Stack useful free images, line up shared windows/edges, and export a modeling reference without paying for image generation.</p>
          </div>
          <button className="compositor-export" onClick={exportComposite} disabled={!layers.length}>
            <Download size={16} />
            Export PNG
          </button>
        </header>

        <div className="compositor-grid">
          <div className="composite-stage" aria-label="Composite preview">
            {layers.length ? layers.map((layer) => {
              const settings = getLayerSettings(settingsByLayer, layer.id);
              return (
                <img
                  className={layer.id === selectedLayer?.id ? "active" : ""}
                  key={layer.id}
                  src={layer.path}
                  alt={`${layer.label} layer for ${selectedBuilding?.name}`}
                  style={{
                    opacity: settings.visible ? settings.opacity : 0,
                    mixBlendMode: settings.blendMode === "source-over" ? "normal" : settings.blendMode,
                    transform: `translate(calc(-50% + ${settings.x}px), calc(-50% + ${settings.y}px)) rotate(${settings.rotate}deg) scale(${settings.scale})`,
                  }}
                  onClick={() => setSelectedLayerId(layer.id)}
                />
              );
            }) : (
              <div className="composite-empty"><ImageOff size={30} /><span>Generate reference candidates first</span></div>
            )}
          </div>

          <aside className="composite-controls">
            <div className="control-head">
              <Layers3 size={18} />
              <strong>Layers</strong>
            </div>

            <div className="layer-list-panel">
              {layers.map((layer) => {
                const settings = getLayerSettings(settingsByLayer, layer.id);
                return (
                  <button
                    className={layer.id === selectedLayer?.id ? "active" : ""}
                    key={layer.id}
                    onClick={() => setSelectedLayerId(layer.id)}
                  >
                    <span>{settings.visible ? <Eye size={15} /> : <EyeOff size={15} />}</span>
                    <div>
                      <strong>{layer.label}</strong>
                      <small>{layer.source ?? "Local reference"}</small>
                    </div>
                  </button>
                );
              })}
            </div>

            {selectedLayer && (
              <div className="transform-panel">
                <div className="transform-title">
                  <strong>{selectedLayer.label}</strong>
                  <button onClick={resetSelected} title="Reset selected layer"><RotateCcw size={15} /></button>
                </div>

                <label>
                  <span>Visible</span>
                  <input
                    checked={selectedSettings.visible}
                    type="checkbox"
                    onChange={(event) => updateLayer(selectedLayer.id, { visible: event.target.checked })}
                  />
                </label>
                <Range label="Opacity" max={1} min={0} step={0.01} value={selectedSettings.opacity} onChange={(value) => updateLayer(selectedLayer.id, { opacity: value })} />
                <Range label="Scale" max={2.6} min={0.35} step={0.01} value={selectedSettings.scale} onChange={(value) => updateLayer(selectedLayer.id, { scale: value })} />
                <Range label="X" max={360} min={-360} step={1} value={selectedSettings.x} onChange={(value) => updateLayer(selectedLayer.id, { x: value })} />
                <Range label="Y" max={260} min={-260} step={1} value={selectedSettings.y} onChange={(value) => updateLayer(selectedLayer.id, { y: value })} />
                <Range label="Rotate" max={12} min={-12} step={0.1} value={selectedSettings.rotate} onChange={(value) => updateLayer(selectedLayer.id, { rotate: value })} />

                <label>
                  <span>Blend</span>
                  <select
                    value={selectedSettings.blendMode}
                    onChange={(event) => updateLayer(selectedLayer.id, { blendMode: event.target.value as BlendMode })}
                  >
                    {BLEND_MODES.map((mode) => <option key={mode.value} value={mode.value}>{mode.label}</option>)}
                  </select>
                </label>

                {selectedLayer.title && <p>{selectedLayer.title}</p>}
              </div>
            )}
          </aside>
        </div>
      </section>
    </main>
  );
}

function Range({
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  step: number;
  value: number;
}) {
  return (
    <label>
      <span>{label}</span>
      <input max={max} min={min} step={step} type="range" value={value} onChange={(event) => onChange(Number(event.target.value))} />
      <em>{Number.isInteger(value) ? value : value.toFixed(2)}</em>
    </label>
  );
}

function getLayers(building: ManifestBuilding): CompositeLayer[] {
  return Object.entries(building.views ?? {})
    .filter(([, view]) => Boolean(view.path))
    .map(([id, view]) => ({
      id,
      label: view.label ?? titleCase(id),
      path: view.path ?? "",
      source: view.source,
      title: view.title,
    }));
}

function getLayerSettings(settingsByLayer: Record<string, LayerSettings>, layerId: string): LayerSettings {
  return settingsByLayer[layerId] ?? DEFAULT_LAYER;
}

function loadImage(src: string) {
  return new Promise<HTMLImageElement>((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = reject;
    image.src = src;
  });
}

function makeShortCode(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((word) => word[0]?.toUpperCase())
    .join("") || "OSM";
}

function titleCase(value: string) {
  return value.replace(/[-_]/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
