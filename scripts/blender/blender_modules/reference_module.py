import base64
import html
import json
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ReferencePanel:
    panel_id: str
    title: str
    image_path: Path
    relative_image_path: str
    width_meters: float
    estimated_height_meters: float
    source_kind: str
    reference_status: str
    quality_status: str
    elevation_role: str = ""
    wall_id: str = ""
    orientation: str = ""
    windows: int = 0
    doors: int = 0
    count_method: str = ""
    notes: str = ""
    primitive_hints: tuple = ()
    opening_layout: tuple = ()
    wall_features: tuple = ()
    stair_features: tuple = ()
    roof_zones: tuple = ()
    roof_profiles: dict = None

    @property
    def aspect_ratio(self):
        width, height = image_size(self.image_path)
        return width / height if width and height else 1.45


def load_reference_bundle(building_reference_dir):
    reference_dir = Path(building_reference_dir)
    manifest = json.loads((reference_dir / "references-manifest.json").read_text())
    rules_path = reference_dir / "modeling-rules.json"
    rules = json.loads(rules_path.read_text()) if rules_path.exists() else {}
    return {"referenceDir": reference_dir, "manifest": manifest, "rules": rules}


def selected_reference_panels(building_reference_dir, estimated_height_meters=14.0, include_unapproved=True):
    bundle = load_reference_bundle(building_reference_dir)
    reference_dir = bundle["referenceDir"]
    manifest = bundle["manifest"]
    rules = bundle["rules"]
    wall_plans = rules.get("windowsAndDoors", {}).get("wallOpeningPlans", {})
    panels = []

    if wall_plans:
        for wall_id, plan in wall_plans.items():
            rel_path = plan.get("reference")
            if not rel_path:
                continue
            image_path = reference_dir / rel_path.removeprefix("references/")
            matched_wall = wall_by_reference(manifest, rel_path)
            width_meters = matched_wall.get("lengthMeters") or plan.get("widthMeters") or estimated_width_from_manifest(manifest)
            panels.append(
                ReferencePanel(
                    panel_id=wall_id,
                    title=wall_id.replace("-", " ").title(),
                    image_path=image_path,
                    relative_image_path=rel_path,
                    width_meters=float(width_meters),
                    estimated_height_meters=float(plan.get("heightMeters", estimated_height_meters)),
                    source_kind="opening-plan",
                    reference_status="approved-by-modeling-rules",
                    quality_status=plan.get("quality", "needs-review"),
                    elevation_role=elevation_role_for_panel(wall_id, matched_wall.get("orientation", ""), plan, rules),
                    wall_id=matched_wall.get("id", wall_id),
                    orientation=matched_wall.get("orientation", ""),
                    windows=int(plan.get("windows", 0)),
                    doors=int(plan.get("doors", 0)),
                    count_method=plan.get("countMethod", "rule-derived"),
                    notes=plan.get("notes", ""),
                    primitive_hints=tuple(plan.get("primitiveHints", opening_plan_primitives(plan))),
                    opening_layout=tuple(opening_layout_for_plan(plan, float(width_meters), float(plan.get("heightMeters", estimated_height_meters)), rel_path)),
                    wall_features=tuple(annotate_wall_features(plan.get("majorWallFeatures", []), rel_path)),
                    stair_features=tuple(annotate_stair_features(plan.get("stairFeatures", []), rel_path)),
                )
            )
        return panels

    approved_sources = set(rules.get("windowsAndDoors", {}).get("approvedWallSources", []))
    blocked_sources = set(rules.get("windowsAndDoors", {}).get("blockedWallSources", []))
    for wall in manifest.get("walls", []):
        reference = wall.get("reference", {})
        if reference.get("status") != "saved":
            continue
        source_id = wall["id"]
        approved = source_id in approved_sources if approved_sources else wall.get("approvedForModeling") or reference.get("qualityStatus") == "approved"
        if source_id in blocked_sources:
            approved = False
        if not approved and not include_unapproved:
            continue
        rel_path = reference.get("path", "")
        panels.append(
            ReferencePanel(
                panel_id=wall["id"],
                title=wall.get("name", wall["id"]),
                image_path=reference_dir / rel_path.removeprefix("references/"),
                relative_image_path=rel_path,
                width_meters=float(wall.get("lengthMeters", estimated_width_from_manifest(manifest))),
                estimated_height_meters=float(estimated_height_meters),
                source_kind="wall-reference",
                reference_status="approved" if approved else "needs-review",
                quality_status=reference.get("qualityStatus", "needs-review"),
                elevation_role=elevation_role_for_panel(wall["id"], wall.get("orientation", ""), {}, rules),
                wall_id=wall["id"],
                orientation=wall.get("orientation", ""),
                count_method="unreviewed-reference" if not approved else "approved-reference",
                primitive_hints=tuple(wall_reference_primitives(wall, approved)),
            )
        )
    return panels


def selected_auxiliary_panels(building_reference_dir, estimated_roof_width_meters=None):
    bundle = load_reference_bundle(building_reference_dir)
    reference_dir = bundle["referenceDir"]
    manifest = bundle["manifest"]
    rules = bundle["rules"]
    panels = []
    roof_source = rules.get("roof", {}).get("referenceSource") or manifest.get("roof", {}).get("path")
    roof_width = estimated_roof_width_meters or estimated_width_from_manifest(manifest)
    if roof_source:
        panels.append(
            ReferencePanel(
                panel_id="roof",
                title="Roof Plan / Satellite",
                image_path=reference_dir / roof_source.removeprefix("references/"),
                relative_image_path=roof_source,
                width_meters=float(roof_width),
                estimated_height_meters=float(roof_width),
                source_kind="roof",
                reference_status="approved-by-modeling-rules" if rules.get("roof", {}).get("mustUseRoofSatelliteReference") else "needs-review",
                quality_status="roof-footprint-only",
                elevation_role="roof",
                notes=rules.get("roof", {}).get("type", ""),
                primitive_hints=tuple(roof_primitives(rules.get("roof", {}))),
                roof_zones=tuple(annotate_roof_zones(rules.get("roof", {}).get("roofZones", []), roof_source)),
                roof_profiles=annotate_roof_profiles(rules.get("roof", {}).get("roofElevationProfiles", {}), roof_source),
            )
        )

    tower_manifest_path = rules.get("tower", {}).get("referenceManifest")
    if tower_manifest_path:
        tower_path = reference_dir / tower_manifest_path.removeprefix("references/")
        if tower_path.exists():
            tower_manifest = json.loads(tower_path.read_text())
            for item in tower_manifest.get("references", []):
                file_name = item.get("file")
                if not file_name:
                    continue
                panels.append(
                    ReferencePanel(
                        panel_id=item.get("id", Path(file_name).stem),
                        title=item.get("id", Path(file_name).stem).replace("-", " ").title(),
                        image_path=tower_path.parent / file_name,
                        relative_image_path=f"references/tower/{file_name}",
                        width_meters=10.0,
                        estimated_height_meters=24.0,
                        source_kind="tower",
                        reference_status="blocked-context-only" if item.get("notApprovedFor") else "approved-by-tower-manifest",
                        quality_status=", ".join(item.get("allowedUses", [])),
                        elevation_role="addition",
                        notes=", ".join(item.get("represents", [])),
                        primitive_hints=tuple(tower_primitives(item, rules.get("tower", {}))),
                    )
                )
    return panels


def write_scaled_reference_sheet(building_reference_dir, output_dir=None, estimated_height_meters=14.0, pixels_per_meter=34):
    bundle = load_reference_bundle(building_reference_dir)
    reference_dir = bundle["referenceDir"]
    manifest = bundle["manifest"]
    rules = bundle["rules"]
    panels = selected_reference_panels(reference_dir, estimated_height_meters=estimated_height_meters)
    auxiliary_panels = selected_auxiliary_panels(reference_dir)
    output_dir = Path(output_dir) if output_dir else reference_dir / "elevation-sheets"
    output_dir.mkdir(parents=True, exist_ok=True)

    all_panels = panels + auxiliary_panels
    layout = layout_panels(all_panels, pixels_per_meter)
    svg = render_svg_board(manifest, all_panels, layout, output_dir, pixels_per_meter)
    orthographic_svg = render_orthographic_elevations(manifest, panels, auxiliary_panels, pixels_per_meter)
    svg_path = output_dir / "scaled-reference-board.svg"
    json_path = output_dir / "scaled-reference-board.json"
    orthographic_svg_path = output_dir / "orthographic-elevations.svg"
    orthographic_json_path = output_dir / "orthographic-elevations.json"
    svg_path.write_text(svg)
    json_path.write_text(json.dumps(reference_plan(manifest, rules, panels, auxiliary_panels, layout, pixels_per_meter, output_dir), indent=2) + "\n")
    orthographic_svg_path.write_text(orthographic_svg)
    orthographic_json_path.write_text(json.dumps(orthographic_plan(manifest, rules, panels, auxiliary_panels, pixels_per_meter, output_dir), indent=2) + "\n")
    return {
        "svg": svg_path,
        "json": json_path,
        "orthographicSvg": orthographic_svg_path,
        "orthographicJson": orthographic_json_path,
        "panelCount": len(panels),
        "auxiliaryPanelCount": len(auxiliary_panels),
    }


def layout_panels(panels, pixels_per_meter):
    margin = 36
    gap = 28
    label_height = 94
    max_panel_width = 520
    cells = []
    for panel in panels:
        width = max(220, min(max_panel_width, panel.width_meters * pixels_per_meter))
        height = max(180, min(360, panel.estimated_height_meters * pixels_per_meter))
        cells.append({"panel": panel, "width": width, "height": height})
    if not cells:
        return {"width": 900, "height": 420, "cells": []}

    columns = 2 if len(cells) > 1 else 1
    column_width = max(cell["width"] for cell in cells)
    x_positions = [margin + column * (column_width + gap) for column in range(columns)]
    row_heights = []
    for index in range(0, len(cells), columns):
        row_heights.append(max(cell["height"] + label_height for cell in cells[index : index + columns]))
    y = margin
    for index, cell in enumerate(cells):
        row = index // columns
        column = index % columns
        cell["x"] = x_positions[column]
        cell["y"] = y
        if column == columns - 1:
            y += row_heights[row] + gap
    if len(cells) % columns:
        y += row_heights[-1] + gap
    board_width = margin * 2 + columns * column_width + (columns - 1) * gap
    board_height = margin + sum(row_heights) + max(0, len(row_heights) - 1) * gap + margin
    return {"width": board_width, "height": board_height, "cells": cells}


def render_svg_board(manifest, panels, layout, output_dir, pixels_per_meter):
    title = manifest.get("displayName") or manifest.get("building") or "Building"
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{layout["width"]:.0f}" height="{layout["height"]:.0f}" viewBox="0 0 {layout["width"]:.0f} {layout["height"]:.0f}">',
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif;fill:#232323}.tiny{font-size:10px}.label{font-size:13px;font-weight:700}.meta{font-size:11px}.frame{fill:#fff;stroke:#1f1f1f;stroke-width:1}.guide{stroke:#b8b8b8;stroke-width:.65}.window{fill:#55a7ff;stroke:#063f78;stroke-width:1.2;fill-opacity:.34}.door{fill:#f2a33a;stroke:#7a3f00;stroke-width:1.4;fill-opacity:.48}.feature{fill:#b58cff;stroke:#4a238a;stroke-width:1.25;fill-opacity:.25}.stair{fill:#77c879;stroke:#1b5e20;stroke-width:1.25;fill-opacity:.33}.openingText{font-size:9px;font-weight:700;fill:#111}.legend{font-size:10px;font-weight:700}",
        "</style>",
        '<rect width="100%" height="100%" fill="#f7f6f1"/>',
        f'<text x="36" y="24" class="label">{escape(title)} scaled exterior reference board</text>',
    ]
    for cell in layout["cells"]:
        panel = cell["panel"]
        x = cell["x"]
        y = cell["y"]
        width = cell["width"]
        height = cell["height"]
        data_url = image_data_url(panel.image_path)
        parts.extend(
            [
                f'<rect class="frame" x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}"/>',
                f'<image href="{escape(data_url)}" x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" preserveAspectRatio="xMidYMid meet"/>',
                f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" fill="white" opacity="0.20"/>',
                grid_lines(x, y, width, height, panel.width_meters, panel.estimated_height_meters, pixels_per_meter),
                opening_overlay(panel, x, y, width, height),
                f'<text x="{x:.1f}" y="{y + height + 18:.1f}" class="label">{escape(panel.title)}</text>',
                f'<text x="{x:.1f}" y="{y + height + 34:.1f}" class="meta">{escape(panel.width_meters)}m wide approx | {escape(panel.estimated_height_meters)}m height guide | {escape(panel.reference_status)}</text>',
                f'<text x="{x:.1f}" y="{y + height + 50:.1f}" class="meta">wall={escape(panel.wall_id)} windows={panel.windows} doors={panel.doors} source={escape(panel.relative_image_path)}</text>',
                f'<text x="{x:.1f}" y="{y + height + 64:.1f}" class="tiny">openings: {escape(opening_summary(panel))}</text>',
                f'<text x="{x:.1f}" y="{y + height + 78:.1f}" class="tiny">primitives: {escape(primitive_summary(panel))}</text>',
            ]
        )
    parts.append("</svg>")
    return "\n".join(parts)


def render_orthographic_elevations(manifest, panels, auxiliary_panels, pixels_per_meter):
    roles = [
        ("front", "Front Elevation"),
        ("rear", "Rear Elevation"),
        ("left-side", "Left Side Elevation"),
        ("right-side", "Right Side Elevation"),
        ("roof", "Roof Plan"),
        ("addition", "Additions / Tower"),
        ("unassigned", "Unassigned References"),
    ]
    margin = 42
    gap = 34
    panel_gap = 12
    label_height = 86
    row_width = 1040
    row_y = margin + 32
    rows = []
    all_panels = panels + auxiliary_panels
    for role, label in roles:
        role_panels = [panel for panel in all_panels if (panel.elevation_role or "unassigned") == role]
        if not role_panels:
            continue
        height = max(260, min(430, max(panel.estimated_height_meters for panel in role_panels) * pixels_per_meter))
        width = min(row_width, sum(min(360, max(180, panel.width_meters * pixels_per_meter)) for panel in role_panels) + panel_gap * (len(role_panels) - 1))
        rows.append({"role": role, "label": label, "panels": role_panels, "x": margin, "y": row_y, "width": width, "height": height})
        row_y += height + label_height + gap
    svg_height = max(520, row_y + margin)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{row_width + margin * 2}" height="{svg_height:.0f}" viewBox="0 0 {row_width + margin * 2} {svg_height:.0f}">',
        "<style>",
        "text{font-family:Arial,Helvetica,sans-serif;fill:#202020}.title{font-size:18px;font-weight:700}.role{font-size:15px;font-weight:700}.meta{font-size:11px}.tiny{font-size:10px}.wall{fill:#fff;stroke:#222;stroke-width:1.4}.grid{stroke:#d8d8d8;stroke-width:.65}.window{fill:#72b8ff;stroke:#063f78;stroke-width:1.1;fill-opacity:.5}.door{fill:#f4aa42;stroke:#7a3f00;stroke-width:1.3;fill-opacity:.62}.feature{fill:#b58cff;stroke:#4a238a;stroke-width:1.25;fill-opacity:.25}.stair{fill:#77c879;stroke:#1b5e20;stroke-width:1.25;fill-opacity:.33}.roof{fill:#e6e6e6;stroke:#333;stroke-width:1.2}.openingText{font-size:9px;font-weight:700;fill:#111}",
        "</style>",
        '<rect width="100%" height="100%" fill="#f7f6f1"/>',
        f'<text x="{margin}" y="28" class="title">{escape(manifest.get("displayName") or manifest.get("building") or "Building")} orthographic modeling elevations</text>',
        f'<text x="{margin}" y="47" class="meta">Straightened diagrams generated from approved rules/counts and scaled wall dimensions. Oblique photos remain evidence, not the modeling surface.</text>',
    ]
    for row in rows:
        parts.append(render_orthographic_row(row, pixels_per_meter, panel_gap))
    parts.append("</svg>")
    return "\n".join(parts)


def render_orthographic_row(row, pixels_per_meter, panel_gap):
    x = row["x"]
    y = row["y"]
    parts = [
        f'<text x="{x}" y="{y - 12}" class="role">{escape(row["label"])}</text>',
    ]
    cursor_x = x
    for panel in row["panels"]:
        panel_width = min(360, max(180, panel.width_meters * pixels_per_meter))
        panel_height = row["height"]
        parts.append(render_orthographic_panel(panel, cursor_x, y, panel_width, panel_height))
        cursor_x += panel_width + panel_gap
    counts = opening_counts_for_panels(row["panels"])
    parts.append(
        f'<text x="{x}" y="{y + row["height"] + 18}" class="meta">counts: windows={counts["windows"]} doors={counts["doors"]}</text>'
    )
    proof = "; ".join(filter(None, [count_proof(panel) for panel in row["panels"]]))
    parts.append(f'<text x="{x}" y="{y + row["height"] + 34}" class="tiny">proof: {escape(proof or "none")}</text>')
    parts.append(f'<text x="{x}" y="{y + row["height"] + 50}" class="tiny">sources: {escape(", ".join(panel.relative_image_path for panel in row["panels"]))}</text>')
    return "\n".join(parts)


def render_orthographic_panel(panel, x, y, width, height):
    if panel.source_kind == "roof":
        return render_roof_panel(panel, x, y, width, height)
    parts = [
        f'<rect class="wall" x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}"/>',
        grid_lines_for_box(x, y, width, height, panel.width_meters, panel.estimated_height_meters),
    ]
    for opening in panel.opening_layout:
        ox = x + width * (opening["xMeters"] / panel.width_meters)
        ow = width * (opening["widthMeters"] / panel.width_meters)
        oh = height * (opening["heightMeters"] / panel.estimated_height_meters)
        oy = y + height - height * ((opening["zMeters"] + opening["heightMeters"]) / panel.estimated_height_meters)
        klass = "door" if opening["kind"] == "door" else "window"
        parts.append(f'<rect class="{klass}" x="{ox:.1f}" y="{oy:.1f}" width="{ow:.1f}" height="{oh:.1f}"/>')
        parts.append(f'<text class="openingText" x="{ox + 3:.1f}" y="{oy + 12:.1f}">{escape(opening["id"])}</text>')
    for feature in panel.wall_features:
        fx = x + width * (feature["xMeters"] / panel.width_meters)
        fw = width * (feature["widthMeters"] / panel.width_meters)
        fh = height * (feature["heightMeters"] / panel.estimated_height_meters)
        fy = y + height - height * ((feature["zMeters"] + feature["heightMeters"]) / panel.estimated_height_meters)
        parts.append(f'<rect class="feature" x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}"/>')
        parts.append(f'<text class="openingText" x="{fx + 3:.1f}" y="{fy + 12:.1f}">{escape(feature["id"])}</text>')
    for feature in panel.stair_features:
        fx = x + width * (feature["xMeters"] / panel.width_meters)
        fw = width * (feature["widthMeters"] / panel.width_meters)
        fh = height * (feature["heightMeters"] / panel.estimated_height_meters)
        fy = y + height - height * ((feature["zMeters"] + feature["heightMeters"]) / panel.estimated_height_meters)
        parts.append(f'<rect class="stair" x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}"/>')
        parts.append(f'<text class="openingText" x="{fx + 3:.1f}" y="{fy + 12:.1f}">{escape(feature["id"])}</text>')
    parts.append(f'<text x="{x + 4:.1f}" y="{y + height - 5:.1f}" class="tiny">{escape(panel.title)}</text>')
    return "\n".join(parts)


def render_roof_panel(panel, x, y, width, height):
    plan_height = height * 0.58
    profile_y = y + plan_height + 10
    profile_height = max(76, height - plan_height - 24)
    parts = [
        f'<rect class="roof" x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}"/>',
        grid_lines_for_box(x, y, width, plan_height, panel.width_meters, panel.estimated_height_meters),
        f'<line x1="{x + width * 0.12:.1f}" y1="{y + plan_height * 0.5:.1f}" x2="{x + width * 0.88:.1f}" y2="{y + plan_height * 0.5:.1f}" stroke="#555" stroke-width="1.2" stroke-dasharray="6 5"/>',
        f'<text x="{x + 6:.1f}" y="{y + 14:.1f}" class="tiny">roof zones from satellite reference</text>',
        f'<text x="{x + 4:.1f}" y="{y + height - 5:.1f}" class="tiny">{escape(panel.title)} | {escape(primitive_summary(panel))}</text>',
    ]
    for zone in panel.roof_zones:
        parts.extend(render_roof_zone_overlay(zone, x, y, width, plan_height))
    for zone in panel.roof_zones:
        parts.extend(render_roof_zone_lines(zone, x, y, width, plan_height))
    parts.extend(render_roof_profiles(panel, x + 6, profile_y, width - 12, profile_height))
    return "\n".join(parts)


def render_roof_profiles(panel, x, y, width, height):
    profiles = panel.roof_profiles or {}
    roles = ["front", "rear", "left-side", "right-side"]
    cell_gap = 8
    cell_width = (width - cell_gap) / 2
    cell_height = (height - cell_gap) / 2
    parts = [f'<text x="{x:.1f}" y="{y - 3:.1f}" class="tiny">3D roof elevation profiles</text>']
    for index, role in enumerate(roles):
        cell_x = x + (index % 2) * (cell_width + cell_gap)
        cell_y = y + (index // 2) * (cell_height + cell_gap)
        profile = profiles.get(role, {})
        parts.extend(render_roof_profile(role, profile, cell_x, cell_y, cell_width, cell_height))
    return parts


def render_roof_profile(role, profile, x, y, width, height):
    baseline = y + height - 10
    parts = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" fill="#fff" fill-opacity="0.52" stroke="#777" stroke-width=".7"/>',
        f'<line x1="{x + 6:.1f}" y1="{baseline:.1f}" x2="{x + width - 6:.1f}" y2="{baseline:.1f}" stroke="#333" stroke-width="1"/>',
        f'<text x="{x + 4:.1f}" y="{y + 11:.1f}" class="tiny">{escape(role)}</text>',
    ]
    for shape in profile.get("shapes", []):
        color = escape(shape.get("color", "#8ecae6"))
        points = []
        for point in shape.get("points", []):
            px = x + width * clamp_fraction(point[0])
            py = baseline - (height - 22) * clamp_fraction(point[1])
            points.append((px, py))
        if len(points) >= 3:
            path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            parts.append(f'<polygon points="{path}" fill="{color}" fill-opacity="0.34" stroke="#1d3557" stroke-width="1.1" stroke-linejoin="round"/>')
            parts.append(f'<text class="openingText" x="{points[0][0] + 3:.1f}" y="{points[0][1] + 12:.1f}">{escape(shape.get("id", ""))}</text>')
        elif len(points) == 2:
            path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="1.8" stroke-linecap="round"/>')
    return parts


def render_roof_zone_overlay(zone, x, y, width, height):
    color = escape(zone.get("color", "#8ecae6"))
    shape = zone.get("roofPlanShape", {})
    kind = shape.get("kind", "rect")
    parts = []
    if kind == "line":
        points = roof_points(shape.get("points", []), x, y, width, height)
        if len(points) >= 2:
            path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
            parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/>')
            parts.append(roof_zone_label(zone, points[0][0], points[0][1]))
        return parts
    if kind == "markers":
        for index, marker in enumerate(shape.get("markers", [])):
            cx = x + width * clamp_fraction(marker.get("x", 0.0))
            cy = y + height * clamp_fraction(marker.get("y", 0.0))
            mw = width * clamp_fraction(marker.get("width", 0.035))
            mh = height * clamp_fraction(marker.get("height", 0.035))
            rotate = float(marker.get("rotate", 0.0))
            parts.append(f'<rect x="{cx - mw / 2:.1f}" y="{cy - mh / 2:.1f}" width="{mw:.1f}" height="{mh:.1f}" fill="{color}" fill-opacity="0.46" stroke="#1d3557" stroke-width="1.1" transform="rotate({rotate:.1f} {cx:.1f} {cy:.1f})"/>')
            parts.append(roof_zone_label({"id": f'{zone["id"]}.{index + 1}'}, cx + mw * 0.35, cy - mh * 0.35))
        return parts
    if kind == "polygon":
        points = roof_points(shape.get("points", []), x, y, width, height)
    else:
        points = roof_rect_points(zone, x, y, width, height)
    if len(points) >= 3:
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        parts.append(f'<polygon points="{path}" fill="{color}" fill-opacity="0.24" stroke="#1d3557" stroke-width="1.2" stroke-linejoin="round"/>')
        cx = sum(point[0] for point in points) / len(points)
        cy = sum(point[1] for point in points) / len(points)
        parts.append(roof_zone_label(zone, cx, cy))
    return parts


def roof_points(points, x, y, width, height):
    return [(x + width * clamp_fraction(point[0]), y + height * clamp_fraction(point[1])) for point in points]


def roof_rect_points(zone, x, y, width, height):
    x0 = clamp_fraction(zone["xFraction"])
    y0 = clamp_fraction(zone["yFraction"])
    x1 = clamp_fraction(x0 + zone["widthFraction"])
    y1 = clamp_fraction(y0 + zone["heightFraction"])
    return roof_points([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], x, y, width, height)


def roof_zone_label(zone, x, y):
    return f'<text class="openingText" x="{x + 3:.1f}" y="{y + 12:.1f}">{escape(zone["id"])}</text>'


def render_roof_zone_lines(zone, x, y, width, height):
    parts = []
    for line in zone.get("roofLines", []):
        points = roof_points(line.get("points", []), x, y, width, height)
        if len(points) < 2:
            continue
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        kind = line.get("kind", "ridge")
        dash = " stroke-dasharray=\"5 4\"" if kind == "valley" else ""
        stroke = "#111" if kind == "ridge" else "#345"
        parts.append(f'<polyline points="{path}" fill="none" stroke="{stroke}" stroke-width="1.5"{dash} stroke-linecap="round" stroke-linejoin="round"/>')
    return parts


def grid_lines_for_box(x, y, width, height, width_meters, height_meters):
    lines = []
    for meter in range(5, int(width_meters), 5):
        gx = x + width * meter / width_meters
        lines.append(f'<line class="grid" x1="{gx:.1f}" y1="{y:.1f}" x2="{gx:.1f}" y2="{y + height:.1f}"/>')
    for meter in range(5, int(height_meters), 5):
        gy = y + height - height * meter / height_meters
        lines.append(f'<line class="grid" x1="{x:.1f}" y1="{gy:.1f}" x2="{x + width:.1f}" y2="{gy:.1f}"/>')
    return "\n".join(lines)


def grid_lines(x, y, width, height, width_meters, height_meters, pixels_per_meter):
    lines = []
    meter_step = 5
    for meter in range(meter_step, int(width_meters), meter_step):
        gx = x + width * (meter / width_meters)
        lines.append(f'<line class="guide" x1="{gx:.1f}" y1="{y:.1f}" x2="{gx:.1f}" y2="{y + height:.1f}"/>')
    for meter in range(meter_step, int(height_meters), meter_step):
        gy = y + height - height * (meter / height_meters)
        lines.append(f'<line class="guide" x1="{x:.1f}" y1="{gy:.1f}" x2="{x + width:.1f}" y2="{gy:.1f}"/>')
    scale_width = min(width, 5 * pixels_per_meter)
    lines.append(f'<line x1="{x:.1f}" y1="{y + height + 8:.1f}" x2="{x + scale_width:.1f}" y2="{y + height + 8:.1f}" stroke="#111" stroke-width="2"/>')
    lines.append(f'<text x="{x + scale_width + 6:.1f}" y="{y + height + 11:.1f}" class="tiny">5m scale</text>')
    return "\n".join(lines)


def opening_overlay(panel, x, y, width, height):
    if not panel.opening_layout:
        return ""
    parts = [
        f'<text x="{x + 6:.1f}" y="{y + 14:.1f}" class="legend">blue=windows orange=doors purple=wall green=stairs/platform</text>',
    ]
    for opening in panel.opening_layout:
        ox = x + width * (opening["xMeters"] / panel.width_meters)
        ow = width * (opening["widthMeters"] / panel.width_meters)
        oh = height * (opening["heightMeters"] / panel.estimated_height_meters)
        oy = y + height - height * ((opening["zMeters"] + opening["heightMeters"]) / panel.estimated_height_meters)
        klass = "door" if opening["kind"] == "door" else "window"
        label_x = ox + max(2, ow * 0.5 - 8)
        label_y = oy + max(11, oh * 0.5 + 3)
        parts.extend(
            [
                f'<rect class="{klass}" x="{ox:.1f}" y="{oy:.1f}" width="{ow:.1f}" height="{oh:.1f}"/>',
                f'<text class="openingText" x="{label_x:.1f}" y="{label_y:.1f}">{escape(opening["id"])}</text>',
            ]
        )
    for feature in panel.wall_features:
        fx = x + width * (feature["xMeters"] / panel.width_meters)
        fw = width * (feature["widthMeters"] / panel.width_meters)
        fh = height * (feature["heightMeters"] / panel.estimated_height_meters)
        fy = y + height - height * ((feature["zMeters"] + feature["heightMeters"]) / panel.estimated_height_meters)
        parts.extend(
            [
                f'<rect class="feature" x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}"/>',
                f'<text class="openingText" x="{fx + 3:.1f}" y="{fy + 12:.1f}">{escape(feature["id"])}</text>',
            ]
        )
    for feature in panel.stair_features:
        fx = x + width * (feature["xMeters"] / panel.width_meters)
        fw = width * (feature["widthMeters"] / panel.width_meters)
        fh = height * (feature["heightMeters"] / panel.estimated_height_meters)
        fy = y + height - height * ((feature["zMeters"] + feature["heightMeters"]) / panel.estimated_height_meters)
        parts.extend(
            [
                f'<rect class="stair" x="{fx:.1f}" y="{fy:.1f}" width="{fw:.1f}" height="{fh:.1f}"/>',
                f'<text class="openingText" x="{fx + 3:.1f}" y="{fy + 12:.1f}">{escape(feature["id"])}</text>',
            ]
        )
    return "\n".join(parts)


def reference_plan(manifest, rules, panels, auxiliary_panels, layout, pixels_per_meter, output_dir):
    return {
        "building": manifest.get("building"),
        "displayName": manifest.get("displayName"),
        "generatedKind": "scaled-reference-board",
        "pixelsPerMeter": pixels_per_meter,
        "modelingRecipe": modeling_recipe(panels, auxiliary_panels, rules),
        "sheet": {
            "widthPx": layout["width"],
            "heightPx": layout["height"],
        },
        "panels": [serialize_panel(panel, output_dir) for panel in panels],
        "auxiliaryPanels": [serialize_panel(panel, output_dir) for panel in auxiliary_panels],
        "elevations": elevation_groups(panels, auxiliary_panels),
    }


def serialize_panel(panel, output_dir):
    return (
            {
                "id": panel.panel_id,
                "title": panel.title,
                "wallId": panel.wall_id,
                "orientation": panel.orientation,
                "sourceKind": panel.source_kind,
                "elevationRole": panel.elevation_role,
                "sourceImage": panel.relative_image_path,
                "imagePath": os.path.relpath(panel.image_path, output_dir),
                "widthMeters": panel.width_meters,
                "estimatedHeightMeters": panel.estimated_height_meters,
                "referenceStatus": panel.reference_status,
                "qualityStatus": panel.quality_status,
                "primitiveStatus": primitive_status(panel),
                "windows": panel.windows,
                "doors": panel.doors,
                "countMethod": panel.count_method,
                "notes": panel.notes,
                "countInference": count_inference_for_panel(panel),
                "layoutIssues": panel_layout_issues(panel),
                "openingLayout": list(panel.opening_layout),
                "majorWallFeatures": list(panel.wall_features),
                "stairFeatures": list(panel.stair_features),
                "roofZones": list(panel.roof_zones),
                "roofElevationPlans": roof_elevation_plans(panel) if panel.source_kind == "roof" else {},
                "roofElevationProfiles": panel.roof_profiles or {},
                "primitiveHints": list(panel.primitive_hints),
            }
    )


def orthographic_plan(manifest, rules, panels, auxiliary_panels, pixels_per_meter, output_dir):
    groups = elevation_groups(panels, auxiliary_panels)
    return {
        "building": manifest.get("building"),
        "displayName": manifest.get("displayName"),
        "generatedKind": "orthographic-elevation-reference",
        "pixelsPerMeter": pixels_per_meter,
        "perspectiveHandling": {
            "photoInputs": "Street View and photo references may be oblique or perspective-distorted.",
            "modelingSurface": "Use the normalized orthographic diagrams for wall/window/door placement.",
            "rectificationPolicy": "Do not claim a photo is perpendicular unless control points or an approved elevation drawing exist.",
            "pixelWarpPolicy": "Perspective warping requires facade control points in modeling-rules. Without control points, the sheet uses rule-derived orthographic geometry and symmetry inference.",
            "requiredControlPoints": ["top-left", "top-right", "bottom-right", "bottom-left"],
        },
        "elevations": groups,
        "panels": [serialize_panel(panel, output_dir) for panel in panels],
        "auxiliaryPanels": [serialize_panel(panel, output_dir) for panel in auxiliary_panels],
    }


def elevation_groups(panels, auxiliary_panels):
    roles = ["front", "rear", "left-side", "right-side", "roof", "addition", "unassigned"]
    groups = {
        role: {
            "role": role,
            "label": role.replace("-", " ").title(),
            "panelIds": [],
            "sourceImages": [],
            "openingCounts": {"windows": 0, "doors": 0},
            "countProof": [],
        }
        for role in roles
    }
    for panel in panels + auxiliary_panels:
        role = panel.elevation_role or "unassigned"
        if role not in groups:
            role = "unassigned"
        groups[role]["panelIds"].append(panel.panel_id)
        groups[role]["sourceImages"].append(panel.relative_image_path)
        groups[role]["openingCounts"]["windows"] += len([item for item in panel.opening_layout if item["kind"] == "window"])
        groups[role]["openingCounts"]["doors"] += len([item for item in panel.opening_layout if item["kind"] == "door"])
        proof = count_proof(panel)
        if proof:
            groups[role]["countProof"].append(proof)
    return {role: group for role, group in groups.items() if group["panelIds"]}


def modeling_recipe(panels, auxiliary_panels, rules):
    all_panels = panels + auxiliary_panels
    tower_panel_ids = [panel.panel_id for panel in auxiliary_panels if panel.source_kind == "tower" and panel.reference_status.startswith("approved")]
    tower_candidates = unique_hints(all_panels, "tower")
    if not tower_candidates and rules.get("tower"):
        tower_candidates = [hint["primitive"] for hint in tower_primitives({}, rules["tower"]) if hint.get("primitive") != "context_only_do_not_model"]
    return {
        "referenceGate": "Only use panels whose referenceStatus starts with approved. needs-review panels require inspection before modeling.",
        "wallDetail": {
            "module": "major_wall_detail_module",
            "primitive": "quad_grid_wall",
            "rules": [
                "openings are cells in the wall mesh",
                "windows and doors must have edge loops",
                "do not add floating opening panels",
                "check major wall features beyond windows, doors, and roofs",
            ],
            "panelIds": [panel.panel_id for panel in panels],
            "featureCount": sum(len(panel.wall_features) for panel in panels),
        },
        "windows": {
            "module": "window_module",
            "primitive": "recessed_rectangular_face_opening",
            "totalPlanned": sum(panel.windows for panel in panels),
        },
        "doors": {
            "module": "door_module",
            "primitive": "recessed_rectangular_or_arched_face_opening",
            "totalPlanned": sum(panel.doors for panel in panels),
        },
        "roof": {
            "module": "roof_module",
            "candidatePrimitives": unique_hints(all_panels, "roof", approved_only=True),
            "reviewPrimitives": unique_hints(all_panels, "roof", approved_only=False, review_only=True),
            "panelIds": [panel.panel_id for panel in auxiliary_panels if panel.source_kind == "roof"],
            "zoneCount": sum(len(panel.roof_zones) for panel in auxiliary_panels if panel.source_kind == "roof"),
            "rules": [
                "use satellite roof zones as top-down source of truth",
                "split roofs into named planes or masses before modeling",
                "derive front, rear, left-side, and right-side roof plans from the same roof zones",
            ],
        },
        "towerChimney": {
            "module": "chimney_tower_module",
            "candidatePrimitives": unique_hints(all_panels, "tower", approved_only=True) + unique_hints(all_panels, "chimney", approved_only=True),
            "reviewPrimitives": unique_hints(all_panels, "tower", approved_only=False, review_only=True) + unique_hints(all_panels, "chimney", approved_only=False, review_only=True),
            "ruleDerivedPrimitives": tower_candidates if not tower_panel_ids else [],
            "panelIds": tower_panel_ids,
            "blockedPanelIds": [panel.panel_id for panel in auxiliary_panels if panel.source_kind == "tower" and not panel.reference_status.startswith("approved")],
        },
        "stairs": {
            "module": "staircase_module",
            "candidatePrimitives": unique_hints(all_panels, "stair"),
            "featureCount": sum(len(panel.stair_features) for panel in panels),
            "panelIds": [panel.panel_id for panel in panels if panel.stair_features],
        },
        "symmetry": {
            "module": "symmetry_module",
            "candidatePrimitives": ["mirror_opening_positions", "paired_facade_counts"],
        },
        "inspect": {
            "module": "inspect_module",
            "checks": ["quad_cleanliness", "loose_geometry", "support_overlap", "reference_traceability"],
        },
    }


def opening_plan_primitives(plan):
    hints = [
        primitive_hint(
            "wall",
            "major_wall_detail_module",
            "quad_grid_wall",
            status="verified",
            confidence=0.98,
            evidence="modeling-rules wallOpeningPlans",
            reason="reference-backed exterior facade with integrated openings",
        )
    ]
    if int(plan.get("windows", 0)):
        hints.append(
            primitive_hint(
                "window",
                "window_module",
                plan.get("windowPrimitive", "recessed_rectangular_face_opening"),
                status="verified",
                confidence=0.9,
                evidence="modeling-rules window count and approved wall source",
                count=int(plan.get("windows", 0)),
                mustBeIntegratedWallFace=True,
            )
        )
    if int(plan.get("doors", 0)):
        hints.append(
            primitive_hint(
                "door",
                "door_module",
                plan.get("doorPrimitive", "recessed_rectangular_or_arched_face_opening"),
                status="verified",
                confidence=0.84,
                evidence="modeling-rules door count and approved wall source",
                count=int(plan.get("doors", 0)),
                mustBeIntegratedWallFace=True,
            )
        )
    count_method = plan.get("countMethod", "")
    if "symmetry" in plan.get("notes", "").lower() or "symmetry" in count_method:
        hints.append(
            primitive_hint(
                "symmetry",
                "symmetry_module",
                "paired_facade_counts",
                status="inferred",
                confidence=0.72,
                evidence="repeated openings in modeling rules",
                reason="large repeated window rhythm should be mirrored or evenly spaced from reference",
                requiresReview=True,
            )
        )
    return hints


def opening_layout_for_plan(plan, wall_width_meters, wall_height_meters, reference):
    if plan.get("openingLayout"):
        return annotate_explicit_openings(plan["openingLayout"])
    openings = []
    windows = int(plan.get("windows", 0))
    doors = int(plan.get("doors", 0))
    floors = int(plan.get("floors", 3))
    floor_height = float(plan.get("floorHeightMeters", max(3.2, wall_height_meters / max(floors + 0.45, 1))))
    sill_height = float(plan.get("windowSillMeters", 1.45))
    window_width = float(plan.get("windowWidthMeters", min(1.25, max(0.75, wall_width_meters * 0.055))))
    window_height = float(plan.get("windowHeightMeters", 2.15))
    door_width = float(plan.get("doorWidthMeters", 1.25))
    door_height = float(plan.get("doorHeightMeters", 2.8))

    if windows:
        if plan.get("windowRows"):
            row_counts = [value if isinstance(value, list) else int(value) for value in plan["windowRows"]]
            floors = len(row_counts)
        else:
            columns = max(1, round(windows / max(floors, 1)))
            remaining = windows
            row_counts = []
            for floor in range(floors):
                row_count = min(columns, remaining)
                remaining -= row_count
                if floor == floors - 1 and remaining > 0:
                    row_count += remaining
                    remaining = 0
                row_counts.append(row_count)
        window_id = 1
        grid_columns = int(plan.get("windowGridColumns", max([len(value) if isinstance(value, list) else int(value) for value in row_counts] or [1])))
        for floor, row_count in enumerate(row_counts):
            if isinstance(row_count, list):
                column_slots = [int(value) for value in row_count]
            else:
                column_slots = list(range(1, int(row_count) + 1))
                grid_columns = max(grid_columns, int(row_count))
            for column_slot in column_slots:
                center_x = wall_width_meters * (column_slot / (grid_columns + 1))
                base_z = sill_height + floor * floor_height
                openings.append(
                    opening_record(
                        f"W{window_id:02d}",
                        "window",
                        center_x,
                        base_z,
                        window_width,
                        min(window_height, wall_height_meters - base_z - 0.55),
                        wall_width_meters,
                        wall_height_meters,
                        reference,
                        position_status="row-derived",
                    )
                )
                window_id += 1

    if doors:
        explicit_door_positions = plan.get("doorPositions")
        door_positions = explicit_door_positions or ([(index + 1) / (doors + 1) for index in range(doors)])
        door_position_status = plan.get("doorPositionStatus") or ("explicit-unverified" if explicit_door_positions else "default-needs-review")
        for index, position in enumerate(door_positions[:doors]):
            openings.append(
                opening_record(
                    f"D{index + 1:02d}",
                    "door",
                    wall_width_meters * float(position),
                    0.0,
                    door_width,
                    door_height,
                    wall_width_meters,
                    wall_height_meters,
                    reference,
                    position_status=door_position_status,
                )
            )
    return openings


def elevation_role_for_panel(panel_id, orientation, plan, rules):
    if plan.get("elevationRole"):
        return plan["elevationRole"]
    role_map = rules.get("elevationRoles", {})
    for role, values in role_map.items():
        if panel_id in values or orientation in values:
            return role
    text = f"{panel_id} {orientation} {plan.get('notes', '')}".lower()
    front_orientation = orientation_from_notes(rules, "front") or "west"
    mapping = cardinal_role_mapping(front_orientation)
    detected_orientation = orientation or orientation_from_text(panel_id)
    if detected_orientation:
        return mapping.get(detected_orientation, "unassigned")
    if "front" in text:
        return "front"
    if "rear" in text or "back" in text:
        return "rear"
    if "left" in text:
        return "left-side"
    if "right" in text:
        return "right-side"
    detected_orientation = orientation_from_text(text)
    return mapping.get(detected_orientation, "unassigned")


def orientation_from_text(text):
    for orientation in ["northwest", "northeast", "southwest", "southeast", "north", "east", "south", "west"]:
        if orientation in text:
            return orientation
    return ""


def orientation_from_notes(rules, needle):
    wall_plans = rules.get("windowsAndDoors", {}).get("wallOpeningPlans", {})
    for wall_id, plan in wall_plans.items():
        text = f"{wall_id} {plan.get('notes', '')}".lower()
        if needle in text:
            from_id = orientation_from_text(wall_id)
            if from_id:
                return base_orientation(from_id)
            for orientation in ["north", "east", "south", "west"]:
                if orientation in text:
                    return orientation
    return ""


def base_orientation(orientation):
    for cardinal in ["north", "east", "south", "west"]:
        if orientation.startswith(cardinal):
            return cardinal
    return orientation


def cardinal_role_mapping(front_orientation):
    if front_orientation == "west":
        return {"west": "front", "east": "rear", "south": "left-side", "north": "right-side", "southwest": "front", "northwest": "front", "southeast": "rear", "northeast": "rear"}
    if front_orientation == "east":
        return {"east": "front", "west": "rear", "north": "left-side", "south": "right-side", "northeast": "front", "southeast": "front", "northwest": "rear", "southwest": "rear"}
    if front_orientation == "south":
        return {"south": "front", "north": "rear", "east": "left-side", "west": "right-side", "southeast": "front", "southwest": "front", "northeast": "rear", "northwest": "rear"}
    return {"north": "front", "south": "rear", "west": "left-side", "east": "right-side", "northwest": "front", "northeast": "front", "southwest": "rear", "southeast": "rear"}


def opening_counts_for_panels(panels):
    return {
        "windows": sum(len([item for item in panel.opening_layout if item["kind"] == "window"]) for panel in panels),
        "doors": sum(len([item for item in panel.opening_layout if item["kind"] == "door"]) for panel in panels),
    }


def count_proof(panel):
    if not panel.opening_layout:
        return ""
    pieces = []
    for kind in ["window", "door"]:
        openings = [item for item in panel.opening_layout if item["kind"] == kind]
        if not openings:
            continue
        rows = grouped_values([item["zMeters"] for item in openings])
        row_counts = []
        for z_value in rows:
            row_counts.append(len([item for item in openings if abs(item["zMeters"] - z_value) < 0.05]))
        if row_counts and len(set(row_counts)) == 1:
            row_label = "row" if len(rows) == 1 else "rows"
            pieces.append(f'{panel.panel_id}: {kind}s {len(rows)} {row_label} x {row_counts[0]} = {len(openings)}')
        elif row_counts:
            pieces.append(f'{panel.panel_id}: {kind}s rows {"+".join(str(value) for value in row_counts)} = {len(openings)}')
    return "; ".join(pieces)


def count_inference_for_panel(panel):
    issues = panel_layout_issues(panel)
    counts = opening_counts_for_panels([panel])
    return {
        "method": panel.count_method or ("approved-rule-layout" if panel.reference_status.startswith("approved") else "needs-review"),
        "usesSymmetry": any(hint.get("target") == "symmetry" for hint in panel.primitive_hints),
        "windows": counts["windows"],
        "doors": counts["doors"],
        "proof": count_proof(panel),
        "layoutValid": not issues,
        "layoutIssues": issues,
        "warning": "Doors and windows are counted separately; multiplication proofs never combine them.",
    }


def opening_layout_issues(openings):
    issues = []
    for opening in openings:
        if opening["kind"] == "door" and opening.get("positionStatus") in {"default-needs-review", "explicit-unverified"}:
            issues.append(
                {
                    "type": "door-position-needs-review",
                    "a": opening["id"],
                    "kinds": [opening["kind"]],
                    "positionStatus": opening.get("positionStatus"),
                }
            )
    for left_index, left in enumerate(openings):
        for right in openings[left_index + 1 :]:
            if not openings_overlap(left, right):
                continue
            issues.append(
                {
                    "type": "opening-overlap",
                    "a": left["id"],
                    "b": right["id"],
                    "kinds": [left["kind"], right["kind"]],
                }
            )
    return issues


def panel_layout_issues(panel):
    issues = opening_layout_issues(panel.opening_layout)
    counts = opening_counts_for_panels([panel])
    if panel.windows != counts["windows"]:
        issues.append(
            {
                "type": "window-count-mismatch",
                "expected": panel.windows,
                "actual": counts["windows"],
            }
        )
    if panel.doors != counts["doors"]:
        issues.append(
            {
                "type": "door-count-mismatch",
                "expected": panel.doors,
                "actual": counts["doors"],
            }
        )
    for feature in panel.wall_features:
        if feature.get("status") not in {"observed", "verified"}:
            issues.append(
                {
                    "type": "major-wall-feature-needs-review",
                    "a": feature.get("id"),
                    "kind": feature.get("kind"),
                    "status": feature.get("status"),
                }
            )
    for feature in panel.stair_features:
        if feature.get("status") not in {"observed", "verified"}:
            issues.append(
                {
                    "type": "stair-platform-feature-needs-review",
                    "a": feature.get("id"),
                    "kind": feature.get("kind"),
                    "status": feature.get("status"),
                }
            )
    return issues


def openings_overlap(a, b, epsilon=0.03):
    ax0 = a["xMeters"]
    ax1 = a["xMeters"] + a["widthMeters"]
    az0 = a["zMeters"]
    az1 = a["zMeters"] + a["heightMeters"]
    bx0 = b["xMeters"]
    bx1 = b["xMeters"] + b["widthMeters"]
    bz0 = b["zMeters"]
    bz1 = b["zMeters"] + b["heightMeters"]
    return ax0 < bx1 - epsilon and ax1 > bx0 + epsilon and az0 < bz1 - epsilon and az1 > bz0 + epsilon


def grouped_values(values, epsilon=0.05):
    groups = []
    for value in sorted(values):
        if not groups or abs(groups[-1] - value) > epsilon:
            groups.append(value)
    return groups


def opening_record(opening_id, kind, center_x, z0, width, height, wall_width, wall_height, reference, position_status="generated"):
    width = max(0.15, min(width, wall_width))
    height = max(0.15, min(height, wall_height))
    x0 = max(0.0, min(wall_width - width, center_x - width * 0.5))
    z0 = max(0.0, min(wall_height - height, z0))
    return {
        "id": opening_id,
        "kind": kind,
        "xMeters": round(x0, 3),
        "zMeters": round(z0, 3),
        "widthMeters": round(width, 3),
        "heightMeters": round(height, 3),
        "centerFraction": round((x0 + width * 0.5) / wall_width, 4) if wall_width else 0.0,
        "sourceImage": reference,
        "positionStatus": position_status,
        "mustBeIntegratedWallFace": True,
    }


def annotate_explicit_openings(openings):
    annotated = []
    for opening in openings:
        copy = dict(opening)
        if copy.get("kind") == "door":
            copy.setdefault("positionStatus", "explicit")
        else:
            copy.setdefault("positionStatus", "explicit")
        annotated.append(copy)
    return annotated


def annotate_wall_features(features, reference):
    annotated = []
    for index, feature in enumerate(features):
        copy = dict(feature)
        copy.setdefault("id", f"F{index + 1:02d}")
        copy.setdefault("kind", "major_wall_feature")
        copy.setdefault("primitive", "raised_or_recessed_wall_detail")
        copy.setdefault("status", "needs-review")
        copy.setdefault("sourceImage", reference)
        copy.setdefault("module", "major_wall_detail_module")
        copy.setdefault("mustBeIntegratedOrSupportedWallDetail", True)
        for key in ["xMeters", "zMeters", "widthMeters", "heightMeters"]:
            copy[key] = round(float(copy.get(key, 0.0)), 3)
        annotated.append(copy)
    return annotated


def annotate_stair_features(features, reference):
    annotated = []
    for index, feature in enumerate(features):
        copy = dict(feature)
        copy.setdefault("id", f"S{index + 1:02d}")
        copy.setdefault("kind", "entry_stair_or_platform")
        copy.setdefault("primitive", "stacked_step_blocks_with_landing")
        copy.setdefault("status", "needs-review")
        copy.setdefault("sourceImage", reference)
        copy.setdefault("module", "staircase_module")
        copy.setdefault("mustTouchGroundAndDoorThreshold", True)
        for key in ["xMeters", "zMeters", "widthMeters", "heightMeters"]:
            copy[key] = round(float(copy.get(key, 0.0)), 3)
        annotated.append(copy)
    return annotated


def annotate_roof_zones(zones, reference):
    annotated = []
    for index, zone in enumerate(zones):
        copy = dict(zone)
        copy.setdefault("id", f"R{index + 1:02d}")
        copy.setdefault("kind", "roof_zone")
        copy.setdefault("primitive", "classify_from_satellite_zone")
        copy.setdefault("status", "needs-review")
        copy.setdefault("sourceImage", reference)
        copy.setdefault("module", "roof_module")
        copy.setdefault("mustUseSatelliteReference", True)
        copy.setdefault("visibleElevations", [])
        copy.setdefault("color", "#8ecae6")
        for key in ["xFraction", "yFraction", "widthFraction", "heightFraction"]:
            copy[key] = clamp_fraction(copy.get(key, 0.0))
        annotated.append(copy)
    return annotated


def annotate_roof_profiles(profiles, reference):
    annotated = {}
    for role, profile in profiles.items():
        copy = dict(profile)
        copy.setdefault("sourceImage", reference)
        copy.setdefault("module", "roof_module")
        copy.setdefault("status", "needs-review")
        shapes = []
        for shape in copy.get("shapes", []):
            shape_copy = dict(shape)
            shape_copy.setdefault("id", "roof-profile-shape")
            shape_copy.setdefault("kind", "roof_profile_shape")
            shape_copy.setdefault("primitive", "profile_polygon")
            shape_copy.setdefault("sourceImage", reference)
            shape_copy.setdefault("status", copy.get("status", "needs-review"))
            shapes.append(shape_copy)
        copy["shapes"] = shapes
        annotated[role] = copy
    return annotated


def roof_elevation_plans(panel):
    if not panel.roof_zones:
        return {}
    plans = {}
    for role, axis in {
        "front": "y",
        "rear": "y",
        "left-side": "x",
        "right-side": "x",
    }.items():
        zones = []
        for zone in panel.roof_zones:
            visible = zone.get("visibleElevations", [])
            if visible and role not in visible:
                continue
            start = zone["xFraction"] if axis == "x" else zone["yFraction"]
            span = zone["widthFraction"] if axis == "x" else zone["heightFraction"]
            zones.append(
                {
                    "id": zone["id"],
                    "kind": zone["kind"],
                    "primitive": zone["primitive"],
                    "startFraction": round(start, 4),
                    "spanFraction": round(span, 4),
                    "status": zone["status"],
                    "sourceImage": zone["sourceImage"],
                }
            )
        plans[role] = {
            "source": "derived-from-satellite-roof-zones",
            "axis": "west-east" if axis == "x" else "north-south",
            "zones": sorted(zones, key=lambda item: item["startFraction"]),
        }
    return plans


def clamp_fraction(value):
    return round(max(0.0, min(1.0, float(value))), 4)


def wall_reference_primitives(wall, approved):
    return [
        primitive_hint(
            "wall",
            "major_wall_detail_module",
            "quad_grid_wall",
            status="verified" if approved else "needs-review",
            confidence=0.96 if approved else 0.45,
            evidence="approved wall source" if approved else "saved wall image pending review",
            widthMeters=wall.get("lengthMeters"),
            referenceRequired=not approved,
            requiresReview=not approved,
        )
    ]


def roof_primitives(roof_rules):
    roof_type = roof_rules.get("type")
    hints = []
    if roof_type == "hip" or roof_rules.get("allowHipRoofZones"):
        hints.append(roof_hint("hip_prism_roof", roof_type, roof_rules, "hip roof type or allowed hip zone"))
    if roof_type == "gable" or roof_rules.get("allowPrismRoofZones"):
        hints.append(roof_hint("gable_prism_roof", roof_type, roof_rules, "gable/prism roof type or allowed prism zone"))
    if roof_type == "flat" or roof_rules.get("allowFlatRoofZones"):
        hints.append(roof_hint("flat_roof_slab", roof_type, roof_rules, "flat roof type or allowed flat zone"))
    if roof_rules.get("noSingleBlanketRoofSlab"):
        hints.append(
            primitive_hint(
                "roof",
                "roof_module",
                "split_roof_zones",
                status="required",
                confidence=1.0,
                evidence="modeling-rules noSingleBlanketRoofSlab",
                required=True,
            )
        )
    if roof_rules.get("requiredDetailKinds"):
        for kind in roof_rules["requiredDetailKinds"]:
            if "chimney" in kind:
                hints.append(
                    primitive_hint(
                        "chimney",
                        "chimney_tower_module",
                        "rectangular_chimney_shaft_with_cap",
                        status="required",
                        confidence=0.74,
                        evidence=f"modeling-rules requiredDetailKinds includes {kind}",
                        required=True,
                        requiresReview=True,
                    )
                )
            if "dormer" in kind:
                hints.append(
                    primitive_hint(
                        "roof",
                        "roof_module",
                        "dormer_prism",
                        status="required",
                        confidence=0.76,
                        evidence=f"modeling-rules requiredDetailKinds includes {kind}",
                        required=True,
                        requiresReview=True,
                    )
                )
            if "pediment" in kind or "gable" in kind:
                hints.append(
                    primitive_hint(
                        "roof",
                        "roof_module",
                        "front_gable_pediment_prism",
                        status="required",
                        confidence=0.78,
                        evidence=f"modeling-rules requiredDetailKinds includes {kind}",
                        required=True,
                        requiresReview=True,
                    )
                )
    return hints or [
        primitive_hint(
            "roof",
            "roof_module",
            "classify_from_roof_reference",
            status="unclassified",
            confidence=0.0,
            evidence="no roof primitive rule found",
            requiresReview=True,
        )
    ]


def tower_primitives(reference_item, tower_rules):
    if reference_item.get("notApprovedFor"):
        return [
            primitive_hint(
                "tower",
                "chimney_tower_module",
                "context_only_do_not_model",
                status="blocked",
                confidence=1.0,
                evidence="tower reference manifest notApprovedFor",
                requiresReview=True,
            )
        ]
    hints = [
        primitive_hint("tower", "chimney_tower_module", "supported_base_shaft", status="verified", confidence=0.88, evidence="approved tower reference and support rule"),
        primitive_hint("tower", "chimney_tower_module", "tiered_box_stack", status="verified", confidence=0.82, evidence="approved tower reference vertical stack"),
    ]
    required = tower_rules.get("requiredDetailKinds", [])
    mapping = {
        "cupola_base": ("chimney_tower_module", "stepped_cupola_base"),
        "cupola_lantern": ("chimney_tower_module", "open_lantern_box_with_posts"),
        "cupola_post": ("chimney_tower_module", "thin_vertical_post_array"),
        "cupola_rail": ("chimney_tower_module", "thin_horizontal_rail_array"),
        "cupola_cap": ("roof_module", "small_hip_or_domed_cap"),
        "spire": ("chimney_tower_module", "thin_spire_cylinder_or_cone"),
        "weathervane": ("chimney_tower_module", "thin_crossbar_weather_vane"),
    }
    for item in required:
        module, primitive = mapping.get(item, ("chimney_tower_module", item))
        hints.append(
            primitive_hint(
                "tower",
                module,
                primitive,
                status="required",
                confidence=0.8,
                evidence=f"modeling-rules requiredDetailKinds includes {item}",
                required=True,
                requiresReview=True,
            )
        )
    if tower_rules.get("clockAndSpireRequired"):
        hints.extend(
            [
                primitive_hint("tower", "chimney_tower_module", "clock_face_disc_or_inset_circle", status="required", confidence=0.78, evidence="modeling-rules clockAndSpireRequired", required=True, requiresReview=True),
                primitive_hint("tower", "chimney_tower_module", "thin_spire_cylinder_or_cone", status="required", confidence=0.82, evidence="modeling-rules clockAndSpireRequired", required=True, requiresReview=True),
            ]
        )
    return hints


def roof_hint(primitive, roof_type, roof_rules, evidence):
    exact = primitive.startswith(str(roof_type or "none"))
    return primitive_hint(
        "roof",
        "roof_module",
        primitive,
        status="verified" if exact else "allowed",
        confidence=0.92 if exact else 0.62,
        evidence=f"modeling-rules {evidence}",
        requiresReview=not exact or roof_rules.get("prismZonesRequireExplicitReferenceBounds", False),
    )


def primitive_hint(target, module, primitive, status, confidence, evidence, **extra):
    hint = {
        "target": target,
        "module": module,
        "primitive": primitive,
        "status": status,
        "confidence": round(confidence, 2),
        "evidence": evidence,
        "requiresReview": extra.pop("requiresReview", status not in {"verified", "required"}),
    }
    hint.update(extra)
    return hint


def primitive_status(panel):
    hints = list(panel.primitive_hints)
    if not hints:
        return "unclassified"
    if any(hint.get("status") == "blocked" for hint in hints):
        return "blocked"
    if any(hint.get("requiresReview") for hint in hints):
        return "needs-review"
    if all(hint.get("status") in {"verified", "required"} for hint in hints):
        return "verified"
    return "mixed"


def unique_hints(panels, target, approved_only=False, review_only=False):
    seen = set()
    values = []
    for panel in panels:
        for hint in panel.primitive_hints:
            if hint.get("target") != target:
                continue
            primitive = hint.get("primitive")
            if primitive == "context_only_do_not_model":
                continue
            approved = hint.get("status") in {"verified", "required", "allowed"} and not hint.get("requiresReview", False)
            review = hint.get("requiresReview", False) or hint.get("status") in {"needs-review", "unclassified", "allowed"}
            if approved_only and not approved:
                continue
            if review_only and not review:
                continue
            if primitive and primitive not in seen:
                seen.add(primitive)
                values.append(primitive)
    return values


def primitive_summary(panel):
    primitives = [hint.get("primitive", "") for hint in panel.primitive_hints if hint.get("primitive")]
    if not primitives:
        return "classify from reference"
    summary = ", ".join(primitives[:3])
    if len(primitives) > 3:
        summary += f", +{len(primitives) - 3} more"
    return summary


def opening_summary(panel):
    if not panel.opening_layout:
        return "none planned"
    doors = [item for item in panel.opening_layout if item["kind"] == "door"]
    windows = [item for item in panel.opening_layout if item["kind"] == "window"]
    pieces = []
    if windows:
        pieces.append(f"{len(windows)} windows")
    if doors:
        door_positions = ", ".join(f'{door["id"]}@{door["centerFraction"]:.2f}w' for door in doors)
        pieces.append(f"{len(doors)} doors ({door_positions})")
    return "; ".join(pieces)


def image_data_url(path):
    path = Path(path)
    if not path.exists():
        return ""
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{payload}"


def wall_by_reference(manifest, reference_path):
    normalized = reference_path.removeprefix("references/")
    for wall in manifest.get("walls", []):
        path = wall.get("reference", {}).get("path", "").removeprefix("references/")
        if path == normalized:
            return wall
    return {}


def estimated_width_from_manifest(manifest):
    widths = [wall.get("lengthMeters", 0) for wall in manifest.get("walls", [])]
    widths = [value for value in widths if value]
    return max(widths) if widths else 12.0


def image_size(path):
    suffix = Path(path).suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return jpeg_size(path)
    if suffix == ".png":
        return png_size(path)
    return (0, 0)


def jpeg_size(path):
    data = Path(path).read_bytes()
    index = 2
    while index < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        length = int.from_bytes(data[index : index + 2], "big")
        if 0xC0 <= marker <= 0xC3:
            height = int.from_bytes(data[index + 3 : index + 5], "big")
            width = int.from_bytes(data[index + 5 : index + 7], "big")
            return width, height
        index += length
    return (0, 0)


def png_size(path):
    data = Path(path).read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return (0, 0)
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def escape(value):
    return html.escape(str(value), quote=True)
