// Supabase repository + private-bucket blob store. Server-only: uses the service-role key.
// Status: implemented against the migration's SQL functions; NOT yet exercised against a live
// Supabase project (none is configured in this workspace). The file repository (fs-repo.ts) is the
// tested reference implementation of the same semantics.

import type { BlobStore, ClaimedJob, FieldRepo, RegisterInput, RegisterResult } from "./repo.ts";
import { SESSION_TTL_SECONDS, decideRegistration, sessionExpired } from "./state.ts";
import { safeSegment } from "./tokens.ts";
import type { Capture, Device, Job, JobOutcome, JobProgress, Session, SurfaceRecord, Worker } from "./types.ts";

const BUCKET = "field-captures";
type Row = Record<string, unknown>;

const camel = (key: string) => key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
const snake = (key: string) => key.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`);
function fromRow<T>(row: Row | null): T | null {
  if (!row) return null;
  return Object.fromEntries(Object.entries(row).filter(([, v]) => v !== null).map(([k, v]) => [camel(k), v])) as T;
}
function toRow(record: Record<string, unknown>): Row {
  return Object.fromEntries(Object.entries(record).filter(([, v]) => v !== undefined).map(([k, v]) => [snake(k), v]));
}

export class SupabaseRepo implements FieldRepo {
  private readonly url: string;
  private readonly key: string;

  constructor(url: string, serviceKey: string) {
    this.url = url.replace(/\/$/, "");
    this.key = serviceKey;
  }

  private async rest(path: string, init: RequestInit = {}): Promise<unknown> {
    const response = await fetch(`${this.url}/rest/v1/${path}`, {
      ...init,
      headers: { apikey: this.key, Authorization: `Bearer ${this.key}`, "Content-Type": "application/json", Prefer: "return=representation", ...(init.headers ?? {}) },
      cache: "no-store",
    });
    if (!response.ok) throw new Error(`Supabase ${path.split("?")[0]} -> ${response.status}: ${await response.text()}`);
    const text = await response.text();
    return text ? JSON.parse(text) : null;
  }

  private rpc(fn: string, args: Row) {
    return this.rest(`rpc/${fn}`, { method: "POST", body: JSON.stringify(args) });
  }

  private async one<T>(path: string): Promise<T | null> {
    const rows = (await this.rest(path)) as Row[];
    return fromRow<T>(rows[0] ?? null);
  }

  deviceByTokenHash(hash: string) {
    return this.one<Device>(`field_devices?token_hash=eq.${hash}&revoked=is.false&limit=1`);
  }

  async workerByTokenHash(hash: string) {
    const rows = (await this.rest(`field_workers?token_hash=eq.${hash}&revoked=is.false`, {
      method: "PATCH", body: JSON.stringify({ last_seen_at: new Date().toISOString() }),
    })) as Row[];
    return fromRow<Worker>(rows[0] ?? null);
  }

  async addDevice(device: Device) {
    await this.rest("field_devices", { method: "POST", body: JSON.stringify(toRow(device)) });
  }

  async addWorker(worker: Worker) {
    await this.rest("field_workers", { method: "POST", body: JSON.stringify(toRow(worker)) });
  }

  async openSession(deviceId: string, clientSessionId: string, buildingId: string, nowMs: number) {
    const rows = (await this.rest("field_sessions?on_conflict=device_id,client_session_id", {
      method: "POST", headers: { Prefer: "return=representation,resolution=ignore-duplicates" },
      body: JSON.stringify({ device_id: deviceId, client_session_id: clientSessionId, building_id: buildingId,
        expires_at: new Date(nowMs + SESSION_TTL_SECONDS * 1000).toISOString() }),
    })) as Row[];
    if (rows[0]) return fromRow<Session>(rows[0])!;
    return (await this.one<Session>(`field_sessions?device_id=eq.${encodeURIComponent(deviceId)}&client_session_id=eq.${encodeURIComponent(clientSessionId)}`))!;
  }

  async renewSession(deviceId: string, sessionId: string, nowMs: number) {
    const rows = (await this.rest(`field_sessions?id=eq.${encodeURIComponent(sessionId)}&device_id=eq.${encodeURIComponent(deviceId)}`, {
      method: "PATCH", body: JSON.stringify({ expires_at: new Date(nowMs + SESSION_TTL_SECONDS * 1000).toISOString() }),
    })) as Row[];
    return fromRow<Session>(rows[0] ?? null);
  }

  session(id: string) {
    return this.one<Session>(`field_sessions?id=eq.${encodeURIComponent(id)}`);
  }

  async registerCapture(input: RegisterInput, nowMs: number): Promise<RegisterResult> {
    if (sessionExpired(input.session.expiresAt, nowMs)) return { status: "conflict", reason: "session expired" };
    const existing = await this.capture(input.captureId);
    const decision = decideRegistration(existing ?? undefined, input.imageSha256);
    if (decision.kind === "conflict") return { status: "conflict", reason: decision.reason };
    if (decision.kind === "existing") return { status: "existing", capture: existing! };
    const building = safeSegment(input.session.buildingId);
    const id = safeSegment(input.captureId);
    const duplicate = await this.one<Capture>(`field_captures?building_id=eq.${encodeURIComponent(building)}&image_sha256=eq.${input.imageSha256}&limit=1`);
    const record = {
      id: input.captureId, session_id: input.session.id, device_id: input.session.deviceId, building_id: input.session.buildingId,
      surface_ids: input.surfaceIds, image_sha256: input.imageSha256, metadata: input.metadata, state: "registered",
      duplicate_of: duplicate?.id ?? null,
      files: input.files.map((f) => ({ ...f, storagePath: `captures/${building}/${id}/${safeSegment(f.name)}`, stored: false })),
    };
    try {
      const rows = (await this.rest("field_captures", { method: "POST", body: JSON.stringify(record) })) as Row[];
      return { status: "created", capture: fromRow<Capture>(rows[0])! };
    } catch (error) {
      // a concurrent retry inserted it first: fall back to the idempotency decision
      const raced = await this.capture(input.captureId);
      if (raced && raced.imageSha256 === input.imageSha256) return { status: "existing", capture: raced };
      throw error;
    }
  }

  capture(id: string) {
    return this.one<Capture>(`field_captures?id=eq.${encodeURIComponent(id)}`);
  }

  async completeUpload(captureId: string, storedFiles: string[]) {
    const before = await this.rest(`field_jobs?state=eq.queued&select=id`) as Row[];
    const capture = fromRow<Capture>((await this.rpc("field_complete_upload", { p_capture: captureId, p_stored: storedFiles })) as Row)!;
    const after = await this.rest(`field_jobs?state=eq.queued&building_id=eq.${encodeURIComponent(capture.buildingId)}`) as Row[];
    const known = new Set(before.map((r) => r.id));
    return { capture, jobs: after.filter((r) => !known.has(r.id)).map((r) => fromRow<Job>(r)!) };
  }

  async claimJob(workerId: string, leaseToken: string): Promise<ClaimedJob | null> {
    const result = (await this.rpc("field_claim_job", { p_worker: workerId, p_lease_token: leaseToken })) as { job: Row; captures: Row[] } | null;
    if (!result) return null;
    return { job: fromRow<Job>(result.job)!, captures: result.captures.map((c) => fromRow<Capture>(c)!) };
  }

  async touchJob(jobId: string, leaseToken: string, progress: JobProgress) {
    const result = await this.rpc("field_touch_job", { p_job: jobId, p_lease_token: leaseToken, p_progress: progress });
    return result === "lease-lost" ? "lease-lost" : fromRow<Job>(result as Row)!;
  }

  async finishJob(jobId: string, leaseToken: string, outcome: JobOutcome) {
    const result = await this.rpc("field_finish_job", { p_job: jobId, p_lease_token: leaseToken, p_outcome: outcome });
    return result === "lease-lost" ? "lease-lost" : fromRow<Job>(result as Row)!;
  }

  job(id: string) {
    return this.one<Job>(`field_jobs?id=eq.${encodeURIComponent(id)}`);
  }

  async surfaceStatus(buildingId: string, surfaceId: string) {
    const b = encodeURIComponent(buildingId);
    const s = encodeURIComponent(surfaceId);
    const [surface, captures, jobs] = await Promise.all([
      this.one<SurfaceRecord>(`field_surfaces?building_id=eq.${b}&surface_id=eq.${s}`),
      this.rest(`field_captures?building_id=eq.${b}&surface_ids=cs.{${JSON.stringify(surfaceId)}}`) as Promise<Row[]>,
      this.rest(`field_jobs?building_id=eq.${b}&surface_id=eq.${s}&order=created_at.desc&limit=10`) as Promise<Row[]>,
    ]);
    return { surface, captures: captures.map((r) => fromRow<Capture>(r)!), jobs: jobs.map((r) => fromRow<Job>(r)!) };
  }

  async reviewSurface(buildingId: string, surfaceId: string, review: NonNullable<SurfaceRecord["review"]>) {
    return fromRow<SurfaceRecord>((await this.rpc("field_review_surface", { p_building: buildingId, p_surface: surfaceId, p_review: review })) as Row)!;
  }
}

export class SupabaseBlobStore implements BlobStore {
  private readonly url: string;
  private readonly key: string;

  constructor(url: string, serviceKey: string) {
    this.url = url.replace(/\/$/, "");
    this.key = serviceKey;
  }

  private headers() {
    return { apikey: this.key, Authorization: `Bearer ${this.key}`, "Content-Type": "application/json" };
  }

  async signUpload(path: string, contentType: string) {
    const response = await fetch(`${this.url}/storage/v1/object/upload/sign/${BUCKET}/${path}`, { method: "POST", headers: { ...this.headers(), "x-upsert": "true" } });
    if (!response.ok) throw new Error(`sign upload ${response.status}`);
    const { url } = (await response.json()) as { url: string };
    return { url: `${this.url}/storage/v1${url}`, method: "PUT" as const, headers: { "Content-Type": contentType, "x-upsert": "true" } };
  }

  async signDownload(path: string) {
    const response = await fetch(`${this.url}/storage/v1/object/sign/${BUCKET}/${path}`, {
      method: "POST", headers: this.headers(), body: JSON.stringify({ expiresIn: 3600 }),
    });
    if (!response.ok) throw new Error(`sign download ${response.status}`);
    const { signedURL } = (await response.json()) as { signedURL: string };
    return `${this.url}/storage/v1${signedURL}`;
  }

  async stat(path: string) {
    const response = await fetch(`${this.url}/storage/v1/object/info/${BUCKET}/${path}`, { headers: this.headers() });
    if (!response.ok) return null;
    const info = (await response.json()) as { size?: number; metadata?: { size?: number } };
    const bytes = info.size ?? info.metadata?.size;
    return typeof bytes === "number" ? { bytes } : null; // Storage does not report SHA-256; the worker re-verifies it
  }
}
