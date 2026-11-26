"""Facade relief from LiDAR depth: how far features sit in front of or behind the wall plane.

For each capture with depth:
  1. back-project the depth map with the camera intrinsics (scaled to the depth grid);
  2. fit the dominant plane inside the wall region by RANSAC (the facade);
  3. signed distance of every point from that plane, positive toward the camera
     (= outward, projecting) and negative into the wall (= recessed);
  4. map each depth sample to texture coordinates through the image homography
     and accumulate a coarse relief grid (median per cell across all captures).

The plane is measured in each frame's own camera coordinates, so relief does
not depend on aligning ARKit's session frame to the building frame. It is
relative to the dominant facade plane, which is exactly what inset/extrude
modelling needs.

Limits (not validated at building scale): iPhone LiDAR is specified for short
range (~5 m) and its error grows with distance and grazing angle; only
high-confidence samples within MAX_RANGE_M are used, and every value carries
its sample count and spread so thin evidence is visible.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

MAX_RANGE_M = 5.0
MIN_CONFIDENCE = 2            # ARKit ARConfidenceLevel.high
PLANE_INLIER_M = 0.03
RANSAC_ITERATIONS = 400
MIN_FEATURE_SAMPLES = 12
# Below this |offset| a feature is reported as flush: LiDAR noise at a few metres
# is on the order of a centimetre or more, so smaller offsets are not claimed.
FLUSH_THRESHOLD_M = 0.03


@dataclass
class ReliefSamples:
    texture_xy: np.ndarray   # (N, 2) texture px
    offset_m: np.ndarray     # (N,) signed distance from the wall plane, + outward
    range_m: np.ndarray      # (N,) camera distance
    capture_id: str
    plane_rms_m: float
    inlier_fraction: float


def fit_plane(points: np.ndarray, rng: np.random.Generator, threshold: float = PLANE_INLIER_M) -> tuple[np.ndarray, float, np.ndarray] | None:
    """RANSAC + least-squares refit. Returns (unit normal, d) with n.x + d = 0, and the inlier mask."""
    if len(points) < 50:
        return None
    best = None
    for _ in range(RANSAC_ITERATIONS):
        sample = points[rng.choice(len(points), 3, replace=False)]
        normal = np.cross(sample[1] - sample[0], sample[2] - sample[0])
        norm = np.linalg.norm(normal)
        if norm < 1e-9:
            continue
        normal /= norm
        d = -normal @ sample[0]
        inliers = np.abs(points @ normal + d) < threshold
        if best is None or inliers.sum() > best[2].sum():
            best = (normal, d, inliers)
    if best is None or best[2].sum() < 30:
        return None
    centre = points[best[2]].mean(axis=0)
    # least-squares normal = smallest-eigenvalue eigenvector of the 3x3 covariance
    # (an SVD of the N x 3 points would build an N x N matrix)
    centred = points[best[2]] - centre
    _, vectors = np.linalg.eigh(centred.T @ centred)
    normal = vectors[:, 0]
    d = -normal @ centre
    inliers = np.abs(points @ normal + d) < threshold
    return normal, float(d), inliers


def depth_relief(capture_id: str, depth: np.ndarray, confidence: np.ndarray | None, intrinsics: dict,
                 image_size: tuple[int, int], image_to_texture: np.ndarray, wall_polygon_image: np.ndarray,
                 obstruction_image: np.ndarray | None, seed: int = 0) -> ReliefSamples | None:
    """Relief samples from one depth frame. Depth and image share the native sensor orientation."""
    dh, dw = depth.shape
    iw, ih = image_size
    sx, sy = dw / iw, dh / ih  # depth grid is a scaled copy of the image grid
    fx, fy = intrinsics["fx"] * iw / intrinsics["referenceWidth"] * sx, intrinsics["fy"] * ih / intrinsics["referenceHeight"] * sy
    cx, cy = intrinsics["cx"] * iw / intrinsics["referenceWidth"] * sx, intrinsics["cy"] * ih / intrinsics["referenceHeight"] * sy

    region = np.zeros((dh, dw), np.uint8)
    cv2.fillPoly(region, [np.round(wall_polygon_image * [sx, sy]).astype(np.int32)], 1)
    valid = region.astype(bool) & np.isfinite(depth) & (depth > 0.1) & (depth <= MAX_RANGE_M)
    if confidence is not None:
        valid &= confidence >= MIN_CONFIDENCE
    if obstruction_image is not None:
        blocked = cv2.resize(obstruction_image.astype(np.uint8), (dw, dh), interpolation=cv2.INTER_NEAREST).astype(bool)
        valid &= ~blocked
    ys, xs = np.nonzero(valid)
    if len(xs) < 50:
        return None
    z = depth[ys, xs].astype(np.float64)
    # depth samples sit at pixel centres of the depth grid
    u = xs + 0.5
    v = ys + 0.5
    points = np.stack([(u - cx) / fx * z, (v - cy) / fy * z, z], axis=1)
    fit = fit_plane(points, np.random.default_rng(seed))
    if fit is None:
        return None
    normal, d, inliers = fit
    if normal @ np.array([0, 0, -1.0]) < 0:  # orient the normal toward the camera (outward)
        normal, d = -normal, -d
    offset = points @ normal + d
    image_xy = np.stack([u / sx, v / sy], axis=1)
    texture_xy = cv2.perspectiveTransform(image_xy[None], image_to_texture)[0]
    rms = float(np.sqrt(np.mean(offset[inliers] ** 2)))
    return ReliefSamples(texture_xy, offset, z, capture_id, rms, float(inliers.mean()))


def relief_grid(samples: list[ReliefSamples], texture_size: tuple[int, int], cell_px: int) -> tuple[np.ndarray, np.ndarray]:
    """Median offset and sample count per cell_px x cell_px texture cell."""
    width, height = texture_size
    gw, gh = (width + cell_px - 1) // cell_px, (height + cell_px - 1) // cell_px
    buckets: dict[int, list[float]] = {}
    for s in samples:
        cols = (s.texture_xy[:, 0] // cell_px).astype(int)
        rows = (s.texture_xy[:, 1] // cell_px).astype(int)
        ok = (cols >= 0) & (cols < gw) & (rows >= 0) & (rows < gh)
        for key, value in zip(rows[ok] * gw + cols[ok], s.offset_m[ok]):
            buckets.setdefault(int(key), []).append(float(value))
    median = np.full((gh, gw), np.nan, np.float32)
    count = np.zeros((gh, gw), np.int32)
    for key, values in buckets.items():
        median.flat[key] = np.median(values)
        count.flat[key] = len(values)
    return median, count


def feature_relief(samples: list[ReliefSamples], box_px: tuple[float, float, float, float], ring_px: float) -> dict:
    """Offset of a feature relative to the wall immediately around it.

    Comparing to a surrounding ring (not the global plane) cancels slow plane
    fit errors and gentle wall bow, leaving the local step a modeller needs.
    """
    x0, y0, x1, y1 = box_px
    inner, ring, ranges = [], [], []
    shrink = 0.15 * min(x1 - x0, y1 - y0)  # stay clear of reveal edges
    for s in samples:
        x, y = s.texture_xy[:, 0], s.texture_xy[:, 1]
        in_box = (x > x0 + shrink) & (x < x1 - shrink) & (y > y0 + shrink) & (y < y1 - shrink)
        in_ring = (x > x0 - ring_px) & (x < x1 + ring_px) & (y > y0 - ring_px) & (y < y1 + ring_px) & \
                  ~((x > x0) & (x < x1) & (y > y0) & (y < y1))
        inner.extend(s.offset_m[in_box])
        ring.extend(s.offset_m[in_ring])
        ranges.extend(s.range_m[in_box])
    result = {"samplesInside": len(inner), "samplesAround": len(ring), "method": "lidar-plane-residual"}
    if len(inner) < MIN_FEATURE_SAMPLES or len(ring) < MIN_FEATURE_SAMPLES:
        return {**result, "status": "insufficient-samples", "offsetM": None, "uncertaintyM": None}
    inner_a, ring_a = np.asarray(inner), np.asarray(ring)
    offset = float(np.median(inner_a) - np.median(ring_a))
    mad = lambda a: 1.4826 * float(np.median(np.abs(a - np.median(a))))
    # spread-based standard error of the two medians (1.25 * sigma / sqrt(n)); excludes LiDAR bias
    sem = float(np.hypot(1.25 * mad(inner_a) / np.sqrt(len(inner_a)), 1.25 * mad(ring_a) / np.sqrt(len(ring_a))))
    direction = "flush" if abs(offset) < max(FLUSH_THRESHOLD_M, 2 * sem) else ("recess" if offset < 0 else "projection")
    return {**result, "status": "measured", "offsetM": round(offset, 4), "uncertaintyM": round(sem, 4),
            "direction": direction, "medianRangeM": round(float(np.median(ranges)), 2),
            "uncertaintyNote": "Spread of samples only; excludes LiDAR range bias. Not validated against tape measurements."}
