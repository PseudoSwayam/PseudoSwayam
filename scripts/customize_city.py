#!/usr/bin/env python3
"""
Customize the actual github-profile-3d-contrib output seen in profile-custom-city.svg.

For the supplied SVG structure this script:
- Keeps the animated contribution-building group.
- Removes the contribution-type radar/statistics group.
- Removes the language pie-chart group.
- Removes the original footer statistics/date group, while extracting its real
  "N contributions" value before removing it.
- Adds a centered "CONTRIBUTION CITY" heading and a larger live-generated count.
- Applies the dark GitHub background and teal/cyan palette.
- Preserves the building SVG elements and their existing animate/animateTransform nodes.

Run from the repository root:
  python scripts/customize_city.py --input profile-3d-contrib/profile-custom-city.svg
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)

DEFAULT_INPUT = Path("profile-3d-contrib/profile-custom-city.svg")
DEFAULT_OUTPUT = Path("profile-3d-contrib/profile-city.svg")

PALETTE = {
    "background": "#0D1117",
    "foreground": "#E6EDF3",
    "muted": "#8B949E",
    "strong": "#62E7E2",
    "weak": "#8B949E",
    # Isometric building faces: top, left, right for contribution levels 0–4.
    "cont-top-0": "#161B22",
    "cont-left-0": "#12171C",
    "cont-right-0": "#0F1318",
    "cont-top-1": "#123D3A",
    "cont-left-1": "#0F3331",
    "cont-right-1": "#0D2B29",
    "cont-top-2": "#176B63",
    "cont-left-2": "#135A53",
    "cont-right-2": "#104B45",
    "cont-top-3": "#27B8A8",
    "cont-left-3": "#219A8D",
    "cont-right-3": "#1B8176",
    "cont-top-4": "#62E7E2",
    "cont-left-4": "#52C1BD",
    "cont-right-4": "#45A29E",
}


def tag_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def text_content(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def style_map(style: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for declaration in style.split(";"):
        if ":" in declaration:
            key, value = declaration.split(":", 1)
            result[key.strip()] = value.strip()
    return result


def set_style_map(element: ET.Element, values: dict[str, str]) -> None:
    element.set("style", "; ".join(f"{key}: {value}" for key, value in values.items()))


def extract_contribution_count(root: ET.Element) -> str:
    """
    The supplied SVG has a footer <text class="fill-strong">214</text>
    followed by <text>contributions</text>. Locate this semantically, not by
    hardcoding the number or relying on a fixed child index.
    """
    nodes = list(root.iter())
    for index, node in enumerate(nodes):
        if tag_name(node) != "text":
            continue
        classes = node.attrib.get("class", "").split()
        value = (node.text or "").strip().replace(",", "")
        if "fill-strong" not in classes or not value.isdigit():
            continue
        # Confirm that the nearby SVG contains the label "contributions".
        nearby = " ".join(text_content(n).lower() for n in nodes[index:index + 5])
        if "contributions" in nearby:
            return value

    # Fallback: accept an explicit title/aria-label such as "214 contributions".
    for node in nodes:
        candidate = " ".join(
            [text_content(node), node.attrib.get("aria-label", ""), node.attrib.get("title", "")]
        )
        match = re.search(r"\b([\d,]+)\s+contributions?\b", candidate, re.IGNORECASE)
        if match:
            return match.group(1).replace(",", "")

    raise ValueError(
        "Could not find the actual contribution count in the source SVG. "
        "No count was invented; inspect the generator output structure."
    )


def set_css_class(css: str, class_name: str, property_name: str, value: str) -> str:
    """Replace a CSS declaration inside a named class rule."""
    pattern = re.compile(
        rf"(\.{re.escape(class_name)}\s*\{{)([^}}]*)(\}})",
        flags=re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(css)
    if not match:
        return css
    declarations = style_map(match.group(2))
    declarations[property_name] = value
    replacement = match.group(1) + " " + "; ".join(
        f"{key}: {val}" for key, val in declarations.items()
    ) + "; " + match.group(3)
    return css[:match.start()] + replacement + css[match.end():]


def update_palette(root: ET.Element) -> None:
    for node in root.iter():
        if tag_name(node) == "style" and node.text:
            css = node.text
            # Set the base semantic classes.
            for class_name, prop, color_key in (
                ("fill-fg", "fill", "foreground"),
                ("stroke-fg", "stroke", "foreground"),
                ("fill-bg", "fill", "background"),
                ("stroke-bg", "stroke", "background"),
                ("fill-strong", "fill", "strong"),
                ("fill-weak", "fill", "weak"),
                ("stroke-weak", "stroke", "weak"),
            ):
                css = set_css_class(css, class_name, prop, PALETTE[color_key])

            # Set all isometric contribution face classes to the selected palette.
            for class_name, color in PALETTE.items():
                if class_name.startswith(("cont-top-", "cont-left-", "cont-right-")):
                    css = set_css_class(css, class_name, "fill", color)

            # The radar rule is removed with its chart group; remove its styling too.
            css = re.sub(r"\.radar\s*\{[^}]*\}", "", css, flags=re.DOTALL)
            node.text = css

    # Ensure the canvas background matches the GitHub dark theme.
    for node in root:
        if tag_name(node) == "rect" and node.attrib.get("x") == "0" and node.attrib.get("y") == "0":
            node.set("fill", PALETTE["background"])
            node.attrib.pop("class", None)
            break


def is_city_buildings_group(node: ET.Element) -> bool:
    # In the supplied generator output, the buildings are the large top-level
    # group containing hundreds of small rects and animation elements.
    if tag_name(node) != "g":
        return False
    descendants = list(node.iter())
    rects = sum(1 for item in descendants if tag_name(item) == "rect")
    animations = sum(1 for item in descendants if tag_name(item) in {"animate", "animatetransform"})
    return rects > 100 and animations > 0


def remove_dashboard_groups(root: ET.Element) -> tuple[int, int]:
    """
    Remove known non-city dashboard groups from the supplied SVG structure.
    Keep the group that contains the animated building grid.
    """
    top_level_groups = [child for child in list(root) if tag_name(child) == "g"]
    city_groups = [group for group in top_level_groups if is_city_buildings_group(group)]
    if len(city_groups) != 1:
        raise ValueError(
            f"Expected exactly one animated city/buildings group, found {len(city_groups)}. "
            "The generator output structure may have changed; refusing to remove groups blindly."
        )

    city = city_groups[0]
    removed_groups = 0
    for group in top_level_groups:
        if group is city:
            continue
        # All other top-level groups in this generator output are dashboards/footer:
        # contribution radar/stat cards, language pie chart, and footer date/stats.
        root.remove(group)
        removed_groups += 1

    # Remove radar CSS rule from <style> is handled in update_palette.
    return removed_groups, len(city_groups)


def improve_building_animations(root: ET.Element) -> int:
    """Make the existing SVG building-growth animations replay continuously.

    GitHub README images are rendered as external SVG images, so JavaScript
    scroll observers cannot reliably run inside them. SMIL animation is kept
    self-contained and loops automatically instead. Existing animation values,
    durations, and building geometry are preserved.
    """
    changed = 0
    for node in root.iter():
        if tag_name(node) not in {"animate", "animatetransform", "animatemotion", "set"}:
            continue
        # The generator marks the initial build as a one-time animation. Make
        # those animations replay; do not overwrite any custom indefinite loop.
        if node.attrib.get("repeatCount", "1") != "indefinite":
            node.set("repeatCount", "indefinite")
            changed += 1
        # Preserve explicit begin timing. If absent, let the animation begin
        # automatically when the SVG is loaded.
        if "begin" not in node.attrib:
            node.set("begin", "0s")
    return changed


def add_heading_and_count(root: ET.Element, count: str) -> None:
    """Create a left-aligned information panel and move the animated city right."""
    view_box = root.attrib.get("viewBox", "0 0 1280 850").replace(",", " ").split()
    try:
        x0, y0, width, height = map(float, view_box)
    except (ValueError, TypeError):
        x0, y0, width, height = 0.0, 0.0, 1280.0, 850.0

    city = next(
        (child for child in list(root) if is_city_buildings_group(child)),
        None,
    )
    if city is None:
        raise ValueError("Could not locate the animated contribution city group.")

    # Keep the contribution city on the right and preserve its child animations.
    # A group transform changes only the presentation, not the building elements.
    city.set("transform", "translate(220, 175) scale(0.86)")

    title = ET.Element(f"{{{SVG_NS}}}text", {
        "id": "custom-contribution-city-heading",
        "x": f"{x0 + 36:.2f}",
        "y": f"{y0 + 66:.2f}",
        "text-anchor": "start",
        "fill": PALETTE["strong"],
        "font-family": "Arial, Helvetica, sans-serif",
        "font-size": "27",
        "font-weight": "700",
        "letter-spacing": "3",
    })
    title.text = "CONTRIBUTION CITY"

    count_node = ET.Element(f"{{{SVG_NS}}}text", {
        "id": "custom-contribution-count",
        "x": f"{x0 + 34:.2f}",
        "y": f"{y0 + 145:.2f}",
        "text-anchor": "start",
        "fill": PALETTE["foreground"],
        "font-family": "Arial, Helvetica, sans-serif",
        "font-size": "76",
        "font-weight": "800",
    })
    count_node.text = count

    subtitle = ET.Element(f"{{{SVG_NS}}}text", {
        "id": "custom-contribution-subtitle",
        "x": f"{x0 + 36:.2f}",
        "y": f"{y0 + 183:.2f}",
        "text-anchor": "start",
        "fill": PALETTE["strong"],
        "font-family": "Arial, Helvetica, sans-serif",
        "font-size": "23",
        "font-weight": "600",
    })
    subtitle.text = "contributions in the last year"

    # Strip any border/stroke from the canvas background and ensure it is plain.
    for child in list(root):
        if tag_name(child) == "rect" and child.attrib.get("x") == "0" and child.attrib.get("y") == "0":
            child.set("fill", PALETTE["background"])
            for attr in ("stroke", "stroke-width", "class"):
                child.attrib.pop(attr, None)
            child.attrib.pop("style", None)
            break

    # Insert text immediately before the city so the city is painted above it only
    # if they overlap; the intended positions keep the two areas separate.
    city_index = list(root).index(city)
    root.insert(city_index, title)
    root.insert(city_index + 1, count_node)
    root.insert(city_index + 2, subtitle)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"ERROR: SVG not found: {args.input}", file=sys.stderr)
        return 2

    try:
        tree = ET.parse(args.input)
        root = tree.getroot()
        count = extract_contribution_count(root)
        # Validate the expected source layout before making any changes.
        groups = [child for child in list(root) if tag_name(child) == "g"]
        city_groups = [g for g in groups if is_city_buildings_group(g)]
        if len(city_groups) != 1:
            raise ValueError(
                f"Expected one animated buildings group, found {len(city_groups)}. "
                "No output written."
            )
    except (ET.ParseError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print(f"Input: {args.input}")
    print(f"Output: {args.output}")
    print(f"Contribution count extracted from generated SVG: {count}")
    print(f"Top-level groups before customization: {len(groups)}")
    print("Planned: retain animated building group; remove other dashboard/footer groups.")
    print("Planned: apply dark teal/cyan palette; left-align title/count/subtitle; enlarge and shift city left/down to fill the canvas; remove canvas border.")

    if args.dry_run:
        print("Dry run complete. No files changed.")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.resolve() == args.input.resolve():
        backup = args.input.with_suffix(args.input.suffix + ".bak")
        if not backup.exists():
            shutil.copy2(args.input, backup)

    try:
        removed, _ = remove_dashboard_groups(root)
        update_palette(root)
        animation_count = improve_building_animations(root)
        add_heading_and_count(root, count)
        tree.write(args.output, encoding="utf-8", xml_declaration=True)
    except (ValueError, OSError) as exc:
        print(f"ERROR: customization failed: {exc}", file=sys.stderr)
        return 2

    # Re-parse output as a basic well-formedness check.
    try:
        ET.parse(args.output)
    except ET.ParseError as exc:
        print(f"ERROR: output SVG is invalid: {exc}", file=sys.stderr)
        return 2

    print(f"Saved customized SVG: {args.output}")
    print(f"Removed {removed} non-city top-level dashboard/footer group(s).")
    print("Building elements and their existing SVG animation nodes were preserved.")
    print(f"Updated {animation_count} animation nodes to loop continuously.")
    print("Note: scroll-triggered animation is not reliable in GitHub README SVG images; this output loops automatically instead.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
