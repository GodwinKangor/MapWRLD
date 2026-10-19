"""Rename exported building assets and update their JSON path references."""
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from model_asset_names import building_filename

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "public/models"
BUILDINGS = MODELS / "dartmouth-energy-twin/renders/buildings"


def main():
    replacements, operations, entries = {}, [], []
    for metadata_path in sorted(BUILDINGS.glob("*/metadata.json")):
        metadata = json.loads(metadata_path.read_text())
        name = building_filename(metadata["displayName"], metadata_path.parent.name)
        links = []
        for extension in ("glb", "fbx"):
            source = metadata_path.parent / metadata[extension]
            target = metadata_path.parent / f"{name}.{extension}"
            if not source.is_file():
                raise FileNotFoundError(source)
            if source != target:
                if target.exists():
                    raise FileExistsError(f"Refusing to overwrite {target}")
                replacements[source.name] = target.name
                operations.append((source, target, hashlib.sha256(source.read_bytes()).hexdigest()))
            links.append(f"[{extension.upper()}]({quote(str(target.relative_to(BUILDINGS)))})")
        entries.append((metadata["displayName"], metadata["osmId"], links))

    # Preflight every affected JSON document before moving any file.
    edits = []

    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            basename = value.rsplit("/", 1)[-1]
            if basename in replacements:
                return value[:-len(basename)] + replacements[basename]
        return value

    for path in MODELS.rglob("*.json"):
        raw = path.read_text()
        if ".glb" not in raw and ".fbx" not in raw:
            continue
        data = json.loads(raw)
        updated = rewrite(data)
        if updated != data:
            edits.append((path, json.dumps(updated, indent=2) + "\n"))
    for source, target, digest in operations:
        source.rename(target)
        assert hashlib.sha256(target.read_bytes()).hexdigest() == digest
    for path, content in edits:
        path.write_text(content)
    lines = ["# Building models", "", "Find a building alphabetically below. Folder and scene IDs stay stable; model files use display names.", "",
             "Buildings sharing a name remain in separate OSM-ID folders. Unnamed buildings retain their recorded address or Building ID.", "",
             "| Building | OSM ID | Files |", "| --- | --- | --- |"]
    for name, osm_id, links in sorted(entries, key=lambda entry: (entry[0].casefold(), entry[1])):
        lines.append(f"| {name.replace('|', '-')} | {osm_id} | {' · '.join(links)} |")
    (BUILDINGS / "README.md").write_text("\n".join(lines) + "\n")
    print(f"Renamed {len(operations)} assets; updated {len(edits)} JSON files; indexed {len(entries)} buildings.")


if __name__ == "__main__":
    main()
