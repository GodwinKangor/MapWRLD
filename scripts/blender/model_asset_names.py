"""Human-readable filenames; object names and OSM IDs remain stable."""
import re


def building_filename(display_name, fallback):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(display_name)).strip(" .")
    return name or fallback
