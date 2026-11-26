// GET: everything the phone needs offline for one building: surfaces (persistent IDs, frames,
// dimensions, Blender mapping) and reference photos per surface.
import { readFile } from "node:fs/promises";
import path from "node:path";
import { authDevice, json, problem, surfaceRegistry } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function GET(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await authDevice(request))) return problem(401, "device token required");
  const { id } = await params;
  const registry = await surfaceRegistry(id);
  if (!registry) return problem(404, `no surface registry for ${id}`);
  const surfaces = registry.surfaces as { surfaceId: string; blender?: { object?: string; panelIds?: string[] } }[];
  const object = surfaces.find((s) => s.blender?.object)?.blender?.object;
  // reference photos: elevation sheets list panel IDs with their source images in the same order
  const references: Record<string, string[]> = {};
  if (object) {
    const base = `/models/dartmouth-energy-twin/renders/buildings/${object}/references`;
    try {
      const sheet = JSON.parse(await readFile(path.join(process.cwd(), "public", base, "elevation-sheets", "orthographic-elevations.json"), "utf8"));
      const byPanel: Record<string, string> = {};
      for (const elevation of Object.values(sheet.elevations ?? {}) as { panelIds?: string[]; sourceImages?: string[] }[]) {
        (elevation.panelIds ?? []).forEach((panel, i) => { if (elevation.sourceImages?.[i]) byPanel[panel] = `${base}/${elevation.sourceImages[i].replace(/^references\//, "")}`; });
      }
      for (const s of surfaces) references[s.surfaceId] = (s.blender?.panelIds ?? []).map((p) => byPanel[p]).filter(Boolean);
    } catch { /* no elevation sheet: the package still works without reference photos */ }
  }
  return json({ ...registry, references, packagedAt: new Date().toISOString() });
}
