"""Lens distortion correction from AVFoundation calibration data.

Apple describes distortion as a radial magnification lookup table about an
optical centre (AVCameraCalibrationData.lensDistortionLookupTable). For a point
p at radius r from the centre, normalised by the largest centre-to-corner
radius, the mapped point is centre + (p - centre) * (1 + LUT(r)), with LUT
linearly interpolated over N evenly spaced radii in [0, 1]. This mirrors the
`lensDistortionPoint(for:lookupTable:distortionOpticalCenter:imageSize:)`
helper in Apple's AVCamPhotoFilter sample.

- `lensDistortionLookupTable` maps an undistorted point to where it lies in
  the distorted (captured) image: used to build the remap for correction.
- `inverseLensDistortionLookupTable` maps a captured point to its undistorted
  position: used to move tapped corners/annotations into the corrected image.

ARKit frames carry intrinsics but no distortion table; such captures are
processed uncorrected and say so in their provenance (never silently).
"""
from __future__ import annotations

import base64

import cv2
import numpy as np


def decode_table(encoded: str | None) -> np.ndarray | None:
    if not encoded:
        return None
    table = np.frombuffer(base64.b64decode(encoded), dtype="<f4").astype(np.float64)
    return table if table.size >= 2 else None


def _magnification(radius_norm: np.ndarray, table: np.ndarray) -> np.ndarray:
    positions = np.clip(radius_norm, 0.0, 1.0) * (table.size - 1)
    return np.interp(positions, np.arange(table.size), table)


def _scaled_centre(calibration: dict, width: int, height: int) -> tuple[float, float]:
    cx, cy = calibration["center"]
    ref_w, ref_h = calibration.get("referenceWidth", width), calibration.get("referenceHeight", height)
    return cx * width / ref_w, cy * height / ref_h


def _max_radius(cx: float, cy: float, width: int, height: int) -> float:
    return max(np.hypot(x - cx, y - cy) for x in (0, width) for y in (0, height))


def apply_table(points: np.ndarray, table: np.ndarray, centre: tuple[float, float], max_radius: float) -> np.ndarray:
    """Map (N, 2) points through a magnification table."""
    delta = points - np.asarray(centre)
    radius = np.hypot(delta[:, 0], delta[:, 1]) / max_radius
    return np.asarray(centre) + delta * (1.0 + _magnification(radius, table))[:, None]


def usable_calibration(camera: dict) -> dict | None:
    calibration = (camera or {}).get("distortion")
    if not calibration:
        return None
    forward = decode_table(calibration.get("lookupTableBase64"))
    inverse = decode_table(calibration.get("inverseLookupTableBase64"))
    if forward is None or inverse is None or "center" not in calibration:
        return None
    return {**calibration, "forward": forward, "inverse": inverse}


def undistort_image(image: np.ndarray, calibration: dict) -> np.ndarray:
    height, width = image.shape[:2]
    centre = _scaled_centre(calibration, width, height)
    max_radius = _max_radius(*centre, width, height)
    xs, ys = np.meshgrid(np.arange(width, dtype=np.float64), np.arange(height, dtype=np.float64))
    grid = np.stack([xs.ravel(), ys.ravel()], axis=1)
    source = apply_table(grid, calibration["forward"], centre, max_radius)
    map_x = source[:, 0].reshape(height, width).astype(np.float32)
    map_y = source[:, 1].reshape(height, width).astype(np.float32)
    return cv2.remap(image, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)


def undistort_points(points: np.ndarray, calibration: dict, width: int, height: int) -> np.ndarray:
    centre = _scaled_centre(calibration, width, height)
    return apply_table(np.asarray(points, dtype=np.float64), calibration["inverse"], centre, _max_radius(*centre, width, height))
