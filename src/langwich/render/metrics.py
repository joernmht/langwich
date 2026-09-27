"""Approximate text measurement with the bundled fonts.

Used for layout decisions that CSS cannot make on its own: the uniform blank
width of a cloze task, whether multiple-choice options fit on one row, and
how glosses and sidebars are distributed along the side column of a scene.
Advance widths come from the TTF files (via fontTools, a WeasyPrint
dependency); without fontTools a conservative average is used.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

_FACES = {
    "serif": "Literata-400.ttf",
    "serif-bold": "Literata-600.ttf",
    "serif-italic": "Literata-400i.ttf",
    "sans": "AtkinsonHyperlegibleNext-400.ttf",
    "sans-bold": "AtkinsonHyperlegibleNext-700.ttf",
}

PT_TO_MM = 25.4 / 72


@lru_cache(maxsize=None)
def _advances(face: str) -> tuple[dict[int, int], int, int] | None:
    try:
        from fontTools.ttLib import TTFont
    except ImportError:
        return None
    try:
        font = TTFont(str(FONTS_DIR / _FACES[face]), lazy=True)
        cmap = font.getBestCmap()
        hmtx = font["hmtx"].metrics
        upm = int(font["head"].unitsPerEm)
        widths = {cp: hmtx[glyph][0] for cp, glyph in cmap.items() if glyph in hmtx}
        fallback = widths.get(ord("n"), upm // 2)
        font.close()
        return widths, upm, fallback
    except Exception:  # a broken or missing font file only degrades the estimate
        return None


def width_mm(text: str, face: str = "serif", pt: float = 11.0) -> float:
    """Advance width of ``text`` set in ``face`` at ``pt`` points, in mm."""
    data = _advances(face)
    if data is None:
        return len(text) * pt * 0.52 * PT_TO_MM
    widths, upm, fallback = data
    units = sum(widths.get(ord(ch), fallback) for ch in text)
    return units / upm * pt * PT_TO_MM


def line_count(text: str, width: float, face: str = "serif", pt: float = 11.0) -> int:
    """Lines needed to set ``text`` ragged-right in a column ``width`` mm wide."""
    if width <= 0:
        return 1
    space = width_mm(" ", face, pt)
    total = 0
    for raw_line in text.split("\n"):
        words = raw_line.split()
        if not words:
            total += 1
            continue
        lines, current = 1, 0.0
        for word in words:
            w = width_mm(word, face, pt)
            if current and current + space + w > width:
                lines += 1
                current = w
            else:
                current = current + space + w if current else w
            while current > width:  # a word longer than the column wraps anywhere
                lines += 1
                current -= width
        total += lines
    return total
