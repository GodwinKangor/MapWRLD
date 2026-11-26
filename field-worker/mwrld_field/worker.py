"""Mac worker: polls the MapWRLD API outbound, processes surface jobs, applies them in Blender.

    python -m mwrld_field.worker            # reads field-worker/.env (see .env.example)
    python -m mwrld_field.worker --once     # one job (or none) then exit; used by the demo/tests

Nothing listens on the Mac: it only makes outbound HTTPS requests, so neither Blender nor the
worker is exposed to the internet. Run it under `caffeinate` (scripts/run-worker.sh does) so the
Mac stays awake while plugged in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import requests

from .pipeline import STAGES, SurfaceJob, run_surface_job

log = logging.getLogger("mwrld.worker")
ROOT = Path(__file__).resolve().parents[2]


class LeaseLost(Exception):
    """The server requeued this job (we were too slow or offline); stop without publishing."""


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"'))


class Api:
    def __init__(self, base: str, token: str, timeout: float = 30):
        self.base = base.rstrip("/")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Bearer {token}"
        self.timeout = timeout

    def post(self, path: str, payload: dict | None = None) -> requests.Response:
        return self.session.post(f"{self.base}{path}", json=payload or {}, timeout=self.timeout)


def free_gb(path: Path) -> float:
    path.mkdir(parents=True, exist_ok=True)
    return shutil.disk_usage(path).free / 1e9


def download(url: str, dest: Path, sha256: str, retries: int = 4) -> None:
    for attempt in range(retries):
        try:
            tmp = dest.with_suffix(dest.suffix + ".part")
            digest = hashlib.sha256()
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(1 << 20):
                        handle.write(chunk)
                        digest.update(chunk)
            if digest.hexdigest() != sha256:
                raise IOError(f"{dest.name}: checksum mismatch")
            tmp.replace(dest)
            return
        except (requests.RequestException, IOError) as exc:
            if attempt == retries - 1:
                raise
            log.warning("download %s failed (%s); retrying", dest.name, exc)
            time.sleep(2 ** attempt)


class Worker:
    def __init__(self, api: Api, work_dir: Path, blender: str | None, blend_file: Path | None, out_blend: Path | None,
                 min_free_gb: float = 2.0):
        self.api = api
        self.work_dir = work_dir
        self.blender = blender
        self.blend_file = blend_file
        self.out_blend = out_blend
        self.min_free_gb = min_free_gb
        self.metrics: dict = {}

    def run_once(self) -> bool:
        """Claim and process one job. Returns False when there was nothing to do."""
        if free_gb(self.work_dir) < self.min_free_gb:
            log.error("only %.1f GB free under %s; not claiming work", free_gb(self.work_dir), self.work_dir)
            return False
        t_claim = time.perf_counter()
        response = self.api.post("/api/field/worker/claim", {"host": socket.gethostname()})
        if response.status_code == 204:
            return False
        response.raise_for_status()
        claim = response.json()
        job, lease = claim["job"], claim["leaseToken"]
        self.metrics = {"claimS": round(time.perf_counter() - t_claim, 3)}
        log.info("job %s: %s (%d captures, attempt %d)", job["id"], job["surfaceId"], len(claim["captures"]), job["attempts"])
        job_dir = self.work_dir / "jobs" / job["id"]
        try:
            self._process(claim, job_dir)
        except LeaseLost:
            log.warning("job %s: lease lost; discarding local results", job["id"])
        except Exception as exc:  # report and keep the worker alive
            retryable = isinstance(exc, (requests.RequestException, OSError))
            log.exception("job %s failed (retryable=%s)", job["id"], retryable)
            self._finish(job["id"], lease, {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:1500], "retryable": retryable}, quiet=True)
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)  # originals live in storage; local copies are disposable
        return True

    def _progress(self, job_id: str, lease: str, stage: str, fraction: float, message: str) -> None:
        response = self.api.post(f"/api/field/worker/jobs/{job_id}/progress",
                                 {"leaseToken": lease, "stage": stage, "fraction": fraction, "message": message})
        if response.status_code == 409:
            raise LeaseLost()

    def _finish(self, job_id: str, lease: str, payload: dict, quiet: bool = False) -> None:
        response = self.api.post(f"/api/field/worker/jobs/{job_id}/finish", {"leaseToken": lease, **payload})
        if response.status_code == 409:
            if quiet:
                return
            raise LeaseLost()
        response.raise_for_status()

    def _process(self, claim: dict, job_dir: Path) -> None:
        job, lease, surface = claim["job"], claim["leaseToken"], claim["surface"]
        job_dir.mkdir(parents=True, exist_ok=True)
        stop_heartbeat = threading.Event()
        last = {"stage": "download", "fraction": 0.0, "message": ""}
        lost = threading.Event()

        def heartbeat():  # keeps the lease alive through long stages (Blender, large textures)
            while not stop_heartbeat.wait(30):
                try:
                    self._progress(job["id"], lease, last["stage"], last["fraction"], last["message"])
                except LeaseLost:
                    lost.set()
                    return
                except requests.RequestException as exc:
                    log.warning("heartbeat failed: %s", exc)

        beat = threading.Thread(target=heartbeat, daemon=True)
        beat.start()
        try:
            t = time.perf_counter()
            self._progress(job["id"], lease, "download", 0.0, f"{len(claim['captures'])} captures")
            capture_dirs = []
            for i, capture in enumerate(claim["captures"]):
                folder = job_dir / "captures" / capture["id"]
                folder.mkdir(parents=True, exist_ok=True)
                for f in capture["files"]:
                    download(f["url"], folder / f["name"], f["sha256"])
                capture_dirs.append(folder)
                last.update(stage="download", fraction=(i + 1) / len(claim["captures"]))
            self.metrics["downloadS"] = round(time.perf_counter() - t, 3)

            sent = {"at": 0.0}

            def progress(stage: str, fraction: float, message: str) -> None:
                if lost.is_set():
                    raise LeaseLost()
                overall = (STAGES.index(stage) + fraction) / (len(STAGES) + 2) if stage in STAGES else fraction
                last.update(stage=stage, fraction=overall, message=message)
                if time.monotonic() - sent["at"] > 2:  # throttle network chatter
                    sent["at"] = time.monotonic()
                    self._progress(job["id"], lease, stage, overall, message)

            out_dir = job_dir / "result"
            t = time.perf_counter()
            result = run_surface_job(SurfaceJob(surface, capture_dirs, out_dir, review=claim.get("review"), progress=progress))
            self.metrics["processS"] = round(time.perf_counter() - t, 3)
            if result.summary["sources"] == 0:
                raise ValueError("no capture could be aligned: " + "; ".join(r["reason"] for r in result.rejected)[:800])

            files = dict(result.files)
            if self.blender and self.blend_file:
                t = time.perf_counter()
                progress("blender", 0.0, "applying texture in Blender")
                preview = out_dir / "preview-blender.png"
                registry = ROOT / "data" / "field-surfaces" / f"{surface['buildingId']}.surfaces.json"
                command = [self.blender, "--background", "--factory-startup", str(self.blend_file), "--python",
                           str(ROOT / "scripts" / "blender" / "blender-apply-facade-texture.py"), "--",
                           "--registry", str(registry), "--surface-id", surface["surfaceId"], "--result-dir", str(out_dir),
                           "--out-blend", str(self.out_blend), "--preview", str(preview), "--job-id", job["id"]]
                done = subprocess.run(command, capture_output=True, text=True, timeout=900)
                report = next((json.loads(line.split(" ", 1)[1]) for line in done.stdout.splitlines() if line.startswith("FACADE_REPORT ")), None)
                if done.returncode != 0 or report is None:
                    raise RuntimeError("Blender bridge failed: " + (done.stdout + done.stderr)[-1200:])
                (out_dir / "blender-report.json").write_text(json.dumps(report, indent=2))
                files["blenderPreview"] = preview.name
                files["blenderReport"] = "blender-report.json"
                self.metrics["blenderS"] = round(time.perf_counter() - t, 3)
                # the source .blend for the next update is the one we just wrote: updates accumulate per wall
                self.blend_file = self.out_blend

            t = time.perf_counter()
            progress("upload", 0.0, "uploading results")
            content_types = {".png": "image/png", ".jpg": "image/jpeg", ".json": "application/json", ".npz": "application/octet-stream"}
            response = self.api.post(f"/api/field/worker/jobs/{job['id']}/results",
                                     {"leaseToken": lease, "files": [{"name": n, "contentType": content_types.get(Path(n).suffix, "application/octet-stream")} for n in files.values()]})
            if response.status_code == 409:
                raise LeaseLost()
            response.raise_for_status()
            signed = response.json()
            for upload in signed["uploads"]:
                data = (out_dir / upload["name"]).read_bytes()
                put = requests.put(upload["url"], data=data, headers=upload["headers"], timeout=120)
                put.raise_for_status()
            self.metrics["uploadS"] = round(time.perf_counter() - t, 3)
            summary = {**result.summary, "timingsS": result.timings, "worker": self.metrics, "rejected": result.rejected}
            self._finish(job["id"], lease, {"ok": True, "files": files, "coverage": result.coverage, "summary": summary,
                                            "resultPrefix": signed["prefix"]})
            log.info("job %s done: usable %.1f%%, %s", job["id"], result.coverage["percent"]["usable"], self.metrics)
        finally:
            stop_heartbeat.set()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--env", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--poll", type=float, default=5.0)
    args = parser.parse_args()
    load_env(args.env)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    base, token = os.environ.get("FIELD_API_URL"), os.environ.get("FIELD_WORKER_TOKEN")
    if not base or not token:
        sys.exit("FIELD_API_URL and FIELD_WORKER_TOKEN are required (field-worker/.env)")
    blend = os.environ.get("FIELD_BLEND_FILE")
    worker = Worker(
        Api(base, token),
        Path(os.environ.get("FIELD_WORKER_DIR", Path(__file__).resolve().parents[1] / ".worker-data")).expanduser(),
        os.environ.get("BLENDER_PATH") if blend else None,
        Path(blend).expanduser() if blend else None,
        Path(os.environ.get("FIELD_OUT_BLEND", "~/MapWRLD-facades/dartmouth-energy-twin.facades.blend")).expanduser(),
        float(os.environ.get("FIELD_MIN_FREE_GB", "2")),
    )
    # resume from the accumulated facade file if a previous run produced one
    if worker.blend_file and worker.out_blend and worker.out_blend.exists():
        worker.blend_file = worker.out_blend
    backoff = args.poll
    while True:
        try:
            did = worker.run_once()
            backoff = args.poll
        except requests.RequestException as exc:  # offline, server restarting, DNS: wait and retry
            log.warning("API unreachable (%s); retrying in %.0fs", exc, backoff)
            did, backoff = False, min(backoff * 2, 300)
        if args.once:
            return
        if not did:
            time.sleep(backoff)


if __name__ == "__main__":
    main()
