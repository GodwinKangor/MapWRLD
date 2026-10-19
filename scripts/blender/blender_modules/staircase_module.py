from .geometry_core import assign_detail_metadata, rectangle_box


def create_staircase(name, min_x, max_x, y0, z0, step_depth, step_height, step_count, material, building=None, reference=None):
    steps = []
    for index in range(step_count):
        step = rectangle_box(
            f"{name}_step_{index + 1:02d}",
            min_x,
            max_x,
            y0 + index * step_depth,
            y0 + (index + 1) * step_depth,
            z0 + index * step_height,
            z0 + (index + 1) * step_height,
            material,
        )
        assign_detail_metadata(step, building, "staircase", reference=reference)
        step["mwrld_stair_index"] = index + 1
        steps.append(step)
    return steps

