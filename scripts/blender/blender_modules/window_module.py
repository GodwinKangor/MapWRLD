def window_opening(along, width_meters, z0, z1, wall_length, reference=None):
    half = width_meters * 0.5
    center = along * wall_length
    return {
        "kind": "window",
        "u0": max(0.0, center - half),
        "u1": min(wall_length, center + half),
        "z0": z0,
        "z1": z1,
        "reference": reference,
    }


def evenly_spaced_windows(count, floors, wall_length, min_z, floor_height, width_meters, height_meters, sill_height=1.4, reference=None):
    openings = []
    if count <= 0 or floors <= 0:
        return openings
    columns = max(1, round(count / floors))
    remaining = count
    for floor in range(floors):
        row_count = min(columns, remaining)
        remaining -= row_count
        if floor == floors - 1 and remaining > 0:
            row_count += remaining
            remaining = 0
        for column in range(row_count):
            z0 = min_z + sill_height + floor * floor_height
            openings.append(
                window_opening(
                    (column + 1) / (row_count + 1),
                    width_meters,
                    z0,
                    z0 + height_meters,
                    wall_length,
                    reference,
                )
            )
    return openings

