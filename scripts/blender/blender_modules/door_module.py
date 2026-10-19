def door_opening(along, width_meters, z0, z1, wall_length, reference=None):
    half = width_meters * 0.5
    center = along * wall_length
    return {
        "kind": "door",
        "u0": max(0.0, center - half),
        "u1": min(wall_length, center + half),
        "z0": z0,
        "z1": z1,
        "reference": reference,
    }


def evenly_spaced_doors(count, wall_length, min_z, width_meters, height_meters, positions=None, reference=None):
    if count <= 0:
        return []
    positions = positions or ([(index + 1) / (count + 1) for index in range(count)])
    return [door_opening(position, width_meters, min_z, min_z + height_meters, wall_length, reference) for position in positions[:count]]

