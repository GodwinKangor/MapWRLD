"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { ArrowLeft, BadgeCheck, Building2, CheckCircle2, ClipboardList, ImageOff, Search } from "lucide-react";
import { buildings } from "@/data/buildings";

const VIEWS = [
  { id: "front", label: "Front" },
  { id: "left", label: "Left Side" },
  { id: "right", label: "Right Side" },
  { id: "back", label: "Back" },
];

const STATUSES = ["Missing", "Found", "Approved", "Modeled"];

export default function ReferenceAtlasPage() {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(buildings[0]?.id ?? "");
  const [statusByBuilding, setStatusByBuilding] = useState<Record<string, string>>({});
  const selected = buildings.find((building) => building.id === selectedId) ?? buildings[0];
  const filtered = useMemo(() => buildings.filter((building) => {
    const haystack = `${building.name} ${building.shortCode} ${building.category} ${building.description}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  }), [query]);
  const summary = useMemo(() => {
    const values = buildings.map((building) => statusByBuilding[building.id] ?? "Missing");
    return STATUSES.map((status) => ({
      status,
      count: values.filter((value) => value === status).length,
    }));
  }, [statusByBuilding]);

  const setStatus = (status: string) => {
    if (!selected) return;
    setStatusByBuilding((current) => ({ ...current, [selected.id]: status }));
  };

  if (!selected) return null;

  return (
    <main className="atlas-page">
      <aside className="atlas-sidebar">
        <Link href="/" className="atlas-back"><ArrowLeft size={17} /> Energy Twin</Link>
        <div className="atlas-title">
          <span className="eyebrow">MODELING REFERENCES</span>
          <h1>Dartmouth Building Reference Atlas</h1>
        </div>

        <div className="atlas-search">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search buildings" />
        </div>

        <div className="atlas-summary">
          {summary.map((item) => (
            <div key={item.status}>
              <strong>{item.count}</strong>
              <span>{item.status}</span>
            </div>
          ))}
        </div>

        <div className="atlas-building-list">
          {filtered.map((building) => {
            const status = statusByBuilding[building.id] ?? "Missing";
            return (
              <button
                className={building.id === selected.id ? "active" : ""}
                key={building.id}
                onClick={() => setSelectedId(building.id)}
              >
                <span>{building.shortCode}</span>
                <div>
                  <strong>{building.name}</strong>
                  <small>{building.category} · {status}</small>
                </div>
              </button>
            );
          })}
        </div>
      </aside>

      <section className="atlas-workspace">
        <header className="atlas-header">
          <div>
            <span className="eyebrow">{selected.category} · {selected.shortCode}</span>
            <h2>{selected.name}</h2>
            <p>{selected.assetStatus.nextStep}</p>
          </div>
          <div className="atlas-status">
            {STATUSES.map((status) => (
              <button
                className={(statusByBuilding[selected.id] ?? "Missing") === status ? "active" : ""}
                key={status}
                onClick={() => setStatus(status)}
              >
                {status === "Modeled" ? <BadgeCheck size={14} /> : <CheckCircle2 size={14} />}
                {status}
              </button>
            ))}
          </div>
        </header>

        <div className="reference-grid">
          {VIEWS.map((view) => (
            <figure className="reference-frame" key={view.id}>
              <img
                src={`/api/streetview?building=${encodeURIComponent(selected.id)}&view=${view.id}`}
                alt={`${view.label} modeling reference for ${selected.name}`}
              />
              <figcaption>
                <span>{view.label}</span>
                <small>Street View heading reference</small>
              </figcaption>
              <div className="reference-fallback"><ImageOff size={22} /><span>No image configured</span></div>
            </figure>
          ))}
        </div>

        <section className="atlas-notes">
          <div>
            <Building2 size={18} />
            <span>Model status</span>
            <strong>{selected.assetStatus.modelStatus}</strong>
          </div>
          <div>
            <ClipboardList size={18} />
            <span>Modeling note</span>
            <strong>{selected.assetStatus.nextStep}</strong>
          </div>
          <div>
            <CheckCircle2 size={18} />
            <span>Reference checklist</span>
            <strong>Front, sides, back, roof, scale check</strong>
          </div>
        </section>
      </section>
    </main>
  );
}
