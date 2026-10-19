from .geometry_core import assign_detail_metadata, rectangle_box


def create_chimney(name, x, y, base_z, width, depth, height, material, building=None, reference=None):
    obj = rectangle_box(
        name,
        x - width * 0.5,
        x + width * 0.5,
        y - depth * 0.5,
        y + depth * 0.5,
        base_z,
        base_z + height,
        material,
    )
    assign_detail_metadata(obj, building, "chimney", reference=reference)
    return obj


def create_tiered_tower(name, center_x, center_y, base_z, tiers, materials, building=None, reference=None):
    objects = []
    z = base_z
    for index, tier in enumerate(tiers):
        material = materials.get(tier.get("material", "tower")) if isinstance(materials, dict) else materials
        width = tier["width"]
        depth = tier.get("depth", width)
        height = tier["height"]
        obj = rectangle_box(
            f"{name}_tier_{index + 1:02d}",
            center_x - width * 0.5,
            center_x + width * 0.5,
            center_y - depth * 0.5,
            center_y + depth * 0.5,
            z,
            z + height,
            material,
        )
        assign_detail_metadata(obj, building, "tower", reference=reference)
        obj["mwrld_tower_tier"] = index + 1
        objects.append(obj)
        z += height
    return objects

