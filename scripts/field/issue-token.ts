// Issue a device (phone) or worker (Mac) token. The token is printed ONCE; only its SHA-256 is stored.
//   node scripts/field/issue-token.ts device "Godwin's iPhone"
//   node scripts/field/issue-token.ts worker "Home M2"
// Uses the same backend selection as the API (FIELD_STORE=supabase or local .field-data).
import path from "node:path";
import { FsRepo } from "../../lib/field/fs-repo.ts";
import { SupabaseRepo } from "../../lib/field/supabase-repo.ts";
import { hashToken, newId, newToken } from "../../lib/field/tokens.ts";

const [kind, label] = process.argv.slice(2);
if ((kind !== "device" && kind !== "worker") || !label) {
  console.error('usage: node scripts/field/issue-token.ts device|worker "label"');
  process.exit(2);
}
const repo = process.env.FIELD_STORE === "supabase"
  ? new SupabaseRepo(process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL ?? "", process.env.SUPABASE_SERVICE_ROLE_KEY ?? "")
  : new FsRepo(path.resolve(process.env.FIELD_DATA_DIR ?? ".field-data"));
const token = newToken(kind === "device" ? "mwrld_dev" : "mwrld_wrk");
const record = { id: `${kind}-${newId().slice(0, 12)}`, label, tokenHash: hashToken(token), revoked: false, createdAt: new Date().toISOString() };
await (kind === "device" ? repo.addDevice(record) : repo.addWorker(record));
console.log(`${kind} ${record.id} (${label})`);
console.log(`token: ${token}`);
console.log("Store it now (phone: Settings > Pair; Mac: worker .env). It is not recoverable.");
