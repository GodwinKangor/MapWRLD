"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { BuildingPanel } from "@/components/building-panel";
import { CampusMap } from "@/components/campus-map";
import { CheckCircle2, Compass, Cuboid, Menu, Search, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { buildings, categories, type Building } from "@/data/buildings";

export default function Home() {
  const [buildingData, setBuildingData] = useState<Building[]>(buildings);
  const [selected, setSelected] = useState<Building | null>(null);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All places");
  const [time, setTime] = useState(14);
  const [season, setSeason] = useState("Fall");
  const [layers, setLayers] = useState({
    accessibility: true,
    boundary: true,
    carbon: false,
    electric: true,
    energyNetwork: true,
    futureWork: false,
    heating: true,
  });
  const [browseOpen, setBrowseOpen] = useState(false);
  const [controlsOpen, setControlsOpen] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/buildings", { signal: controller.signal })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Building request failed")))
      .then((payload: { buildings?: Building[] }) => {
        if (payload.buildings?.length) setBuildingData(payload.buildings);
      })
      .catch((error) => {
        if (error.name !== "AbortError") console.warn("Using bundled building data", error);
      });
    return () => controller.abort();
  }, []);

  const filtered = useMemo(() => buildingData.filter((building) => {
    const matchesQuery = `${building.name} ${building.description} ${building.category}`.toLowerCase().includes(query.toLowerCase());
    return matchesQuery && (category === "All places" || building.category === category);
  }), [buildingData, query, category]);
  const productionSummary = useMemo(() => {
    const total = buildingData.length || 1;
    const ready = buildingData.filter((building) => building.assetStatus.modelStatus === "Ready").length;
    const active = buildingData.filter((building) => building.assetStatus.modelStatus === "In progress").length;
    const highPriority = buildingData.filter((building) => building.assetStatus.priority === "High").length;
    return { total, ready, active, highPriority, percent: Math.round((ready / total) * 100) };
  }, [buildingData]);

  const selectBuilding = (building: Building) => {
    setSelected(building);
    setBrowseOpen(false);
  };

  return (
    <main className={`app season-${season.toLowerCase()} ${time < 7 || time > 19 ? "night" : ""}`}>
      <header className="topbar">
        <button className="brand" onClick={() => setSelected(null)} aria-label="Dartmouth Energy Twin home">
          <span className="brand-mark"><Compass size={22} strokeWidth={1.7} /></span>
          <span>ENERGY<span>TWIN</span></span>
        </button>

        <div className="search-wrap">
          <Search size={18} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} onFocus={() => setBrowseOpen(true)} placeholder="Search Dartmouth buildings" aria-label="Search buildings" />
          {query && <button onClick={() => setQuery("")} aria-label="Clear search"><X size={16} /></button>}
        </div>

        <div className="top-actions">
          <Link className="atlas-top-link" href="/reference-atlas">Reference Atlas</Link>
          <button className="time-pill" onClick={() => setControlsOpen(!controlsOpen)}><span className="live-dot" /> Live · {formatTime(time)}</button>
          <button className="icon-button" onClick={() => setBrowseOpen(!browseOpen)} aria-label="Browse places"><Menu size={20} /></button>
        </div>
      </header>

      <CampusMap buildings={filtered} selected={selected} onSelect={selectBuilding} layers={layers} time={time} />

      <div className="place-label">
        <span>Dartmouth College</span>
        <small>Hanover, New Hampshire</small>
      </div>

      <button className="explore-hint" onClick={() => setBrowseOpen(true)}>
        <Sparkles size={15} /> {filtered.length} campus assets
      </button>

      <section className={`browse-drawer ${browseOpen ? "open" : ""}`}>
        <div className="drawer-head">
          <div><span className="eyebrow">DARTMOUTH DIGITAL TWIN</span><h2>Campus assets</h2></div>
          <button className="icon-button" onClick={() => setBrowseOpen(false)} aria-label="Close"><X size={20} /></button>
        </div>
        <div className="categories">
          {categories.map((item) => <button key={item} className={category === item ? "active" : ""} onClick={() => setCategory(item)}>{item}</button>)}
        </div>
        <div className="place-list">
          {filtered.map((building) => (
            <button className="place-card" key={building.id} onClick={() => selectBuilding(building)}>
              <div className={`card-image ${building.imageClass}`}><span>{building.shortCode}</span></div>
              <div><span className="category-label">{building.category}</span><h3>{building.name}</h3><p>{building.subtitle}</p></div>
              <span className={`status ${building.open ? "is-open" : ""}`}>{building.open ? "Open" : "Closed"}</span>
              <small className={`model-pill model-${slugStatus(building.assetStatus.modelStatus)}`}>{building.assetStatus.modelStatus}</small>
            </button>
          ))}
          {!filtered.length && <p className="empty">No places match that search. Try another path.</p>}
        </div>
      </section>

      <section className={`environment-panel ${controlsOpen ? "open" : ""}`}>
        <div className="drawer-head"><div><span className="eyebrow">DIGITAL TWIN</span><h2>Layers & atmosphere</h2></div><button className="icon-button" onClick={() => setControlsOpen(false)}><X size={18} /></button></div>
        <div className="layer-list">
          <label><span>Campus boundary</span><input type="checkbox" checked={layers.boundary} onChange={(e) => setLayers((current) => ({ ...current, boundary: e.target.checked }))} /></label>
          <label><span>Energy network</span><input type="checkbox" checked={layers.energyNetwork} onChange={(e) => setLayers((current) => ({ ...current, energyNetwork: e.target.checked }))} /></label>
          <label><span>District heat</span><input type="checkbox" checked={layers.heating} onChange={(e) => setLayers((current) => ({ ...current, heating: e.target.checked }))} /></label>
          <label><span>Electric</span><input type="checkbox" checked={layers.electric} onChange={(e) => setLayers((current) => ({ ...current, electric: e.target.checked }))} /></label>
          <label><span>Carbon intensity</span><input type="checkbox" checked={layers.carbon} onChange={(e) => setLayers((current) => ({ ...current, carbon: e.target.checked }))} /></label>
          <label><span>Accessibility</span><input type="checkbox" checked={layers.accessibility} onChange={(e) => setLayers((current) => ({ ...current, accessibility: e.target.checked }))} /></label>
          <label><span>Future work</span><input type="checkbox" checked={layers.futureWork} onChange={(e) => setLayers((current) => ({ ...current, futureWork: e.target.checked }))} /></label>
        </div>
        <div className="readiness-card">
          <div>
            <span className="eyebrow">MODEL READINESS</span>
            <strong>{productionSummary.percent}% ready</strong>
          </div>
          <i><b style={{ width: `${productionSummary.percent}%` }} /></i>
          <div className="readiness-grid">
            <span><CheckCircle2 size={14} /> {productionSummary.ready} ready</span>
            <span><Cuboid size={14} /> {productionSummary.active} active</span>
            <span>{productionSummary.highPriority} high priority</span>
          </div>
        </div>
        <label><span>Time of day</span><strong>{formatTime(time)}</strong></label>
        <input type="range" min="0" max="23" value={time} onChange={(e) => setTime(Number(e.target.value))} />
        <div className="time-labels"><span>Midnight</span><span>Noon</span><span>Midnight</span></div>
        <label className="season-title"><span>Season</span></label>
        <div className="season-grid">{["Spring", "Summer", "Fall", "Winter"].map((item) => <button className={season === item ? "active" : ""} key={item} onClick={() => setSeason(item)}>{item}</button>)}</div>
      </section>

      <button className="controls-button" onClick={() => setControlsOpen(!controlsOpen)}><SlidersHorizontal size={18} /> Atmosphere</button>

      <BuildingPanel building={selected} onClose={() => setSelected(null)} />
    </main>
  );
}

function formatTime(hour: number) {
  const h = hour % 12 || 12;
  return `${h}:00 ${hour >= 12 ? "PM" : "AM"}`;
}

function slugStatus(status: string) {
  return status.toLowerCase().replace(/\s+/g, "-");
}
