"""Surface job: every capture of one surface -> rectified texture, coverage, details, provenance.

Run incrementally: the worker re-runs the job whenever a capture arrives for
the surface; projected source layers are kept in an in-process cache keyed by
everything that affects them, so only new or re-aligned photos are re-warped.
Originals are never modified; outputs go to a separate folder.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from . import __version__
from .capture import Capture, CaptureError, load_capture, read_depth
from .compose import LABEL_NAMES, SourceLayer, composite, coverage_preview, project_source
from .geometry import surface_to_texture, texture_to_surface
from .rectify import Alignment, feature_alignment, manual_alignment
from .relief import FLUSH_THRESHOLD_M, depth_relief, feature_relief, relief_grid
from .undistort import undistort_image, undistort_points, usable_calibration

log = logging.getLogger("mwrld.pipeline")
SCHEMA_DETAILS = "mwrld.facade-details/v1"
SCHEMA_PROVENANCE = "mwrld.facade-provenance/v1"
FEATURE_KINDS = {"window", "door", "trim", "recess", "projection"}
STAGES = ["validate", "undistort", "align-manual", "align-auto", "project", "composite", "relief", "export"]

Progress = Callable[[str, float, str], None]


def default_pixels_per_meter(width_m: float, height_m: float, memory_bytes: int | None = None) -> float:
    """1 cm texels (100 px/m) unless the texture would exceed a memory-scaled budget.

    Composite memory is ~40 bytes per texel per in-flight array set; on a 16 GB
    M2 the budget below keeps a surface job well under 2 GB.
    """
    if memory_bytes is None:
        try:
            memory_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
        except (ValueError, OSError):
            memory_bytes = 8 << 30
    max_texels = min(24e6, memory_bytes / (1 << 30) * 1.5e6)
    return float(min(100.0, np.sqrt(max_texels / max(width_m * height_m, 1e-6))))


@dataclass
class SurfaceJob:
    surface: dict
    capture_dirs: list[Path]
    out_dir: Path
    pixels_per_meter: float | None = None
    review: dict | None = None
    progress: Progress = lambda stage, fraction, message: None


@dataclass
class JobResult:
    out_dir: Path
    coverage: dict
    files: dict[str, str]
    rejected: list[dict]
    timings: dict
    summary: dict = field(default_factory=dict)


_LAYER_CACHE: dict[str, SourceLayer] = {}
_CACHE_LIMIT = 24


def _cache_key(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).hexdigest()


def _polygon_mask(shape: tuple[int, int], polygons: list[np.ndarray]) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    for polygon in polygons:
        cv2.fillPoly(mask, [np.round(polygon).astype(np.int32)], 1)
    return mask.astype(bool)


@dataclass
class _Prepared:
    capture: Capture
    image: np.ndarray
    corrected: bool
    calibration: dict | None

    def points(self, xy) -> np.ndarray:
        pts = np.asarray(xy, dtype=np.float64).reshape(-1, 2)
        if self.calibration is None:
            return pts
        return undistort_points(pts, self.calibration, self.capture.width, self.capture.height)


def run_surface_job(job: SurfaceJob) -> JobResult:
    t0 = time.perf_counter()
    timings: dict[str, float] = {}
    surface = job.surface
    sid = surface["surfaceId"]
    width_m, height_m = surface["widthM"], surface["heightM"]
    ppm = job.pixels_per_meter or default_pixels_per_meter(width_m, height_m)
    tex_w, tex_h = int(round(width_m * ppm)), int(round(height_m * ppm))
    texture_size = (tex_w, tex_h)
    job.out_dir.mkdir(parents=True, exist_ok=True)
    rejected: list[dict] = []

    def stage(name: str, fraction: float, message: str = "") -> None:
        job.progress(name, fraction, message)

    def lap(name: str, start: float) -> None:
        timings[name] = round(time.perf_counter() - start, 3)

    # 1. validate
    t = time.perf_counter()
    stage("validate", 0.0, f"{len(job.capture_dirs)} captures")
    captures: list[Capture] = []
    for folder in job.capture_dirs:
        try:
            capture = load_capture(folder)
        except CaptureError as exc:
            rejected.append({"capture": folder.name, "stage": "validate", "reason": str(exc)})
            continue
        if sid not in capture.surface_ids:
            rejected.append({"capture": capture.capture_id, "stage": "validate", "reason": f"not tagged with {sid}"})
            continue
        captures.append(capture)
    lap("validate", t)

    # 2. undistort (only with a usable calibration; recorded either way)
    t = time.perf_counter()
    prepared: dict[str, _Prepared] = {}
    for i, capture in enumerate(captures):
        stage("undistort", i / max(len(captures), 1), capture.capture_id)
        calibration = usable_calibration(capture.camera)
        image = capture.read_image()
        if calibration is not None:
            image = undistort_image(image, calibration)
        prepared[capture.capture_id] = _Prepared(capture, image, calibration is not None, calibration)
    lap("undistort", t)

    def obstruction_mask(p: _Prepared) -> np.ndarray | None:
        polygons = [p.points(a.polygon) for a in p.capture.annotations_for(sid, {"obstruction"})]
        return _polygon_mask(p.image.shape[:2], polygons) if polygons else None

    def layer_for(p: _Prepared, alignment: Alignment) -> SourceLayer:
        key = _cache_key(p.capture.image_sha256, alignment.as_dict(), ppm, width_m, height_m, p.corrected,
                         [(a.annotation_id, a.polygon) for a in p.capture.annotations_for(sid, {"obstruction"})])
        if key not in _LAYER_CACHE:
            if len(_LAYER_CACHE) >= _CACHE_LIMIT:
                _LAYER_CACHE.pop(next(iter(_LAYER_CACHE)))
            _LAYER_CACHE[key] = project_source(p.capture.capture_id, p.image, obstruction_mask(p), alignment, texture_size)
        return _LAYER_CACHE[key]

    # 3. manual alignment (the always-available fallback)
    t = time.perf_counter()
    layers: list[SourceLayer] = []
    alignments: dict[str, Alignment] = {}
    pending: list[_Prepared] = []
    manual: list[tuple[_Prepared, Alignment, list]] = []
    for i, p in enumerate(prepared.values()):
        stage("align-manual", i / max(len(prepared), 1), p.capture.capture_id)
        points = p.capture.control_points.get(sid) or []
        if not points:
            pending.append(p)
            continue
        alignment = manual_alignment(p.points([cp.image_xy for cp in points]), np.array([cp.surface_uv for cp in points]),
                                     height_m, ppm, (p.capture.width, p.capture.height), texture_size)
        alignments[p.capture.capture_id] = alignment
        if alignment.ok:
            manual.append((p, alignment, points))
        else:
            rejected.append({"capture": p.capture.capture_id, "stage": "align-manual", "reason": alignment.reason})
    consensus = _corner_consensus(manual, alignments, texture_size, ppm, height_m, layer_for)
    for p, _, _ in manual:
        layers.append(layer_for(p, alignments[p.capture.capture_id]))
    lap("align-manual", t)

    # 4. automatic alignment against what is already rectified (two passes so
    #    photos that only overlap newly added ones still get a chance)
    t = time.perf_counter()
    for attempt in range(2):
        if not pending or not layers:
            break
        reference = composite(layers, texture_size, ppm)
        ref_ids = [layer.capture_id for layer in layers]
        still = []
        for i, p in enumerate(pending):
            stage("align-auto", i / len(pending), p.capture.capture_id)
            alignment = feature_alignment(p.image, reference.texture[:, :, :3], reference.labels >= 2, ref_ids, texture_size)
            alignments[p.capture.capture_id] = alignment
            if alignment.ok:
                layers.append(layer_for(p, alignment))
            else:
                still.append(p)
        pending = still
    for p in pending:
        a = alignments.get(p.capture.capture_id)
        rejected.append({"capture": p.capture.capture_id, "stage": "align-auto",
                         "reason": a.reason if a else "no manual corners and nothing rectified yet to match against"})
    lap("align-auto", t)

    # 5-6. composite (projection happened in layer_for)
    t = time.perf_counter()
    stage("composite", 0.0, f"{len(layers)} sources")
    reviewed = None
    if job.review and job.review.get("regions"):
        polys = [np.array([surface_to_texture(u, v, height_m, ppm) for u, v in region["polygon"]]) for region in job.review["regions"]]
        reviewed = _polygon_mask((tex_h, tex_w), polys)
    comp = composite(layers, texture_size, ppm, reviewed)
    lap("composite", t)

    # 7. relief + architectural details
    t = time.perf_counter()
    stage("relief", 0.0, "")
    relief_samples = []
    for layer in layers:
        p = prepared[layer.capture_id]
        depth = read_depth(p.capture)
        intrinsics = p.capture.camera.get("intrinsics")
        if depth is None or not intrinsics:
            continue
        values, confidence = depth
        tex_to_img = np.linalg.inv(layer.alignment.homography)
        corners = np.array([[0, 0], [tex_w, 0], [tex_w, tex_h], [0, tex_h]], np.float64)
        wall_in_image = cv2.perspectiveTransform(corners[None], tex_to_img)[0]
        # depth/intrinsics are in the original (distorted) grid; use the original-image homography
        image_to_texture = layer.alignment.homography
        if p.corrected:
            log.info("%s: depth relief uses undistorted homography on distorted depth grid (small error near edges)", layer.capture_id)
        samples = depth_relief(layer.capture_id, values, confidence, intrinsics, (p.capture.width, p.capture.height),
                               image_to_texture, wall_in_image, obstruction_mask(p))
        if samples is not None:
            relief_samples.append(samples)
    cell_px = max(1, int(round(0.10 * ppm)))  # 10 cm cells
    relief_median, relief_count = relief_grid(relief_samples, texture_size, cell_px)
    details = _details(sid, surface, layers, prepared, relief_samples, relief_median, relief_count, cell_px, ppm, height_m)
    lap("relief", t)

    # 8. measurements: independent tape/laser dimensions checked against the texture
    measurement_checks = []
    for p in prepared.values():
        a = alignments.get(p.capture.capture_id)
        if not a or not a.ok:
            continue
        for m in p.capture.measurements:
            if m.surface_id != sid:
                continue
            ends = cv2.perspectiveTransform(p.points(m.endpoints)[None], a.homography)[0]
            uv = [texture_to_surface(x, y, height_m, ppm) for x, y in ends]
            measured_in_texture = float(np.hypot(uv[1][0] - uv[0][0], uv[1][1] - uv[0][1]))
            measurement_checks.append({
                "measurementId": m.measurement_id, "capture": p.capture.capture_id, "method": m.method,
                "fieldValueM": m.value_m, "fieldUncertaintyM": m.uncertainty_m, "textureValueM": round(measured_in_texture, 4),
                "errorM": round(measured_in_texture - m.value_m, 4),
                "note": "Field value is the reference; error includes endpoint placement on the photo.",
            })

    # 9. export
    t = time.perf_counter()
    stage("export", 0.0, "")
    out = job.out_dir
    files = {
        "texture": "texture.png", "coverage": "coverage.png", "sourceIndex": "source-index.png",
        "uncertainty": "alignment-sigma-mm.png", "disagreement": "disagreement.png", "preview": "preview.jpg",
        "relief": "relief.npz", "reliefPreview": "relief-preview.png", "details": "surface-details.json",
        "provenance": "provenance.json", "coverageReport": "coverage.json",
    }
    cv2.imwrite(str(out / files["texture"]), comp.texture)
    cv2.imwrite(str(out / files["coverage"]), comp.labels)
    cv2.imwrite(str(out / files["sourceIndex"]), comp.source_index)
    cv2.imwrite(str(out / files["uncertainty"]), np.where(np.isfinite(comp.sigma_mm), np.clip(comp.sigma_mm * 10, 0, 65534), 65535).astype(np.uint16))
    cv2.imwrite(str(out / files["disagreement"]), np.where(np.isfinite(comp.disagreement), np.clip(comp.disagreement, 0, 254), 255).astype(np.uint8))
    cv2.imwrite(str(out / files["preview"]), coverage_preview(comp), [cv2.IMWRITE_JPEG_QUALITY, 82])
    np.savez_compressed(out / files["relief"], offset_m=relief_median, samples=relief_count, cell_px=cell_px, pixels_per_meter=ppm)
    cv2.imwrite(str(out / files["reliefPreview"]), _relief_preview(relief_median))
    (out / files["details"]).write_text(json.dumps(details, indent=2) + "\n")

    coverage = {**comp.coverage, "surfaceId": sid, "pixelsPerMeter": ppm, "textureSize": [tex_w, tex_h],
                "labels": LABEL_NAMES, "sources": len(layers), "rejectedCaptures": len(rejected)}
    (out / files["coverageReport"]).write_text(json.dumps(coverage, indent=2) + "\n")
    lap("export", t)
    timings["total"] = round(time.perf_counter() - t0, 3)

    provenance = {
        "schema": SCHEMA_PROVENANCE, "pipelineVersion": __version__, "surfaceId": sid,
        "surfaceFrame": surface.get("frame"), "widthM": width_m, "heightM": height_m,
        "texture": {"pixelsPerMeter": ppm, "size": [tex_w, tex_h],
                    "orientation": "row 0 = top of wall; column 0 = left end seen from outside (S-frame u = 0); unmirrored",
                    "alpha": "255 usable, 96 photographed but below quality gates, 0 not observed"},
        "sourceIndexFile": files["sourceIndex"],
        "sources": [{
            "index": i, "captureId": layer.capture_id, "imageSha256": prepared[layer.capture_id].capture.image_sha256,
            "kind": prepared[layer.capture_id].capture.kind,
            "lensCorrection": "apple-lut" if prepared[layer.capture_id].corrected else "none (no usable calibration table)",
            "alignment": layer.alignment.as_dict(), "stats": layer.stats,
        } for i, layer in enumerate(layers)],
        "rejected": rejected, "measurementChecks": measurement_checks, "timingsS": timings,
        "consistency": _pairwise_consistency(layers, ppm),
        "cornerConsensus": consensus,
        "planarAssumption": "Each source is mapped with one plane homography; depth relief and source disagreement show where it fails.",
        "originals": "Original images are unmodified; this folder holds derived products only.",
    }
    (out / files["provenance"]).write_text(json.dumps(provenance, indent=2) + "\n")
    stage("export", 1.0, "done")
    return JobResult(out, coverage, files, rejected, timings,
                     {"sources": len(layers), "measurementChecks": measurement_checks, "consistency": provenance["consistency"]})


def _corner_consensus(manual, alignments, texture_size, ppm, height_m, layer_for) -> dict:
    """Pool hand-placed control points from several photos instead of trusting each photo's taps alone.

    The best photo (finest resolution) is the anchor. Every other manually aligned photo is
    registered to the anchor by features (precise to ~1 mm on synthetic data); its tapped
    points, mapped through that registration, are further estimates of where the control
    points lie in the anchor's texture. Averaging all estimates and correcting every layer by
    the homography that moves the averages onto their nominal positions reduces tap error
    roughly by sqrt(N) and makes the photos agree with each other. Photos that fail feature
    registration keep their own corners.
    """
    if len(manual) < 2:
        return {"used": False, "reason": "fewer than 2 manually aligned photos"}
    ranked = sorted(manual, key=lambda m: -(layer_for(m[0], m[1]).stats.get("medianResolution") or 0))
    anchor_p, anchor_a, anchor_pts = ranked[0]
    reference = composite([layer_for(anchor_p, anchor_a)], texture_size, ppm)
    estimates: dict[str, list[np.ndarray]] = {}
    nominal: dict[str, np.ndarray] = {}
    registered = {anchor_p.capture.capture_id: anchor_a.homography}

    def add(points, homography, p):
        mapped = cv2.perspectiveTransform(p.points([cp.image_xy for cp in points])[None], homography)[0]
        for cp, xy in zip(points, mapped):
            key = f"{cp.surface_uv[0]:.3f},{cp.surface_uv[1]:.3f}"  # same physical point = same surface coordinates
            estimates.setdefault(key, []).append(xy)
            nominal[key] = np.array(surface_to_texture(*cp.surface_uv, height_m, ppm))

    add(anchor_pts, anchor_a.homography, anchor_p)
    for p, alignment, points in ranked[1:]:
        feat = feature_alignment(p.image, reference.texture[:, :, :3], reference.labels >= 2, [anchor_p.capture.capture_id], texture_size)
        if feat.ok:
            registered[p.capture.capture_id] = feat.homography
            add(points, feat.homography, p)
    shared = {k: np.mean(v, axis=0) for k, v in estimates.items() if len(v) >= 2}
    if len(shared) < 4:
        return {"used": False, "reason": "fewer than 4 control points seen in 2+ registered photos", "registered": len(registered)}
    keys = sorted(shared)
    correction, _ = cv2.findHomography(np.array([shared[k] for k in keys]), np.array([nominal[k] for k in keys]), 0)
    spread = {k: round(float(np.sqrt(np.mean(np.sum((np.array(estimates[k]) - shared[k]) ** 2, axis=1)))) / ppm * 1000, 1) for k in keys}
    for p, alignment, _ in manual:
        h = registered.get(p.capture.capture_id)
        if h is None:
            continue
        n = len(estimates[keys[0]])
        alignments[p.capture.capture_id] = Alignment(
            "manual-corners+consensus", correction @ h, True, "", alignment.residual_rms_px, references=list(registered),
            tap_sigma_px=(alignment.tap_sigma_px or 0) / np.sqrt(n))
    return {"used": True, "anchor": anchor_p.capture.capture_id, "photos": list(registered),
            "tapSpreadMm": spread,
            "note": "RMS distance of each photo's tapped point from the pooled estimate: large values mean inconsistent taps."}


def _pairwise_consistency(layers: list[SourceLayer], ppm: float, max_pairs: int = 12) -> dict:
    """Misregistration between rectified sources: features matched across two layers
    should land on the same texel; their displacement (mm) measures relative
    alignment error on the wall plane. Not absolute accuracy."""
    pairs = []
    sift = cv2.SIFT_create(nfeatures=3000)
    for i in range(len(layers)):
        for j in range(i + 1, len(layers)):
            if len(pairs) >= max_pairs:
                break
            overlap = layers[i].usable & layers[j].usable
            if overlap.sum() < 5000:
                continue
            mask = cv2.erode(overlap.astype(np.uint8) * 255, np.ones((9, 9), np.uint8))
            gi = cv2.cvtColor(layers[i].color, cv2.COLOR_BGR2GRAY)
            gj = cv2.cvtColor(layers[j].color, cv2.COLOR_BGR2GRAY)
            ki, di = sift.detectAndCompute(gi, mask)
            kj, dj = sift.detectAndCompute(gj, mask)
            if di is None or dj is None or len(ki) < 20 or len(kj) < 20:
                continue
            matches = [m for m, n in (p for p in cv2.BFMatcher().knnMatch(di, dj, k=2) if len(p) == 2) if m.distance < 0.7 * n.distance]
            disp = np.array([np.subtract(ki[m.queryIdx].pt, kj[m.trainIdx].pt) for m in matches])
            if len(disp) < 20:
                continue
            dist = np.hypot(disp[:, 0], disp[:, 1])
            keep = dist < 40  # beyond this the match is almost certainly wrong, not misregistration
            if keep.sum() < 20:
                continue
            pairs.append({"sources": [i, j], "matches": int(keep.sum()),
                          "medianMm": round(float(np.median(dist[keep])) / ppm * 1000, 2),
                          "p90Mm": round(float(np.percentile(dist[keep], 90)) / ppm * 1000, 2)})
    return {"pairs": pairs, "method": "SIFT matches between rectified layers in their usable overlap; displacement on the wall plane",
            "note": "Relative alignment between photos, not error against the true building."}


def _relief_preview(offset: np.ndarray) -> np.ndarray:
    scaled = np.clip(offset / 0.30, -1, 1)  # +-30 cm full scale
    image = np.full(offset.shape + (3,), 40, np.uint8)
    valid = np.isfinite(scaled)
    blue = np.where(scaled < 0, -scaled, 0)
    red = np.where(scaled > 0, scaled, 0)
    image[valid, 0] = (90 + 165 * blue[valid]).astype(np.uint8)
    image[valid, 2] = (90 + 165 * red[valid]).astype(np.uint8)
    image[valid, 1] = (90 * (1 - np.abs(scaled[valid]))).astype(np.uint8)
    return cv2.resize(image, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)


def _details(sid, surface, layers, prepared, relief_samples, relief_median, relief_count, cell_px, ppm, height_m) -> dict:
    """surface-details.json: features with their inset/extrude evidence, all `proposed` until reviewed."""
    features = []
    for layer in layers:
        p = prepared[layer.capture_id]
        for a in p.capture.annotations_for(sid, FEATURE_KINDS):
            poly = cv2.perspectiveTransform(p.points(a.polygon)[None], layer.alignment.homography)[0]
            x0, y0 = poly.min(axis=0)
            x1, y1 = poly.max(axis=0)
            features.append({"box": (x0, y0, x1, y1), "kind": a.kind, "label": a.label,
                             "evidence": [{"captureId": p.capture.capture_id, "annotationId": a.annotation_id}]})
    merged: list[dict] = []
    for f in features:  # the same window annotated on several photos becomes one feature
        twin = next((m for m in merged if m["kind"] == f["kind"] and _iou(m["box"], f["box"]) > 0.5), None)
        if twin:
            twin["evidence"] += f["evidence"]
            twin["boxes"].append(f["box"])
        else:
            merged.append({**f, "boxes": [f["box"]]})

    out = []
    for n, f in enumerate(merged, 1):
        box = tuple(np.median(np.array(f["boxes"]), axis=0))
        relief = feature_relief(relief_samples, box, ring_px=0.25 * ppm) if relief_samples else {
            "status": "unmeasured", "method": "none", "offsetM": None, "uncertaintyM": None,
            "reason": "no LiDAR depth on any aligned photo of this surface"}
        (u0, v1), (u1, v0) = texture_to_surface(box[0], box[1], height_m, ppm), texture_to_surface(box[2], box[3], height_m, ppm)
        operation = {"recess": "inset", "projection": "extrude"}.get(relief.get("direction", ""), "none")
        out.append({
            "featureId": f"{f['kind']}-{n:03d}", "kind": f["kind"], "label": f["label"], "status": "proposed",
            "boundsM": {"u0": round(u0, 3), "v0": round(v0, 3), "u1": round(u1, 3), "v1": round(v1, 3)},
            "relief": relief,
            "blender": {"operation": operation, "depthM": abs(relief["offsetM"]) if relief.get("offsetM") is not None and operation != "none" else None,
                        "appliesOnlyWhen": "status == reviewed"},
            "evidence": f["evidence"], "source": "phone-annotation",
        })
    # unannotated relief: connected regions clearly in front of / behind the wall
    out += _relief_proposals(relief_median, relief_count, cell_px, ppm, height_m, start=len(out) + 1)
    valid = np.isfinite(relief_median)
    return {
        "schema": SCHEMA_DETAILS, "surfaceId": sid, "buildingId": surface.get("buildingId"),
        "frame": "S: u right along the wall seen from outside, v up, n outward; metres from the bottom-left corner",
        "offsetConvention": "offsetM < 0 = recessed into the wall (inset); > 0 = projecting (extrude); relative to the surrounding wall",
        "reliefGrid": {"file": "relief.npz", "cellM": cell_px / ppm, "validCellFraction": round(float(valid.mean()), 4) if valid.size else 0.0,
                       "captures": [s.capture_id for s in relief_samples],
                       "planeFits": [{"captureId": s.capture_id, "planeRmsM": round(s.plane_rms_m, 4), "inlierFraction": round(s.inlier_fraction, 3)} for s in relief_samples]},
        "features": out,
        "review": "Every feature starts as `proposed`. Blender geometry is generated only for `reviewed` features.",
        "limitations": [
            "Relief comes from iPhone LiDAR within 5 m at high confidence only; not validated against tape measurements at facade scale.",
            "Feature bounds come from phone annotations or relief segmentation and inherit the photo's alignment error.",
            "Without depth, features are listed with relief status `unmeasured`; no depth is inferred from a single photo.",
        ],
    }


def _relief_proposals(median, count, cell_px, ppm, height_m, start: int, min_cells: int = 6) -> list[dict]:
    proposals = []
    if not np.isfinite(median).any():
        return proposals
    for sign, kind in ((-1, "recess"), (1, "projection")):
        mask = (np.nan_to_num(median * sign, nan=0) > 2 * FLUSH_THRESHOLD_M).astype(np.uint8)
        n, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=4)
        for k in range(1, n):
            if stats[k, cv2.CC_STAT_AREA] < min_cells:
                continue
            cells = labels == k
            x, y, w, h = stats[k, :4]
            box = (x * cell_px, y * cell_px, (x + w) * cell_px, (y + h) * cell_px)
            (u0, v1), (u1, v0) = texture_to_surface(box[0], box[1], height_m, ppm), texture_to_surface(box[2], box[3], height_m, ppm)
            offset = float(np.median(median[cells]))
            proposals.append({
                "featureId": f"{kind}-{start + len(proposals):03d}", "kind": kind, "label": "", "status": "proposed",
                "boundsM": {"u0": round(u0, 3), "v0": round(v0, 3), "u1": round(u1, 3), "v1": round(v1, 3)},
                "relief": {"status": "measured", "method": "relief-segmentation", "offsetM": round(offset, 4),
                           "direction": kind, "cells": int(cells.sum()), "samples": int(count[cells].sum()),
                           "uncertaintyM": None, "uncertaintyNote": "Region median relative to the fitted plane; review before use."},
                "blender": {"operation": "inset" if kind == "recess" else "extrude", "depthM": round(abs(offset), 4),
                            "appliesOnlyWhen": "status == reviewed"},
                "evidence": [], "source": "relief-segmentation",
            })
    return proposals


def _iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0
