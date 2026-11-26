"""Known-geometry validation of the facade pipeline (synthetic renders; see synthetic.py).

These establish that the projection math, orientation, coverage accounting and
relief measurement are right on exact data. They say nothing about accuracy on
real facades, which needs real captures with independent measurements.
"""
import base64
import json

import cv2
import numpy as np
import pytest

from mwrld_field.capture import CaptureError, load_capture
from mwrld_field.compose import LABEL_MISSING, LABEL_OBSTRUCTED
from mwrld_field.geometry import surface_to_texture
from mwrld_field.pipeline import SurfaceJob, default_pixels_per_meter, run_surface_job
from mwrld_field.synthetic import Camera, make_facade, measure_fiducials, write_capture
from mwrld_field.undistort import apply_table

SID = "osm:way/1/wall/1-2"
PPM = 50.0


@pytest.fixture(scope="module")
def facade():
    return make_facade()


def surface_for(facade):
    return {"surfaceId": SID, "buildingId": "b", "widthM": facade.width_m, "heightM": facade.height_m}


def overview(facade, **kw):
    return Camera((facade.width_m / 2, facade.height_m / 2, 21.0), (facade.width_m / 2, facade.height_m / 2, 0), **kw)


def run(tmp_path, facade, captures, ppm=PPM, review=None):
    return run_surface_job(SurfaceJob(surface_for(facade), captures, tmp_path / "out", pixels_per_meter=ppm, review=review))


def texture(tmp_path):
    return cv2.imread(str(tmp_path / "out" / "texture.png"), cv2.IMREAD_UNCHANGED)


def test_exact_corners_rectify_to_millimetres(tmp_path, facade):
    c = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", seed=1)
    run(tmp_path, facade, [c], ppm=100)
    errors = measure_fiducials(texture(tmp_path), facade, 100)
    assert len(errors) >= 18
    assert np.median(errors) < 3.0 and max(errors) < 8.0  # mm; texels are 10 mm


def test_noisy_hand_corners_stay_within_a_few_centimetres(tmp_path, facade):
    c = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", corner_noise_px=4.0, seed=3)
    result = run(tmp_path, facade, [c])
    errors = measure_fiducials(texture(tmp_path), facade, PPM)
    # 4 px taps at ~95 px/m of wall in the photo -> a few cm; the heuristic sigma should be of the same order
    assert np.median(errors) < 60
    sigma = result.coverage["medianAlignmentSigmaMm"]
    assert 10 < sigma < 120


def test_orientation_unmirrored_for_portrait_capture(tmp_path, facade):
    """Phone held in portrait: native landscape pixels + EXIF orientation 6. The output must
    still have the red 'F' marker at the top-left, reading the right way round."""
    cam = overview(facade, roll_deg=90, focal_px=1300)
    c = write_capture(tmp_path / "c1", facade, cam, SID, "b", "s", exif_orientation=6, seed=4)
    run(tmp_path, facade, [c])
    tex = texture(tmp_path)
    col, row = surface_to_texture(*facade.marker_uv, facade.height_m, PPM)
    r = int(PPM)  # 1 m window around where the marker must be
    c0, r0 = int(round(col)), int(round(row))
    window = tex[r0 - r:r0 + r, c0 - r:c0 + r]
    red = (window[:, :, 2] > 170) & (window[:, :, 0] < 60) & (window[:, :, 1] < 60)  # marker is pure (0, 0, 230) BGR
    assert red.sum() > 50, "marker not found where it belongs (rotated, flipped or misplaced output)"
    # same window in the ground truth (also at 50 px/m): the F's centroid must land in the same place
    gt = facade.texture[r0 - r:r0 + r, c0 - r:c0 + r]
    gt_red = (gt[:, :, 2] > 170) & (gt[:, :, 0] < 60) & (gt[:, :, 1] < 60)
    ys, xs = np.nonzero(red)
    gys, gxs = np.nonzero(gt_red)
    assert abs(xs.mean() - gxs.mean()) < 2 and abs(ys.mean() - gys.mean()) < 2
    # the F's long stroke is on its LEFT; mirrored output would put more red on the right
    assert red[:, :r].sum() > red[:, r:].sum()
    # and its top bar is at the TOP; a vertical flip would put more red at the bottom
    assert red[:r, :].sum() > red[r:, :].sum()


def test_detail_photo_without_corners_aligns_automatically(tmp_path, facade):
    c1 = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", seed=1)
    c2 = write_capture(tmp_path / "c2", facade, Camera((4, 4, 8), (6, 6, 0)), SID, "b", "s", kind="detail", corners=False, seed=2)
    result = run(tmp_path, facade, [c1, c2])
    assert result.rejected == []
    prov = json.loads((tmp_path / "out" / "provenance.json").read_text())
    methods = [s["alignment"]["method"] for s in prov["sources"]]
    assert methods == ["manual-corners", "auto-feature-homography"]
    assert prov["sources"][1]["alignment"]["inliers"] >= 40
    assert prov["consistency"]["pairs"] and prov["consistency"]["pairs"][0]["medianMm"] < 15


def test_unrelated_photo_is_rejected_not_forced(tmp_path, facade):
    c1 = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", seed=1)
    other = make_facade(seed=99)  # a different building's texture
    c2 = write_capture(tmp_path / "c2", other, Camera((5, 5, 9), (5, 5, 0)), SID, "b", "s", corners=False, seed=5)
    result = run(tmp_path, facade, [c1, c2])
    assert [r["stage"] for r in result.rejected] == ["align-auto"]


def test_obstruction_never_counts_and_missing_is_marked(tmp_path, facade):
    # camera sees only the left ~60% of the wall; a 'tree' covers part of what it sees
    cam = Camera((6.0, 7.5, 14.0), (6.0, 7.5, 0))
    tree = [(2.0, 0.0), (5.0, 0.0), (5.0, 6.0), (2.0, 6.0)]
    labels_uv = None
    c = write_capture(tmp_path / "c1", facade, cam, SID, "b", "s", corners=False, obstruction_uv=tree, seed=6)
    # corners outside the view: align with four visible window corners instead (landmarks)
    raw = json.loads((c / "capture.json").read_text())
    box = facade.recess_boxes[0]
    landmarks = {"a": (box[0], box[3]), "b": (box[2] + 4.0, box[3]), "c": (box[2] + 4.0, box[1] + 4.4), "d": (box[0], box[1] + 4.4)}
    pts = cam.project(np.array([[u, v, 0] for u, v in landmarks.values()]))
    raw["alignment"][SID] = {"method": "manual-corners", "points": [
        {"label": k, "image": list(map(float, p)), "surface": list(map(float, uv))} for (k, uv), p in zip(landmarks.items(), pts)]}
    (c / "capture.json").write_text(json.dumps(raw))
    result = run(tmp_path, facade, [c])
    labels = cv2.imread(str(tmp_path / "out" / "coverage.png"), cv2.IMREAD_UNCHANGED)
    col, row = surface_to_texture(3.5, 3.0, facade.height_m, PPM)
    assert labels[int(row), int(col)] == LABEL_OBSTRUCTED            # behind the tree
    col, row = surface_to_texture(facade.width_m - 0.5, 7.0, facade.height_m, PPM)
    assert labels[int(row), int(col)] == LABEL_MISSING               # never photographed
    pct = result.coverage["percent"]
    assert pct["obstructedOnly"] > 3 and pct["missing"] > 20
    assert pct["photographed"] + pct["obstructedOnly"] + pct["missing"] == pytest.approx(100, abs=0.05)
    tex = texture(tmp_path)
    assert tex[labels == LABEL_OBSTRUCTED, 3].max() == 0               # no alpha where only a tree was seen


def test_second_view_fills_what_the_first_could_not_see(tmp_path, facade):
    tree = [(2.0, 0.0), (5.0, 0.0), (5.0, 6.0), (2.0, 6.0)]
    c1 = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", obstruction_uv=tree, seed=1)
    alone = run(tmp_path, facade, [c1]).coverage["percent"]
    c2 = write_capture(tmp_path / "c2", facade, Camera((1.0, 3.0, 10.0), (4.0, 3.0, 0)), SID, "b", "s", corners=False, seed=7)
    both = run(tmp_path, facade, [c1, c2]).coverage["percent"]
    assert alone["obstructedOnly"] > 3
    assert both["obstructedOnly"] < alone["obstructedOnly"] / 4


def test_lidar_relief_finds_recessed_windows(tmp_path, facade):
    # close-range (LiDAR) view of the lower-left bays, with the bays annotated as windows
    cam = Camera((3.5, 2.4, 3.8), (3.5, 2.4, 0), focal_px=1100)
    windows = [{"box": b, "kind": "window"} for b in facade.recess_boxes[:2]]
    c1 = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", seed=1)
    c2 = write_capture(tmp_path / "c2", facade, cam, SID, "b", "s", kind="detail", corners=False, depth=True,
                       annotations_uv=windows, seed=8)
    run(tmp_path, facade, [c1, c2])
    details = json.loads((tmp_path / "out" / "surface-details.json").read_text())
    annotated = [f for f in details["features"] if f["source"] == "phone-annotation"]
    measured = [f for f in annotated if f["relief"]["status"] == "measured"]
    assert measured, annotated
    for f in measured:
        assert f["relief"]["direction"] == "recess"
        assert f["relief"]["offsetM"] == pytest.approx(-facade.recess_depth_m, abs=0.02)
        assert f["blender"]["operation"] == "inset" and f["status"] == "proposed"
    assert any(f["source"] == "relief-segmentation" and f["kind"] == "recess" for f in details["features"])


def test_without_depth_features_are_unmeasured_not_guessed(tmp_path, facade):
    c1 = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s",
                       annotations_uv=[{"box": facade.recess_boxes[0], "kind": "window"}], seed=1)
    run(tmp_path, facade, [c1])
    details = json.loads((tmp_path / "out" / "surface-details.json").read_text())
    (feature,) = details["features"]
    assert feature["relief"]["status"] == "unmeasured" and feature["relief"]["offsetM"] is None
    assert feature["blender"]["operation"] == "none"


def test_field_measurement_is_checked_against_texture(tmp_path, facade):
    c = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s",
                      measurement_uv=((2.0, 1.0), (12.0, 1.0)), seed=1)
    result = run(tmp_path, facade, [c], ppm=100)
    (check,) = result.summary["measurementChecks"]
    assert abs(check["errorM"]) < 0.02


def test_reviewed_coverage_requires_a_review_region(tmp_path, facade):
    c = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", seed=1)
    assert run(tmp_path, facade, [c]).coverage["percent"]["reviewed"] == 0
    half = {"regions": [{"polygon": [[0, 0], [facade.width_m / 2, 0], [facade.width_m / 2, facade.height_m], [0, facade.height_m]]}]}
    pct = run(tmp_path, facade, [c], review=half).coverage["percent"]
    assert pct["reviewed"] == pytest.approx(pct["usable"] / 2, abs=1.0)


def test_corrupt_upload_is_rejected_by_hash(tmp_path, facade):
    c = write_capture(tmp_path / "c1", facade, overview(facade), SID, "b", "s", seed=1)
    data = bytearray((c / "image.jpg").read_bytes())
    (c / "image.jpg").write_bytes(bytes(data[: len(data) // 2]))  # truncated upload
    with pytest.raises(CaptureError, match="sha256"):
        load_capture(c)


def test_apple_lut_round_trip():
    """Forward and inverse magnification tables must invert each other (synthetic barrel distortion)."""
    radii = np.linspace(0, 1, 42)
    forward = -0.06 * radii ** 2
    centre, max_radius = (1000.0, 750.0), 1250.0
    pts = np.array([[100.0, 80.0], [1000.0, 750.0], [1900.0, 1400.0], [1500.0, 300.0]])
    distorted = apply_table(pts, forward, centre, max_radius)
    # build the inverse table numerically, as Apple ships it
    r_dist = radii * (1 + forward)
    inverse = np.interp(radii, r_dist, radii) / np.maximum(radii, 1e-9) - 1
    inverse[0] = 0
    back = apply_table(distorted, inverse, centre, max_radius)
    assert np.abs(back - pts).max() < 0.5


def test_default_resolution_respects_memory():
    assert default_pixels_per_meter(19.26, 14.98, memory_bytes=16 << 30) == pytest.approx(100.0)
    small = default_pixels_per_meter(120.0, 40.0, memory_bytes=4 << 30)
    assert 120 * 40 * small ** 2 <= 4 * 1.5e6 * 1.01


def test_corner_consensus_makes_hand_tapped_overviews_agree(tmp_path, facade):
    """Two overviews tapped with independent 4 px error disagree by centimetres on their own;
    pooled through feature registration they must agree closely, and be closer to the truth."""
    cams = [overview(facade), Camera((facade.width_m / 2 + 2, facade.height_m / 2, 22.0), (facade.width_m / 2, facade.height_m / 2, 0))]
    caps = [write_capture(tmp_path / f"c{i}", facade, cam, SID, "b", "s", corner_noise_px=4.0, seed=20 + i) for i, cam in enumerate(cams)]
    single = [np.median(measure_fiducials(texture_after(tmp_path / f"s{i}", facade, [c]), facade, PPM)) for i, c in enumerate(caps)]
    run_surface_job(SurfaceJob(surface_for(facade), caps, tmp_path / "both", pixels_per_meter=PPM))
    prov = json.loads((tmp_path / "both" / "provenance.json").read_text())
    assert prov["cornerConsensus"]["used"]
    assert all(s["alignment"]["method"] == "manual-corners+consensus" for s in prov["sources"])
    assert prov["consistency"]["pairs"][0]["medianMm"] < 10
    pooled = np.median(measure_fiducials(cv2.imread(str(tmp_path / "both" / "texture.png"), cv2.IMREAD_UNCHANGED), facade, PPM))
    assert pooled < max(single)


def texture_after(out, facade, caps):
    run_surface_job(SurfaceJob(surface_for(facade), caps, out, pixels_per_meter=PPM))
    return cv2.imread(str(out / "texture.png"), cv2.IMREAD_UNCHANGED)
