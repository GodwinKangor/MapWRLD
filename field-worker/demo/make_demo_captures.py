"""Write the reproducible one-wall demo captures (synthetic, known geometry) for McNutt Hall's west front.

    python field-worker/demo/make_demo_captures.py OUT_DIR

Uses the real surface from data/field-surfaces (ID, width, height) and a synthetic facade, so the
loop can be exercised end to end without a phone. Real captures replace these one for one.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "field-worker"))
from mwrld_field.synthetic import Camera, make_facade, write_capture  # noqa: E402

SURFACE_ID = "osm:way/261793901/wall/2674282718-2674282725"


def main(out: Path) -> None:
    registry = json.loads((ROOT / "data/field-surfaces/mcnutt-hall-261793901.surfaces.json").read_text())
    surface = next(s for s in registry["surfaces"] if s["surfaceId"] == SURFACE_ID)
    w, h = surface["widthM"], surface["heightM"]
    facade = make_facade(w, h)
    common = dict(surface_id=SURFACE_ID, building_id=registry["buildingId"], session_id="(set on upload)")
    write_capture(out / "01-overview", facade, Camera((w / 2, h / 2, 21.0), (w / 2, h / 2, 0)), corner_noise_px=3.0,
                  measurement_uv=((facade.recess_boxes[0][0], 1.2), (facade.recess_boxes[4][2], 1.2)), seed=11, **common)
    write_capture(out / "02-oblique-left", facade, Camera((2.0, 5.0, 12.0), (7.0, 6.0, 0)), kind="detail", corners=False, seed=12, **common)
    write_capture(out / "03-lidar-detail", facade, Camera((3.5, 2.4, 3.8), (3.5, 2.4, 0), focal_px=1100), kind="detail", corners=False,
                  depth=True, annotations_uv=[{"box": b, "kind": "window"} for b in facade.recess_boxes[:2]], seed=13, **common)
    write_capture(out / "04-overview-tree", facade, Camera((w / 2 + 2, h / 2, 22.0), (w / 2, h / 2, 0)), corner_noise_px=3.0,
                  obstruction_uv=[(12.0, 0.0), (16.0, 0.0), (16.0, 7.0), (12.0, 7.0)], seed=14, **common)
    print(f"wrote 4 captures for {SURFACE_ID} ({w:.2f} x {h:.2f} m) to {out}")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
