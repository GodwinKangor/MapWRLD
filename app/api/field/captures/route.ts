// POST: register a capture (idempotent on captureId) and get signed upload URLs for files not yet stored.
import { backend, authDevice, body, json, problem, registrySurface } from "@/lib/field/server";
import { sessionExpired } from "@/lib/field/state";

export const dynamic = "force-dynamic";

type Input = {
  captureId?: string;
  sessionId?: string;
  surfaceIds?: string[];
  imageSha256?: string;
  files?: { name: string; sha256: string; bytes: number; contentType: string }[];
  metadata?: Record<string, unknown>;
};

const MAX_FILE_BYTES = 200 * 1024 * 1024;

export async function POST(request: Request) {
  const device = await authDevice(request);
  if (!device) return problem(401, "device token required");
  const input = await body<Input>(request);
  if (!input?.captureId || !input.sessionId || !input.imageSha256 || !input.files?.length || !input.surfaceIds?.length || !input.metadata) {
    return problem(400, "captureId, sessionId, surfaceIds, imageSha256, files and metadata are required");
  }
  if (!/^[0-9a-fA-F-]{8,64}$/.test(input.captureId)) return problem(400, "captureId must be a UUID");
  if (input.files.some((f) => !/^[\w.-]{1,80}$/.test(f.name) || !(f.bytes > 0 && f.bytes <= MAX_FILE_BYTES) || !/^[0-9a-f]{64}$/.test(f.sha256))) {
    return problem(400, "file names must be simple, sizes 1 B..200 MB, sha256 hex");
  }
  const { repo, blobs } = backend(request);
  const session = await repo.session(input.sessionId);
  if (!session || session.deviceId !== device.id) return problem(404, "unknown session");
  if (sessionExpired(session.expiresAt, Date.now())) return problem(410, "session expired; renew it and retry");
  for (const surfaceId of input.surfaceIds) {
    if (!(await registrySurface(session.buildingId, surfaceId))) return problem(400, `unknown surface ${surfaceId}`);
  }
  const result = await repo.registerCapture({
    captureId: input.captureId, session, imageSha256: input.imageSha256, surfaceIds: input.surfaceIds, files: input.files, metadata: input.metadata,
  }, Date.now());
  if (result.status === "conflict") return problem(409, result.reason);
  const now = Date.now();
  const uploads = await Promise.all(result.capture.files.filter((f) => !f.stored).map(async (f) => ({ name: f.name, ...(await blobs.signUpload(f.storagePath, f.contentType, now)) })));
  return json({ capture: result.capture, status: result.status, uploads });
}
