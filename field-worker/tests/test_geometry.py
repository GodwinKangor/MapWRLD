"""Frame and identity checks for mwrld_field.geometry (see docs/field-capture/SPEC.md)."""
import json
import math
from pathlib import Path

import pytest

from mwrld_field.geometry import (
    Georeference, signed_area, surface_to_texture, texture_to_surface, walls_from_footprint,
)

ROOT = Path(__file__).resolve().parents[2]

# 10 m (east-west) x 6 m (north-south) box, counter-clockwise, with an extra
# collinear node on the south edge (as OSM entrance nodes are).
BOX_CCW = [(1, 0.0, 0.0), (5, 4.0, 0.0), (2, 10.0, 0.0), (3, 10.0, 6.0), (4, 0.0, 6.0), (1, 0.0, 0.0)]


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def by_facing(walls):
    return {w.facing: w for w in walls}


def test_collinear_nodes_merge_and_ids_use_end_nodes():
    walls = walls_from_footprint("b", "way/9", BOX_CCW, 8.0)
    assert len(walls) == 4
    south = by_facing(walls)["south"]
    assert south.node_chain == [1, 5, 2]
    assert south.surface_id == "osm:way/9/wall/1-2"
    assert math.isclose(south.width_m, 10.0)


@pytest.mark.parametrize("ring", [BOX_CCW, BOX_CCW[::-1]], ids=["ccw", "cw"])
def test_normals_point_outward_regardless_of_winding(ring):
    walls = by_facing(walls_from_footprint("b", "way/9", ring, 8.0))
    centre = (5.0, 3.0)
    for facing, wall in walls.items():
        mid = wall.to_campus(wall.width_m / 2, 0)
        outward = (mid[0] - centre[0]) * wall.normal[0] + (mid[1] - centre[1]) * wall.normal[1]
        assert outward > 0, facing
    assert set(walls) == {"north", "south", "east", "west"}


@pytest.mark.parametrize("ring", [BOX_CCW, BOX_CCW[::-1]], ids=["ccw", "cw"])
def test_surface_frame_is_right_handed_and_unmirrored_from_outside(ring):
    walls = by_facing(walls_from_footprint("b", "way/9", ring, 8.0))
    for wall in walls.values():
        assert cross(wall.u_axis, wall.v_axis) == pytest.approx(wall.normal)
    # Standing south of the building looking north, east is on the viewer's right:
    # u must increase eastward on the south wall, westward on the north wall.
    assert walls["south"].u_axis[0] == pytest.approx(1.0)
    assert walls["north"].u_axis[0] == pytest.approx(-1.0)
    assert walls["east"].u_axis[1] == pytest.approx(1.0)
    assert walls["west"].u_axis[1] == pytest.approx(-1.0)
    # IDs are stable under winding: same origin node either way
    assert walls["south"].surface_id == "osm:way/9/wall/1-2"


def test_surface_campus_round_trip():
    wall = walls_from_footprint("b", "way/9", BOX_CCW, 8.0, base_z=2.0)[1]
    for u, v, n in [(0, 0, 0), (3.2, 5.1, 0), (1.0, 2.0, 0.4)]:
        assert wall.from_campus(*wall.to_campus(u, v, n)) == pytest.approx((u, v, n))
    assert wall.to_campus(0, 0)[2] == 2.0


def test_texture_rows_run_top_down_and_round_trip():
    height, ppm = 8.0, 50.0
    u, v = texture_to_surface(0, 0, height, ppm)
    assert v > height - 0.05 and u < 0.05  # first texel is the top-left of the wall
    for col, row in [(0, 0), (123, 77), (499, 399)]:
        assert surface_to_texture(*texture_to_surface(col, row, height, ppm), height, ppm) == pytest.approx((col, row))


def test_georeference_round_trip_and_scale():
    meta = json.loads((ROOT / "public/models/dartmouth-campus/terrain/campus-terrain.json").read_text())
    geo = Georeference.from_campus_terrain(meta)
    lon, lat = geo.to_geographic(100.0, -50.0)
    assert geo.to_campus(lon, lat) == pytest.approx((100.0, -50.0))
    # 1 m north is ~1/111,000 degree of latitude at Hanover
    assert geo.latitude_per_meter == pytest.approx(1 / 111_000, rel=0.01)


def test_signed_area_sign():
    pts = [(x, y) for _, x, y in BOX_CCW[:-1]]
    assert signed_area(pts) == pytest.approx(60.0)
    assert signed_area(pts[::-1]) == pytest.approx(-60.0)


def test_mcnutt_registry_consistency():
    """The committed registry must agree with the geometry module that defines it."""
    path = ROOT / "data/field-surfaces/mcnutt-hall-261793901.surfaces.json"
    registry = json.loads(path.read_text())
    walls = [s for s in registry["surfaces"] if s["kind"] == "wall"]
    ids = [s["surfaceId"] for s in walls]
    assert len(ids) == len(set(ids)) == 8
    for s in walls:
        frame = s["frame"]
        assert cross(frame["uAxis"], frame["vAxis"]) == pytest.approx(frame["normal"], abs=1e-9)
        assert s["blender"]["mappingStatus"] == "matched"
        assert max(s["blender"]["cornerMatchErrorM"]) < 0.05
    west_front = next(s for s in walls if s["surfaceId"] == "osm:way/261793901/wall/2674282718-2674282725")
    assert west_front["blender"]["panelIds"] == ["west-01"]
    assert west_front["widthM"] == pytest.approx(19.26, abs=0.01)
