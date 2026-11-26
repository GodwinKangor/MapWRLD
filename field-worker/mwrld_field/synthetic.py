"""Synthetic facade captures with known geometry, for validation and the reproducible demo.

Renders a ground-truth wall texture through an ideal pinhole camera at known
poses and writes capture folders exactly as the iOS app would (schema
mwrld.capture/v1), including LiDAR-style depth with a recessed window bay.
Rendering world = surface frame S: x = u (right), y = v (up), z = n (outward).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .capture import SCHEMA_CAPTURE
from .geometry import surface_to_texture

GT_PPM = 50.0


@dataclass
class Facade:
    width_m: float
    height_m: float
    texture: np.ndarray                      # BGR ground truth at GT_PPM
    fiducials: list[tuple[float, float]]     # (u, v) metres of bright dots
    marker_uv: tuple[float, float]           # centre of the asymmetric red marker (top-left area)
    recess_boxes: list[tuple[float, float, float, float]]  # (u0, v0, u1, v1) recessed by recess_depth_m
    recess_depth_m: float = 0.25


def make_facade(width_m: float = 19.26, height_m: float = 14.98, seed: int = 7) -> Facade:
    rng = np.random.default_rng(seed)
    w, h = int(round(width_m * GT_PPM)), int(round(height_m * GT_PPM))
    # brick-like base with plenty of distinctive texture for feature matching
    base = rng.normal(150, 22, (h // 4 + 1, w // 4 + 1, 3)).clip(0, 255).astype(np.uint8)
    texture = cv2.resize(base, (w, h), interpolation=cv2.INTER_NEAREST)
    texture = cv2.GaussianBlur(texture, (3, 3), 0)
    texture[:, :, 2] = np.clip(texture[:, :, 2].astype(int) + 35, 0, 255)  # reddish brick tone
    for row in range(0, h, 4):
        texture[row, :] = (texture[row, :] * 0.7).astype(np.uint8)
    blobs = rng.integers(0, [w, h], size=(900, 2))
    for (x, y), r in zip(blobs, rng.integers(2, 7, 900)):
        cv2.circle(texture, (int(x), int(y)), int(r), tuple(int(c) for c in rng.integers(40, 230, 3)), -1)

    def px(u, v):
        col, row = surface_to_texture(u, v, height_m, GT_PPM)
        return int(round(col)), int(round(row))

    recess_boxes = []
    for floor in range(3):
        for bay in range(5):
            u0 = 1.6 + bay * (width_m - 3.2) / 5 + 0.6
            v0 = 1.2 + floor * 4.4
            box = (u0, v0, u0 + 1.5, v0 + 2.4)
            recess_boxes.append(box)
            cv2.rectangle(texture, px(box[0], box[3]), px(box[2], box[1]), (60, 55, 50), -1)
            cv2.rectangle(texture, px(box[0], box[3]), px(box[2], box[1]), (225, 225, 220), 4)  # trim
            for k in (1, 2):  # mullions: high-contrast structure inside each window
                x = int(px(box[0] + k * 0.5, 0)[0])
                cv2.line(texture, (x, px(0, box[3])[1]), (x, px(0, box[1])[1]), (200, 200, 195), 2)
    # asymmetric "F" marker near the top-left: catches any mirroring or flipping
    mu, mv = 1.2, height_m - 1.0
    c, r = px(mu, mv)
    cv2.rectangle(texture, (c - 20, r - 30), (c - 12, r + 30), (0, 0, 230), -1)
    cv2.rectangle(texture, (c - 20, r - 30), (c + 22, r - 22), (0, 0, 230), -1)
    cv2.rectangle(texture, (c - 20, r - 4), (c + 10, r + 4), (0, 0, 230), -1)
    fiducials = [(u, v) for u in np.linspace(0.8, width_m - 0.8, 7) for v in (0.6, height_m / 2 + 0.3, height_m - 0.6)]
    for u, v in fiducials:  # sub-pixel centres (shift=4) so the ground truth itself is exact
        col, row = surface_to_texture(u, v, height_m, GT_PPM)
        centre = (int(round(col * 16)), int(round(row * 16)))
        cv2.circle(texture, centre, 6 * 16, (0, 0, 0), -1, cv2.LINE_AA, 4)
        cv2.circle(texture, centre, 4 * 16, (255, 255, 255), -1, cv2.LINE_AA, 4)
    return Facade(width_m, height_m, texture, fiducials, (mu, mv), recess_boxes)


@dataclass
class Camera:
    position: tuple[float, float, float]   # S frame metres (n > 0 is outside)
    target: tuple[float, float, float]
    focal_px: float = 1700.0
    size: tuple[int, int] = (2016, 1512)   # native landscape sensor grid
    roll_deg: float = 0.0                  # 90 = phone held in portrait

    def matrices(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        c = np.asarray(self.position, float)
        f = np.asarray(self.target, float) - c
        f /= np.linalg.norm(f)
        r = np.cross(f, [0, 1, 0])
        r /= np.linalg.norm(r)
        d = np.cross(f, r)
        roll = np.radians(self.roll_deg)
        r, d = np.cos(roll) * r + np.sin(roll) * d, -np.sin(roll) * r + np.cos(roll) * d
        rot = np.stack([r, d, f])  # rows: camera x (right), y (down), z (forward) in world
        w, h = self.size
        k = np.array([[self.focal_px, 0, w / 2], [0, self.focal_px, h / 2], [0, 0, 1]])
        return k, rot, c

    def project(self, points: np.ndarray) -> np.ndarray:
        k, rot, c = self.matrices()
        cam = (np.asarray(points, float) - c) @ rot.T
        pix = cam @ k.T
        return pix[:, :2] / pix[:, 2:3]


def render(facade: Facade, camera: Camera) -> np.ndarray:
    """Planar render of the wall (image) through the camera."""
    w, h = facade.texture.shape[1], facade.texture.shape[0]
    tex_corners = np.array([[0, 0], [w, 0], [w, h], [0, h]], float)
    # OpenCV puts pixel centres at integer coordinates, matching geometry.texture_to_surface
    world = np.array([[(x + 0.5) / GT_PPM, facade.height_m - (y + 0.5) / GT_PPM, 0.0] for x, y in tex_corners])
    img_corners = camera.project(world)
    hmat = cv2.getPerspectiveTransform(tex_corners.astype(np.float32), img_corners.astype(np.float32))
    sky = np.full((camera.size[1], camera.size[0], 3), (235, 206, 170), np.uint8)
    image = cv2.warpPerspective(facade.texture, hmat, camera.size, dst=sky, borderMode=cv2.BORDER_TRANSPARENT, flags=cv2.INTER_LINEAR)
    return image


def render_depth(facade: Facade, camera: Camera, size: tuple[int, int] = (256, 192)) -> np.ndarray:
    """Ray-traced depth (camera z, metres) on a scaled copy of the image grid, with recessed window bays."""
    k, rot, c = camera.matrices()
    dw, dh = size
    sx, sy = dw / camera.size[0], dh / camera.size[1]
    xs, ys = np.meshgrid((np.arange(dw) + 0.5) / sx, (np.arange(dh) + 0.5) / sy)
    rays_cam = np.stack([(xs - k[0, 2]) / k[0, 0], (ys - k[1, 2]) / k[1, 1], np.ones_like(xs)], axis=-1)
    rays = rays_cam @ rot  # world directions (rot rows are camera axes)
    depth = np.full((dh, dw), np.nan, np.float32)
    for plane_n, region in [(-facade.recess_depth_m, "recess"), (0.0, "wall")]:
        t = (plane_n - c[2]) / rays[..., 2]
        hit = c + rays * t[..., None]
        u, v = hit[..., 0], hit[..., 1]
        inside_wall = (u >= 0) & (u <= facade.width_m) & (v >= 0) & (v <= facade.height_m) & (t > 0)
        in_bay = np.zeros_like(inside_wall)
        for u0, v0, u1, v1 in facade.recess_boxes:
            in_bay |= (u > u0) & (u < u1) & (v > v0) & (v < v1)
        take = inside_wall & (in_bay if region == "recess" else ~in_bay) & np.isnan(depth)
        depth[take] = t[take]  # rays_cam has z = 1, so t is camera-space depth
    return depth


def write_capture(folder: Path, facade: Facade, camera: Camera, surface_id: str, building_id: str, session_id: str,
                  kind: str = "overview", corners: bool = True, corner_noise_px: float = 0.0, depth: bool = False,
                  obstruction_uv: list[tuple[float, float]] | None = None, annotations_uv: list[dict] | None = None,
                  measurement_uv: tuple[tuple[float, float], tuple[float, float]] | None = None,
                  exif_orientation: int = 1, seed: int = 0) -> Path:
    """Render and save one capture exactly as the app writes it (native pixel grid)."""
    rng = np.random.default_rng(seed)
    folder.mkdir(parents=True, exist_ok=True)
    image = render(facade, camera)
    if obstruction_uv:  # paint a 'tree' over the wall where the obstruction polygon is
        poly = camera.project(np.array([[u, v, 0.4] for u, v in obstruction_uv]))
        cv2.fillPoly(image, [np.round(poly).astype(np.int32)], (40, 110, 50))
    cv2.imwrite(str(folder / "image.jpg"), image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    data = (folder / "image.jpg").read_bytes()
    k, rot, c = camera.matrices()
    w, h = camera.size
    capture = {
        "schema": SCHEMA_CAPTURE, "captureId": str(uuid.UUID(int=int(rng.integers(0, 2**63)))), "sessionId": session_id,
        "buildingId": building_id, "surfaceIds": [surface_id], "primarySurfaceId": surface_id, "kind": kind,
        "createdAt": "2026-11-26T12:00:00Z",
        "device": {"model": "synthetic", "app": "mwrld_field.synthetic"},
        "image": {"file": "image.jpg", "sha256": hashlib.sha256(data).hexdigest(), "width": w, "height": h,
                  "exifOrientation": exif_orientation, "format": "jpeg", "pixelGrid": "native-sensor"},
        "camera": {"source": "synthetic-pinhole",
                   "intrinsics": {"fx": k[0, 0], "fy": k[1, 1], "cx": k[0, 2], "cy": k[1, 2], "referenceWidth": w, "referenceHeight": h},
                   "distortion": None},
        "pose": {"frame": "synthetic-surface-frame", "note": "ground truth, for validation only",
                 "position": list(map(float, c)), "rotationRowsCameraAxes": rot.tolist()},
        "alignment": {}, "annotations": [], "measurements": [],
        "synthetic": True,
    }
    if corners:
        labels_uv = {"top-left": (0, facade.height_m), "top-right": (facade.width_m, facade.height_m),
                     "bottom-right": (facade.width_m, 0), "bottom-left": (0, 0)}
        pts = camera.project(np.array([[u, v, 0] for u, v in labels_uv.values()]))
        pts += rng.normal(0, corner_noise_px, pts.shape) if corner_noise_px else 0
        capture["alignment"][surface_id] = {"method": "manual-corners", "provenance": "synthetic", "points": [
            {"label": label, "image": [float(x), float(y)], "surface": [float(u), float(v)]}
            for (label, (u, v)), (x, y) in zip(labels_uv.items(), pts)]}
    if obstruction_uv:
        poly = camera.project(np.array([[u, v, 0.4] for u, v in obstruction_uv]))
        capture["annotations"].append({"id": "obs-1", "surfaceId": surface_id, "kind": "obstruction", "label": "tree",
                                       "polygon": poly.tolist()})
    for i, ann in enumerate(annotations_uv or []):
        u0, v0, u1, v1 = ann["box"]
        poly = camera.project(np.array([[u0, v1, 0], [u1, v1, 0], [u1, v0, 0], [u0, v0, 0]]))
        capture["annotations"].append({"id": f"ann-{i}", "surfaceId": surface_id, "kind": ann["kind"], "label": ann.get("label", ""),
                                       "polygon": poly.tolist()})
    if measurement_uv:
        ends = camera.project(np.array([[u, v, 0] for u, v in measurement_uv]))
        true = float(np.hypot(*np.subtract(measurement_uv[1], measurement_uv[0])))
        capture["measurements"].append({"id": "m-1", "surfaceId": surface_id, "valueM": true, "uncertaintyM": 0.005,
                                        "endpoints": ends.tolist(), "method": "synthetic-tape"})
    if depth:
        d = render_depth(facade, camera)
        d.astype("<f4").tofile(folder / "depth.f32")
        conf = np.where(np.isfinite(d) & (d <= 5.0), 2, 0).astype(np.uint8)
        conf.tofile(folder / "confidence.u8")
        capture["depth"] = {"file": "depth.f32", "confidenceFile": "confidence.u8", "width": d.shape[1], "height": d.shape[0],
                            "encoding": "float32-le row-major", "units": "m", "source": "synthetic ray-traced", "pixelGrid": "native-sensor (scaled)"}
    (folder / "capture.json").write_text(json.dumps(capture, indent=2))
    return folder


def measure_fiducials(texture: np.ndarray, facade: Facade, ppm: float, search_m: float = 0.12) -> list[float]:
    """Distance (mm) between each fiducial's true position and its centroid in a rectified texture."""
    gray = cv2.cvtColor(texture[:, :, :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
    alpha = texture[:, :, 3] if texture.shape[2] == 4 else np.full(gray.shape, 255, np.uint8)
    errors = []
    r = int(round(search_m * ppm))
    for u, v in facade.fiducials:
        col, row = surface_to_texture(u, v, facade.height_m, ppm)
        c0, r0 = int(round(col)), int(round(row))
        if not (r <= c0 < gray.shape[1] - r and r <= r0 < gray.shape[0] - r) or alpha[r0, c0] == 0:
            continue
        patch = gray[r0 - r:r0 + r + 1, c0 - r:c0 + r + 1]
        bright = patch > 235
        if bright.sum() < 3:
            continue
        ys, xs = np.nonzero(bright)
        # compare against the exact (sub-pixel) expected centre, not the rounded patch centre
        dx, dy = xs.mean() + c0 - r - col, ys.mean() + r0 - r - row
        errors.append(float(np.hypot(dx, dy) / ppm * 1000))
    return errors
