"use client";

import { Activity, ArrowLeft, ArrowRight, Building2, ClipboardList, Clock3, DoorOpen, Flame, Gauge, MapPin, Route, Share2, Sparkles, X, Zap } from "lucide-react";
import { useEffect, useState } from "react";
import type { Building } from "@/data/buildings";

export function BuildingPanel({ building, onClose }: { building: Building | null; onClose: () => void }) {
  const [slide, setSlide] = useState(0);
  const [tab, setTab] = useState<"overview" | "energy" | "infrastructure" | "retrofit">("energy");
  const [streetViewAvailable, setStreetViewAvailable] = useState(true);
  useEffect(() => { setSlide(0); setTab("energy"); setStreetViewAvailable(true); }, [building?.id]);

  if (!building) return null;
  const totalSlides = building.gallery.length + 1;
  const next = () => setSlide((slide + 1) % totalSlides);
  const previous = () => setSlide((slide - 1 + totalSlides) % totalSlides);
  const caption = slide === 0 ? building.entrance.label : building.gallery[slide - 1];
  const demandPercent = Math.min(100, Math.round(building.energy.demandKw / 14));
  const carbonPercent = building.energy.emissions === "High" ? 86 : building.energy.emissions === "Medium" ? 58 : 28;
  const priority = building.energy.score >= 75 ? "Monitor" : building.energy.score >= 62 ? "Plan" : "Priority";
  const accessibleEntrances = (building.entrances ?? [building.entrance]).filter((entrance) => entrance.kind === "accessible").length;

  return (
    <aside className="building-panel">
      <div className={`hero-image ${building.imageClass} gallery-${slide}`}>
        {slide === 0 && streetViewAvailable && (
          <img
            className="streetview-image"
            src={`/api/streetview?building=${encodeURIComponent(building.id)}`}
            alt={`Street-level view near ${building.entrance.label} at ${building.name}`}
            onError={() => setStreetViewAvailable(false)}
          />
        )}
        {slide === 0 && streetViewAvailable && <span className="imagery-source">Street View · facing entrance</span>}
        <div className="hero-actions"><button onClick={onClose} aria-label="Close"><X size={19} /></button><button aria-label="Share"><Share2 size={18} /></button></div>
        <div className="gallery-caption"><span>{String(slide + 1).padStart(2, "0")} / {String(totalSlides).padStart(2, "0")}</span><strong>{caption}</strong></div>
        <div className="gallery-actions"><button onClick={previous}><ArrowLeft size={18} /></button><button onClick={next}><ArrowRight size={18} /></button></div>
      </div>
      <div className="panel-content">
        <span className="eyebrow">{building.category} · DARTMOUTH COLLEGE</span>
        <h1>{building.name}</h1>
        <div className="open-row"><span className={building.open ? "open-tag" : "closed-tag"}>{building.open ? "Open now" : "Closed"}</span><span><Clock3 size={15} /> {building.hours}</span></div>
        <div className="asset-tabs">
          <button className={tab === "overview" ? "active" : ""} onClick={() => setTab("overview")}><Building2 size={15} /> Overview</button>
          <button className={tab === "energy" ? "active" : ""} onClick={() => setTab("energy")}><Zap size={15} /> Energy</button>
          <button className={tab === "infrastructure" ? "active" : ""} onClick={() => setTab("infrastructure")}><Route size={15} /> Infra</button>
          <button className={tab === "retrofit" ? "active" : ""} onClick={() => setTab("retrofit")}><ClipboardList size={15} /> Retrofit</button>
        </div>

        {tab === "overview" && (
          <section className="asset-section">
            <p className="description">{building.description}</p>
            <div className="feature-list">{building.features.map((feature) => <span key={feature}><Sparkles size={13} /> {feature}</span>)}</div>
            <div className="panel-location"><MapPin size={18} /><div><strong>{building.entrance.label}</strong><span>Dartmouth College · Hanover, New Hampshire</span></div></div>
          </section>
        )}

        {tab === "energy" && (
          <section className="energy-profile">
            <div className="energy-head">
              <span className="eyebrow">ENERGY PROFILE</span>
              <strong>{building.energy.score ? `${building.energy.score}/100` : "Draft"}</strong>
            </div>
            <div className="energy-grid">
              <div><Zap size={16} /><span>Peak demand</span><strong>{building.energy.demandKw || "TBD"}{building.energy.demandKw ? " kW" : ""}</strong></div>
              <div><Activity size={16} /><span>Annual use</span><strong>{building.energy.annualMwh || "TBD"}{building.energy.annualMwh ? " MWh" : ""}</strong></div>
              <div><Flame size={16} /><span>Emissions</span><strong>{building.energy.emissions}</strong></div>
              <div><Gauge size={16} /><span>System</span><strong>{building.energy.system}</strong></div>
            </div>
            <div className="metric-bars">
              <div><label><span>Demand load</span><strong>{demandPercent}%</strong></label><i><b style={{ width: `${demandPercent}%` }} /></i></div>
              <div><label><span>Carbon signal</span><strong>{carbonPercent}%</strong></label><i><b className={`carbon-${building.energy.emissions.toLowerCase()}`} style={{ width: `${carbonPercent}%` }} /></i></div>
            </div>
            <p><strong>{building.energy.useType}</strong> · {building.energy.retrofit}</p>
          </section>
        )}

        {tab === "infrastructure" && (
          <section className="asset-section">
            <div className="inspector-list">
              <div><span>Primary system</span><strong>{building.energy.system}</strong></div>
              <div><span>Accessible entrances</span><strong>{accessibleEntrances || "Needs verification"}</strong></div>
              <div><span>Model status</span><strong>Placeholder geometry</strong></div>
            </div>
            {building.entrances && building.entrances.length > 1 && (
              <div className="entrance-list">
                <span className="entrance-list-title">Entrances & exits</span>
                {building.entrances.map((entrance) => (
                  <div key={entrance.id}><i className={`entrance-dot ${entrance.kind}`} /><span>{entrance.label}</span><small>{entrance.kind}</small></div>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "retrofit" && (
          <section className="asset-section">
            <div className="retrofit-card">
              <span>{priority}</span>
              <h3>{building.energy.retrofit}</h3>
              <p>Use this as the planning note until real facilities data, metering, and model geometry are connected.</p>
            </div>
            <div className="inspector-list">
              <div><span>Next dataset</span><strong>Meter + floor area</strong></div>
              <div><span>Model dependency</span><strong>GLB campus asset</strong></div>
            </div>
          </section>
        )}

        <button className="enter-button"><DoorOpen size={19} /> Inspect asset <ArrowRight size={18} /></button>
        <p className="preview-note">Planning estimates until live energy data is connected</p>
      </div>
    </aside>
  );
}
