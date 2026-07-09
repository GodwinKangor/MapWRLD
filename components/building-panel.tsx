"use client";

import { ArrowLeft, ArrowRight, Clock3, DoorOpen, MapPin, Share2, Sparkles, X } from "lucide-react";
import { useEffect, useState } from "react";
import type { Building } from "@/data/buildings";

export function BuildingPanel({ building, onClose }: { building: Building | null; onClose: () => void }) {
  const [slide, setSlide] = useState(0);
  const [streetViewAvailable, setStreetViewAvailable] = useState(true);
  useEffect(() => { setSlide(0); setStreetViewAvailable(true); }, [building?.id]);

  if (!building) return null;
  const totalSlides = building.gallery.length + 1;
  const next = () => setSlide((slide + 1) % totalSlides);
  const previous = () => setSlide((slide - 1 + totalSlides) % totalSlides);
  const caption = slide === 0 ? building.entrance.label : building.gallery[slide - 1];

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
        <p className="description">{building.description}</p>
        <div className="feature-list">{building.features.map((feature) => <span key={feature}><Sparkles size={13} /> {feature}</span>)}</div>
        <div className="panel-location"><MapPin size={18} /><div><strong>{building.entrance.label}</strong><span>Dartmouth College · Hanover, New Hampshire</span></div></div>
        {building.entrances && building.entrances.length > 1 && (
          <div className="entrance-list">
            <span className="entrance-list-title">Entrances & exits</span>
            {building.entrances.map((entrance) => (
              <div key={entrance.id}><i className={`entrance-dot ${entrance.kind}`} /><span>{entrance.label}</span><small>{entrance.kind}</small></div>
            ))}
          </div>
        )}
        <button className="enter-button"><DoorOpen size={19} /> Step inside <ArrowRight size={18} /></button>
        <p className="preview-note">Interior preview coming soon</p>
      </div>
    </aside>
  );
}
