import { readFile, writeFile } from "node:fs/promises";

const manifestPath = "public/models/dartmouth-energy-twin/renders/buildings/building__baker-library__way_295888783/references/references-manifest.json";
const manifest = JSON.parse(await readFile(manifestPath, "utf8"));
const reviewedAt = new Date().toISOString();

const audits = {
  "wall-01": ["linked-partial", "Exterior wall is visible, but a central tree obscures window rhythm; usable for partial facade layout only."],
  "wall-02": ["linked-partial", "Promoted wall-02-candidate-03. Exterior overview shows the front/southwest Baker wing and tower context; use as contextual/partial reference, not isolated wall-only truth."],
  "wall-03": ["linked-partial", "Exterior wall visible with tree obstruction; usable for window rhythm with caution."],
  "wall-04": ["linked-partial", "Exterior wall visible with tree obstruction; usable for proportions and openings with caution."],
  "wall-05": ["rejected", "Primary and alternates are indoor/door close-ups, not an exterior major wall face. Do not model from this wall reference."],
  "wall-06": ["linked-partial", "Exterior street-side wall visible, but cars and trees obstruct the lower facade."],
  "wall-07": ["linked-partial", "Exterior face and tower context visible; tree blocks part of facade."],
  "wall-08": ["rejected", "Primary and alternates are close brick or indoor views, not an exterior major wall face."],
  "wall-09": ["linked-partial", "Exterior connector/courtyard wall visible; includes adjacent massing, so use only for this segment after checking footprint context."],
  "wall-10": ["linked-partial-needs-verify", "Promoted wall-10-candidate-04. Exterior Berry/north facade view; verify this segment belongs to the exported Baker/Berry footprint before approval."],
  "wall-11": ["linked-detail-only", "Exterior brick/window close-up; good for proportions/material rhythm, not full wall layout."],
  "wall-12": ["rejected", "Primary and alternates are indoor/wood close-ups, not an exterior major wall face."],
  "wall-13": ["linked-partial", "Exterior wall visible with strong tree obstruction; usable for partial layout only."],
  "wall-14": ["linked-partial", "Exterior wall visible with central tree obstruction; usable for partial layout only."],
};

const promotedCandidates = {
  "wall-02": 2,
  "wall-10": 3,
};

for (const wall of manifest.walls) {
  const [status, notes] = audits[wall.id] ?? ["needs-review", "Not visually audited yet."];
  const promotedIndex = promotedCandidates[wall.id];
  if (promotedIndex !== undefined) {
    const candidate = wall.candidateCameras[promotedIndex];
    wall.reference = {
      ...wall.reference,
      status: "saved",
      path: `references/walls/${wall.id}.jpg`,
      source: "Google Street View Static API",
      panoId: candidate.panoId,
      heading: candidate.heading,
      fov: candidate.fov,
      distanceMeters: candidate.distanceMeters,
      camera: candidate.camera,
      promotedFrom: `${wall.id}-candidate-${String(promotedIndex + 1).padStart(2, "0")}.jpg`,
    };
  }
  wall.reference.qualityStatus = status;
  wall.linkReview = {
    status,
    reviewedAt,
    reviewer: "codex-visual-audit",
    notes,
  };
  wall.approvedForModeling = false;
}

manifest.wallReferenceAudit = {
  reviewedAt,
  reviewer: "codex-visual-audit",
  summary: {
    total: manifest.walls.length,
    linkedPartial: manifest.walls.filter((wall) => wall.linkReview.status.startsWith("linked-partial")).length,
    linkedDetailOnly: manifest.walls.filter((wall) => wall.linkReview.status === "linked-detail-only").length,
    rejected: manifest.walls.filter((wall) => wall.linkReview.status === "rejected").length,
  },
  rule: "Only walls with linkReview.status starting linked and approvedForModeling=true may drive procedural exterior details.",
};

await writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
console.log(JSON.stringify(manifest.wallReferenceAudit, null, 2));
