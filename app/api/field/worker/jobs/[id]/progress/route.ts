// POST {leaseToken, stage, fraction, message}: progress for the phone; also renews the lease.
import { authWorker, backend, body, json, problem } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await authWorker(request))) return problem(401, "worker token required");
  const input = await body<{ leaseToken?: string; stage?: string; fraction?: number; message?: string }>(request);
  if (!input?.leaseToken || !input.stage) return problem(400, "leaseToken and stage are required");
  const result = await backend(request).repo.touchJob((await params).id, input.leaseToken,
    { stage: input.stage, fraction: Math.max(0, Math.min(1, Number(input.fraction) || 0)), message: String(input.message ?? "").slice(0, 300), at: new Date().toISOString() }, Date.now());
  return result === "lease-lost" ? problem(409, "lease lost") : json({ ok: true, leaseExpiresAt: result.leaseExpiresAt });
}
