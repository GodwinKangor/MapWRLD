// Field-capture coordinator records. Mirrors supabase/migrations/202611260001_field_capture.sql.
// The phone adds two local-only states before the server knows a capture: "captured" and "uploading".

export const CAPTURE_STATES = ["registered", "uploaded", "processing", "processed", "failed", "reviewed"] as const;
export type CaptureState = (typeof CAPTURE_STATES)[number];

export const JOB_STATES = ["queued", "leased", "succeeded", "failed"] as const;
export type JobState = (typeof JOB_STATES)[number];

export type Device = { id: string; label: string; tokenHash: string; revoked: boolean; createdAt: string };
export type Worker = { id: string; label: string; tokenHash: string; revoked: boolean; lastSeenAt?: string; createdAt: string };

export type Session = {
  id: string;
  deviceId: string;
  clientSessionId: string;
  buildingId: string;
  createdAt: string;
  expiresAt: string;
};

export type CaptureFile = { name: string; sha256: string; bytes: number; contentType: string; storagePath: string; stored: boolean };

export type Capture = {
  id: string;                 // client-generated UUID: the idempotency key for uploads
  sessionId: string;
  deviceId: string;
  buildingId: string;
  surfaceIds: string[];
  imageSha256: string;
  files: CaptureFile[];
  metadata: Record<string, unknown>; // capture.json as written by the phone
  state: CaptureState;
  duplicateOf?: string;       // same image bytes already uploaded for this building
  error?: string;
  reviewedAt?: string;        // survives rebuilds: a reprocessed reviewed capture returns to "reviewed"
  createdAt: string;
  updatedAt: string;
};

export type JobProgress = { stage: string; fraction: number; message: string; at: string };

export type Job = {
  id: string;
  kind: "surface-texture";
  buildingId: string;
  surfaceId: string;
  captureIds: string[];       // snapshot taken when the job was leased
  state: JobState;
  attempts: number;
  maxAttempts: number;
  workerId?: string;
  leaseToken?: string;
  leaseExpiresAt?: string;
  progress?: JobProgress;
  error?: string;
  resultPrefix?: string;
  createdAt: string;
  updatedAt: string;
};

export type SurfaceResult = {
  jobId: string;
  prefix: string;              // storage prefix of the result files
  files: Record<string, string>;
  coverage: Record<string, unknown>;
  summary: Record<string, unknown>;
  finishedAt: string;
};

export type SurfaceRecord = {
  key: string;                 // `${buildingId}|${surfaceId}`
  buildingId: string;
  surfaceId: string;
  rerunRequested: boolean;     // a capture arrived while a job was running
  latest?: SurfaceResult;
  review?: { regions: { polygon: [number, number][] }[]; reviewedBy: string; reviewedAt: string };
};

export type JobOutcome =
  | { ok: true; files: Record<string, string>; coverage: Record<string, unknown>; summary: Record<string, unknown>; resultPrefix: string }
  | { ok: false; error: string; retryable: boolean };
