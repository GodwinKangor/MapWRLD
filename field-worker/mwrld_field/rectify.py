"""Image -> wall-plane alignment (homographies) and their quality checks.

A homography is exact only for points ON the plane through the four control
points. Recessed windows, projecting trim, columns and roofs violate it and
show up as parallax between sources; that disagreement is measured
(compose.py) rather than hidden. Non-planar parts need separate surfaces or
multi-view geometry (later milestones).

Every homography maps native image pixels -> texture pixels (T frame).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from .geometry import surface_to_texture

# Assumed 1-sigma error of a corner tapped by hand on a phone photo, in source
# pixels. A planning value for the uncertainty indicator, not a measurement.
MANUAL_TAP_SIGMA_PX = 4.0
# Feature-alignment acceptance thresholds (working values, tuned on synthetic data only).
MIN_INLIERS = 40
MIN_INLIER_RATIO = 0.25
MAX_RMS_PX = 2.5
MATCH_MAX_SIDE = 1600


@dataclass
class Alignment:
    method: str                       # manual-corners | auto-feature-homography
    homography: np.ndarray            # 3x3, native image px -> texture px
    ok: bool
    reason: str = ""
    residual_rms_px: float | None = None   # in texture px; None when the fit is exactly determined
    inliers: int | None = None
    matches: int | None = None
    references: list[str] = field(default_factory=list)
    tap_sigma_px: float | None = None

    def as_dict(self) -> dict:
        return {
            "method": self.method, "ok": self.ok, "reason": self.reason,
            "imageToTexture": [[float(v) for v in row] for row in self.homography],
            "residualRmsTexturePx": self.residual_rms_px, "inliers": self.inliers, "matches": self.matches,
            "references": self.references, "assumedTapSigmaPx": self.tap_sigma_px,
        }


def surface_to_texture_matrix(height_m: float, ppm: float) -> np.ndarray:
    """Affine S (u, v) -> T (col, row) as a 3x3 matrix; matches geometry.surface_to_texture."""
    return np.array([[ppm, 0.0, -0.5], [0.0, -ppm, height_m * ppm - 0.5], [0.0, 0.0, 1.0]])


def check_homography(h: np.ndarray, image_size: tuple[int, int], texture_size: tuple[int, int]) -> str:
    """Empty string when plausible, otherwise why it is rejected."""
    if h is None or not np.all(np.isfinite(h)) or abs(np.linalg.det(h)) < 1e-12:
        return "degenerate homography"
    width, height = image_size
    corners = np.array([[0, 0], [width, 0], [width, height], [0, height]], dtype=np.float64)
    mapped = cv2.perspectiveTransform(corners[None], h)[0]
    # The image's corners must stay on the near side of the horizon (positive w)...
    w = (h @ np.c_[corners, np.ones(4)].T)[2]
    if not (np.all(w > 0) or np.all(w < 0)):
        return "image straddles the plane's horizon (camera too oblique or wrong plane)"
    # ...and map to a convex quad of sane size.
    if not cv2.isContourConvex(mapped.astype(np.float32)):
        return "image maps to a non-convex quad"
    area = cv2.contourArea(mapped.astype(np.float32))
    tex_area = texture_size[0] * texture_size[1]
    if area < 1e-4 * tex_area or area > 400 * tex_area:
        return f"implausible footprint ({area / tex_area:.3g} x texture area)"
    return ""


def manual_alignment(points_image: np.ndarray, points_surface: np.ndarray, height_m: float, ppm: float,
                     image_size: tuple[int, int], texture_size: tuple[int, int]) -> Alignment:
    """Homography from 4+ hand-placed control points (image px <-> surface metres)."""
    image_pts = np.asarray(points_image, dtype=np.float64)
    texture_pts = np.array([surface_to_texture(u, v, height_m, ppm) for u, v in points_surface])
    if len(image_pts) < 4:
        return Alignment("manual-corners", np.eye(3), False, "fewer than 4 control points")
    if len(image_pts) == 4:
        h = cv2.getPerspectiveTransform(image_pts.astype(np.float32), texture_pts.astype(np.float32)).astype(np.float64)
        rms = None
    else:
        h, _ = cv2.findHomography(image_pts, texture_pts, 0)
        rms = float(np.sqrt(np.mean(np.sum((cv2.perspectiveTransform(image_pts[None], h)[0] - texture_pts) ** 2, axis=1))))
    reason = check_homography(h, image_size, texture_size)
    return Alignment("manual-corners", h, not reason, reason, rms, tap_sigma_px=MANUAL_TAP_SIGMA_PX)


def _gray_small(image: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    scale = min(1.0, max_side / max(gray.shape[:2]))
    if scale < 1.0:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return gray, scale


def feature_alignment(image: np.ndarray, reference_texture: np.ndarray, reference_valid: np.ndarray,
                      reference_ids: list[str], texture_size: tuple[int, int]) -> Alignment:
    """Align a photo to the current rectified texture with SIFT + ratio test + RANSAC.

    The reference is already in texture coordinates, so the homography found is
    image -> texture directly. Only valid (observed) texture pixels are used.
    """
    src, s_scale = _gray_small(image, MATCH_MAX_SIDE)
    ref, r_scale = _gray_small(reference_texture, MATCH_MAX_SIDE)
    ref_mask = cv2.resize(reference_valid.astype(np.uint8) * 255, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_NEAREST)
    sift = cv2.SIFT_create(nfeatures=6000)
    kp_s, des_s = sift.detectAndCompute(src, None)
    kp_r, des_r = sift.detectAndCompute(ref, cv2.erode(ref_mask, np.ones((5, 5), np.uint8)))
    fail = lambda why, **kw: Alignment("auto-feature-homography", np.eye(3), False, why, references=reference_ids, **kw)
    if des_s is None or des_r is None or len(kp_s) < MIN_INLIERS or len(kp_r) < MIN_INLIERS:
        return fail("too few features (texture-poor surface or blur)")
    pairs = cv2.BFMatcher(cv2.NORM_L2).knnMatch(des_s, des_r, k=2)
    good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
    if len(good) < MIN_INLIERS:
        return fail(f"only {len(good)} distinctive matches", matches=len(good))
    pts_s = np.float64([kp_s[m.queryIdx].pt for m in good]) / s_scale
    pts_r = np.float64([kp_r[m.trainIdx].pt for m in good]) / r_scale
    h, mask = cv2.findHomography(pts_s, pts_r, cv2.USAC_MAGSAC, 3.0, maxIters=10000, confidence=0.9999)
    if h is None:
        return fail("RANSAC found no consistent homography", matches=len(good))
    inl = mask.ravel().astype(bool)
    rms = float(np.sqrt(np.mean(np.sum((cv2.perspectiveTransform(pts_s[inl][None], h)[0] - pts_r[inl]) ** 2, axis=1))))
    ratio = inl.sum() / len(good)
    kw = dict(residual_rms_px=rms, inliers=int(inl.sum()), matches=len(good))
    if inl.sum() < MIN_INLIERS or ratio < MIN_INLIER_RATIO:
        return fail(f"{inl.sum()} inliers of {len(good)} matches is too few", **kw)
    if rms > MAX_RMS_PX:
        return fail(f"inlier residual {rms:.2f} px exceeds {MAX_RMS_PX}", **kw)
    reason = check_homography(h, (image.shape[1], image.shape[0]), texture_size)
    return Alignment("auto-feature-homography", h, not reason, reason, references=reference_ids, **kw)


def local_jacobian_metrics(h_tex_to_img: np.ndarray, texture_size: tuple[int, int], step: int = 16) -> tuple[np.ndarray, np.ndarray]:
    """Per texel: source pixels per texture pixel (resolution) and min/max stretch (obliquity, 1 = frontal).

    Computed from the analytic Jacobian of the texture -> image homography on a
    coarse grid and upsampled, which is accurate because homographies are smooth.
    """
    width, height = texture_size
    xs = np.arange(0, width + step, step, dtype=np.float64)
    ys = np.arange(0, height + step, step, dtype=np.float64)
    gx, gy = np.meshgrid(xs, ys)
    h = h_tex_to_img
    w = h[2, 0] * gx + h[2, 1] * gy + h[2, 2]
    px = (h[0, 0] * gx + h[0, 1] * gy + h[0, 2]) / w
    py = (h[1, 0] * gx + h[1, 1] * gy + h[1, 2]) / w
    j11 = (h[0, 0] - px * h[2, 0]) / w
    j12 = (h[0, 1] - px * h[2, 1]) / w
    j21 = (h[1, 0] - py * h[2, 0]) / w
    j22 = (h[1, 1] - py * h[2, 1]) / w
    # singular values of the 2x2 Jacobian
    a = j11 ** 2 + j21 ** 2
    b = j11 * j12 + j21 * j22
    c = j12 ** 2 + j22 ** 2
    root = np.sqrt(np.maximum(((a - c) / 2) ** 2 + b ** 2, 0))
    s_max = np.sqrt(np.maximum((a + c) / 2 + root, 0))
    s_min = np.sqrt(np.maximum((a + c) / 2 - root, 0))
    resolution = np.sqrt(np.abs(j11 * j22 - j12 * j21))
    obliquity = np.where(s_max > 0, s_min / np.maximum(s_max, 1e-12), 0)
    up = lambda grid: cv2.resize(grid.astype(np.float32), (len(xs) * step, len(ys) * step), interpolation=cv2.INTER_LINEAR)[:height, :width]
    return up(resolution), up(obliquity)
