def mirror_openings(openings, center=0.5):
    mirrored = []
    for opening in openings:
        copy = dict(opening)
        copy["u0"] = 2 * center - opening["u1"]
        copy["u1"] = 2 * center - opening["u0"]
        copy["mwrld_symmetry_source"] = opening.get("id", opening.get("reference", "unknown"))
        mirrored.append(copy)
    return mirrored


def assert_symmetric_counts(left_count, right_count, label):
    if left_count != right_count:
        raise ValueError(f"{label} symmetry count mismatch: left={left_count}, right={right_count}")


def paired_positions(count, margin=0.18):
    if count <= 0:
        return []
    if count == 1:
        return [0.5]
    span = 1.0 - margin * 2
    return [margin + span * (index / (count - 1)) for index in range(count)]

