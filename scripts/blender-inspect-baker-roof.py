import json
import sys
from pathlib import Path

import bpy


BAKER_NAME = "building__baker-library__way_295888783"


def main():
    args = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    blend_path = Path(args[0]).resolve()
    bpy.ops.wm.open_mainfile(filepath=str(blend_path))
    obj = bpy.data.objects[BAKER_NAME]
    mesh = obj.data
    max_z = max(vertex.co.z for vertex in mesh.vertices)
    mats = [mat.name for mat in mesh.materials]
    roof = []
    for poly in mesh.polygons:
        coords = [mesh.vertices[index].co.copy() for index in poly.vertices]
        if min(co.z for co in coords) > max_z - 0.05:
            roof.append(
                {
                    "index": poly.index,
                    "center": [round(poly.center.x, 3), round(poly.center.y, 3), round(poly.center.z, 3)],
                    "area": round(poly.area, 3),
                    "material": mats[poly.material_index] if poly.material_index < len(mats) else "",
                    "verts": [[round(co.x, 3), round(co.y, 3), round(co.z, 3)] for co in coords],
                }
            )
    tower = []
    for item in bpy.context.scene.objects:
        if item.name.startswith("mwrld_tower__baker-library__"):
            tower.append(
                {
                    "name": item.name,
                    "location": [round(value, 3) for value in item.location],
                    "dimensions": [round(value, 3) for value in item.dimensions],
                }
            )

    min_z = min(vertex.co.z for vertex in mesh.vertices)
    min_x = min(vertex.co.x for vertex in mesh.vertices)
    max_x = max(vertex.co.x for vertex in mesh.vertices)
    min_y = min(vertex.co.y for vertex in mesh.vertices)
    max_y = max(vertex.co.y for vertex in mesh.vertices)
    bottom_edges = []
    for edge in mesh.edges:
        a = mesh.vertices[edge.vertices[0]].co
        b = mesh.vertices[edge.vertices[1]].co
        if abs(a.z - min_z) < 0.02 and abs(b.z - min_z) < 0.02:
            mid = (a + b) * 0.5
            distances = {
                "south": abs(mid.y - min_y),
                "north": abs(mid.y - max_y),
                "west": abs(mid.x - min_x),
                "east": abs(mid.x - max_x),
            }
            side = min(distances, key=distances.get)
            bottom_edges.append(
                {
                    "side": side,
                    "length": round((a.xy - b.xy).length, 3),
                    "a": [round(a.x, 3), round(a.y, 3)],
                    "b": [round(b.x, 3), round(b.y, 3)],
                }
            )
    print(
        "CODEX_BAKER_ROOF",
        json.dumps(
            {"maxZ": round(max_z, 3), "roof": roof, "tower": tower, "bottomEdges": sorted(bottom_edges, key=lambda row: (row["side"], -row["length"]))},
            sort_keys=True,
        ),
    )


if __name__ == "__main__":
    main()
