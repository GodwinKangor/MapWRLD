"""Coordinate frames and persistent surface identity for field capture.

Pure Python (no numpy) so Blender's bundled interpreter can import it unchanged.
Frames are specified in docs/field-capture/SPEC.md; this module is the
executable definition and tests/test_geometry.py checks it.

Frames
------
G  geographic: WGS84 longitude/latitude in degrees.
C  campus/Blender frame: metres, x east, y north, z up. Origin at the campus
   georeference origin (public/models/dartmouth-campus/terrain/campus-terrain.json).
   Longitude/latitude map linearly onto x/y (the calibrated campus export is
   linear at campus scale). z = 0 at the building's own base: Blender building
   meshes start at z = 0 and are lifted onto the terrain only at display time.
   The GLB/Three.js frame is (x, z_up, -y) of this frame.
S  surface frame of one wall: metres. Origin at the wall's bottom-left corner as
   seen from OUTSIDE the building. u along the wall to the viewer's right,
   v straight up, n outward (toward the viewer). u x v = n (right-handed).
T  texture: pixels. Column i covers u in [i/ppm, (i+1)/ppm); row 0 is the TOP
   of the wall. A texture viewed normally shows the wall as seen from outside,
   unmirrored.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field

SCHEMA_SURFACES = "mwrld.surfaces/v1"
# Consecutive footprint edges turning by less than this are one physical wall:
# OSM often inserts entrance or survey nodes on a straight facade.
COLLINEAR_TOLERANCE_DEG = 3.0


@dataclass(frozen=True)
class Georeference:
    origin_longitude: float
    origin_latitude: float
    longitude_per_meter: float
    latitude_per_meter: float

    @classmethod
    def from_campus_terrain(cls, meta: dict) -> "Georeference":
        frame = meta["frame"]
        return cls(
            frame["origin"]["longitude"], frame["origin"]["latitude"],
            frame["georeference"]["longitudePerMeter"], frame["georeference"]["latitudePerMeter"],
        )

    def to_campus(self, longitude: float, latitude: float) -> tuple[float, float]:
        """G -> C (x east, y north), metres."""
        return ((longitude - self.origin_longitude) / self.longitude_per_meter,
                (latitude - self.origin_latitude) / self.latitude_per_meter)

    def to_geographic(self, x: float, y: float) -> tuple[float, float]:
        """C -> G."""
        return (self.origin_longitude + x * self.longitude_per_meter,
                self.origin_latitude + y * self.latitude_per_meter)

    def as_dict(self) -> dict:
        return {"originLongitude": self.origin_longitude, "originLatitude": self.origin_latitude,
                "longitudePerMeter": self.longitude_per_meter, "latitudePerMeter": self.latitude_per_meter}


def signed_area(points: list[tuple[float, float]]) -> float:
    """Shoelace area; positive for counter-clockwise rings (x east, y north)."""
    total = 0.0
    for (x0, y0), (x1, y1) in zip(points, points[1:] + points[:1]):
        total += x0 * y1 - x1 * y0
    return total / 2


@dataclass
class WallSurface:
    surface_id: str
    building_id: str
    osm_id: str
    node_chain: list[int]           # OSM nodes from the surface origin (left) to the right end
    origin: tuple[float, float, float]   # C frame, bottom-left seen from outside
    u_axis: tuple[float, float, float]   # unit, C frame
    normal: tuple[float, float, float]   # unit outward, C frame
    width_m: float
    height_m: float
    kind: str = "wall"
    facing: str = ""                # compass label of the outward normal, informational only
    blender: dict = field(default_factory=dict)

    v_axis = (0.0, 0.0, 1.0)

    def to_campus(self, u: float, v: float, n: float = 0.0) -> tuple[float, float, float]:
        """S -> C."""
        ox, oy, oz = self.origin
        return (ox + u * self.u_axis[0] + n * self.normal[0],
                oy + u * self.u_axis[1] + n * self.normal[1],
                oz + v + n * self.normal[2])

    def from_campus(self, x: float, y: float, z: float) -> tuple[float, float, float]:
        """C -> S (u, v, n)."""
        dx, dy, dz = x - self.origin[0], y - self.origin[1], z - self.origin[2]
        return (dx * self.u_axis[0] + dy * self.u_axis[1],
                dz,
                dx * self.normal[0] + dy * self.normal[1])

    def corners(self) -> dict[str, tuple[float, float]]:
        """Named corners in S (u, v), as seen from outside."""
        return {"bottom-left": (0.0, 0.0), "bottom-right": (self.width_m, 0.0),
                "top-right": (self.width_m, self.height_m), "top-left": (0.0, self.height_m)}

    def as_dict(self) -> dict:
        return {
            "surfaceId": self.surface_id, "kind": self.kind, "buildingId": self.building_id, "osmId": self.osm_id,
            "nodeChain": self.node_chain, "facing": self.facing,
            "frame": {"origin": list(self.origin), "uAxis": list(self.u_axis), "vAxis": list(self.v_axis),
                      "normal": list(self.normal)},
            "widthM": round(self.width_m, 4), "heightM": round(self.height_m, 4),
            "corners": {k: list(v) for k, v in self.corners().items()},
            "blender": self.blender,
        }


def compass(dx: float, dy: float) -> str:
    bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return ["north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest"][int((bearing + 22.5) // 45) % 8]


def wall_surface_id(osm_id: str, node_chain: list[int]) -> str:
    """Persistent ID: the OSM way plus the end nodes of the wall in S-frame order.

    Independent of mesh triangle/vertex indices and of Blender's side-ordered
    names (`south-01`), which change whenever the mesh is rebuilt.
    """
    return f"osm:{osm_id}/wall/{node_chain[0]}-{node_chain[-1]}"


def roof_surface_id(osm_id: str, part: str = "main") -> str:
    return f"osm:{osm_id}/roof/{part}"


def walls_from_footprint(
    building_id: str, osm_id: str, ring: list[tuple[int, float, float]], height_m: float, base_z: float = 0.0,
    collinear_tolerance_deg: float = COLLINEAR_TOLERANCE_DEG,
) -> list[WallSurface]:
    """Wall surfaces of a closed footprint ring [(node_id, x, y), ...] in C.

    The ring may or may not repeat its first node at the end, and may be
    clockwise or counter-clockwise; outward normals are derived from the
    winding, never assumed.
    """
    if len(ring) > 1 and ring[0][0] == ring[-1][0]:
        ring = ring[:-1]
    if len(ring) < 3:
        raise ValueError("footprint needs at least 3 distinct nodes")
    ccw = signed_area([(x, y) for _, x, y in ring]) > 0
    if not ccw:  # work counter-clockwise so 'right of the edge' is outward
        ring = ring[::-1]
    n = len(ring)

    def direction(i: int) -> tuple[float, float]:
        (_, x0, y0), (_, x1, y1) = ring[i], ring[(i + 1) % n]
        return x1 - x0, y1 - y0

    def turn(i: int) -> float:  # angle between edge i-1 and edge i, degrees
        ax, ay = direction(i - 1)
        bx, by = direction(i)
        return abs(math.degrees(math.atan2(ax * by - ay * bx, ax * bx + ay * by)))

    # start at a real corner so a merged wall never wraps around the ring start
    corners = [i for i in range(n) if turn(i) >= collinear_tolerance_deg]
    if not corners:
        raise ValueError("footprint has no corners")
    start = corners[0]
    order = [(start + k) % n for k in range(n)]
    walls: list[list[int]] = []
    for i in order:
        if i in corners or not walls:
            walls.append([i])
        else:
            walls[-1].append(i)

    surfaces = []
    for chain in walls:
        nodes = [ring[i] for i in chain] + [ring[(chain[-1] + 1) % n]]
        (_, x0, y0), (_, x1, y1) = nodes[0], nodes[-1]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-6:
            continue
        ux, uy = dx / length, dy / length
        normal = (uy, -ux, 0.0)  # right of a CCW edge is outward; seen from outside, u points right
        node_chain = [node for node, _, _ in nodes]
        surfaces.append(WallSurface(
            surface_id=wall_surface_id(osm_id, node_chain), building_id=building_id, osm_id=osm_id,
            node_chain=node_chain, origin=(x0, y0, base_z), u_axis=(ux, uy, 0.0), normal=normal,
            width_m=length, height_m=height_m, facing=compass(normal[0], normal[1]),
        ))
    return surfaces


def texture_to_surface(col: float, row: float, height_m: float, pixels_per_meter: float) -> tuple[float, float]:
    """T pixel centre (col, row) -> S (u, v). Row 0 is the top of the wall."""
    return (col + 0.5) / pixels_per_meter, height_m - (row + 0.5) / pixels_per_meter


def surface_to_texture(u: float, v: float, height_m: float, pixels_per_meter: float) -> tuple[float, float]:
    """S (u, v) -> continuous T coordinates (col, row) of pixel centres."""
    return u * pixels_per_meter - 0.5, (height_m - v) * pixels_per_meter - 0.5


def registry_digest(registry: dict) -> str:
    """Content hash of the geometry that defines surfaces, for change detection."""
    payload = json.dumps([(s["surfaceId"], s["frame"], s["widthM"], s["heightM"]) for s in registry["surfaces"]], sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
