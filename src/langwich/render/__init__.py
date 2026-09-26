"""Render a ``langwich/3`` worksheet to HTML and PDF.

``build_html`` produces a self-contained HTML document (print CSS, bundled
fonts via ``file://`` URIs, pictures as ``data:`` URIs). ``render_worksheet``
writes that HTML next to the PDF and converts it with WeasyPrint. WeasyPrint
is imported lazily: without it (or without its system libraries) the HTML is
still written and :attr:`RenderResult.weasyprint_error` explains why there is
no PDF.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from langwich.model import Worksheet
from langwich.render.css import font_face_css
from langwich.render.html import FONT_MARKER, Builder
from langwich.render.options import RenderOptions, RenderResult

__all__ = ["RenderOptions", "RenderResult", "build_html", "render_worksheet"]


def _build(
    ws: Worksheet,
    options: RenderOptions,
    part: Literal["worksheet", "solutions", "all"],
    pictures: dict | None = None,
) -> tuple[str, Builder]:
    builder = Builder(ws, options, pictures)
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


def _load_weasyprint() -> tuple[Any, Any, Any]:
    import weasyprint
    from weasyprint.text.fonts import FontConfiguration

    return weasyprint.HTML, weasyprint.CSS, FontConfiguration


def _write_pdf(html: str, out_pdf: Path, base_dir: Path | None, api: tuple[Any, Any, Any]) -> int:
    html_cls, css_cls, font_config_cls = api
    font_config = font_config_cls()
    fonts = css_cls(string=font_face_css(), font_config=font_config)
    doc = html_cls(string=html.replace(FONT_MARKER, "", 1),
                   base_url=str(base_dir or Path.cwd()) + "/")
    rendered = doc.render(stylesheets=[fonts], font_config=font_config)
    rendered.write_pdf(str(out_pdf))
    return len(rendered.pages)


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
    warnings = builder.warnings
    html_path.write_text(html.replace(FONT_MARKER, font_face_css(), 1), encoding="utf-8")

    sol_html: str | None = None
    if options.solutions == "separate":
        # share the picture cache: no second download, no duplicate warnings
        sol_html, _ = _build(ws, options, "solutions", builder._pictures)
        sol_pdf_path.with_suffix(".html").write_text(
            sol_html.replace(FONT_MARKER, font_face_css(), 1), encoding="utf-8")

    result = RenderResult(html=html_path, pdf=None, solutions_pdf=None, pages=None,
                          warnings=warnings, image_prompts=builder.image_prompts)
    if options.html_only:
        return result
    try:
        api = _load_weasyprint()
    except (ImportError, OSError) as exc:
        result.weasyprint_error = f"{exc.__class__.__name__}: {exc}"
        return result
    result.pages = _write_pdf(html, out_pdf, options.base_dir, api)
    result.pdf = out_pdf
    if sol_html is not None:
        _write_pdf(sol_html, sol_pdf_path, options.base_dir, api)
        result.solutions_pdf = sol_pdf_path
    return result
