// POST {leaseToken, files:[{name, contentType}]}: signed upload URLs for result files.
// Results go to results/<building>/<surface key>/<job id>/, so a retried upload overwrites itself
// and never touches another job's output.
import { authWorker, backend, body, json, problem } from "@/lib/field/server";
import { safeSegment, surfaceKey } from "@/lib/field/tokens";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  if (!(await authWorker(request))) return problem(401, "worker token required");
  const input = await body<{ leaseToken?: string; files?: { name: string; contentType: string }[] }>(request);
  const { repo, blobs } = backend(request);
  const job = await repo.job((await params).id);
  if (!job || !input?.leaseToken || job.leaseToken !== input.leaseToken || job.state !== "leased") return problem(409, "lease lost");
  if (!input.files?.length || input.files.length > 40) return problem(400, "1..40 files");
  const prefix = `results/${safeSegment(job.buildingId)}/${surfaceKey(job.surfaceId)}/${safeSegment(job.id)}`;
  const now = Date.now();
  const uploads = await Promise.all(input.files.map(async (f) => ({ name: safeSegment(f.name), ...(await blobs.signUpload(`${prefix}/${safeSegment(f.name)}`, f.contentType, now)) })));
  return json({ prefix, uploads });
}
