// Compare the Cesium view and the standalone Three.js scene under identical conditions.
// The Cesium view was removed after this comparison: to re-run it, check out commit 52622c4
// (Cesium at /, standalone scene at /preview), build, and point --base at that server.
// Each run uses a fresh browser context (empty HTTP cache), the default layers, and the same
// two camera views. Draw calls and triangles are counted at the WebGL API for both renderers.
//
//   npm i -D playwright   (or: npx playwright install chromium)
//   node scripts/perf/compare-renderers.mjs --base http://localhost:3000 --runs 3 [--chrome /path/to/chrome]
//   (Cesium requires NEXT_PUBLIC_CESIUM_ION_TOKEN on the server being measured)

import { chromium } from "playwright";

const args = Object.fromEntries(process.argv.slice(2).reduce((pairs, value, index, all) => (value.startsWith("--") ? [...pairs, [value.slice(2), all[index + 1]]] : pairs), []));
const base = args.base ?? "http://localhost:3000";
const runs = Number(args.runs ?? 3);
// --targets three --three-path / measures only the standalone scene (e.g. a deployment)
const targets = [
  { name: "cesium", path: "/", ready: () => document.querySelector(".campus-model-preview small")?.textContent?.includes("grounded") },
  { name: "three", path: args["three-path"] ?? "/preview", ready: () => Boolean(window.__campusScene?.metrics?.readyMs) },
].filter((target) => !args.targets || args.targets.split(",").includes(target.name));

// counts draws and primitives between animation frames, for whichever WebGL context is used
const INSTRUMENT = () => {
  const frames = [];
  let calls = 0;
  let triangles = 0;
  const add = (mode, count, instances = 1) => { calls += 1; if (mode === 4) triangles += Math.floor(count / 3) * instances; };
  for (const proto of [window.WebGLRenderingContext?.prototype, window.WebGL2RenderingContext?.prototype].filter(Boolean)) {
    const wrap = (name, fn) => { const original = proto[name]; if (original) proto[name] = function (...a) { fn(...a); return original.apply(this, a); }; };
    wrap("drawArrays", (mode, first, count) => add(mode, count));
    wrap("drawElements", (mode, count) => add(mode, count));
    wrap("drawArraysInstanced", (mode, first, count, instances) => add(mode, count, instances));
    wrap("drawElementsInstanced", (mode, count, type, offset, instances) => add(mode, count, instances));
  }
  const tick = (now) => {
    frames.push({ t: now, calls, triangles });
    calls = 0; triangles = 0;
    if (frames.length > 20000) frames.splice(0, 10000);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
  window.__perf = { frames, mark: () => frames.length };
};

const median = (values) => { const s = [...values].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0; };
const pct = (values, p) => { const s = [...values].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(s.length * p))] : 0; };

async function measure(browser, target) {
  const context = await browser.newContext({ viewport: { width: 1500, height: 950 } });
  const page = await context.newPage();
  await page.addInitScript(INSTRUMENT);
  let requests = 0;
  let bytes = 0;
  page.on("requestfinished", async (request) => {
    requests += 1;
    try { const sizes = await request.sizes(); bytes += sizes.responseBodySize + sizes.responseHeadersSize; } catch { /* ignore */ }
  });
  const started = Date.now();
  await page.goto(base + target.path, { waitUntil: "load", timeout: 180000 });
  await page.waitForFunction(target.ready, null, { timeout: 180000 });
  const loadMs = Date.now() - started;
  await page.waitForTimeout(4000); // let late layers (trees, roads, imagery refinement) settle
  const network = { requests, megabytes: +(bytes / 1e6).toFixed(2) };
  await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });

  const renderedFrames = async (from) => (await page.evaluate((i) => window.__perf.frames.slice(i), from)).filter((f) => f.calls > 0);
  const view = async (label) => {
    // force a few renders by nudging the camera, then read draw stats of rendered frames
    const from = await page.evaluate(() => window.__perf.mark());
    await page.mouse.move(750, 600);
    await page.mouse.wheel(0, -1); await page.waitForTimeout(400); await page.mouse.wheel(0, 1); await page.waitForTimeout(1200);
    const frames = await renderedFrames(from);
    return { view: label, calls: median(frames.map((f) => f.calls)), triangles: median(frames.map((f) => f.triangles)) };
  };
  const overview = await view("overview");

  // scripted pan drag across the campus: frame intervals while interacting
  const dragFrom = await page.evaluate(() => window.__perf.mark());
  await page.mouse.move(600, 650);
  await page.mouse.down();
  for (let i = 0; i < 90; i += 1) { await page.mouse.move(600 + i * 4, 650 - i * 2); await page.waitForTimeout(16); }
  await page.mouse.up();
  await page.waitForTimeout(800);
  const dragFrames = await page.evaluate((i) => window.__perf.frames.slice(i), dragFrom);
  const intervals = dragFrames.slice(1).map((f, i) => f.t - dragFrames[i].t);
  const drag = { frames: intervals.length, p50: +median(intervals).toFixed(1), p95: +pct(intervals, 0.95).toFixed(1), over33ms: intervals.filter((v) => v > 33.4).length };

  await page.evaluate(() => document.querySelector('[aria-label="Ground campus view"]')?.click());
  await page.waitForTimeout(target.name === "cesium" ? 6000 : 2500);
  const ground = await view("ground");
  const heapMB = await page.evaluate(() => (performance.memory ? +(performance.memory.usedJSHeapSize / 1e6).toFixed(1) : null));
  await context.close();
  return { loadMs, network, overview, ground, drag, heapMB };
}

const browser = await chromium.launch({
  executablePath: args.chrome,
  args: ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist", "--disable-quic", "--enable-precise-memory-info"],
});
const results = {};
for (const target of targets) {
  results[target.name] = [];
  for (let run = 0; run < runs; run += 1) {
    try { results[target.name].push(await measure(browser, target)); }
    catch (error) { results[target.name].push({ error: error.message }); }
    console.error(`${target.name} run ${run + 1}:`, JSON.stringify(results[target.name].at(-1)));
  }
}
await browser.close();

const summary = {};
for (const [name, list] of Object.entries(results)) {
  const ok = list.filter((r) => !r.error);
  if (!ok.length) { summary[name] = { error: list[0]?.error }; continue; }
  summary[name] = {
    runs: ok.length,
    loadMs: median(ok.map((r) => r.loadMs)),
    requests: median(ok.map((r) => r.network.requests)),
    megabytes: median(ok.map((r) => r.network.megabytes)),
    overviewCalls: median(ok.map((r) => r.overview.calls)),
    overviewTriangles: median(ok.map((r) => r.overview.triangles)),
    groundCalls: median(ok.map((r) => r.ground.calls)),
    groundTriangles: median(ok.map((r) => r.ground.triangles)),
    dragFrameP50: median(ok.map((r) => r.drag.p50)),
    dragFrameP95: median(ok.map((r) => r.drag.p95)),
    dragFramesOver33ms: median(ok.map((r) => r.drag.over33ms)),
    heapMB: median(ok.map((r) => r.heapMB ?? 0)),
  };
}
console.log(JSON.stringify(summary, null, 2));
