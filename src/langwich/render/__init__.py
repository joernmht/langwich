"""Render a ``langwich/3`` worksheet to HTML and PDF.

``build_html`` produces a self-contained HTML document (print CSS, bundled
fonts via ``file://`` URIs, pictures as ``data:`` URIs). ``render_worksheet``
writes that HTML next to the PDF and converts it with WeasyPrint. WeasyPrint
is imported lazily: without it (or without its system libraries) the HTML is
still written and :attr:`RenderResult.weasyprint_error` explains why there is
no PDF.

Rendering never touches the network or the file system beyond the bundled
fonts: WeasyPrint gets a URL fetcher that serves ``data:`` URIs and the font
files and refuses everything else (pictures are embedded as ``data:`` URIs by
:mod:`langwich.images`, which also strips external references from SVG).

``build_html`` has to guess where pages break. ``render_worksheet`` checks the
guesses on WeasyPrint's layout and builds once more when one was wrong (a
label task and its picture task did not fit on one page, or a few word-list
rows spilled onto an almost empty page).
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal

from langwich.model import Worksheet
from langwich.render.css import FONTS_DIR, font_face_css
from langwich.render.html import FONT_MARKER, Builder
from langwich.render.options import LayoutHints, RenderOptions, RenderResult

__all__ = ["RenderOptions", "RenderResult", "build_html", "render_worksheet"]

#: Build-and-check rounds at most (the first layout plus corrections).
MAX_LAYOUT_PASSES = 4
#: A word-list page filled less than this (after the list spilled over from
#: the page before) is set again with tighter rows.
WORD_LIST_TAIL_FILL = 0.3
#: A page filled less than this because the next task did not fit is worth
#: another layout pass.
LOW_FILL = 0.5
#: How far a picture may shrink to fit the page before it (share of its
#: height), and the lowest drawing frame (mm).
MIN_PICTURE_SCALE = 0.58
MIN_FRAME_H = 50.0


def _build(
    ws: Worksheet,
    options: RenderOptions,
    part: Literal["worksheet", "solutions", "all"],
    pictures: dict | None = None,
    hints: LayoutHints | None = None,
) -> tuple[str, Builder]:
    builder = Builder(ws, options, pictures, hints)
    return builder.build(part), builder


def build_html(
    ws: Worksheet,
    options: RenderOptions | None = None,
    *,
    part: Literal["worksheet", "solutions", "all"] = "all",
) -> str:
    """The worksheet as one HTML document.

    ``part="worksheet"`` leaves out the answer section, ``"solutions"`` is
    the answer section alone, ``"all"`` is both (unless
    ``options.solutions == "none"``).
    """
    html, _ = _build(ws, options or RenderOptions(), part)
    return html.replace(FONT_MARKER, font_face_css(), 1)


# ---------------------------------------------------------------------------
# WeasyPrint
# ---------------------------------------------------------------------------


def _load_weasyprint() -> tuple[Any, Any, Any]:
    import weasyprint
    from weasyprint.text.fonts import FontConfiguration

    return weasyprint.HTML, weasyprint.CSS, FontConfiguration


def is_allowed_url(url: str) -> bool:
    """``data:`` URIs and the bundled font files; nothing else."""
    if url.startswith("data:"):
        return True
    if not url.startswith("file:"):
        return False
    try:
        path = Path(urllib.request.url2pathname(urllib.parse.urlparse(url).path)).resolve()
    except (OSError, ValueError):
        return False
    return path.is_relative_to(FONTS_DIR.resolve())


def make_url_fetcher(blocked: list[str]) -> Any:
    """A WeasyPrint URL fetcher restricted by :func:`is_allowed_url`.

    Refused URLs are appended to ``blocked``. Works with the ``URLFetcher``
    class of WeasyPrint ≥ 66 and the ``default_url_fetcher`` function before.
    """
    from weasyprint import urls

    def refuse(url: str) -> None:
        if url not in blocked:
            blocked.append(url)
        raise ValueError(f"langwich renders offline; not fetched: {url[:120]}")

    fetcher_cls = getattr(urls, "URLFetcher", None)
    if fetcher_cls is not None:
        class OfflineFetcher(fetcher_cls):  # type: ignore[misc, valid-type]
            def fetch(self, url: str, headers: Any = None) -> Any:
                if not is_allowed_url(url):
                    refuse(url)
                return super().fetch(url, headers)

        return OfflineFetcher()

    default = urls.default_url_fetcher  # pragma: no cover - WeasyPrint < 66

    def fetcher(url: str, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        if not is_allowed_url(url):
            refuse(url)
        return default(url, *args, **kwargs)

    return fetcher  # pragma: no cover


class _Quiet(logging.Filter):
    """Drops two expected WeasyPrint messages: refused URLs (each becomes one
    langwich warning) and the running header's ``string()`` seen outside its
    margin box (WeasyPrint builds the header once in the flow before it moves
    it into the page margin, where the named strings resolve)."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        return not ("langwich renders offline" in message
                    or ('"string(' in message and "only allowed in page margins" in message))


def _render(html: str, base_dir: Path | None, api: tuple[Any, Any, Any],
            blocked: list[str]) -> Any:
    html_cls, css_cls, font_config_cls = api
    fetcher = make_url_fetcher(blocked)
    font_config = font_config_cls()
    fonts = css_cls(string=font_face_css(), font_config=font_config, url_fetcher=fetcher)
    doc = html_cls(string=html.replace(FONT_MARKER, "", 1),
                   base_url=str(base_dir or Path.cwd()) + "/", url_fetcher=fetcher)
    logger = logging.getLogger("weasyprint")
    quiet = _Quiet()
    logger.addFilter(quiet)
    try:
        return doc.render(stylesheets=[fonts], font_config=font_config)
    finally:
        logger.removeFilter(quiet)


# ---------------------------------------------------------------------------
# Checking the layout
# ---------------------------------------------------------------------------


def _classes(box: Any) -> list[str]:
    element = getattr(box, "element", None)
    if element is None or getattr(box, "element_tag", "").endswith(("::before", "::after")):
        return []
    return (element.get("class") or "").split()


def _page_root(page: Any) -> Any:
    box = page._page_box
    return next((c for c in box.children if type(c).__name__ != "MarginBox"), None)


def _page_fill(page: Any) -> float:
    """Share of the page's content height down to its lowest box."""
    box = page._page_box
    root = _page_root(page)
    if root is None or not box.height:
        return 0.0
    top, bottom = box.content_box_y(), box.content_box_y()
    for child in root.descendants():
        if getattr(child, "children", None) and type(child).__name__ != "LineBox":
            continue
        try:
            bottom = max(bottom, child.position_y + child.margin_height())
        except (TypeError, AttributeError):
            continue
    return max(0.0, (bottom - top) / box.height)


PX_TO_MM = 25.4 / 96


def _first_unit(page: Any) -> Any:
    """The task (or label + picture pair) a page starts with, if any."""
    root = _page_root(page)
    if root is None:
        return None
    for box in root.descendants():
        element = getattr(box, "element", None)
        if element is None or not hasattr(box, "children"):
            continue
        classes = _classes(box)
        if "pair" in classes or ("task" in classes and element.tag == "section"):
            return box
        if classes and classes[0] in ("scene", "back", "teaser", "cover", "para", "sh"):
            return None
        if box.element_tag in ("p", "li", "td", "span"):
            return None
    return None


def _on_page(page: Any, element: Any) -> bool:
    root = _page_root(page)
    return root is not None and any(getattr(b, "element", None) is element
                                    for b in root.descendants())


def _shrinkable(unit: Any) -> list[tuple[int, float, str]]:
    """(task number, current height mm, "fig"/"frame") of the pictures and
    drawing frames inside a unit."""
    out = []
    for box in unit.descendants():
        classes = _classes(box)
        if ("fig" in classes and "mini" not in classes) or "frame" in classes:
            section = box.element
            height = box.element.get("data-h")
            owner = next((b for b in _ancestors(unit, box) if (b.element.get("id") or "")
                          .startswith("task-")), None)
            if height and owner is not None and section is not None:
                number = int(owner.element.get("id")[5:])
                out.append((number, float(height), "fig" if "fig" in classes else "frame"))
    return out


def _ancestors(root: Any, target: Any) -> list[Any]:
    """Boxes from ``root`` down to ``target`` (innermost first)."""
    path: list[Any] = []

    def walk(box: Any) -> bool:
        if box is target:
            return True
        for child in getattr(box, "children", []) or []:
            if walk(child):
                if getattr(child, "element", None) is not None:
                    path.append(child)
                return True
        return False

    walk(root)
    if getattr(root, "element", None) is not None:
        path.append(root)
    return path


def layout_hints(rendered: Any, current: LayoutHints, one_task_per_page: bool = False) -> LayoutHints:
    """Corrections for the next build, judged on WeasyPrint's pages.

    * a label + picture pair that spans two pages is split up;
    * a word list whose last page holds only a few rows is set tighter;
    * a page left less than LOW_FILL full because the next task did not fit
      gets that task: a smaller picture or drawing frame, permission to break
      between items (a task kept whole only for convenience), or permission
      to leave its header with just its first block at the foot of the page
      (a flowing task whose header, boxes and first items did not fit).
    """
    pair_pages: dict[int, set[int]] = {}
    word_pages: list[int] = []
    for number, page in enumerate(rendered.pages):
        root = _page_root(page)
        if root is None:
            continue
        for box in root.descendants():
            classes = _classes(box)
            if "pair" in classes:
                partner = box.element.get("data-pair")
                if partner and partner.isdigit():
                    pair_pages.setdefault(int(partner), set()).add(number)
            elif "words-sec" in classes and (not word_pages or word_pages[-1] != number):
                word_pages.append(number)
    unpair = set(current.unpair) | {n for n, pages in pair_pages.items() if len(pages) > 1}
    compact = current.compact_words
    if (len(word_pages) > 1 and compact < 2
            and _page_fill(rendered.pages[word_pages[-1]]) < WORD_LIST_TAIL_FILL):
        compact += 1

    flow = set(current.flow)
    loose = set(current.loose)
    shrink = dict(current.shrink)
    if not one_task_per_page:
        pages = rendered.pages
        for i in range(len(pages) - 1):
            fill = _page_fill(pages[i])
            if fill >= LOW_FILL:
                continue
            unit = _first_unit(pages[i + 1])
            if unit is None or _on_page(pages[i], unit.element):
                continue  # a scene or back matter comes next, or the unit began on page i
            page_h = pages[i]._page_box.height * PX_TO_MM
            free = (1 - fill) * page_h - 8.0
            unit_h = unit.margin_height() * PX_TO_MM
            need = max(unit_h - free, 1.0)  # (it did not fit, even if only just)
            done = False
            for number, height, what in _shrinkable(unit):
                smallest = height * MIN_PICTURE_SCALE if what == "fig" else MIN_FRAME_H
                if number not in shrink and height - need >= smallest:
                    shrink[number] = round(height - need - 2.0, 1)
                    done = True
                    break
            if done:
                continue
            element = unit.element
            ident = element.get("id") or ""
            task_no = int(ident[5:]) if ident.startswith("task-") and ident[5:].isdigit() else None
            if task_no is not None and element.get("data-soft"):
                flow.add(task_no)
            elif task_no is not None and "flow" in _classes(unit):
                loose.add(task_no)
            elif "pair" in _classes(unit) and element.get("data-pair", "").isdigit():
                unpair.add(int(element.get("data-pair")))
    return LayoutHints(unpair=frozenset(unpair), compact_words=compact, flow=frozenset(flow),
                       loose=frozenset(loose), shrink=tuple(sorted(shrink.items())))


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def lay_out(ws: Worksheet, options: RenderOptions, part: Literal["worksheet", "solutions", "all"],
            api: tuple[Any, Any, Any], blocked: list[str],
            pictures: dict | None = None) -> tuple[str, Builder, Any]:
    """Build and lay out with WeasyPrint, correcting the build with
    :func:`layout_hints` until nothing changes (at most MAX_LAYOUT_PASSES
    layouts). The checks lay out the worksheet part only: the answer section
    always starts on a new page and is slow to set in columns."""
    check_part: Literal["worksheet", "solutions", "all"] = (
        "worksheet" if part == "all" else part)
    html, builder = _build(ws, options, check_part, pictures)
    pictures = builder._pictures
    hints = builder.hints
    if part != "solutions":
        rendered = _render(html, options.base_dir, api, blocked)
        for _ in range(MAX_LAYOUT_PASSES - 1):
            try:
                better = layout_hints(rendered, hints, options.one_task_per_page)
            except Exception:  # a WeasyPrint internals change only costs the correction
                break
            if better == hints:
                break
            hints = better
            html, builder = _build(ws, options, check_part, pictures, hints)
            rendered = _render(html, options.base_dir, api, blocked)
        if check_part == part:
            return html, builder, rendered
    html, final = _build(ws, options, part, pictures, hints)
    final.warnings = builder.warnings + [w for w in final.warnings if w not in builder.warnings]
    return html, final, _render(html, options.base_dir, api, blocked)


def render_worksheet(ws: Worksheet, out_pdf: Path, options: RenderOptions | None = None) -> RenderResult:
    """Write ``<out_pdf stem>.html`` and ``out_pdf`` (plus
    ``<stem>-solutions.pdf/.html`` when ``options.solutions == "separate"``)."""
    options = options or RenderOptions()
    out_pdf = Path(out_pdf)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    html_path = out_pdf.with_suffix(".html")
    sol_pdf_path = out_pdf.with_name(out_pdf.stem + "-solutions.pdf")

    part: Literal["worksheet", "all"] = "all" if options.solutions == "append" else "worksheet"
    html, builder = _build(ws, options, part)
    pictures = builder._pictures

    sol_html: str | None = None
    if options.solutions == "separate":
        # share the picture cache: no second download, no duplicate warnings
        sol_html, _ = _build(ws, options, "solutions", pictures)

    # picture warnings come from the first build only (later builds share its cache)
    warnings = list(builder.warnings)
    result = RenderResult(html=html_path, pdf=None, solutions_pdf=None, pages=None,
                          warnings=warnings, image_prompts=builder.image_prompts)

    def write_html() -> None:
        html_path.write_text(html.replace(FONT_MARKER, font_face_css(), 1), encoding="utf-8")
        if sol_html is not None:
            sol_pdf_path.with_suffix(".html").write_text(
                sol_html.replace(FONT_MARKER, font_face_css(), 1), encoding="utf-8")

    if options.html_only:
        write_html()
        return result
    try:
        api = _load_weasyprint()
    except (ImportError, OSError) as exc:
        write_html()
        result.weasyprint_error = f"{exc.__class__.__name__}: {exc}"
        return result

    blocked: list[str] = []
    html, builder, rendered = lay_out(ws, options, part, api, blocked, pictures)
    write_html()
    rendered.write_pdf(str(out_pdf))
    result.pages = len(rendered.pages)
    result.pdf = out_pdf
    warnings.extend(w for w in builder.warnings if w not in warnings)
    result.image_prompts = builder.image_prompts
    if sol_html is not None:
        _render(sol_html, options.base_dir, api, blocked).write_pdf(str(sol_pdf_path))
        result.solutions_pdf = sol_pdf_path
    for url in blocked:
        warnings.append(f"an external resource was not loaded (langwich renders offline): "
                        f"{url[:120]}")
    return result
