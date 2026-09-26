"""Load, convert and embed scene pictures — and never crash doing it.

A picture comes either as ``svg`` (line art written by the LLM) or as an
``image`` reference: a local path (relative paths resolve against the folder
of the worksheet JSON), an ``http(s)`` URL or a ``data:`` URI. Everything is
turned into a self-contained ``data:`` URI so the HTML and the PDF never
depend on files next to them.

Raster images are converted to high-contrast greyscale for monochrome output
(e-paper and black-and-white print) and scaled down to print resolution.
Anything that cannot be read produces a warning and ``None``: the renderer
then falls back to a drawing frame instead of failing the whole worksheet.
"""

from __future__ import annotations

import base64
import binascii
import io
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from langwich.model import Picture

SVG_NS = "http://www.w3.org/2000/svg"

#: Longest edge of an embedded raster image, in pixels (≈ 340 dpi at 178 mm).
MAX_RASTER_EDGE = 2400
#: Refuse downloads and files larger than this.
MAX_BYTES = 25 * 1024 * 1024
URL_TIMEOUT = 15
USER_AGENT = "langwich/3 (worksheet renderer; +https://github.com/joernmht/langwich)"

_RASTER_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif"}


@dataclass
class PreparedPicture:
    """A picture ready to embed: a ``data:`` URI plus its intrinsic size.

    ``width``/``height`` are pixels for raster images and a scaled copy of
    the viewBox for SVG (only the ratio matters to the layout).
    """

    data_uri: str
    width: int
    height: int
    is_vector: bool

    @property
    def aspect(self) -> float:
        """Height divided by width."""
        return self.height / self.width if self.width else 0.75


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_NUM_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _length(value: str | None) -> float | None:
    if not value:
        return None
    m = _NUM_RE.match(value.strip())
    if not m or value.strip().endswith("%"):
        return None
    number = float(m.group(0))
    return number if number > 0 else None


def _svg_size(root: ET.Element) -> tuple[float, float]:
    view_box = root.get("viewBox") or root.get("viewbox")
    if view_box:
        nums = [float(n) for n in _NUM_RE.findall(view_box)]
        if len(nums) == 4 and nums[2] > 0 and nums[3] > 0:
            return nums[2], nums[3]
    w, h = _length(root.get("width")), _length(root.get("height"))
    if w and h:
        return w, h
    return 400.0, 300.0


def _int_size(w: float, h: float) -> tuple[int, int]:
    """Scale a (possibly tiny or fractional) size to integers that keep the ratio."""
    scale = 1000.0 / max(w, h)
    return max(1, round(w * scale)), max(1, round(h * scale))


def svg_from_text(text: str, what: str, warnings: list[str]) -> PreparedPicture | None:
    """Extract the ``<svg>`` element from ``text`` and embed it.

    Tolerates code fences or an XML declaration around the element; adds the
    SVG namespace when the LLM left it out. Invalid XML gives a warning.
    """
    start = text.lower().find("<svg")
    end = text.lower().rfind("</svg>")
    if start < 0 or end < start:
        warnings.append(f"{what}: no complete <svg>…</svg> element found; the picture is left out.")
        return None
    svg = text[start:end + len("</svg>")]
    opening = _SVG_OPEN_RE.match(svg)
    if opening and "xmlns=" not in opening.group(0):
        svg = svg[:4] + f' xmlns="{SVG_NS}"' + svg[4:]
    if "xlink:" in svg and "xmlns:xlink" not in (opening.group(0) if opening else ""):
        svg = svg[:4] + ' xmlns:xlink="http://www.w3.org/1999/xlink"' + svg[4:]
    try:
        root = ET.fromstring(svg)
    except ET.ParseError as exc:
        warnings.append(f"{what}: the SVG is not valid XML ({exc}); the picture is left out.")
        return None
    w, h = _int_size(*_svg_size(root))
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return PreparedPicture(f"data:image/svg+xml;base64,{data}", w, h, is_vector=True)


# ---------------------------------------------------------------------------
# Raster
# ---------------------------------------------------------------------------


def _looks_like_svg(raw: bytes) -> bool:
    head = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head) or (
        head.startswith(b"<!doctype svg")
    )


def prepare_raster(raw: bytes, monochrome: bool, what: str, warnings: list[str]) -> PreparedPicture | None:
    """Decode raster bytes with Pillow; greyscale + autocontrast for monochrome
    output, scaled to print resolution, re-encoded as PNG (or JPEG for large
    colour photos)."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        warnings.append(f"{what}: Pillow is not installed, so the image cannot be embedded.")
        return None
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        img = Image.open(io.BytesIO(raw))
        fmt = img.format or ""
        img.load()
        img = ImageOps.exif_transpose(img) or img
        resized = max(img.size) > MAX_RASTER_EDGE
        if resized:
            img.thumbnail((MAX_RASTER_EDGE, MAX_RASTER_EDGE), Image.Resampling.LANCZOS)
        if monochrome:
            if img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info):
                background = Image.new("RGBA", img.size, (255, 255, 255, 255))
                background.alpha_composite(img.convert("RGBA"))
                img = background
            img = ImageOps.autocontrast(img.convert("L"), cutoff=1)
            out, mime = io.BytesIO(), "image/png"
            img.save(out, "PNG", optimize=True)
            data = out.getvalue()
        elif not resized and fmt in _RASTER_MIME:
            data, mime = raw, _RASTER_MIME[fmt]
        else:
            out = io.BytesIO()
            if img.mode in ("RGBA", "LA", "P"):
                img.convert("RGBA").save(out, "PNG", optimize=True)
                mime = "image/png"
            else:
                img.convert("RGB").save(out, "JPEG", quality=88, optimize=True)
                mime = "image/jpeg"
            data = out.getvalue()
        width, height = img.size
    except Exception as exc:  # Pillow raises many different types for bad data
        warnings.append(f"{what}: the image could not be read ({exc.__class__.__name__}: {exc}); "
                        "the picture is left out.")
        return None
    if not width or not height:
        warnings.append(f"{what}: the image has no size; the picture is left out.")
        return None
    uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return PreparedPicture(uri, width, height, is_vector=False)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def _read_source(source: str, base_dir: Path | None, what: str, warnings: list[str]) -> bytes | None:
    try:
        if source.startswith("data:"):
            header, _, payload = source.partition(",")
            if ";base64" in header:
                return base64.b64decode(payload, validate=False)
            return urllib.parse.unquote_to_bytes(payload)
        if source.startswith(("http://", "https://")):
            request = urllib.request.Request(source, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=URL_TIMEOUT) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                warnings.append(f"{what}: {source} is larger than {MAX_BYTES // 2**20} MB; left out.")
                return None
            return raw
        path = Path(source[7:] if source.startswith("file://") else source).expanduser()
        if not path.is_absolute():
            path = (base_dir or Path.cwd()) / path
        if not path.is_file():
            warnings.append(f"{what}: image file not found: {path}")
            return None
        if path.stat().st_size > MAX_BYTES:
            warnings.append(f"{what}: {path} is larger than {MAX_BYTES // 2**20} MB; left out.")
            return None
        return path.read_bytes()
    except (OSError, ValueError, binascii.Error) as exc:
        warnings.append(f"{what}: could not load image {source!r} ({exc.__class__.__name__}: {exc}).")
        return None


def prepare_picture(
    picture: Picture,
    base_dir: Path | None,
    monochrome: bool,
    warnings: list[str],
    *,
    what: str = "picture",
) -> PreparedPicture | None:
    """Turn a :class:`~langwich.model.Picture` into an embeddable picture.

    ``svg`` wins over ``image``. Returns ``None`` (after appending a warning
    when something was wrong) if there is nothing that can be shown.
    """
    if picture.svg:
        return svg_from_text(picture.svg, what, warnings)
    if not picture.image:
        return None
    raw = _read_source(picture.image.strip(), base_dir, what, warnings)
    if raw is None:
        return None
    if not raw:
        warnings.append(f"{what}: the image {picture.image!r} is empty; the picture is left out.")
        return None
    if _looks_like_svg(raw) or picture.image.lower().split("?")[0].endswith(".svg"):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            warnings.append(f"{what}: {picture.image!r} is not UTF-8 SVG; the picture is left out.")
            return None
        return svg_from_text(text, what, warnings)
    return prepare_raster(raw, monochrome, what, warnings)
