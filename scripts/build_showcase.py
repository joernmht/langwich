#!/usr/bin/env python3
"""Render the bundled examples for the website and the README.

The landing page (docs/index.html) and the README show real langwich output,
not mock-ups. This script makes it from ``examples/*.json``:

* ``docs/examples/<stem>.pdf`` — every example rendered with the default
  options (A4, solutions appended), the same PDF ``langwich render FILE``
  writes when no profile says otherwise;
* ``docs/assets/<name>-page1.png`` — a preview of the first page, about
  110 dpi (910 px wide);
* ``docs/assets/<name>-picture.png`` — the page that holds the scene picture,
  for examples whose picture has numbered labels;
* for the examples in ``EPAPER_EXAMPLES`` also the e-paper version:
  ``docs/examples/<stem>-epaper.pdf`` (``--page epaper``) and
  ``docs/assets/<name>-epaper-page1.png``.

``<name>`` is the file name without its language pair, with dashes:
``lena_01_en_de`` becomes ``lena-01`` (if two examples would get the same
name, both keep their full stem: ``coffee-en-de``).

The output is deterministic: the default shuffle seed, and a fixed
``SOURCE_DATE_EPOCH`` so that the embedded font subsets — and with them the
PDF files — are byte-identical from run to run. Files whose content did not
change are not rewritten, and generated files that no example produces any
more (a renamed or removed example) are deleted.

Usage:
    python3 scripts/build_showcase.py           # render everything
    python3 scripts/build_showcase.py --check   # compare only; exit 1 if stale

``--check`` writes nothing: it renders every example into a temporary folder
and compares page count and page text with the committed PDFs (robust across
font-subset names and PDF byte details), and checks that every preview PNG
exists. Run the full build — and commit ``docs/examples/`` and
``docs/assets/`` — after changing ``src/langwich/render/``, the planner or an
example. Unknown options are an error; nothing is ever rebuilt by accident.

Needs WeasyPrint (a langwich dependency) and PyMuPDF for the previews and the
comparison (``pip install -e ".[dev]"``).
"""

from __future__ import annotations

import argparse
import html
import os
import re
import sys
import tempfile
from collections import Counter
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

# fontTools stamps every font subset with the current time unless this is set.
os.environ.setdefault("SOURCE_DATE_EPOCH", "1767225600")  # 2026-01-01

from langwich.model import Worksheet  # noqa: E402
from langwich.validate import check_file  # noqa: E402

EXAMPLES_DIR = REPO_ROOT / "examples"
PDF_DIR = REPO_ROOT / "docs" / "examples"
ASSETS_DIR = REPO_ROOT / "docs" / "assets"

#: Examples that also get an e-paper PDF and preview.
EPAPER_EXAMPLES: tuple[str, ...] = ("lena_01_en_de",)

#: Preview width in pixels (A4 at about 110 dpi).
PREVIEW_WIDTH_PX = 910

#: Task titles are set at 13 pt and scene headings at 15 pt; the route on the
#: cover and the answer key repeat them in smaller type.
HEADING_MIN_PT = 12.0

_LANG_PAIR = re.compile(r"_[a-z]{2,3}(?:-[a-z0-9]+)?_[a-z]{2,3}(?:-[a-z0-9]+)?$", re.IGNORECASE)


@dataclass
class Example:
    path: Path
    name: str  # short name for the PNG files, e.g. "lena-01"

    @property
    def stem(self) -> str:
        return self.path.stem

    @property
    def pdf(self) -> Path:
        return PDF_DIR / f"{self.stem}.pdf"

    @property
    def page1_png(self) -> Path:
        return ASSETS_DIR / f"{self.name}-page1.png"

    @property
    def picture_png(self) -> Path:
        return ASSETS_DIR / f"{self.name}-picture.png"

    @property
    def epaper(self) -> bool:
        return self.stem in EPAPER_EXAMPLES

    @property
    def epaper_pdf(self) -> Path:
        return PDF_DIR / f"{self.stem}-epaper.pdf"

    @property
    def epaper_png(self) -> Path:
        return ASSETS_DIR / f"{self.name}-epaper-page1.png"


def find_examples() -> list[Example]:
    paths = sorted(EXAMPLES_DIR.glob("*.json"))
    short = {p: _LANG_PAIR.sub("", p.stem).replace("_", "-").lower() for p in paths}
    taken = Counter(short.values())
    return [
        Example(p, short[p] if short[p] and taken[short[p]] == 1
                else p.stem.replace("_", "-").lower())
        for p in paths
    ]


def has_labelled_picture(ws: Worksheet) -> bool:
    return any(s.picture is not None and s.picture.has_visual and s.picture.labels
               for s in ws.story.scenes)


def expected_outputs(example: Example, ws: Worksheet) -> list[Path]:
    out = [example.pdf, example.page1_png]
    if has_labelled_picture(ws):
        out.append(example.picture_png)
    if example.epaper:
        out += [example.epaper_pdf, example.epaper_png]
    return out


#: Files this script generates; anything matching that no example produces
#: is a leftover (the other files in docs/assets/ are left alone).
GENERATED_PATTERNS: tuple[tuple[Path, str], ...] = (
    (PDF_DIR, "*.pdf"),
    (ASSETS_DIR, "*-page1.png"),
    (ASSETS_DIR, "*-picture.png"),
)

#: The pages that show the previews; a preview none of them uses is noted.
SHOWCASE_PAGES: tuple[Path, ...] = (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "index.html")


def leftover_files(expected: set[Path]) -> list[Path]:
    """Generated-looking files in docs/ that no example produces any more."""
    found = {p for folder, pattern in GENERATED_PATTERNS for p in folder.glob(pattern)}
    return sorted(found - expected)


def unused_previews(expected: set[Path]) -> list[Path]:
    """Preview PNGs that neither the README nor the landing page shows."""
    pages = "".join(p.read_text(encoding="utf-8") for p in SHOWCASE_PAGES if p.is_file())
    return sorted(p for p in expected
                  if p.suffix == ".png" and p.name not in pages)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render(example: Example, ws: Worksheet, out_dir: Path, page: str) -> tuple[Path, str]:
    """Render with the default options (and ``page``); returns (PDF, HTML text)."""
    from langwich.render import RenderOptions, render_worksheet

    options = RenderOptions(page=page, base_dir=example.path.parent.resolve())
    result = render_worksheet(ws, out_dir / f"{example.stem}-{page}.pdf", options)
    if result.weasyprint_error or result.pdf is None:
        raise SystemExit(f"error: no PDF for {example.path.name}: "
                         f"{result.weasyprint_error or 'unknown reason'}")
    for warning in result.warnings:
        print(f"  warning: {warning}", file=sys.stderr)
    return result.pdf, result.html.read_text(encoding="utf-8")


def picture_heading(page_html: str) -> str | None:
    """The heading of the task (or scene) that shows the scene picture."""
    at = page_html.find('<figure class="fig"')
    if at < 0:
        return None
    start = page_html.rfind("<section", 0, at)
    match = re.compile(r"<h[23][^>]*>(.*?)</h[23]>", re.S).search(page_html, start, at)
    if match is None:
        return None
    text = html.unescape(re.sub(r"<[^>]+>", "", match.group(1)))
    return " ".join(text.split())


def find_heading_page(doc, heading: str) -> int | None:
    """Index of the first page that sets ``heading`` in heading type."""
    for index, page in enumerate(doc):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = line["spans"]
                text = " ".join("".join(s["text"] for s in spans).split())
                if (text and max(s["size"] for s in spans) >= HEADING_MIN_PT
                        and heading.startswith(text) and len(text) >= min(len(heading), 6)):
                    return index
    return None


def png_bytes(page) -> bytes:
    """A greyscale PNG of ``page``, PREVIEW_WIDTH_PX wide."""
    import pymupdf
    from PIL import Image

    dpi = PREVIEW_WIDTH_PX / (page.rect.width / 72)
    pix = page.get_pixmap(dpi=round(dpi), colorspace=pymupdf.csGRAY, alpha=False)
    image = Image.frombytes("L", (pix.width, pix.height), pix.samples)
    buf = BytesIO()
    image.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_if_changed(path: Path, data: bytes) -> None:
    rel = path.relative_to(REPO_ROOT)
    if path.is_file() and path.read_bytes() == data:
        print(f"  unchanged  {rel}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    print(f"  written    {rel} ({len(data) // 1024} KB)")


def page_texts(pdf: Path) -> list[str]:
    """The text of every page, whitespace-normalised."""
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return [" ".join(page.get_text("text").split()) for page in doc]


def compare_pdf(fresh: Path, committed: Path) -> str | None:
    """None when ``committed`` has the pages and text of ``fresh``, else why not."""
    rel = committed.relative_to(REPO_ROOT)
    if not committed.is_file() or committed.stat().st_size == 0:
        return f"missing: {rel}"
    new, old = page_texts(fresh), page_texts(committed)
    if len(new) != len(old):
        return f"stale: {rel} has {len(old)} pages, the renderer now makes {len(new)}"
    for number, (a, b) in enumerate(zip(new, old), start=1):
        if a != b:
            return f"stale: {rel} differs from a fresh render on page {number}"
    return None


def check(example: Example, ws: Worksheet, tmp: Path) -> list[str]:
    """Problems of one example's committed showcase files (nothing is written)."""
    problems = []
    pdf, _ = render(example, ws, tmp, "a4")
    problems.append(compare_pdf(pdf, example.pdf))
    if example.epaper:
        pdf, _ = render(example, ws, tmp, "epaper")
        problems.append(compare_pdf(pdf, example.epaper_pdf))
    problems += [f"missing: {p.relative_to(REPO_ROOT)}" for p in expected_outputs(example, ws)
                 if p.suffix == ".png" and (not p.is_file() or p.stat().st_size == 0)]
    return [p for p in problems if p]


def build(example: Example, ws: Worksheet, tmp: Path) -> None:
    import pymupdf

    pdf, page_html = render(example, ws, tmp, "a4")
    write_if_changed(example.pdf, pdf.read_bytes())
    with pymupdf.open(pdf) as doc:
        write_if_changed(example.page1_png, png_bytes(doc[0]))
        if has_labelled_picture(ws):
            heading = picture_heading(page_html)
            index = find_heading_page(doc, heading) if heading else None
            if index is None:
                raise SystemExit(f"error: cannot find the picture page of {example.path.name} "
                                 f"(heading {heading!r})")
            write_if_changed(example.picture_png, png_bytes(doc[index]))

    if example.epaper:
        pdf, _ = render(example, ws, tmp, "epaper")
        write_if_changed(example.epaper_pdf, pdf.read_bytes())
        with pymupdf.open(pdf) as doc:
            write_if_changed(example.epaper_png, png_bytes(doc[0]))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def load(example: Example) -> Worksheet:
    report = check_file(example.path)
    if not report.ok or report.worksheet is None:
        raise SystemExit(f"error: {example.path.name} does not validate:\n{report.format_text()}")
    return report.worksheet


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="build_showcase.py",
        description="Render examples/*.json into docs/examples/ (PDFs) and docs/assets/ "
                    "(PNG previews) for the README and the website.",
        epilog="Run it after changing the renderer, the planner or an example, and commit "
               "docs/examples/ and docs/assets/.",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="write nothing: render into a temporary folder, compare page count and text "
             "with the committed PDFs, check that every preview exists; exit 1 if anything "
             "is stale or missing",
    )
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)  # --help and unknown options stop here, before any rendering
    examples = find_examples()
    if not examples:
        print("error: no examples/*.json found", file=sys.stderr)
        return 1

    try:
        import pymupdf  # noqa: F401
    except ImportError:
        print("error: the previews and --check need PyMuPDF: pip install -e \".[dev]\"",
              file=sys.stderr)
        return 1

    worksheets = [(example, load(example)) for example in examples]
    expected = {p for example, ws in worksheets for p in expected_outputs(example, ws)}

    with tempfile.TemporaryDirectory(prefix="langwich-showcase-") as tmp:
        if args.check:
            problems = [p for example, ws in worksheets for p in check(example, ws, Path(tmp))]
            problems += [f"leftover: {p.relative_to(REPO_ROOT)} (no example produces it; "
                         "delete it)" for p in leftover_files(expected)]
            for problem in problems:
                print(problem, file=sys.stderr)
            for path in unused_previews(expected):
                print(f"note: {path.relative_to(REPO_ROOT)} is shown neither in README.md nor "
                      "in docs/index.html", file=sys.stderr)
            if problems:
                print("Run 'python3 scripts/build_showcase.py' and commit docs/examples/ and "
                      "docs/assets/.", file=sys.stderr)
                return 1
            print(f"The showcase files of {len(examples)} examples match the renderer.")
            return 0

        for example, ws in worksheets:
            print(f"{example.path.relative_to(REPO_ROOT)}")
            build(example, ws, Path(tmp))
    for path in leftover_files(expected):
        path.unlink()
        print(f"  removed    {path.relative_to(REPO_ROOT)} (no example produces it)")
    for path in unused_previews(expected):
        print(f"note: {path.relative_to(REPO_ROOT)} is shown neither in README.md nor in "
              "docs/index.html", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
