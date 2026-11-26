// POST: the phone finished PUTting files. The server checks each object (size, and SHA-256 where the
// store can compute it), marks the capture uploaded, and queues (or coalesces) processing.
import { authDevice, backend, json, problem } from "@/lib/field/server";

export const dynamic = "force-dynamic";

export async function POST(request: Request, { params }: { params: Promise<{ id: string }> }) {
  const device = await authDevice(request);
  if (!device) return problem(401, "device token required");
  const { repo, blobs } = backend(request);
  const capture = await repo.capture((await params).id);
  if (!capture || capture.deviceId !== device.id) return problem(404, "unknown capture");
  const verified: string[] = [];
  const missing: string[] = [];
  for (const file of capture.files) {
    const info = await blobs.stat(file.storagePath);
    const ok = info && info.bytes === file.bytes && (!info.sha256 || info.sha256 === file.sha256);
    (ok ? verified : missing).push(file.name);
  }
  const { capture: updated, jobs } = await repo.completeUpload(capture.id, verified, Date.now());
  return json({ capture: updated, queuedJobs: jobs.map((j) => j.id), missing }, missing.length ? 202 : 200);
}
