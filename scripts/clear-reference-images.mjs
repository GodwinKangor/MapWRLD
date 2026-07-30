import { mkdir, rm } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const target = path.join(root, "public", "reference-atlas", "images");

if (!process.argv.includes("--confirm")) {
  console.log("This removes local generated reference photos only.");
  console.log("Run: node scripts/clear-reference-images.mjs --confirm");
  process.exit(0);
}

await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
console.log(`Removed ${path.relative(root, target)}`);
