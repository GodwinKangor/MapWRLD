import type { Building } from "@/data/buildings";
import type { EnergyEvidence } from "@/data/energy-evidence";
import evidenceFile from "@/data/energy-evidence.json";

// Server-only: keeps the generated evidence JSON out of the client bundle.
type EvidenceFile = {
  generatedAt: string;
  buildings: Record<string, Omit<EnergyEvidence, "generatedAt"> & { name: string }>;
};

const file = evidenceFile as unknown as EvidenceFile;

export function attachEnergyEvidence(buildings: Building[]): Building[] {
  return buildings.map((building) => {
    const record = file.buildings[building.id];
    if (!record) return building;
    const { name: _name, ...evidence } = record;
    return { ...building, evidence: { ...evidence, generatedAt: file.generatedAt } };
  });
}
