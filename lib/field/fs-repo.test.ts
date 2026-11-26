// node --test lib/field/*.test.ts   (Node >= 23 runs TypeScript by stripping types)
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { after, before, beforeEach, describe, it } from "node:test";
import { FsRepo } from "./fs-repo.ts";
import { LEASE_SECONDS, MAX_ATTEMPTS, SESSION_TTL_SECONDS, canTransition } from "./state.ts";
import type { Session } from "./types.ts";

const SURFACE = "osm:way/261793901/wall/2674282718-2674282725";
const T0 = Date.parse("2026-11-26T12:00:00Z");
let dir: string;
let repo: FsRepo;
let session: Session;

async function register(id: string, sha = `sha-${id}`, surfaceIds = [SURFACE]) {
  const result = await repo.registerCapture({
    captureId: id, session, imageSha256: sha, surfaceIds,
    files: [{ name: "image.jpg", sha256: sha, bytes: 10, contentType: "image/jpeg" }, { name: "capture.json", sha256: "j", bytes: 5, contentType: "application/json" }],
    metadata: {},
  }, T0);
  return result;
}

async function uploaded(id: string, sha?: string) {
  await register(id, sha);
  return repo.completeUpload(id, ["image.jpg", "capture.json"], T0);
}

before(async () => { dir = await mkdtemp(path.join(tmpdir(), "field-repo-")); });
after(async () => { await rm(dir, { recursive: true, force: true }); });
beforeEach(async () => {
  repo = new FsRepo(await mkdtemp(path.join(dir, "case-")));
  session = await repo.openSession("dev1", "client-session-1", "mcnutt-hall-261793901", T0);
});

describe("sessions", () => {
  it("are idempotent per client session id", async () => {
    const again = await repo.openSession("dev1", "client-session-1", "mcnutt-hall-261793901", T0 + 1000);
    assert.equal(again.id, session.id);
  });
  it("refuse captures once expired, until renewed", async () => {
    const late = T0 + (SESSION_TTL_SECONDS + 1) * 1000;
    const refused = await repo.registerCapture({ captureId: "c-late", session, imageSha256: "x", surfaceIds: [SURFACE], files: [], metadata: {} }, late);
    assert.equal(refused.status, "conflict");
    const renewed = await repo.renewSession("dev1", session.id, late);
    assert.ok(renewed);
    const accepted = await repo.registerCapture({ captureId: "c-late", session: renewed, imageSha256: "x", surfaceIds: [SURFACE], files: [], metadata: {} }, late);
    assert.equal(accepted.status, "created");
    assert.equal(await repo.renewSession("someone-else", session.id, late), null);
  });
});

describe("duplicate uploads", () => {
  it("a retried registration returns the same capture", async () => {
    assert.equal((await register("c1")).status, "created");
    assert.equal((await register("c1")).status, "existing");
  });
  it("the same id with different bytes is a conflict", async () => {
    await register("c1", "aaa");
    const result = await register("c1", "bbb");
    assert.equal(result.status, "conflict");
  });
  it("identical bytes under a new id are kept but not reprocessed", async () => {
    await uploaded("c1", "same");
    const { capture, jobs } = await uploaded("c2", "same");
    assert.equal(capture.duplicateOf, "c1");
    assert.equal(jobs.length, 0);
  });
  it("completing an upload twice queues nothing new", async () => {
    const first = await uploaded("c1");
    assert.equal(first.jobs.length, 1);
    const second = await repo.completeUpload("c1", ["image.jpg", "capture.json"], T0);
    assert.equal(second.jobs.length, 0);
  });
  it("a partial upload stays registered", async () => {
    await register("c1");
    const { capture, jobs } = await repo.completeUpload("c1", ["capture.json"], T0);
    assert.equal(capture.state, "registered");
    assert.equal(jobs.length, 0);
  });
});

describe("jobs", () => {
  it("coalesce: many photos while queued -> one job", async () => {
    await uploaded("c1");
    await uploaded("c2");
    await uploaded("c3");
    const status = await repo.surfaceStatus(session.buildingId, SURFACE);
    assert.equal(status.jobs.filter((j) => j.state === "queued").length, 1);
  });

  it("a photo arriving mid-run triggers exactly one follow-up run that includes it", async () => {
    await uploaded("c1");
    const claimed = await repo.claimJob("w1", "lease-a", T0);
    assert.deepEqual(claimed?.job.captureIds, ["c1"]);
    await uploaded("c2");
    await uploaded("c3");
    let status = await repo.surfaceStatus(session.buildingId, SURFACE);
    assert.equal(status.surface?.rerunRequested, true);
    assert.equal(status.jobs.filter((j) => j.state === "queued").length, 0);
    await repo.finishJob(claimed!.job.id, "lease-a", { ok: true, files: {}, coverage: {}, summary: {}, resultPrefix: "r1" }, T0 + 1000);
    status = await repo.surfaceStatus(session.buildingId, SURFACE);
    assert.equal(status.jobs.filter((j) => j.state === "queued").length, 1);
    const next = await repo.claimJob("w1", "lease-b", T0 + 2000);
    assert.deepEqual(new Set(next?.job.captureIds), new Set(["c1", "c2", "c3"]));
  });

  it("an interrupted worker's job is requeued after the lease expires, and its stale lease can't finish", async () => {
    await uploaded("c1");
    const first = await repo.claimJob("w1", "lease-a", T0);
    assert.ok(first);
    assert.equal(await repo.claimJob("w2", "lease-b", T0 + 1000), null); // still leased
    const later = T0 + (LEASE_SECONDS + 1) * 1000;
    const second = await repo.claimJob("w2", "lease-b", later);
    assert.equal(second?.job.id, first.job.id);
    assert.equal(second?.job.attempts, 2);
    // the restarted first worker reports late: rejected, so it can't overwrite newer work
    const stale = await repo.finishJob(first.job.id, "lease-a", { ok: true, files: {}, coverage: {}, summary: {}, resultPrefix: "old" }, later + 10);
    assert.equal(stale, "lease-lost");
    const touch = await repo.touchJob(first.job.id, "lease-a", { stage: "x", fraction: 0, message: "", at: "" }, later + 10);
    assert.equal(touch, "lease-lost");
  });

  it("progress extends the lease", async () => {
    await uploaded("c1");
    const claimed = await repo.claimJob("w1", "lease-a", T0);
    const nearlyExpired = T0 + (LEASE_SECONDS - 1) * 1000;
    await repo.touchJob(claimed!.job.id, "lease-a", { stage: "composite", fraction: 0.5, message: "", at: "" }, nearlyExpired);
    assert.equal(await repo.claimJob("w2", "lease-b", nearlyExpired + 5000), null);
  });

  it("gives up after MAX_ATTEMPTS crashed runs and marks captures failed", async () => {
    await uploaded("c1");
    let now = T0;
    for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
      const claimed = await repo.claimJob("w", `lease-${attempt}`, now);
      assert.equal(claimed?.job.attempts, attempt);
      now += (LEASE_SECONDS + 1) * 1000;
    }
    assert.equal(await repo.claimJob("w", "lease-final", now), null);
    const status = await repo.surfaceStatus(session.buildingId, SURFACE);
    assert.equal(status.jobs[0].state, "failed");
    assert.equal(status.captures[0].state, "failed");
  });

  it("a retryable failure requeues; a permanent one fails the captures", async () => {
    await uploaded("c1");
    const a = await repo.claimJob("w", "l1", T0);
    const retry = await repo.finishJob(a!.job.id, "l1", { ok: false, error: "disk full", retryable: true }, T0 + 1);
    assert.equal(retry !== "lease-lost" && retry.state, "queued");
    assert.equal((await repo.capture("c1"))?.state, "uploaded");
    const b = await repo.claimJob("w", "l2", T0 + 2);
    const fail = await repo.finishJob(b!.job.id, "l2", { ok: false, error: "bad package", retryable: false }, T0 + 3);
    assert.equal(fail !== "lease-lost" && fail.state, "failed");
    assert.equal((await repo.capture("c1"))?.state, "failed");
  });

  it("success publishes the result; review survives the rebuild it triggers", async () => {
    await uploaded("c1");
    const a = await repo.claimJob("w", "l1", T0);
    await repo.finishJob(a!.job.id, "l1", { ok: true, files: { preview: "preview.jpg" }, coverage: { percent: { usable: 80 } }, summary: {}, resultPrefix: "results/x/1" }, T0 + 1);
    assert.equal((await repo.capture("c1"))?.state, "processed");
    const status = await repo.surfaceStatus(session.buildingId, SURFACE);
    assert.equal(status.surface?.latest?.prefix, "results/x/1");

    await repo.reviewSurface(session.buildingId, SURFACE, { regions: [{ polygon: [[0, 0], [1, 0], [1, 1]] }], reviewedBy: "dev1", reviewedAt: "" }, T0 + 2);
    assert.equal((await repo.capture("c1"))?.state, "reviewed");
    const b = await repo.claimJob("w", "l2", T0 + 3); // the review queues a rebuild
    assert.equal((await repo.capture("c1"))?.state, "processing");
    await repo.finishJob(b!.job.id, "l2", { ok: true, files: {}, coverage: {}, summary: {}, resultPrefix: "results/x/2" }, T0 + 4);
    assert.equal((await repo.capture("c1"))?.state, "reviewed");
  });

  it("concurrent claims never lease the same job twice", async () => {
    await uploaded("c1");
    const claims = await Promise.all(["a", "b", "c", "d"].map((w) => repo.claimJob(w, `lease-${w}`, T0)));
    assert.equal(claims.filter(Boolean).length, 1);
  });
});

describe("capture transitions", () => {
  it("disallow skipping upload", () => {
    assert.equal(canTransition("registered", "processing"), false);
    assert.equal(canTransition("registered", "uploaded"), true);
  });
});
