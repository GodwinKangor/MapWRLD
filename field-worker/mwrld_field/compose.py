"""Project aligned photographs onto the wall texture, score, blend, and measure coverage.

Coverage classes (per texel; definitions are also written into coverage.json):
  missing          no source image's frame contains it
  obstructed-only  inside some frame, but every such view is masked as a foreground obstruction
  photographed     at least one view sees it unobstructed
  usable           photographed by at least one view passing every quality gate below
  reviewed         usable AND inside a region a person approved (review.json)
Percentages are texel counts over the full surface rectangle. "missing" and
"obstructed-only" never count as observed. No synthetic fill is produced, so
synthetic coverage is always 0.

Quality gates and weights are heuristics chosen for this pipeline; they rank
sources, they are not calibrated accuracy estimates.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .rectify import Alignment, local_jacobian_metrics

LABEL_MISSING, LABEL_OBSTRUCTED, LABEL_PHOTOGRAPHED, LABEL_USABLE, LABEL_REVIEWED = 0, 1, 2, 3, 4
LABEL_NAMES = {LABEL_MISSING: "missing", LABEL_OBSTRUCTED: "obstructed-only", LABEL_PHOTOGRAPHED: "photographed",
               LABEL_USABLE: "usable", LABEL_REVIEWED: "reviewed"}

GATES = {
    "minObliquity": 0.34,        # min/max stretch of the projection; ~70 deg from frontal for a plane
    "minResolution": 0.5,        # source pixels per texture pixel
    "minExposure": 0.5,          # 1 = no clipping or crushed shadows
    "maxAlignmentSigmaTexturePx": 6.0,
}
FEATHER_PX = 24
WEIGHT_POWER = 4.0


@dataclass
class SourceLayer:
    """One aligned photo resampled into texture space."""
    capture_id: str
    alignment: Alignment
    color: np.ndarray        # (H, W, 3) uint8, BGR
    inside: np.ndarray       # bool: within the photo's frame
    unobstructed: np.ndarray # bool: inside and not masked as obstruction
    quality: np.ndarray      # float32 [0, 1], 0 where unusable
    usable: np.ndarray       # bool: passes every gate
    sigma_px: np.ndarray     # float32 alignment 1-sigma in texture px (heuristic)
    sharpness: np.ndarray    # float32 local |Laplacian| energy
    stats: dict = field(default_factory=dict)


def _exposure_weight(color: np.ndarray) -> np.ndarray:
    high = color.max(axis=2).astype(np.float32)
    low = color.min(axis=2).astype(np.float32)
    return np.clip((252 - high) / 20, 0, 1) * np.clip((low - 3) / 20, 0, 1)


def _feather(mask: np.ndarray) -> np.ndarray:
    if not mask.any():
        return mask.astype(np.float32)
    distance = cv2.distanceTransform(mask.astype(np.uint8), cv2.DIST_L2, 3)
    return np.clip(distance / FEATHER_PX, 0, 1).astype(np.float32)


def project_source(capture_id: str, image: np.ndarray, obstruction: np.ndarray | None, alignment: Alignment,
                   texture_size: tuple[int, int]) -> SourceLayer:
    """Warp one undistorted photo (and its obstruction mask) into texture space and score it."""
    width, height = texture_size
    h = alignment.homography
    color = cv2.warpPerspective(image, h, (width, height), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    frame = np.full(image.shape[:2], 255, np.uint8)
    inside = cv2.warpPerspective(frame, h, (width, height), flags=cv2.INTER_NEAREST) > 0
    inside = cv2.erode(inside.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)  # drop resampled border
    unobstructed = inside.copy()
    if obstruction is not None and obstruction.any():
        blocked = cv2.warpPerspective(obstruction.astype(np.uint8) * 255, h, (width, height), flags=cv2.INTER_NEAREST) > 0
        blocked = cv2.dilate(blocked.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)  # masks are drawn loosely
        unobstructed &= ~blocked

    resolution, obliquity = local_jacobian_metrics(np.linalg.inv(h), texture_size)
    exposure = _exposure_weight(color)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY).astype(np.float32)
    sharpness = cv2.GaussianBlur(np.abs(cv2.Laplacian(gray, cv2.CV_32F, ksize=3)), (0, 0), 3)
    sharpness[~inside] = 0

    if alignment.method.startswith("manual-corners"):
        tap = alignment.tap_sigma_px or 0.0
        # a tap error of `tap` source px moves texels by tap / (source px per texel)
        sigma = tap / np.maximum(resolution, 1e-3)
        if alignment.residual_rms_px:
            sigma = np.sqrt(sigma ** 2 + alignment.residual_rms_px ** 2)
    else:
        sigma = np.full((height, width), alignment.residual_rms_px or 0.0, np.float32)
    sigma = sigma.astype(np.float32)

    usable = (unobstructed & (obliquity >= GATES["minObliquity"]) & (resolution >= GATES["minResolution"])
              & (exposure >= GATES["minExposure"]) & (sigma <= GATES["maxAlignmentSigmaTexturePx"]))
    angle_term = np.clip((obliquity - 0.2) / 0.5, 0, 1)
    res_term = np.clip(resolution, 0, 1)
    align_term = np.exp(-0.5 * (sigma / 3.0) ** 2)
    quality = (unobstructed * angle_term * res_term * exposure * align_term).astype(np.float32)
    stats = {
        "insideTexels": int(inside.sum()), "unobstructedTexels": int(unobstructed.sum()), "usableTexels": int(usable.sum()),
        "medianResolution": float(np.median(resolution[inside])) if inside.any() else None,
        "medianObliquity": float(np.median(obliquity[inside])) if inside.any() else None,
        "medianSigmaTexturePx": float(np.median(sigma[inside])) if inside.any() else None,
    }
    return SourceLayer(capture_id, alignment, color, inside, unobstructed, quality, usable, sigma, sharpness, stats)


@dataclass
class Composite:
    texture: np.ndarray        # (H, W, 4) uint8 BGRA; alpha 255 usable, 96 photographed-only, 0 otherwise
    labels: np.ndarray         # uint8 coverage label per texel
    source_index: np.ndarray   # uint8 index of the winning source, 255 = none
    sigma_mm: np.ndarray       # float32 alignment sigma of the winning source in mm, nan = none
    disagreement: np.ndarray   # float32 weighted luma std-dev between overlapping sources, nan = single/no source
    source_count: np.ndarray   # uint8 number of unobstructed views
    coverage: dict


def composite(layers: list[SourceLayer], texture_size: tuple[int, int], ppm: float,
              reviewed_region: np.ndarray | None = None) -> Composite:
    width, height = texture_size
    shape = (height, width)
    if len(layers) > 254:
        raise ValueError("more than 254 sources on one surface; split the job")
    # sharpness is ranked relative to the sharpest view of the same texel
    best_sharp = np.zeros(shape, np.float32)
    for layer in layers:
        np.maximum(best_sharp, np.where(layer.unobstructed, layer.sharpness, 0), out=best_sharp)

    acc = np.zeros((height, width, 3), np.float64)
    acc_w = np.zeros(shape, np.float64)
    luma_sum = np.zeros(shape, np.float64)
    luma_sq = np.zeros(shape, np.float64)
    best_score = np.full(shape, -1.0, np.float32)
    source_index = np.full(shape, 255, np.uint8)
    sigma_best = np.full(shape, np.nan, np.float32)
    any_inside = np.zeros(shape, bool)
    photographed = np.zeros(shape, bool)
    usable = np.zeros(shape, bool)
    count = np.zeros(shape, np.uint8)

    for index, layer in enumerate(layers):
        rel_sharp = np.sqrt(np.where(best_sharp > 0, layer.sharpness / np.maximum(best_sharp, 1e-6), 0))
        score = layer.quality * rel_sharp
        weight = (score ** WEIGHT_POWER) * _feather(layer.unobstructed)
        acc += layer.color.astype(np.float64) * weight[..., None]
        acc_w += weight
        luma = cv2.cvtColor(layer.color, cv2.COLOR_BGR2GRAY).astype(np.float64)
        luma_sum += weight * luma
        luma_sq += weight * luma ** 2
        better = layer.unobstructed & (score > best_score)
        best_score[better] = score[better]
        source_index[better] = index
        sigma_best[better] = layer.sigma_px[better] / ppm * 1000.0
        any_inside |= layer.inside
        photographed |= layer.unobstructed
        usable |= layer.usable
        count += layer.unobstructed.astype(np.uint8)

    texture = np.zeros((height, width, 4), np.uint8)
    blended = acc_w > 1e-12
    texture[blended, :3] = np.clip(acc[blended] / acc_w[blended, None], 0, 255).astype(np.uint8)
    # where every view is feathered to zero weight, fall back to the best single view
    fallback = photographed & ~blended
    for index, layer in enumerate(layers):
        pick = fallback & (source_index == index)
        texture[pick, :3] = layer.color[pick]
    texture[photographed, 3] = 96
    texture[usable, 3] = 255

    mean = np.where(acc_w > 1e-12, luma_sum / np.maximum(acc_w, 1e-12), 0)
    variance = np.where(acc_w > 1e-12, luma_sq / np.maximum(acc_w, 1e-12) - mean ** 2, 0)
    disagreement = np.where(count >= 2, np.sqrt(np.maximum(variance, 0)), np.nan).astype(np.float32)

    labels = np.full(shape, LABEL_MISSING, np.uint8)
    labels[any_inside] = LABEL_OBSTRUCTED
    labels[photographed] = LABEL_PHOTOGRAPHED
    labels[usable] = LABEL_USABLE
    if reviewed_region is not None:
        labels[usable & reviewed_region] = LABEL_REVIEWED

    total = height * width
    pct = lambda mask: round(100.0 * float(mask.sum()) / total, 2)
    observed = labels >= LABEL_PHOTOGRAPHED
    coverage = {
        "texels": total,
        "percent": {
            "photographed": pct(observed),
            "usable": pct(labels >= LABEL_USABLE),
            "reviewed": pct(labels == LABEL_REVIEWED),
            "obstructedOnly": pct(labels == LABEL_OBSTRUCTED),
            "missing": pct(labels == LABEL_MISSING),
            "synthetic": 0.0,
        },
        "definitions": {name: doc for name, doc in [
            ("photographed", "inside at least one photo's frame and not under that photo's obstruction mask"),
            ("usable", "photographed by at least one photo passing every gate in `gates`"),
            ("reviewed", "usable and inside a person-approved region (review.json)"),
            ("obstructedOnly", "inside some photo's frame but masked as foreground in all of them; counted as NOT observed"),
            ("missing", "no photo covers it"),
            ("synthetic", "AI/generated fill; this pipeline produces none"),
        ]},
        "denominator": "all texels of the surface rectangle (width x height at pixelsPerMeter)",
        "gates": GATES,
        "medianAlignmentSigmaMm": float(np.nanmedian(sigma_best)) if np.isfinite(sigma_best).any() else None,
        "medianDisagreementLuma": float(np.nanmedian(disagreement)) if np.isfinite(disagreement).any() else None,
        "sigmaNote": "Heuristic: assumed tap/feature error propagated through each projection; not a validated accuracy.",
    }
    return Composite(texture, labels, source_index, sigma_best, disagreement, count, coverage)


def coverage_preview(comp: Composite, max_side: int = 1024) -> np.ndarray:
    """Phone preview: the texture with missing (magenta hatch), obstructed-only (orange hatch)
    and photographed-but-unusable (dimmed) areas made obvious."""
    image = comp.texture[:, :, :3].copy()
    labels = comp.labels
    height, width = labels.shape
    yy, xx = np.mgrid[0:height, 0:width]
    stripe = ((xx + yy) // 8) % 2 == 0
    image[labels == LABEL_PHOTOGRAPHED] = (image[labels == LABEL_PHOTOGRAPHED] * 0.55).astype(np.uint8)
    image[(labels == LABEL_MISSING) & stripe] = (180, 0, 200)
    image[(labels == LABEL_MISSING) & ~stripe] = (60, 0, 70)
    image[(labels == LABEL_OBSTRUCTED) & stripe] = (0, 140, 255)
    image[(labels == LABEL_OBSTRUCTED) & ~stripe] = (0, 50, 90)
    scale = min(1.0, max_side / max(height, width))
    if scale < 1.0:
        image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return image
