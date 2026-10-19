"use client";

import Link from "next/link";
import Script from "next/script";
import { useEffect, useMemo, useState } from "react";
import { ArrowLeft, Box, ImageOff, Ruler, Search } from "lucide-react";
import FbxViewer from "@/components/fbx-viewer";

const MODEL_DIR = "/models/dartmouth-energy-twin";
const QUICK_PICKS = ["dartmouth-hall", "baker-library", "mcnutt-hall"];

type ManifestBuilding = {
  name: string;
  folder: string;
  glb?: string;
  fbx?: string;
  dimensions?: { x: number; y: number; z: number };
};

type PartsManifest = { buildings: ManifestBuilding[] };

type BuildingMetadata = {
  displayName?: string;
  osmId?: string;
  vertices?: number;
  edges?: number;
  faces?: number;
  generatedDetails?: number;
  topology?: {
    looseVertices?: number;
    looseEdges?: number;
    boundaryEdges?: number;
    nonManifoldEdges?: number;
  };
};

type ReferenceImageEntry = {
  status?: string;
  path?: string;
  source?: string;
  heading?: number;
  distanceMeters?: number;
  qualityStatus?: string;
  flags?: string[];
};

type ReferencesManifest = {
  displayName?: string;
  streetView?: Record<string, ReferenceImageEntry>;
  roof?: { status?: string; path?: string };
  walls?: Array<{
    id: string;
    name?: string;
    orientation?: string;
    lengthMeters?: number;
    reference?: ReferenceImageEntry;
  }>;
};

type WallOpeningPlan = {
  reference?: string;
  windows?: number;
  doors?: number;
  floors?: number;
  countMethod?: string;
  confidence?: number;
  quality?: string;
  notes?: string;
  visionModel?: string;
};

type ModelingRules = {
  displayName?: string;
  windowsAndDoors?: { wallOpeningPlans?: Record<string, WallOpeningPlan> };
};

export default function DesignSpacePage() {
  const [manifestBuildings, setManifestBuildings] = useState<ManifestBuilding[]>([]);
  const [query, setQuery] = useState("");
  const [selectedFolder, setSelectedFolder] = useState<string>("");

  const [metadata, setMetadata] = useState<BuildingMetadata | null>(null);
  const [referencesManifest, setReferencesManifest] = useState<ReferencesManifest | null>(null);
  const [modelingRules, setModelingRules] = useState<ModelingRules | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    fetch(`${MODEL_DIR}/renders/parts-manifest.json`, { cache: "no-store" })
      .then((response) => response.json())
      .then((manifest: PartsManifest) => {
        setManifestBuildings(manifest.buildings ?? []);
        const first = manifest.buildings?.find((building) => building.folder.includes(QUICK_PICKS[0]));
        setSelectedFolder(first?.folder ?? manifest.buildings?.[0]?.folder ?? "");
      })
      .catch(() => setManifestBuildings([]));
  }, []);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return manifestBuildings;
    return manifestBuildings.filter((building) => building.name.toLowerCase().includes(needle));
  }, [manifestBuildings, query]);

  const selected = manifestBuildings.find((building) => building.folder === selectedFolder);

  useEffect(() => {
    if (!selected) return;
    let cancelled = false;
    setDetailLoading(true);
    setMetadata(null);
    setReferencesManifest(null);
    setModelingRules(null);

    const base = `${MODEL_DIR}/renders/${selected.folder}`;
    Promise.all([
      fetchJsonOrNull<BuildingMetadata>(`${base}/metadata.json`),
      fetchJsonOrNull<ReferencesManifest>(`${base}/references/references-manifest.json`),
      fetchJsonOrNull<ModelingRules>(`${base}/references/modeling-rules.json`),
    ]).then(([metadataResult, referencesResult, rulesResult]) => {
      if (cancelled) return;
      setMetadata(metadataResult);
      setReferencesManifest(referencesResult);
      setModelingRules(rulesResult);
      setDetailLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, [selected]);

  const referencesBase = selected ? `${MODEL_DIR}/renders/${selected.folder}/references` : "";
  const glbSrc = selected?.glb ? encodeURI(`${MODEL_DIR}/renders/${selected.glb}`) : undefined;
  const fbxSrc = selected?.fbx ? encodeURI(`${MODEL_DIR}/renders/${selected.fbx}`) : undefined;
  const wallOpeningPlans = modelingRules?.windowsAndDoors?.wallOpeningPlans ?? {};
  const wallPlanEntries = Object.entries(wallOpeningPlans);

  return (
    <main className="design-space-page">
      <Script type="module" src="https://ajax.googleapis.com/ajax/libs/model-viewer/4.3.0/model-viewer.min.js" strategy="afterInteractive" />
      <aside className="design-space-sidebar">
        <Link href="/" className="atlas-back"><ArrowLeft size={17} /> Energy Twin</Link>
        <div className="atlas-title">
          <span className="eyebrow">DESIGN SPACE</span>
          <h1>Model &amp; Reference Inspector</h1>
        </div>

        <div className="design-space-quickpicks">
          {QUICK_PICKS.map((needle) => {
            const match = manifestBuildings.find((building) => building.folder.includes(needle));
            if (!match) return null;
            return (
              <button
                key={needle}
                className={match.folder === selectedFolder ? "active" : ""}
                onClick={() => setSelectedFolder(match.folder)}
              >
                {match.name.replace(/^building__/, "").split("__way_")[0].replace(/-/g, " ")}
              </button>
            );
          })}
        </div>

        <div className="atlas-search">
          <Search size={17} />
          <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder={`Search ${manifestBuildings.length} buildings`} />
        </div>

        <div className="design-space-building-list">
          {filtered.map((building) => (
            <button
              key={building.folder}
              className={building.folder === selectedFolder ? "active" : ""}
              onClick={() => setSelectedFolder(building.folder)}
            >
              <strong>{displayNameFor(building.name)}</strong>
              <small>{building.glb ? "glb" : "no glb"} · {building.fbx ? "fbx" : "no fbx"}</small>
            </button>
          ))}
          {!filtered.length && <p className="design-space-empty-list">No buildings match &quot;{query}&quot;.</p>}
        </div>
      </aside>

      <section className="design-space-workspace">
        {!selected ? (
          <div className="reference-empty"><Box size={24} /><strong>Select a building</strong></div>
        ) : (
          // Keyed by folder so switching buildings remounts this whole
          // subtree fresh instead of reusing stale per-image "broken" state
          // (e.g. ElevationSheet/ReferenceThumb) across different buildings.
          <div key={selected.folder} className="design-space-detail">
            <header className="atlas-header">
              <div>
                <span className="eyebrow">{metadata?.osmId ?? "building"}</span>
                <h2>{modelingRules?.displayName ?? referencesManifest?.displayName ?? metadata?.displayName ?? displayNameFor(selected.name)}</h2>
                <p>
                  {selected.dimensions && (
                    <span><Ruler size={13} /> {selected.dimensions.x.toFixed(1)}m x {selected.dimensions.y.toFixed(1)}m x {selected.dimensions.z.toFixed(1)}m</span>
                  )}
                  {metadata && (
                    <span> · {metadata.vertices} verts · {metadata.edges} edges · {metadata.faces} faces · {metadata.generatedDetails ?? 0} generated details</span>
                  )}
                </p>
              </div>
            </header>

            <div className="design-space-model-row">
              <div className="model-panel-frame">
                <span className="model-panel-label">GLB</span>
                {glbSrc ? (
                  <model-viewer
                    src={glbSrc}
                    camera-controls
                    shadow-intensity="1"
                    exposure="1"
                    style={{ width: "100%", height: "100%", background: "#ece9df" }}
                  />
                ) : (
                  <div className="model-panel-status"><span>No GLB export available</span></div>
                )}
              </div>
              <div className="model-panel-frame">
                <span className="model-panel-label">FBX</span>
                <FbxViewer src={fbxSrc} label={displayNameFor(selected.name)} />
              </div>
            </div>

            <ReferencesSection referencesBase={referencesBase} manifest={referencesManifest} loading={detailLoading} />
            <WallOpeningsSection entries={wallPlanEntries} referencesBase={referencesBase} loading={detailLoading} />
            <ElevationSheet referencesBase={referencesBase} />
          </div>
        )}
      </section>
    </main>
  );
}

function ReferencesSection({ referencesBase, manifest, loading }: { referencesBase: string; manifest: ReferencesManifest | null; loading: boolean }) {
  if (loading) return null;
  const streetViews = Object.entries(manifest?.streetView ?? {});
  const walls = manifest?.walls ?? [];
  if (!streetViews.length && !walls.length) {
    return (
      <section>
        <h3 className="design-space-section-title">Reference photos</h3>
        <div className="reference-empty"><ImageOff size={22} /><strong>No reference photos generated yet</strong><span>Run npm run model:dartmouth:references for this building first.</span></div>
      </section>
    );
  }
  return (
    <section>
      <h3 className="design-space-section-title">Reference photos</h3>
      <div className="reference-grid design-space-reference-grid">
        {streetViews.map(([id, view]) => (
          <ReferenceThumb key={id} label={id} referencesBase={referencesBase} view={view} />
        ))}
        {walls.map((wall) => (
          <ReferenceThumb key={wall.id} label={`${wall.id}${wall.orientation ? ` (${wall.orientation})` : ""}`} referencesBase={referencesBase} view={wall.reference} meta={wall.lengthMeters ? `${wall.lengthMeters}m` : undefined} />
        ))}
      </div>
    </section>
  );
}

function ReferenceThumb({ label, referencesBase, view, meta }: { label: string; referencesBase: string; view?: ReferenceImageEntry; meta?: string }) {
  const [broken, setBroken] = useState(false);
  const src = view?.path ? `${referencesBase}/${view.path.replace(/^references\//, "")}` : undefined;
  return (
    <figure className="reference-frame">
      {src && !broken ? (
        <img src={encodeURI(src)} alt={label} onError={() => setBroken(true)} />
      ) : (
        <div className="reference-fallback"><ImageOff size={22} /><span>No image</span></div>
      )}
      <figcaption>
        <span>{label}</span>
        <small>{[view?.qualityStatus, meta].filter(Boolean).join(" · ") || "unreviewed"}</small>
      </figcaption>
    </figure>
  );
}

function WallOpeningsSection({ entries, referencesBase, loading }: { entries: [string, WallOpeningPlan][]; referencesBase: string; loading: boolean }) {
  if (loading) return null;
  if (!entries.length) {
    return (
      <section>
        <h3 className="design-space-section-title">Wall openings (modeling-rules.json)</h3>
        <div className="reference-empty"><strong>No modeling-rules.json yet</strong><span>Run npm run model:dartmouth:extract-openings for this building first.</span></div>
      </section>
    );
  }
  return (
    <section>
      <h3 className="design-space-section-title">Wall openings (modeling-rules.json)</h3>
      <div className="design-space-wall-list">
        {entries.map(([wallId, plan]) => (
          <div key={wallId} className="design-space-wall-row">
            {plan.reference && (
              <img
                className="design-space-wall-thumb"
                src={encodeURI(`${referencesBase}/${plan.reference.replace(/^references\//, "")}`)}
                alt={wallId}
              />
            )}
            <div>
              <div className="design-space-wall-head">
                <strong>{wallId}</strong>
                <ConfidenceBadge confidence={plan.confidence} countMethod={plan.countMethod} />
              </div>
              <small>{plan.windows ?? 0} windows · {plan.doors ?? 0} doors · {plan.floors ?? "?"} floors{plan.quality ? ` · ${plan.quality}` : ""}</small>
              {plan.notes && <p>{plan.notes}</p>}
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ConfidenceBadge({ confidence, countMethod }: { confidence?: number; countMethod?: string }) {
  if (confidence === undefined) return <span className="design-space-badge manual">{countMethod ?? "manual"}</span>;
  const tier = confidence >= 0.7 ? "high" : confidence >= 0.55 ? "medium" : "low";
  return <span className={`design-space-badge ${tier}`}>confidence {confidence.toFixed(2)}</span>;
}

function ElevationSheet({ referencesBase }: { referencesBase: string }) {
  const [broken, setBroken] = useState(false);
  if (!referencesBase || broken) return null;
  const src = `${referencesBase}/elevation-sheets/orthographic-elevations.svg`;
  return (
    <section>
      <h3 className="design-space-section-title">Orthographic elevation sheet</h3>
      <img className="design-space-elevation-sheet" src={src} alt="Orthographic elevation sheet" onError={() => setBroken(true)} />
    </section>
  );
}

function fetchJsonOrNull<T>(url: string): Promise<T | null> {
  return fetch(url, { cache: "no-store" })
    .then((response) => (response.ok ? (response.json() as Promise<T>) : null))
    .catch(() => null);
}

function displayNameFor(manifestName: string) {
  return manifestName.replace(/^building__/, "").split("__way_")[0].replace(/-/g, " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}
