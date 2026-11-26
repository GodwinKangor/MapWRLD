// Route-handler glue: picks the repository, authenticates devices/workers, shapes responses.

import { readFile } from "node:fs/promises";
import path from "node:path";
import { NextResponse } from "next/server";
import { FsBlobStore, FsRepo } from "./fs-repo.ts";
import type { BlobStore, FieldRepo } from "./repo.ts";
import { SupabaseBlobStore, SupabaseRepo } from "./supabase-repo.ts";
import { bearer, hashToken, safeSegment } from "./tokens.ts";
import type { Device, Worker } from "./types.ts";

type Backend = { repo: FieldRepo; blobs: BlobStore; kind: "supabase" | "local" };
let cached: Backend | null = null;

/** FIELD_STORE=supabase (production) needs SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY; otherwise local files. */
export function backend(request?: Request): Backend {
  if (cached) return cached;
  const supabaseUrl = process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL;
  const serviceKey = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (process.env.FIELD_STORE === "supabase") {
    if (!supabaseUrl || !serviceKey) throw new Error("FIELD_STORE=supabase needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY");
    cached = { repo: new SupabaseRepo(supabaseUrl, serviceKey), blobs: new SupabaseBlobStore(supabaseUrl, serviceKey), kind: "supabase" };
    return cached;
  }
  if (process.env.VERCEL) throw new Error("The local field store cannot run on Vercel; set FIELD_STORE=supabase");
  const dir = path.resolve(process.env.FIELD_DATA_DIR ?? ".field-data");
  const secret = process.env.FIELD_SIGNING_SECRET;
  if (!secret || secret.length < 32) throw new Error("FIELD_SIGNING_SECRET (32+ chars) is required");
  const base = process.env.FIELD_PUBLIC_URL ?? (request ? new URL(request.url).origin : "http://localhost:3000");
  cached = { repo: new FsRepo(dir), blobs: new FsBlobStore(path.join(dir, "blobs"), base, secret), kind: "local" };
  return cached;
}

export function json(body: unknown, status = 200) {
  return NextResponse.json(body, { status, headers: { "Cache-Control": "no-store" } });
}

export function problem(status: number, message: string) {
  return json({ error: message }, status);
}

export async function authDevice(request: Request): Promise<Device | null> {
  const token = bearer(request.headers.get("authorization"));
  return token?.startsWith("mwrld_dev_") ? backend(request).repo.deviceByTokenHash(hashToken(token)) : null;
}

export async function authWorker(request: Request): Promise<Worker | null> {
  const token = bearer(request.headers.get("authorization"));
  return token?.startsWith("mwrld_wrk_") ? backend(request).repo.workerByTokenHash(hashToken(token)) : null;
}

export async function body<T>(request: Request): Promise<T | null> {
  try {
    return (await request.json()) as T;
  } catch {
    return null;
  }
}

/** Surface registries are versioned files in data/field-surfaces (built by blender-build-surface-registry.py). */
export async function surfaceRegistry(buildingId: string): Promise<Record<string, unknown> | null> {
  const file = path.join(process.cwd(), "data", "field-surfaces", `${safeSegment(buildingId)}.surfaces.json`);
  try {
    return JSON.parse(await readFile(file, "utf8"));
  } catch {
    return null;
  }
}

export async function registrySurface(buildingId: string, surfaceId: string) {
  const registry = await surfaceRegistry(buildingId);
  const surfaces = (registry?.surfaces ?? []) as { surfaceId: string }[];
  return surfaces.find((s) => s.surfaceId === surfaceId) ?? null;
}
