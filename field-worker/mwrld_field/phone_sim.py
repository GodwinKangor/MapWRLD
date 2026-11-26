"""Phone simulator: uploads capture folders through the same API calls the iOS app makes.

    python -m mwrld_field.phone_sim --api http://localhost:3000 --token mwrld_dev_... \
        --building mcnutt-hall-261793901 --captures DIR [DIR ...] [--wait]

Used for the reproducible one-wall demo and for end-to-end checks without a device.
It deliberately repeats some calls (retries) to exercise idempotency.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path

import requests

CONTENT_TYPES = {".jpg": "image/jpeg", ".heic": "image/heic", ".json": "application/json", ".f32": "application/octet-stream", ".u8": "application/octet-stream"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phone:
    def __init__(self, api: str, token: str):
        self.api = api.rstrip("/")
        self.http = requests.Session()
        self.http.headers["Authorization"] = f"Bearer {token}"
        self.timings: list[dict] = []

    def call(self, method: str, path: str, **kw) -> requests.Response:
        t = time.perf_counter()
        response = self.http.request(method, f"{self.api}{path}", timeout=60, **kw)
        self.timings.append({"call": f"{method} {path.split('?')[0]}", "status": response.status_code, "s": round(time.perf_counter() - t, 3)})
        return response

    def package(self, building: str) -> dict:
        response = self.call("GET", f"/api/field/buildings/{building}/package")
        response.raise_for_status()
        return response.json()

    def open_session(self, building: str, client_session: str) -> dict:
        response = self.call("POST", "/api/field/sessions", json={"clientSessionId": client_session, "buildingId": building})
        response.raise_for_status()
        return response.json()["session"]

    def upload(self, session: dict, folder: Path) -> dict:
        meta = json.loads((folder / "capture.json").read_text())
        meta["sessionId"] = session["id"]
        (folder / "capture.json").write_text(json.dumps(meta, indent=2))
        names = [meta["image"]["file"], "capture.json"] + [meta["depth"][k] for k in ("file", "confidenceFile") if meta.get("depth") and meta["depth"].get(k)]
        files = [{"name": n, "sha256": sha(folder / n), "bytes": (folder / n).stat().st_size, "contentType": CONTENT_TYPES.get(Path(n).suffix, "application/octet-stream")} for n in names]
        payload = {"captureId": meta["captureId"], "sessionId": session["id"], "surfaceIds": meta["surfaceIds"], "imageSha256": meta["image"]["sha256"],
                   "files": files, "metadata": meta}
        response = self.call("POST", "/api/field/captures", json=payload)
        if response.status_code == 410:  # expired session: renew and retry once
            self.call("POST", f"/api/field/sessions/{session['id']}/renew").raise_for_status()
            response = self.call("POST", "/api/field/captures", json=payload)
        response.raise_for_status()
        reply = response.json()
        for upload in reply["uploads"]:
            t = time.perf_counter()
            put = requests.put(upload["url"], data=(folder / upload["name"]).read_bytes(), headers=upload["headers"], timeout=120)
            put.raise_for_status()
            self.timings.append({"call": f"PUT {upload['name']}", "status": put.status_code, "s": round(time.perf_counter() - t, 3),
                                 "bytes": (folder / upload["name"]).stat().st_size})
        done = self.call("POST", f"/api/field/captures/{meta['captureId']}/complete")
        done.raise_for_status()
        return done.json()

    def status(self, building: str, surface: str) -> dict:
        response = self.call("GET", "/api/field/surfaces/status", params={"buildingId": building, "surfaceId": surface})
        response.raise_for_status()
        return response.json()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--building", required=True)
    parser.add_argument("--captures", type=Path, nargs="+", required=True)
    parser.add_argument("--wait", action="store_true", help="poll until the surface's job finishes")
    parser.add_argument("--save-preview", type=Path)
    args = parser.parse_args()
    phone = Phone(args.api, args.token)
    package = phone.package(args.building)
    print(f"package: {len(package['surfaces'])} surfaces, references for {sum(bool(v) for v in package['references'].values())}")
    session = phone.open_session(args.building, str(uuid.uuid4()))
    surface = None
    t_upload = time.perf_counter()
    for folder in args.captures:
        reply = phone.upload(session, folder)
        surface = reply["capture"]["surfaceIds"][0]
        print(f"uploaded {folder.name}: {reply['capture']['state']} queued={reply['queuedJobs']} missing={reply['missing']}")
    uploaded_at = time.perf_counter()
    print(f"upload wall time {uploaded_at - t_upload:.2f}s")
    if args.wait and surface:
        last = None
        while True:
            status = phone.status(args.building, surface)
            job = status["job"] or {}
            line = (job.get("state"), (job.get("progress") or {}).get("stage"))
            if line != last:
                print(f"  +{time.perf_counter() - uploaded_at:6.1f}s job {line[0]} {line[1] or ''}  captures {[c['state'] for c in status['captures']]}")
                last = line
            if job.get("state") in ("succeeded", "failed") and not status["rerunRequested"]:
                break
            time.sleep(1)
        print(f"result after {time.perf_counter() - uploaded_at:.1f}s from last upload")
        if status["latest"]:
            print("coverage:", json.dumps(status["latest"]["coverage"]["percent"]))
            print("links:", sorted(status["latest"]["links"]))
            if args.save_preview and "preview" in status["latest"]["links"]:
                args.save_preview.write_bytes(requests.get(status["latest"]["links"]["preview"], timeout=60).content)
        else:
            print("job error:", job.get("error"))
    print(json.dumps({"timings": phone.timings}, indent=1)[:3000])


if __name__ == "__main__":
    main()
