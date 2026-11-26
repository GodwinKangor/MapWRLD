// GET ?buildingId=&surfaceId=: capture states, job progress, and the latest result with signed preview URLs.
import { authDevice, backend, json, problem } from "@/lib/field/server";

export const dynamic = "force-dynamic";
const PHONE_FILES = ["preview", "coverageReport", "details", "reliefPreview", "blenderPreview"];

export async function GET(request: Request) {
  if (!(await authDevice(request))) return problem(401, "device token required");
  const url = new URL(request.url);
  const buildingId = url.searchParams.get("buildingId");
  const surfaceId = url.searchParams.get("surfaceId");
  if (!buildingId || !surfaceId) return problem(400, "buildingId and surfaceId are required");
  const { repo, blobs } = backend(request);
  const status = await repo.surfaceStatus(buildingId, surfaceId);
  const latest = status.surface?.latest;
  const now = Date.now();
  const links: Record<string, string> = {};
  if (latest) {
    for (const key of PHONE_FILES) if (latest.files[key]) links[key] = await blobs.signDownload(`${latest.prefix}/${latest.files[key]}`, now);
  }
  const job = status.jobs[0];
  return json({
    surfaceId, buildingId,
    captures: status.captures.map((c) => ({ id: c.id, state: c.state, error: c.error, duplicateOf: c.duplicateOf, updatedAt: c.updatedAt })),
    job: job ? { id: job.id, state: job.state, attempts: job.attempts, progress: job.progress, error: job.error, updatedAt: job.updatedAt } : null,
    rerunRequested: status.surface?.rerunRequested ?? false,
    latest: latest ? { jobId: latest.jobId, finishedAt: latest.finishedAt, coverage: latest.coverage, summary: latest.summary, links } : null,
    review: status.surface?.review ?? null,
  });
}
