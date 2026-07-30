"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, BadgeCheck, Building2, CheckCircle2, ClipboardList, ImageOff, Search } from "lucide-react";
import { buildings } from "@/data/buildings";

const VIEWS = [
  { id: "front", label: "Front" },
  { id: "left", label: "Left Side" },
  { id: "right", label: "Right Side" },
  { id: "back", label: "Back" },
];

const STATUSES = ["Missing", "Found", "Approved", "Modeled"];

type AtlasView = {
  id: string;
  label: string;
  path?: string;
  fov?: number;
  wallLengthMeters?: number;
  panoramaDistanceMeters?: number;
};

type AtlasBuilding = {
  id: string;
  name: string;
  shortCode: string;
  category: string;
  nextStep: string;
  modelStatus: string;
  views?: AtlasView[];
};

type ReferenceManifest = {
  mode?: string;
  buildings?: Array<{
    id: string;
    name: string;
    shortCode?: string;
    category?: string;
    views?: Record<string, {
      label?: string;
      path?: string;
      fov?: number;
      wallLengthMeters?: number;
      panoramaDistanceMeters?: number;
    }>;
  }>;
};

const bundledBuildings: AtlasBuilding[] = buildings.map((building) => ({
  id: building.id,
  name: building.name,
  shortCode: building.shortCode,
  category: building.category,
  nextStep: building.assetStatus.nextStep,
  modelStatus: building.assetStatus.modelStatus,
  views: VIEWS,
}));

export default function ReferenceAtlasPage() {
  const [query, setQuery] = useState("");
  const [atlasBuildings, setAtlasBuildings] = useState<AtlasBuilding[]>(bundledBuildings);
  const [selectedId, setSelectedId] = useState(bundledBuildings[0]?.id ?? "");
  const [statusByBuilding, setStatusByBuilding] = useState<Record<string, string>>({});
  const selected = atlasBuildings.find((building) => building.id === selectedId) ?? atlasBuildings[0];

  useEffect(() => {
    let cancelled = false;
    fetch("/reference-atlas/images/manifest.json", { cache: "no-store" })
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("No reference manifest")))
      .then((manifest: ReferenceManifest) => {
        if (cancelled || !manifest.buildings?.length) return;
        const generated = manifest.buildings.map((building) => ({
          id: building.id,
          name: building.name,
          shortCode: building.shortCode ?? makeShortCode(building.name),
          category: building.category ?? "OSM building",
          nextStep: manifest.mode === "facade" ? "Model from generated wall/facade references" : "Model from generated view references",
          modelStatus: "Generated reference",
          views: Object.entries(building.views ?? {}).map(([id, view]) => ({
            id,
            label: view.label ?? titleCase(id),
            path: view.path,
            fov: view.fov,
            wallLengthMeters: view.wallLengthMeters,
            panoramaDistanceMeters: view.panoramaDistanceMeters,
          })),
        }));
        setAtlasBuildings(generated);
        setSelectedId((current) => generated.some((building) => building.id === current) ? current : generated[0].id);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);

  const filtered = useMemo(() => atlasBuildings.filter((building) => {
    const haystack = `${building.name} ${building.shortCode} ${building.category}`.toLowerCase();
    return haystack.includes(query.toLowerCase());
  }), [atlasBuildings, query]);
  const summary = useMemo(() => {
    const values = atlasBuildings.map((building) => statusByBuilding[building.id] ?? "Missing");
    return STATUSES.map((status) => ({
      status,
      count: values.filter((value) => value === status).length,
    }));
  }, [atlasBuildings, statusByBuilding]);

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
            <p>{selected.nextStep}</p>
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
          {(selected.views?.length ? selected.views : VIEWS).map((view) => (
            <ReferenceImage buildingId={selected.id} buildingName={selected.name} key={view.id} view={view} />
          ))}
        </div>

        <section className="atlas-notes">
          <div>
            <Building2 size={18} />
            <span>Model status</span>
            <strong>{selected.modelStatus}</strong>
          </div>
          <div>
            <ClipboardList size={18} />
            <span>Modeling note</span>
            <strong>{selected.nextStep}</strong>
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

function ReferenceImage({
  buildingId,
  buildingName,
  view,
}: {
  buildingId: string;
  buildingName: string;
  view: AtlasView;
}) {
  const [source, setSource] = useState<"local" | "live" | "missing">("local");
  const localPath = view.path ?? `/reference-atlas/images/${buildingId}/${view.id}.jpg`;
  const src = source === "local"
    ? localPath
    : `/api/streetview?building=${encodeURIComponent(buildingId)}&view=${view.id}`;

  return (
    <figure className="reference-frame">
      {source !== "missing" && (
        <img
          src={src}
          alt={`${view.label} modeling reference for ${buildingName}`}
          onError={() => setSource(source === "local" ? "live" : "missing")}
        />
      )}
      <figcaption>
        <span>{view.label}</span>
        <small>{facadeMeta(view) ?? (source === "local" ? "Generated local reference" : "Street View heading reference")}</small>
      </figcaption>
      <div className="reference-fallback"><ImageOff size={22} /><span>No image configured</span></div>
    </figure>
  );
}

function facadeMeta(view: { fov?: number; wallLengthMeters?: number; panoramaDistanceMeters?: number }) {
  const details = [
    view.wallLengthMeters ? `${view.wallLengthMeters}m wall` : null,
    view.panoramaDistanceMeters ? `${view.panoramaDistanceMeters}m camera` : null,
    view.fov ? `${view.fov} deg FOV` : null,
  ].filter(Boolean);
  return details.length ? details.join(" · ") : null;
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
