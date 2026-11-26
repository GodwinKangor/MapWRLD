// POST {clientSessionId, buildingId}: open (or return) a capture session. Idempotent per client session id.
import { authDevice, backend, body, json, problem, surfaceRegistry } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const device = await authDevice(request);
  if (!device) return problem(401, "device token required");
  const input = await body<{ clientSessionId?: string; buildingId?: string }>(request);
  if (!input?.clientSessionId || !input.buildingId) return problem(400, "clientSessionId and buildingId are required");
  if (!(await surfaceRegistry(input.buildingId))) return problem(404, `no surface registry for ${input.buildingId}`);
  const session = await backend(request).repo.openSession(device.id, input.clientSessionId, input.buildingId, Date.now());
  return json({ session });
}
