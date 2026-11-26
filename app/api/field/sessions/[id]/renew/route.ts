// POST: extend an expired or expiring session owned by this device (the phone calls this on a 410).
import { authDevice, backend, json, problem } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const device = await authDevice(request);
  if (!device) return problem(401, "device token required");
  const session = await backend(request).repo.renewSession(device.id, (await params).id, Date.now());
  return session ? json({ session }) : problem(404, "no such session for this device");
}
