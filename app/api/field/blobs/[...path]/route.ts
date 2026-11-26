// Local blob store only (FIELD_STORE unset): serves HMAC-signed GET/PUT URLs minted by FsBlobStore.
// With Supabase, clients use Storage's own signed URLs and this route returns 404.
import { readFile } from "node:fs/promises";
import { FsBlobStore } from "@/lib/field/fs-repo";
import { backend, problem } from "@/lib/field/server";
import { verifySignature } from "@/lib/field/tokens";

export const dynamic = "force-dynamic";

async function authorise(request: Request, segments: string[], method: string) {
  const { blobs } = backend(request);
  if (!(blobs instanceof FsBlobStore)) return null;
  const url = new URL(request.url);
  const storagePath = segments.map(decodeURIComponent).join("/");
  const ok = verifySignature(process.env.FIELD_SIGNING_SECRET!, method, storagePath, Number(url.searchParams.get("expires")), url.searchParams.get("sig") ?? "", Date.now());
  return ok ? { blobs, storagePath } : null;
}

export async function PUT(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const access = await authorise(request, (await params).path, "PUT");
  if (!access) return problem(403, "bad or expired signature");
  await access.blobs.write(access.storagePath, new Uint8Array(await request.arrayBuffer()));
  return new Response(null, { status: 200 });
}

export async function GET(request: Request, { params }: { params: Promise<{ path: string[] }> }) {
  const access = await authorise(request, (await params).path, "GET");
  if (!access) return problem(403, "bad or expired signature");
  try {
    const data = await readFile(access.blobs.resolve(access.storagePath));
    const type = access.storagePath.endsWith(".jpg") ? "image/jpeg" : access.storagePath.endsWith(".png") ? "image/png"
      : access.storagePath.endsWith(".json") ? "application/json" : "application/octet-stream";
    return new Response(data, { headers: { "Content-Type": type, "Cache-Control": "private, max-age=300" } });
  } catch {
    return problem(404, "not found");
  }
}
