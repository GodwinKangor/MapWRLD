// POST {buildingId, surfaceId, regions:[{polygon:[[u,v],...]}]}: mark regions (surface metres) as
// reviewed by a person. Triggers a rebuild so `reviewed` coverage is recomputed.
import { authDevice, backend, body, json, problem, registrySurface } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const device = await authDevice(request);
  if (!device) return problem(401, "device token required");
  const input = await body<{ buildingId?: string; surfaceId?: string; regions?: { polygon: [number, number][] }[] }>(request);
  if (!input?.buildingId || !input.surfaceId || !Array.isArray(input.regions)) return problem(400, "buildingId, surfaceId and regions are required");
  if (input.regions.some((r) => !Array.isArray(r.polygon) || r.polygon.length < 3 || r.polygon.some((p) => p.length !== 2 || !p.every(Number.isFinite)))) {
    return problem(400, "each region needs a polygon of 3+ [u, v] points in metres");
  }
  if (!(await registrySurface(input.buildingId, input.surfaceId))) return problem(404, "unknown surface");
  const surface = await backend(request).repo.reviewSurface(input.buildingId, input.surfaceId,
    { regions: input.regions, reviewedBy: device.id, reviewedAt: new Date().toISOString() }, Date.now());
  return json({ surface });
}
