"""Capture package: one photograph plus everything known about it.

A capture is a folder holding `capture.json` (schema mwrld.capture/v1, written
by the iOS app; see docs/field-capture/SPEC.md) and the files it names.

Pixel convention: every pixel coordinate in capture.json (corners,
annotations, intrinsics, depth) is in the stored image's NATIVE pixel grid,
i.e. EXIF orientation is NOT applied. `image.exifOrientation` only says how
to display it. Images are therefore read with IMREAD_IGNORE_ORIENTATION.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

SCHEMA_CAPTURE = "mwrld.capture/v1"
CAPTURE_KINDS = {"overview", "detail", "focus-sweep"}
ANNOTATION_KINDS = {"obstruction", "window", "door", "trim", "recess", "projection", "note", "reviewed-region"}
CORNER_LABELS = ("top-left", "top-right", "bottom-right", "bottom-left")


class CaptureError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class ControlPoint:
    label: str
    image_xy: tuple[float, float]       # native pixels
    surface_uv: tuple[float, float]     # S frame metres


@dataclass
class Annotation:
    annotation_id: str
    surface_id: str
    kind: str
    polygon: list[tuple[float, float]]  # native pixels
    label: str = ""


@dataclass
class Measurement:
    measurement_id: str
    surface_id: str
    value_m: float
    uncertainty_m: float
    endpoints: list[tuple[float, float]]  # native pixels
    method: str


@dataclass
class Capture:
    folder: Path
    raw: dict
    capture_id: str
    session_id: str
    building_id: str
    surface_ids: list[str]
    kind: str
    image_path: Path
    width: int
    height: int
    image_sha256: str
    control_points: dict[str, list[ControlPoint]] = field(default_factory=dict)  # by surface id
    annotations: list[Annotation] = field(default_factory=list)
    measurements: list[Measurement] = field(default_factory=list)

    @property
    def camera(self) -> dict:
        return self.raw.get("camera") or {}

    @property
    def depth(self) -> dict | None:
        return self.raw.get("depth")

    def read_image(self) -> np.ndarray:
        image = cv2.imread(str(self.image_path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if image is None:
            raise CaptureError(f"{self.capture_id}: cannot decode {self.image_path.name}")
        return image

    def annotations_for(self, surface_id: str, kinds: set[str] | None = None) -> list[Annotation]:
        return [a for a in self.annotations if a.surface_id == surface_id and (kinds is None or a.kind in kinds)]


def _pairs(value, name: str) -> list[tuple[float, float]]:
    try:
        points = [(float(x), float(y)) for x, y in value]
    except (TypeError, ValueError) as exc:
        raise CaptureError(f"{name}: expected [[x, y], ...]") from exc
    return points


def load_capture(folder: Path, verify_hash: bool = True) -> Capture:
    """Read and validate one capture folder. Raises CaptureError listing every problem."""
    path = folder / "capture.json"
    if not path.exists():
        raise CaptureError(f"{folder.name}: missing capture.json")
    raw = json.loads(path.read_text())
    problems: list[str] = []
    if raw.get("schema") != SCHEMA_CAPTURE:
        problems.append(f"schema is {raw.get('schema')!r}, expected {SCHEMA_CAPTURE}")
    for key in ("captureId", "sessionId", "buildingId", "surfaceIds", "kind", "image", "createdAt"):
        if key not in raw:
            problems.append(f"missing {key}")
    if problems:
        raise CaptureError(f"{folder.name}: " + "; ".join(problems))
    if raw["kind"] not in CAPTURE_KINDS:
        problems.append(f"unknown kind {raw['kind']!r}")
    surface_ids = list(raw["surfaceIds"])
    if not surface_ids:
        problems.append("surfaceIds is empty")

    image = raw["image"]
    image_path = folder / image.get("file", "")
    width, height = int(image.get("width", 0)), int(image.get("height", 0))
    sha = image.get("sha256", "")
    if not image_path.is_file():
        problems.append(f"image file {image.get('file')!r} missing")
    else:
        if verify_hash and sha != sha256_file(image_path):
            problems.append("image sha256 does not match the file (corrupt or partial upload)")
        decoded = cv2.imread(str(image_path), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
        if decoded is None:
            problems.append("image does not decode")
        elif decoded.shape[:2] != (height, width):
            problems.append(f"image is {decoded.shape[1]}x{decoded.shape[0]}, capture.json says {width}x{height}")
    if image.get("exifOrientation", 1) not in range(1, 9):
        problems.append("exifOrientation must be 1..8")

    control_points: dict[str, list[ControlPoint]] = {}
    for surface_id, alignment in (raw.get("alignment") or {}).items():
        if surface_id not in surface_ids:
            problems.append(f"alignment for {surface_id} which is not in surfaceIds")
            continue
        points = []
        for point in alignment.get("points", []):
            (ix, iy), = _pairs([point["image"]], "alignment.image")
            (u, v), = _pairs([point["surface"]], "alignment.surface")
            if not (0 <= ix < width and 0 <= iy < height):
                problems.append(f"control point {point.get('label')} lies outside the image")
            points.append(ControlPoint(point.get("label", ""), (ix, iy), (u, v)))
        if points and len(points) < 4:
            problems.append(f"{surface_id}: manual alignment needs 4+ control points, got {len(points)}")
        control_points[surface_id] = points

    annotations = []
    for item in raw.get("annotations", []):
        if item.get("kind") not in ANNOTATION_KINDS:
            problems.append(f"annotation {item.get('id')}: unknown kind {item.get('kind')!r}")
            continue
        polygon = _pairs(item.get("polygon", []), "annotation.polygon")
        if len(polygon) < 3:
            problems.append(f"annotation {item.get('id')}: polygon needs 3+ points")
            continue
        annotations.append(Annotation(item.get("id", ""), item.get("surfaceId", surface_ids[0] if surface_ids else ""),
                                      item["kind"], polygon, item.get("label", "")))

    measurements = []
    for item in raw.get("measurements", []):
        endpoints = _pairs(item.get("endpoints", []), "measurement.endpoints")
        value, sigma = float(item.get("valueM", 0)), float(item.get("uncertaintyM", -1))
        if len(endpoints) != 2 or value <= 0 or sigma < 0:
            problems.append(f"measurement {item.get('id')}: needs 2 endpoints, valueM > 0, uncertaintyM >= 0")
            continue
        measurements.append(Measurement(item.get("id", ""), item.get("surfaceId", surface_ids[0] if surface_ids else ""),
                                        value, sigma, endpoints, item.get("method", "unspecified")))

    depth = raw.get("depth")
    if depth:
        depth_path = folder / depth.get("file", "")
        dw, dh = int(depth.get("width", 0)), int(depth.get("height", 0))
        if not depth_path.is_file():
            problems.append("depth file missing")
        elif depth_path.stat().st_size != dw * dh * 4:
            problems.append(f"depth file is {depth_path.stat().st_size} bytes, expected {dw}x{dh} float32")

    if problems:
        raise CaptureError(f"{folder.name}: " + "; ".join(problems))
    return Capture(folder, raw, raw["captureId"], raw["sessionId"], raw["buildingId"], surface_ids, raw["kind"],
                   image_path, width, height, sha, control_points, annotations, measurements)


def read_depth(capture: Capture) -> tuple[np.ndarray, np.ndarray | None] | None:
    """Depth (metres, float32, native depth grid) and ARKit confidence (0 low, 1 medium, 2 high)."""
    depth = capture.depth
    if not depth:
        return None
    dw, dh = int(depth["width"]), int(depth["height"])
    values = np.fromfile(capture.folder / depth["file"], dtype="<f4").reshape(dh, dw)
    confidence = None
    if depth.get("confidenceFile"):
        confidence = np.fromfile(capture.folder / depth["confidenceFile"], dtype=np.uint8).reshape(dh, dw)
    return values, confidence
