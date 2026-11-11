#!/usr/bin/env python3
"""Make the landing page's web fonts from the fonts langwich typesets with.

The website is set in the worksheets' own typefaces: Atkinson Hyperlegible
Next for instructions and Literata for the stories. This script converts the
bundled TTF files (``src/langwich/fonts/``, SIL Open Font License) to WOFF2
files in ``docs/assets/fonts/``, keeping only the Latin characters the page
needs, and copies the licence texts next to them.

    python3 scripts/build_page_fonts.py

Run it after changing the bundled fonts, and commit ``docs/assets/fonts/``.
The output is the same from run to run (a fixed ``SOURCE_DATE_EPOCH``).
Needs fontTools with Brotli, which WeasyPrint installs.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "langwich" / "fonts"
TARGET = ROOT / "docs" / "assets" / "fonts"

# fontTools stamps a font with the current time unless this is set.
os.environ.setdefault("SOURCE_DATE_EPOCH", "1767225600")  # 2026-01-01

#: The styles the page uses.
FONTS: tuple[str, ...] = (
    "AtkinsonHyperlegibleNext-400", "AtkinsonHyperlegibleNext-700",
    "Literata-600", "Literata-400i",
)
#: Latin with the accents of the European languages, punctuation, arrows.
UNICODES: tuple[tuple[int, int], ...] = (
    (0x20, 0x7E), (0xA0, 0x24F), (0x2010, 0x2027), (0x2030, 0x203A), (0x20AC, 0x20AC),
    (0x2190, 0x2193), (0x2212, 0x2212), (0x2260, 0x2265),
)


def main() -> int:
    try:
        from fontTools import subset
        from fontTools.ttLib import TTFont
    except ImportError:
        print("error: fontTools is needed (pip install -e .)", file=sys.stderr)
        return 1
    TARGET.mkdir(parents=True, exist_ok=True)
    wanted = [cp for low, high in UNICODES for cp in range(low, high + 1)]
    for name in FONTS:
        font = TTFont(SOURCE / f"{name}.ttf")
        options = subset.Options(layout_features=["kern", "liga", "locl", "mark", "mkmk"],
                                 notdef_outline=True, name_IDs=[0, 1, 2, 3, 4, 6, 13, 14])
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=wanted)
        subsetter.subset(font)
        font.flavor = "woff2"
        out = TARGET / f"{name}.woff2"
        font.save(out)
        print(f"  {out.relative_to(ROOT)} ({out.stat().st_size // 1024} KB)")
    for licence in sorted(SOURCE.glob("OFL-*.txt")):
        shutil.copyfile(licence, TARGET / licence.name)
        print(f"  {(TARGET / licence.name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
