// POST: the Mac worker asks for work (it polls outbound; nothing connects to the Mac).
// 204 = nothing queued. Otherwise: the job, its lease token, the surface definition, and
// signed download URLs for every capture file.
import { randomBytes } from "node:crypto";
import { authWorker, backend, json, problem, registrySurface } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const worker = await authWorker(request);
  if (!worker) return problem(401, "worker token required");
  const { repo, blobs } = backend(request);
  const leaseToken = randomBytes(24).toString("base64url");
  const claimed = await repo.claimJob(worker.id, leaseToken, Date.now());
  if (!claimed) return new Response(null, { status: 204, headers: { "Cache-Control": "no-store" } });
  const { job, captures } = claimed;
  const surface = await registrySurface(job.buildingId, job.surfaceId);
  if (!surface) {
    await repo.finishJob(job.id, leaseToken, { ok: false, error: "surface missing from registry", retryable: false }, Date.now());
    return problem(409, "job surface missing from registry");
  }
  const now = Date.now();
  return json({
    job, leaseToken, surface,
    captures: await Promise.all(captures.map(async (c) => ({
      id: c.id, imageSha256: c.imageSha256,
      files: await Promise.all(c.files.map(async (f) => ({ name: f.name, sha256: f.sha256, bytes: f.bytes, url: await blobs.signDownload(f.storagePath, now) }))),
    }))),
    review: (await repo.surfaceStatus(job.buildingId, job.surfaceId)).surface?.review ?? null,
  });
}
