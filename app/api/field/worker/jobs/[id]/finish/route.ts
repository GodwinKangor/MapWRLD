// POST {leaseToken, ok, ...}: report success (with result files and coverage) or failure.
// A stale lease (the job was requeued after this worker went quiet) is rejected with 409.
import { authWorker, backend, body, json, problem } from "@/lib/field/server";
import type { JobOutcome } from "@/lib/field/types";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await authWorker(request))) return problem(401, "worker token required");
  const input = await body<{ leaseToken?: string } & Partial<JobOutcome> & Record<string, unknown>>(request);
  if (!input?.leaseToken || typeof input.ok !== "boolean") return problem(400, "leaseToken and ok are required");
  const outcome: JobOutcome = input.ok
    ? { ok: true, files: (input.files ?? {}) as Record<string, string>, coverage: (input.coverage ?? {}) as Record<string, unknown>,
        summary: (input.summary ?? {}) as Record<string, unknown>, resultPrefix: String(input.resultPrefix ?? "") }
    : { ok: false, error: String(input.error ?? "unknown error").slice(0, 2000), retryable: Boolean(input.retryable) };
  if (outcome.ok && !outcome.resultPrefix.startsWith("results/")) return problem(400, "resultPrefix must come from /results");
  const result = await backend(request).repo.finishJob((await params).id, input.leaseToken, outcome, Date.now());
  return result === "lease-lost" ? problem(409, "lease lost") : json({ job: result });
}
