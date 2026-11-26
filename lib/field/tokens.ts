// Bearer tokens (stored only as SHA-256 hashes) and HMAC-signed storage URLs for the local blob store.

import { createHash, createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export function newToken(prefix: "mwrld_dev" | "mwrld_wrk"): string {
  return `${prefix}_${randomBytes(32).toString("base64url")}`;
}

export function hashToken(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export function bearer(header: string | null): string | null {
  const match = /^Bearer\s+(\S+)$/i.exec(header ?? "");
  return match ? match[1] : null;
}

export function newId(): string {
  return randomBytes(16).toString("hex");
}

export function sign(secret: string, method: string, path: string, expires: number): string {
  return createHmac("sha256", secret).update(`${method}\n${path}\n${expires}`).digest("base64url");
}

export function verifySignature(secret: string, method: string, path: string, expires: number, signature: string, nowMs: number): boolean {
  if (!Number.isFinite(expires) || expires * 1000 < nowMs) return false;
  const expected = Buffer.from(sign(secret, method, path, expires));
  const given = Buffer.from(signature);
  return expected.length === given.length && timingSafeEqual(expected, given);
}

/** Storage keys never come straight from clients: only these characters, no traversal. */
export function safeSegment(value: string): string {
  const cleaned = value.replace(/[^A-Za-z0-9._-]/g, "_");
  if (!cleaned || cleaned === "." || cleaned === "..") throw new Error(`unsafe path segment: ${value}`);
  return cleaned;
}

/** Surface IDs contain ':' and '/', so storage paths use a reversible-enough key plus a short hash. */
export function surfaceKey(surfaceId: string): string {
  return `${safeSegment(surfaceId).slice(0, 80)}-${createHash("sha256").update(surfaceId).digest("hex").slice(0, 8)}`;
}
