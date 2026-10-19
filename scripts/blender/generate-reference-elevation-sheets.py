import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.blender.blender_modules.reference_module import write_scaled_reference_sheet


MODEL_DIR = ROOT / "public" / "models" / "dartmouth-energy-twin"
MANIFEST_PATH = MODEL_DIR / "renders" / "parts-manifest.json"


def main():
    parser = argparse.ArgumentParser(description="Generate scaled exterior reference boards for a building.")
    parser.add_argument("query", help="Building name/folder query, e.g. dartmouth-hall or baker-library")
    parser.add_argument("--height", type=float, default=14.0, help="Estimated facade height in meters when rules do not specify one.")
    parser.add_argument("--pixels-per-meter", type=int, default=34)
    args = parser.parse_args()

    building = find_building(args.query)
    reference_dir = MODEL_DIR / "renders" / building["folder"] / "references"
    if not (reference_dir / "references-manifest.json").exists():
        raise SystemExit(f"Missing references-manifest.json for {building['name']}")

    result = write_scaled_reference_sheet(
        reference_dir,
        estimated_height_meters=args.height,
        pixels_per_meter=args.pixels_per_meter,
    )
    print(f"Wrote {result['svg'].relative_to(ROOT)}")
    print(f"Wrote {result['json'].relative_to(ROOT)}")
    print(f"Wrote {result['orthographicSvg'].relative_to(ROOT)}")
    print(f"Wrote {result['orthographicJson'].relative_to(ROOT)}")
    print(f"panels: {result['panelCount']}")
    print(f"auxiliaryPanels: {result['auxiliaryPanelCount']}")


def find_building(query):
    import json

    manifest = json.loads(MANIFEST_PATH.read_text())
    needle = query.lower()
    matches = [
        building
        for building in manifest.get("buildings", [])
        if needle in building.get("name", "").lower() or needle in building.get("folder", "").lower()
    ]
    if not matches:
        raise SystemExit(f"No building matched {query}")
    return matches[0]


if __name__ == "__main__":
    main()
