// File-backed repository and blob store for local development, tests, and the one-wall demo.
// One JSON document guarded by a lock directory (atomic mkdir), so separate Next.js route bundles
// and the test process can share it. Not for Vercel: its filesystem is per-invocation.

import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import { mkdir, readFile, rename, rm, stat, writeFile } from "node:fs/promises";
import path from "node:path";
import type { BlobStore, ClaimedJob, FieldRepo, RegisterInput, RegisterResult } from "./repo.ts";
import {
  MAX_ATTEMPTS, SESSION_TTL_SECONDS, decideRegistration, enqueueDecision, expireLease, finish, holdsLease, lease, leaseExpired,
  sessionExpired, settledState, transition,
} from "./state.ts";
import { newId, safeSegment, sign, surfaceKey } from "./tokens.ts";
import type { Capture, Device, Job, JobOutcome, JobProgress, Session, SurfaceRecord, Worker } from "./types.ts";

type Db = {
  devices: Device[];
  workers: Worker[];
  sessions: Session[];
  captures: Record<string, Capture>;
  jobs: Record<string, Job>;
  surfaces: Record<string, SurfaceRecord>;
};

const empty = (): Db => ({ devices: [], workers: [], sessions: [], captures: {}, jobs: {}, surfaces: {} });

async function sleep(ms: number) {
  await new Promise((resolve) => setTimeout(resolve, ms));
}

export class FsRepo implements FieldRepo {
  readonly dir: string;
  private readonly file: string;
  private readonly lockDir: string;

  constructor(dir: string) {
    this.dir = dir;
    this.file = path.join(dir, "db.json");
    this.lockDir = path.join(dir, "db.lock");
  }

  private async read(): Promise<Db> {
    try {
      return { ...empty(), ...JSON.parse(await readFile(this.file, "utf8")) };
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return empty();
      throw error;
    }
  }

  private async write(db: Db) {
    const tmp = `${this.file}.${process.pid}.${newId()}.tmp`;
    await writeFile(tmp, JSON.stringify(db, null, 1));
    await rename(tmp, this.file); // atomic replace: readers never see a half-written file
  }

  /** Run `fn` holding the lock; a lock older than 10 s is treated as left by a crashed process. */
  private async locked<T>(fn: (db: Db) => T | Promise<T>, mutate = true): Promise<T> {
    await mkdir(this.dir, { recursive: true });
    for (let attempt = 0; ; attempt += 1) {
      try {
        await mkdir(this.lockDir);
        break;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error;
        const info = await stat(this.lockDir).catch(() => null);
        if (info && Date.now() - info.mtimeMs > 10_000) await rm(this.lockDir, { recursive: true, force: true });
        if (attempt > 400) throw new Error("field db lock timeout");
        await sleep(5 + Math.random() * 20);
      }
    }
    try {
      const db = await this.read();
      const result = await fn(db);
      if (mutate) await this.write(db);
      return result;
    } finally {
      await rm(this.lockDir, { recursive: true, force: true });
    }
  }

  async deviceByTokenHash(hash: string) {
    return this.locked((db) => db.devices.find((d) => d.tokenHash === hash && !d.revoked) ?? null, false);
  }

  async workerByTokenHash(hash: string) {
    return this.locked((db) => {
      const worker = db.workers.find((w) => w.tokenHash === hash && !w.revoked);
      if (worker) worker.lastSeenAt = new Date().toISOString();
      return worker ?? null;
    });
  }

  async addDevice(device: Device) {
    await this.locked((db) => { db.devices.push(device); });
  }

  async addWorker(worker: Worker) {
    await this.locked((db) => { db.workers.push(worker); });
  }

  async openSession(deviceId: string, clientSessionId: string, buildingId: string, nowMs: number) {
    return this.locked((db) => {
      const existing = db.sessions.find((s) => s.deviceId === deviceId && s.clientSessionId === clientSessionId);
      if (existing) return existing; // idempotent: the phone retries session creation freely
      const session: Session = {
        id: newId(), deviceId, clientSessionId, buildingId, createdAt: new Date(nowMs).toISOString(),
        expiresAt: new Date(nowMs + SESSION_TTL_SECONDS * 1000).toISOString(),
      };
      db.sessions.push(session);
      return session;
    });
  }

  async renewSession(deviceId: string, sessionId: string, nowMs: number) {
    return this.locked((db) => {
      const session = db.sessions.find((s) => s.id === sessionId && s.deviceId === deviceId);
      if (!session) return null;
      session.expiresAt = new Date(nowMs + SESSION_TTL_SECONDS * 1000).toISOString();
      return session;
    });
  }

  async session(id: string) {
    return this.locked((db) => db.sessions.find((s) => s.id === id) ?? null, false);
  }

  async registerCapture(input: RegisterInput, nowMs: number): Promise<RegisterResult> {
    return this.locked((db) => {
      if (sessionExpired(input.session.expiresAt, nowMs)) return { status: "conflict", reason: "session expired" };
      const decision = decideRegistration(db.captures[input.captureId], input.imageSha256);
      if (decision.kind === "conflict") return { status: "conflict", reason: decision.reason };
      if (decision.kind === "existing") return { status: "existing", capture: db.captures[input.captureId] };
      const now = new Date(nowMs).toISOString();
      const building = safeSegment(input.session.buildingId);
      const id = safeSegment(input.captureId);
      const duplicate = Object.values(db.captures).find((c) => c.buildingId === input.session.buildingId && c.imageSha256 === input.imageSha256);
      const capture: Capture = {
        id: input.captureId, sessionId: input.session.id, deviceId: input.session.deviceId, buildingId: input.session.buildingId,
        surfaceIds: input.surfaceIds, imageSha256: input.imageSha256, metadata: input.metadata, state: "registered",
        duplicateOf: duplicate?.id,
        files: input.files.map((f) => ({ ...f, storagePath: `captures/${building}/${id}/${safeSegment(f.name)}`, stored: false })),
        createdAt: now, updatedAt: now,
      };
      db.captures[capture.id] = capture;
      return { status: "created", capture };
    });
  }

  async capture(id: string) {
    return this.locked((db) => db.captures[id] ?? null, false);
  }

  async completeUpload(captureId: string, storedFiles: string[], nowMs: number) {
    return this.locked((db) => {
      const now = new Date(nowMs).toISOString();
      let capture = db.captures[captureId];
      if (!capture) throw new Error("unknown capture");
      capture = { ...capture, files: capture.files.map((f) => (storedFiles.includes(f.name) ? { ...f, stored: true } : f)) };
      const jobs: Job[] = [];
      if (capture.files.every((f) => f.stored) && capture.state === "registered") {
        capture = transition(capture, "uploaded", now);
        // an exact duplicate of an existing upload adds no evidence: store it, don't reprocess
        if (!capture.duplicateOf) for (const surfaceId of capture.surfaceIds) jobs.push(...enqueue(db, capture.buildingId, surfaceId, now));
      }
      db.captures[captureId] = capture;
      return { capture, jobs };
    });
  }

  async claimJob(workerId: string, leaseToken: string, nowMs: number): Promise<ClaimedJob | null> {
    return this.locked((db) => {
      const now = new Date(nowMs).toISOString();
      for (const job of Object.values(db.jobs)) {
        if (!leaseExpired(job, nowMs)) continue;
        db.jobs[job.id] = expireLease(job, now);
        settleCaptures(db, db.jobs[job.id], now);
      }
      const next = Object.values(db.jobs).filter((j) => j.state === "queued").sort((a, b) => a.createdAt.localeCompare(b.createdAt))[0];
      if (!next) return null;
      const captures = Object.values(db.captures).filter(
        (c) => c.buildingId === next.buildingId && c.surfaceIds.includes(next.surfaceId) && !c.duplicateOf
          && ["uploaded", "processing", "processed", "reviewed", "failed"].includes(c.state),
      );
      const leased = lease(next, workerId, leaseToken, nowMs, captures.map((c) => c.id));
      db.jobs[next.id] = leased;
      for (const c of captures) db.captures[c.id] = transition(c, "processing", now);
      const surface = db.surfaces[`${next.buildingId}|${next.surfaceId}`];
      if (surface) surface.rerunRequested = false; // this run includes everything uploaded so far
      return { job: leased, captures: captures.map((c) => db.captures[c.id]) };
    });
  }

  async touchJob(jobId: string, leaseToken: string, progress: JobProgress, nowMs: number) {
    return this.locked((db): Job | "lease-lost" => {
      const job = db.jobs[jobId];
      if (!holdsLease(job, leaseToken, nowMs)) return "lease-lost";
      const updated = { ...job, progress, leaseExpiresAt: new Date(nowMs + 120_000).toISOString(), updatedAt: new Date(nowMs).toISOString() };
      db.jobs[jobId] = updated;
      return updated;
    });
  }

  async finishJob(jobId: string, leaseToken: string, outcome: JobOutcome, nowMs: number) {
    return this.locked((db): Job | "lease-lost" => {
      const job = db.jobs[jobId];
      if (!holdsLease(job, leaseToken, nowMs)) return "lease-lost"; // a restarted worker must not overwrite newer work
      const now = new Date(nowMs).toISOString();
      const done = finish(job, outcome, now);
      db.jobs[jobId] = done;
      settleCaptures(db, done, now);
      const key = `${job.buildingId}|${job.surfaceId}`;
      const surface = (db.surfaces[key] ??= { key, buildingId: job.buildingId, surfaceId: job.surfaceId, rerunRequested: false });
      if (outcome.ok) {
        surface.latest = { jobId, prefix: outcome.resultPrefix, files: outcome.files, coverage: outcome.coverage, summary: outcome.summary, finishedAt: now };
      }
      if (surface.rerunRequested && done.state !== "queued") {
        surface.rerunRequested = false;
        enqueue(db, job.buildingId, job.surfaceId, now);
      }
      return done;
    });
  }

  async job(id: string) {
    return this.locked((db) => db.jobs[id] ?? null, false);
  }

  async surfaceStatus(buildingId: string, surfaceId: string) {
    return this.locked((db) => ({
      surface: db.surfaces[`${buildingId}|${surfaceId}`] ?? null,
      captures: Object.values(db.captures).filter((c) => c.buildingId === buildingId && c.surfaceIds.includes(surfaceId)),
      jobs: Object.values(db.jobs).filter((j) => j.buildingId === buildingId && j.surfaceId === surfaceId)
        .sort((a, b) => b.createdAt.localeCompare(a.createdAt)),
    }), false);
  }

  async reviewSurface(buildingId: string, surfaceId: string, review: NonNullable<SurfaceRecord["review"]>, nowMs: number) {
    return this.locked((db) => {
      const key = `${buildingId}|${surfaceId}`;
      const surface = (db.surfaces[key] ??= { key, buildingId, surfaceId, rerunRequested: false });
      surface.review = review;
      const now = new Date(nowMs).toISOString();
      for (const c of Object.values(db.captures)) {
        if (c.buildingId !== buildingId || !c.surfaceIds.includes(surfaceId)) continue;
        if (c.state === "processed") db.captures[c.id] = { ...transition(c, "reviewed", now), reviewedAt: now };
      }
      enqueue(db, buildingId, surfaceId, now); // rebuild so `reviewed` coverage is recomputed
      return surface;
    });
  }
}

function enqueue(db: Db, buildingId: string, surfaceId: string, now: string): Job[] {
  const key = `${buildingId}|${surfaceId}`;
  const existing = Object.values(db.jobs).filter((j) => j.buildingId === buildingId && j.surfaceId === surfaceId);
  const decision = enqueueDecision(existing);
  if (decision === "already-queued") return [];
  if (decision === "rerun-after-running") {
    const surface = (db.surfaces[key] ??= { key, buildingId, surfaceId, rerunRequested: false });
    surface.rerunRequested = true;
    return [];
  }
  const job: Job = {
    id: newId(), kind: "surface-texture", buildingId, surfaceId, captureIds: [], state: "queued", attempts: 0,
    maxAttempts: MAX_ATTEMPTS, createdAt: now, updatedAt: now,
  };
  db.jobs[job.id] = job;
  return [job];
}

/** Keep capture states in step with the job that holds them. */
function settleCaptures(db: Db, job: Job, now: string) {
  for (const id of job.captureIds) {
    const c = db.captures[id];
    const to = c && settledState(c, job);
    if (to) db.captures[id] = transition(c, to, now, job.error);
  }
}

/** Local blobs under <dir>/blobs, reached through HMAC-signed URLs served by /api/field/blobs. */
export class FsBlobStore implements BlobStore {
  readonly root: string;
  private readonly baseUrl: string;
  private readonly secret: string;

  constructor(root: string, baseUrl: string, secret: string) {
    this.root = root;
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.secret = secret;
  }

  resolve(storagePath: string): string {
    const full = path.resolve(this.root, storagePath);
    if (!full.startsWith(path.resolve(this.root) + path.sep)) throw new Error("path escapes blob root");
    return full;
  }

  private signed(method: string, storagePath: string, nowMs: number, ttlS: number) {
    const expires = Math.floor(nowMs / 1000) + ttlS;
    const sig = sign(this.secret, method, storagePath, expires);
    return `${this.baseUrl}/api/field/blobs/${storagePath.split("/").map(encodeURIComponent).join("/")}?expires=${expires}&sig=${sig}`;
  }

  async signUpload(storagePath: string, contentType: string, nowMs: number) {
    return { url: this.signed("PUT", storagePath, nowMs, 3600), method: "PUT" as const, headers: { "Content-Type": contentType } };
  }

  async signDownload(storagePath: string, nowMs: number) {
    return this.signed("GET", storagePath, nowMs, 3600);
  }

  async stat(storagePath: string) {
    const full = this.resolve(storagePath);
    const info = await stat(full).catch(() => null);
    if (!info) return null;
    const hash = createHash("sha256");
    for await (const chunk of createReadStream(full)) hash.update(chunk as Buffer);
    return { bytes: info.size, sha256: hash.digest("hex") };
  }

  async write(storagePath: string, body: Uint8Array) {
    const full = this.resolve(storagePath);
    await mkdir(path.dirname(full), { recursive: true });
    const tmp = `${full}.${newId()}.part`;
    await writeFile(tmp, body);
    await rename(tmp, full); // an interrupted upload never leaves a truncated object behind
  }
}

export { surfaceKey };
