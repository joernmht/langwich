#!/usr/bin/env python3
"""Draw the map of Europe on the landing page from Natural Earth data.

The examples section of ``docs/index.html`` has a clickable map: every
country is one ``<path data-iso="DE">``. This script makes those paths and
writes them between the ``<!-- europe-map:start -->`` and
``<!-- europe-map:end -->`` markers of the page.

    npm pack world-atlas@2.0.2 && tar xzf world-atlas-2.0.2.tgz
    python3 scripts/build_europe_map.py package/countries-50m.json           # rewrite the page
    python3 scripts/build_europe_map.py package/countries-50m.json --print   # the SVG to stdout

The input is not in the repository and nothing is downloaded here: pass the
TopoJSON file of the ``world-atlas`` package (Natural Earth 1:50m country
polygons, public domain). Run the script again only to change the map's
frame, projection or detail; the page keeps the result.

How the map is made, so that it can be made again:

* **Projection:** Lambert azimuthal equal-area centred on 52° N, 10° E — the
  projection of the EU's reference grid (ETRS89-LAEA, EPSG:3035), on a sphere.
  The page projects the story locations with the same formula; its constants
  are written to the ``<svg>`` as ``data-`` attributes.
* **Frame:** from Lisbon to Kyiv and from Sicily to southern Norway, so that
  Germany and its neighbours sit in the middle.
* **Detail:** every border arc is simplified once (Douglas–Peucker, about half
  a pixel), before the countries are assembled from the arcs — neighbours
  share their border arc, so no gaps open between them.
* **Output:** one path per country in frame order of the data, coordinates
  rounded to one decimal in a 1000-unit-wide viewBox. Countries outside
  Europe that reach into the frame are drawn as plain land (no ``data-iso``).
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = ROOT / "docs" / "index.html"
START, END = "<!-- europe-map:start -->", "<!-- europe-map:end -->"

EARTH_KM = 6371.0
LON0, LAT0 = 10.0, 52.0
#: The frame in kilometres from the centre of projection (x east, y north).
FRAME = (-1800.0, -1830.0, 1400.0, 1020.0)  # west, south, east, north
WIDTH = 1000.0
#: Simplification tolerance in kilometres (the frame is 3200 km wide).
TOLERANCE_KM = 1.6

#: ISO 3166-1 numeric -> (alpha-2, English name) of the countries that are
#: clickable. Kosovo has no numeric code in the data and is found by name.
COUNTRIES: dict[str, tuple[str, str]] = {
    "008": ("AL", "Albania"), "020": ("AD", "Andorra"), "040": ("AT", "Austria"),
    "112": ("BY", "Belarus"), "056": ("BE", "Belgium"), "070": ("BA", "Bosnia and Herzegovina"),
    "100": ("BG", "Bulgaria"), "191": ("HR", "Croatia"), "203": ("CZ", "Czechia"),
    "208": ("DK", "Denmark"), "233": ("EE", "Estonia"), "246": ("FI", "Finland"),
    "250": ("FR", "France"), "276": ("DE", "Germany"), "300": ("GR", "Greece"),
    "348": ("HU", "Hungary"), "372": ("IE", "Ireland"), "380": ("IT", "Italy"),
    "428": ("LV", "Latvia"), "438": ("LI", "Liechtenstein"), "440": ("LT", "Lithuania"),
    "442": ("LU", "Luxembourg"), "470": ("MT", "Malta"), "498": ("MD", "Moldova"),
    "492": ("MC", "Monaco"), "499": ("ME", "Montenegro"), "528": ("NL", "Netherlands"),
    "807": ("MK", "North Macedonia"), "578": ("NO", "Norway"), "616": ("PL", "Poland"),
    "620": ("PT", "Portugal"), "642": ("RO", "Romania"), "643": ("RU", "Russia"),
    "674": ("SM", "San Marino"), "688": ("RS", "Serbia"), "703": ("SK", "Slovakia"),
    "705": ("SI", "Slovenia"), "724": ("ES", "Spain"), "752": ("SE", "Sweden"),
    "756": ("CH", "Switzerland"), "792": ("TR", "Türkiye"), "804": ("UA", "Ukraine"),
    "826": ("GB", "United Kingdom"), "336": ("VA", "Vatican City"),
}
BY_NAME: dict[str, tuple[str, str]] = {"Kosovo": ("XK", "Kosovo")}


def project(lon: float, lat: float) -> tuple[float, float]:
    """Lambert azimuthal equal-area, in kilometres from (LON0, LAT0)."""
    lam, phi = math.radians(lon - LON0), math.radians(lat)
    phi0 = math.radians(LAT0)
    cos_c = math.sin(phi0) * math.sin(phi) + math.cos(phi0) * math.cos(phi) * math.cos(lam)
    k = math.sqrt(2.0 / (1.0 + max(cos_c, -0.999999)))
    x = EARTH_KM * k * math.cos(phi) * math.sin(lam)
    y = EARTH_KM * k * (math.cos(phi0) * math.sin(phi)
                        - math.sin(phi0) * math.cos(phi) * math.cos(lam))
    return x, y


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Douglas–Peucker; the end points stay."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        first, last = stack.pop()
        (x1, y1), (x2, y2) = points[first], points[last]
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        worst, index = 0.0, -1
        for i in range(first + 1, last):
            px, py = points[i]
            if length == 0:
                distance = math.hypot(px - x1, py - y1)
            else:
                distance = abs(dy * px - dx * py + x2 * y1 - y2 * x1) / length
            if distance > worst:
                worst, index = distance, i
        if worst > tolerance and index > 0:
            keep[index] = True
            stack += [(first, index), (index, last)]
    return [p for p, k in zip(points, keep) if k]


def decode_arcs(topology: dict) -> list[list[tuple[float, float]]]:
    """Every arc as projected points (kilometres), simplified."""
    (sx, sy), (tx, ty) = topology["transform"]["scale"], topology["transform"]["translate"]
    arcs = []
    for arc in topology["arcs"]:
        x = y = 0
        points = []
        for dx, dy in arc:
            x, y = x + dx, y + dy
            points.append(project(x * sx + tx, y * sy + ty))
        arcs.append(simplify(points, TOLERANCE_KM))
    return arcs


def ring_points(ring: list[int], arcs: list[list[tuple[float, float]]]) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    for index in ring:
        arc = arcs[index] if index >= 0 else arcs[~index][::-1]
        points += arc[1:] if points else arc
    return points


def clip(points: list[tuple[float, float]], box: tuple[float, float, float, float]) -> list[tuple[float, float]]:
    """Sutherland–Hodgman clipping of a ring against a rectangle."""
    west, south, east, north = box

    def cut(ring: list[tuple[float, float]], inside, cross) -> list[tuple[float, float]]:
        out: list[tuple[float, float]] = []
        for i, current in enumerate(ring):
            previous = ring[i - 1]
            if inside(current):
                if not inside(previous):
                    out.append(cross(previous, current))
                out.append(current)
            elif inside(previous):
                out.append(cross(previous, current))
        return out

    def at_x(x: float):
        return lambda a, b: (x, a[1] + (b[1] - a[1]) * (x - a[0]) / (b[0] - a[0]))

    def at_y(y: float):
        return lambda a, b: (a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]), y)

    for inside, cross in (
        (lambda p: p[0] >= west, at_x(west)), (lambda p: p[0] <= east, at_x(east)),
        (lambda p: p[1] >= south, at_y(south)), (lambda p: p[1] <= north, at_y(north)),
    ):
        points = cut(points, inside, cross)
        if not points:
            break
    return points


def to_view(point: tuple[float, float]) -> tuple[float, float]:
    west, _, east, north = FRAME
    scale = WIDTH / (east - west)
    return (point[0] - west) * scale, (north - point[1]) * scale


def path_data(rings: list[list[tuple[float, float]]]) -> str:
    parts = []
    for ring in rings:
        coords: list[str] = []
        last = None
        for point in map(to_view, ring):
            text = f"{point[0]:.1f},{point[1]:.1f}".replace(".0,", ",")
            text = text[:-2] if text.endswith(".0") else text
            if text != last:
                coords.append(text)
                last = text
        if len(coords) >= 3:
            parts.append("M" + "L".join(coords) + "Z")
    return "".join(parts)


def build_svg(topology: dict) -> str:
    arcs = decode_arcs(topology)
    west, south, east, north = FRAME
    # clip a little outside the frame, so the cut edges are never visible
    pad = 40.0
    box = (west - pad, south - pad, east + pad, north + pad)
    height = WIDTH * (north - south) / (east - west)
    land: list[str] = []
    countries: list[str] = []
    for geometry in topology["objects"]["countries"]["geometries"]:
        polygons = geometry.get("arcs") or []
        if geometry["type"] == "Polygon":
            polygons = [polygons]
        rings = []
        for polygon in polygons:
            outer = clip(ring_points(polygon[0], arcs), box)
            if len(outer) < 3:
                continue
            rings.append(outer)
            rings += [hole for hole in (clip(ring_points(r, arcs), box) for r in polygon[1:])
                      if len(hole) >= 3]
        data = path_data(rings)
        if not data:
            continue
        name = geometry.get("properties", {}).get("name", "")
        known = COUNTRIES.get(str(geometry.get("id", ""))) or BY_NAME.get(name)
        if known is None:
            land.append(f'<path class="land" d="{data}"/>')
        else:
            iso, label = known
            countries.append(
                f'<path class="country" data-iso="{iso}" d="{data}"><title>{label}</title></path>')
    scale = WIDTH / (east - west)
    countries.sort()
    lines = [
        # the filter chips beside the map do the same for keyboards and screen readers
        f'<svg class="europe" viewBox="0 0 {WIDTH:.0f} {height:.0f}" aria-hidden="true" '
        f'data-lon0="{LON0:g}" data-lat0="{LAT0:g}" data-radius="{EARTH_KM:g}" '
        f'data-west="{west:g}" data-north="{north:g}" data-scale="{scale:.6f}">',
        '<g class="lands">', *land, "</g>",
        '<g class="countries">', *countries, "</g>",
        '<g class="places"></g>',
        "</svg>",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("topojson", metavar="COUNTRIES_50M_JSON",
                        help="countries-50m.json of the world-atlas package (Natural Earth)")
    parser.add_argument("--print", action="store_true", dest="stdout",
                        help="print the SVG instead of writing it into docs/index.html")
    args = parser.parse_args(argv)
    topology = json.loads(Path(args.topojson).read_text(encoding="utf-8"))
    svg = build_svg(topology)
    if args.stdout:
        print(svg)
        return 0
    page = INDEX_HTML.read_text(encoding="utf-8")
    if page.count(START) != 1 or page.count(END) != 1:
        print(f"error: {INDEX_HTML.relative_to(ROOT)} needs exactly one '{START}' and one "
              f"'{END}'", file=sys.stderr)
        return 1
    head, rest = page.split(START)
    _, tail = rest.split(END)
    INDEX_HTML.write_text(f"{head}{START}\n{svg}\n{END}{tail}", encoding="utf-8")
    print(f"Wrote the map ({len(svg) // 1024} KB) into {INDEX_HTML.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
