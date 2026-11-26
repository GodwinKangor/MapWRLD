// Pure state rules shared by every repository implementation (and mirrored in the SQL functions).
// No I/O here, so the rules are unit-tested directly (lib/field/state.test.ts).

import type { Capture, CaptureState, Job, JobOutcome } from "./types.ts";

export const LEASE_SECONDS = 120;
export const MAX_ATTEMPTS = 3;
export const SESSION_TTL_SECONDS = 12 * 3600;

const CAPTURE_TRANSITIONS: Record<CaptureState, CaptureState[]> = {
  registered: ["uploaded"],
  uploaded: ["processing", "failed"],
  processing: ["processed", "reviewed", "failed", "uploaded"], // uploaded again when its job is requeued
  processed: ["processing", "reviewed"],            // reprocessed when the surface is rebuilt
  failed: ["uploaded", "processing"],               // re-upload or retry
  reviewed: ["processing", "reviewed"],             // a rebuild returns it to reviewed (Capture.reviewedAt)
};

export function canTransition(from: CaptureState, to: CaptureState): boolean {
  return from === to || CAPTURE_TRANSITIONS[from].includes(to);
}

export function transition(capture: Capture, to: CaptureState, now: string, error?: string): Capture {
  if (!canTransition(capture.state, to)) throw new Error(`capture ${capture.id}: ${capture.state} -> ${to} is not allowed`);
  return { ...capture, state: to, error: to === "failed" ? error ?? capture.error : undefined, updatedAt: now };
}

export type RegisterDecision =
  | { kind: "create" }
  | { kind: "existing" }           // same id, same bytes: idempotent retry
  | { kind: "conflict"; reason: string };

/** Duplicate-upload policy: the client UUID is the idempotency key, the image hash guards it. */
export function decideRegistration(existing: Capture | undefined, imageSha256: string): RegisterDecision {
  if (!existing) return { kind: "create" };
  if (existing.imageSha256 === imageSha256) return { kind: "existing" };
  return { kind: "conflict", reason: "captureId already used for different image bytes" };
}

export function leaseExpired(job: Job, nowMs: number): boolean {
  return job.state === "leased" && (!job.leaseExpiresAt || Date.parse(job.leaseExpiresAt) <= nowMs);
}

/** What happens to a job whose worker vanished (crash, restart, sleep, network loss). */
export function expireLease(job: Job, now: string): Job {
  const exhausted = job.attempts >= job.maxAttempts;
  return {
    ...job,
    state: exhausted ? "failed" : "queued",
    error: exhausted ? `lease expired ${job.attempts} times; giving up` : job.error,
    workerId: undefined, leaseToken: undefined, leaseExpiresAt: undefined, updatedAt: now,
  };
}

export function lease(job: Job, workerId: string, token: string, nowMs: number, captureIds: string[]): Job {
  return {
    ...job, state: "leased", workerId, leaseToken: token, attempts: job.attempts + 1, captureIds,
    leaseExpiresAt: new Date(nowMs + LEASE_SECONDS * 1000).toISOString(), updatedAt: new Date(nowMs).toISOString(),
  };
}

/** A worker may only report on a job it still holds; anything else means the lease moved on. */
export function holdsLease(job: Job | undefined, token: string, nowMs: number): job is Job {
  return Boolean(job && job.state === "leased" && job.leaseToken === token && !leaseExpired(job, nowMs));
}

export function finish(job: Job, outcome: JobOutcome, now: string): Job {
  const base = { ...job, leaseToken: undefined, leaseExpiresAt: undefined, updatedAt: now };
  if (outcome.ok) return { ...base, state: "succeeded", error: undefined, resultPrefix: outcome.resultPrefix };
  if (outcome.retryable && job.attempts < job.maxAttempts) return { ...base, state: "queued", workerId: undefined, error: outcome.error };
  return { ...base, state: "failed", error: outcome.error };
}

/**
 * Progressive processing: at most one queued job per surface. A capture that
 * arrives while the surface's job is running sets `rerunRequested`, so exactly
 * one follow-up job runs afterwards instead of one per photo.
 */
export function enqueueDecision(jobsForSurface: Job[]): "already-queued" | "rerun-after-running" | "create" {
  if (jobsForSurface.some((job) => job.state === "queued")) return "already-queued";
  if (jobsForSurface.some((job) => job.state === "leased")) return "rerun-after-running";
  return "create";
}

/** Where a capture lands when the job that processed it ends. */
export function settledState(capture: Capture, job: Job): CaptureState | null {
  if (capture.state !== "processing") return null;
  if (job.state === "succeeded") return capture.reviewedAt ? "reviewed" : "processed";
  if (job.state === "failed") return "failed";
  if (job.state === "queued") return "uploaded";
  return null;
}

export function sessionExpired(expiresAt: string, nowMs: number): boolean {
  return Date.parse(expiresAt) <= nowMs;
}
