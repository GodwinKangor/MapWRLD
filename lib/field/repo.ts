// Operation-level storage interface. Every method that changes more than one record is atomic:
// the file repository holds a cross-process lock; the Supabase repository calls SQL functions.

import type { Capture, CaptureFile, Device, Job, JobOutcome, JobProgress, Session, SurfaceRecord, Worker } from "./types.ts";

export type RegisterInput = {
  captureId: string;
  session: Session;
  imageSha256: string;
  surfaceIds: string[];
  files: Omit<CaptureFile, "storagePath" | "stored">[];
  metadata: Record<string, unknown>;
};

export type RegisterResult =
  | { status: "created" | "existing"; capture: Capture }
  | { status: "conflict"; reason: string };

export type ClaimedJob = { job: Job; captures: Capture[] };

export interface FieldRepo {
  deviceByTokenHash(hash: string): Promise<Device | null>;
  workerByTokenHash(hash: string): Promise<Worker | null>;
  addDevice(device: Device): Promise<void>;
  addWorker(worker: Worker): Promise<void>;

  openSession(deviceId: string, clientSessionId: string, buildingId: string, nowMs: number): Promise<Session>;
  renewSession(deviceId: string, sessionId: string, nowMs: number): Promise<Session | null>;
  session(id: string): Promise<Session | null>;

  registerCapture(input: RegisterInput, nowMs: number): Promise<RegisterResult>;
  capture(id: string): Promise<Capture | null>;
  /** Mark files stored, move the capture to `uploaded`, and queue (or coalesce) its surfaces' jobs. */
  completeUpload(captureId: string, storedFiles: string[], nowMs: number): Promise<{ capture: Capture; jobs: Job[] }>;

  /** Requeue expired leases, then lease the oldest queued job with a snapshot of its uploaded captures. */
  claimJob(workerId: string, leaseToken: string, nowMs: number): Promise<ClaimedJob | null>;
  touchJob(jobId: string, leaseToken: string, progress: JobProgress, nowMs: number): Promise<Job | "lease-lost">;
  finishJob(jobId: string, leaseToken: string, outcome: JobOutcome, nowMs: number): Promise<Job | "lease-lost">;
  job(id: string): Promise<Job | null>;

  surfaceStatus(buildingId: string, surfaceId: string): Promise<{ surface: SurfaceRecord | null; captures: Capture[]; jobs: Job[] }>;
  reviewSurface(buildingId: string, surfaceId: string, review: NonNullable<SurfaceRecord["review"]>, nowMs: number): Promise<SurfaceRecord>;
}

export interface BlobStore {
  /** URL the client PUTs the bytes to (short-lived). */
  signUpload(path: string, contentType: string, nowMs: number): Promise<{ url: string; method: "PUT"; headers: Record<string, string> }>;
  signDownload(path: string, nowMs: number): Promise<string>;
  /** Size and (when the store can compute it) SHA-256 of a stored object; null if absent. */
  stat(path: string): Promise<{ bytes: number; sha256?: string } | null>;
}
