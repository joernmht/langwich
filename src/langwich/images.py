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

SVG written by an LLM is untrusted: scripts, ``<foreignObject>`` and every
reference to an outside resource (``href``, ``xlink:href``, ``src``, CSS
``url()`` and ``@import``) are removed before it is embedded, so a picture can
neither run code nor pull files or network resources into the PDF. HEIC/HEIF
photos are read when ``pillow-heif`` is installed; very large images are
decoded at a reduced size or refused with a warning instead of exhausting
memory.
"""

from __future__ import annotations

import base64
import binascii
import http.client
import io
import re
import urllib.parse
from urllib.parse import unquote, urlparse
import urllib.request
import warnings as _warnings
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal
from pathlib import Path

from langwich.model import Picture

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"

#: Longest edge of an embedded raster image, in pixels (≈ 340 dpi at 178 mm).
MAX_RASTER_EDGE = 2400
#: Refuse downloads and files larger than this.
MAX_BYTES = 25 * 1024 * 1024
URL_TIMEOUT = 15
USER_AGENT = "langwich/3 (worksheet renderer; +https://github.com/joernmht/langwich)"

#: Images with more pixels than this are refused unless they can be decoded
#: at a reduced size (JPEG): a small file can unpack into gigabytes.
MAX_PIXELS = 60_000_000

_RASTER_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif"}

_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif")


def _register_heif() -> bool:
    """Let Pillow open HEIC/HEIF (iPhone photos) when pillow-heif is installed."""
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return False
    try:
        register_heif_opener()
    except Exception:  # a broken pillow-heif must not break rendering
        return False
    return True


HEIF_SUPPORT = _register_heif()

#: The raster formats langwich decodes (Pillow's names). Pillow never sees
#: anything else from a worksheet: its EPS plugin, for one, runs Ghostscript
#: on the bytes. (HEIF and AVIF only when a plugin registered them.)
RASTER_FORMATS: tuple[str, ...] = (
    "JPEG", "MPO", "PNG", "GIF", "WEBP", "TIFF", "BMP", "HEIF", "AVIF",
)

#: First bytes of the raster formats WeasyPrint may decode from a data: URI.
_RASTER_SIGNATURES: tuple[bytes, ...] = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a")


def open_raster(raw: bytes) -> PILImage:
    """``Image.open`` for picture bytes, limited to :data:`RASTER_FORMATS`
    (those registered); anything else raises ``UnidentifiedImageError``."""
    from PIL import Image

    Image.init()
    formats = [f for f in RASTER_FORMATS if f in Image.OPEN]
    return Image.open(io.BytesIO(raw), formats=formats)


def is_safe_data_uri(url: str) -> bool:
    """May WeasyPrint decode this ``data:`` URI? An SVG (by its media type),
    or a PNG, JPEG, GIF or WebP picture (by its first bytes). WeasyPrint hands
    any other image to Pillow, which picks its decoder from the content, not
    the media type: EPS bytes inside an SVG's ``<image>`` would reach Ghostscript."""
    header, sep, payload = url.partition(",")
    if not sep or not header.lower().startswith("data:"):
        return False
    media = header[5:].split(";", 1)[0].strip().lower()
    if media == "image/svg+xml":
        return True
    try:
        if ";base64" in header.lower():
            head = base64.b64decode(re.sub(r"\s+", "", payload[:64])[:32] + "==", validate=False)
        else:
            head = urllib.parse.unquote_to_bytes(payload[:64])
    except (ValueError, binascii.Error):
        return False
    return head.startswith(_RASTER_SIGNATURES) or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")


def _shorten(source: str, limit: int = 80) -> str:
    """``source`` for a message: a data: URI or long path cut to ``limit``."""
    return source if len(source) <= limit else source[: limit - 1] + "…"


def looks_like_heif(raw: bytes) -> bool:
    """HEIC/HEIF/AVIF container (``ftyp`` box with a HEIF brand)."""
    return raw[4:8] == b"ftyp" and raw[8:12] in _HEIF_BRANDS


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


_DANGEROUS_TAGS = frozenset({"script", "foreignobject", "iframe", "object", "embed", "audio",
                             "video", "handler", "listener"})
#: An external url(…): anything but an internal reference, which may be
#: quoted or spaced (url(#g), url('#g'), url( "#g" )).
_CSS_URL = re.compile(r"url\((?!\s*['\"]?\s*#)[^)]*\)", re.IGNORECASE)
_CSS_IMPORT = re.compile(r"@import\b[^;]*;?", re.IGNORECASE)


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1].lower()


def _safe_ref(value: str) -> bool:
    value = value.strip()
    return value.startswith("#") or value.lower().startswith("data:image/")


def sanitize_svg(root: ET.Element) -> list[str]:
    """Remove scripts and outside references from an SVG tree *in place*.

    Returns a description of each removal (empty when the SVG was clean).
    Internal references (``#id``) and embedded ``data:image/…`` stay.
    """
    removed: list[str] = []
    parents = {child: parent for parent in root.iter() for child in parent}
    for el in list(root.iter()):
        tag = _local(el.tag) if isinstance(el.tag, str) else ""
        if tag in _DANGEROUS_TAGS:
            parent = parents.get(el)
            if parent is not None:
                parent.remove(el)
                removed.append(f"<{tag}>")
            continue
        for attr in list(el.attrib):
            name = _local(attr)
            value = el.attrib[attr]
            if name.startswith("on"):
                del el.attrib[attr]
                removed.append(f"{name}=")
            elif name in ("href", "src") and not _safe_ref(value):
                del el.attrib[attr]
                removed.append(f"{name}={value[:60]!r}")
            elif name == "style" and (_CSS_URL.search(value) or _CSS_IMPORT.search(value)):
                el.attrib[attr] = _CSS_IMPORT.sub("", _CSS_URL.sub("none", value))
                removed.append("style url()")
            elif _CSS_URL.search(value) and name in ("fill", "stroke", "filter", "mask",
                                                      "clip-path", "marker-start", "marker-mid",
                                                      "marker-end", "cursor"):
                el.attrib[attr] = _CSS_URL.sub("none", value)
                removed.append(f"{name} url()")
        if tag == "style" and el.text and (_CSS_URL.search(el.text) or _CSS_IMPORT.search(el.text)):
            el.text = _CSS_IMPORT.sub("", _CSS_URL.sub("none", el.text))
            removed.append("<style> url()")
    return removed


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
    if _local(root.tag) != "svg":
        warnings.append(f"{what}: the SVG has no <svg> root element; the picture is left out.")
        return None
    removed = sanitize_svg(root)
    if removed:
        ET.register_namespace("", SVG_NS)
        ET.register_namespace("xlink", XLINK_NS)
        svg = ET.tostring(root, encoding="unicode")
        warnings.append(f"{what}: removed from the SVG (scripts and outside resources are never "
                        f"loaded): {', '.join(dict.fromkeys(removed))}.")
    w, h = _int_size(*_svg_size(root))
    data = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return PreparedPicture(f"data:image/svg+xml;base64,{data}", w, h, is_vector=True)


# ---------------------------------------------------------------------------
# Raster
# ---------------------------------------------------------------------------


def _svg_prolog_end(head: bytes) -> int:
    """Where the element after the prolog starts: whitespace, comments,
    processing instructions (the XML declaration) and a doctype are skipped.

    A plain scan, linear in ``len(head)``: a backtracking regex for this
    took exponential time on a long whitespace run or a row of comments that
    is not followed by <svg."""
    pos, end = 0, len(head)
    while pos < end:
        if head[pos] in b" \t\r\n\f\v":
            pos += 1
            continue
        for opening, closing in ((b"<!--", b"-->"), (b"<?", b"?>"), (b"<!doctype", b">")):
            if head.startswith(opening, pos):
                found = head.find(closing, pos + len(opening))
                if found < 0:
                    return end  # unclosed: no element follows
                pos = found + len(closing)
                break
        else:
            return pos
    return pos


def _looks_like_svg(raw: bytes) -> bool:
    head = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head) or (
        head.startswith(b"<!doctype svg")
    ) or head.startswith(b"<svg", _svg_prolog_end(head))


def is_svg_source(image: str, raw: bytes) -> bool:
    """Is the picture.image ``image`` (with the bytes ``raw``) an SVG: by its
    content, a ``data:image/svg+xml`` media type, or a ``.svg`` name?"""
    low = image.strip().lower()
    return (_looks_like_svg(raw) or low.startswith("data:image/svg+xml")
            or low.split("?")[0].endswith(".svg"))


def _unreadable(raw: bytes, what: str, name: str, exc: Exception) -> str:
    """A warning a person can act on (no Pillow internals, no BytesIO reprs)."""
    label = f" {name!r}" if name else ""
    if looks_like_heif(raw) and not HEIF_SUPPORT:
        return (f"{what}: the image{label} is a HEIC/HEIF photo, which cannot be read without "
                "pillow-heif; export it as JPEG (or run 'pip install pillow-heif'). "
                "The picture is left out.")
    reason = str(exc)
    if "cannot identify image file" in reason:
        reason = "not an image format langwich can read (use JPEG, PNG, WebP or GIF)"
    else:
        reason = re.sub(r"<_io\.BytesIO object at 0x[0-9a-f]+>", "the file", reason)
        reason = f"{exc.__class__.__name__}: {reason}"
    return f"{what}: the image{label} could not be read ({reason}); the picture is left out."


def to_8bit(img: PILImage) -> PILImage:
    """``img`` with 8-bit samples. Pillow's ``convert('L')`` clips 16-bit
    greyscale ('I;16', 'I') at 255, which prints a white box; the samples are
    scaled instead, by the bit depth the brightest one needs: 10-, 12- and
    14-bit data is often stored in 16 bits without being scaled up, and
    dividing it by 65535 would leave a near-black picture."""
    if img.mode.startswith("I;16"):
        img = img.convert("I")
    if img.mode == "I":
        high = img.getextrema()[1]  # one band: (low, high) numbers
        if isinstance(high, (int, float)) and high > 255:
            bits = int(high).bit_length()  # 4095 → 12 bits, 65535 → 16
            scale = 255 / (2 ** bits - 1)
            img = img.point(lambda v: v * scale)
        img = img.convert("L")
    return img


def prepare_raster(raw: bytes, monochrome: bool, what: str, warnings: list[str],
                   name: str = "") -> PreparedPicture | None:
    """Decode raster bytes with Pillow; greyscale + autocontrast for monochrome
    output, scaled to print resolution, re-encoded as PNG (or JPEG for large
    colour photos). ``name`` (the file or URL) is used in warnings."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        warnings.append(f"{what}: Pillow is not installed, so the image cannot be embedded.")
        return None
    label = f" {name!r}" if name else ""
    try:
        with _warnings.catch_warnings():
            # Pillow's own bomb check is replaced by the size check below
            _warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            limit, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, None
            try:
                with open_raster(raw) as probe:
                    probe.verify()
                img: Image.Image = open_raster(raw)
            finally:
                Image.MAX_IMAGE_PIXELS = limit
        fmt = img.format or ""
        pixels = img.size[0] * img.size[1]
        if pixels > MAX_PIXELS:
            if fmt == "JPEG":
                # decode at 1/2, 1/4 or 1/8 of the size: cheap, and still sharp
                img.draft("RGB" if img.mode not in ("L", "1") else "L",
                          (MAX_RASTER_EDGE, MAX_RASTER_EDGE))
            if img.size[0] * img.size[1] > MAX_PIXELS:
                w, h = img.size
                warnings.append(
                    f"{what}: the image{label} is too large ({w} × {h} pixels); scale it down to "
                    f"at most {MAX_RASTER_EDGE * 2} pixels on the long edge. "
                    "The picture is left out.")
                return None
        img.load()
        img = ImageOps.exif_transpose(img) or img
        # 16-bit samples ('I;16', 'I'): never passed through as they are
        deep = img.mode.startswith("I")
        img = to_8bit(img)
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
        elif not resized and not deep and fmt in _RASTER_MIME:
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
        warnings.append(_unreadable(raw, what, name, exc))
        return None
    if not width or not height:
        warnings.append(f"{what}: the image{label} has no size; the picture is left out.")
        return None
    uri = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return PreparedPicture(uri, width, height, is_vector=False)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


@dataclass(frozen=True)
class ImageSource:
    """Where a ``picture.image`` points: ``kind`` is ``'data'`` (a data: URI),
    ``'url'`` (http/https), ``'file'`` (with ``path``) or ``'unsupported'``
    (another URL scheme, which the renderer cannot load)."""

    kind: Literal["data", "url", "file", "unsupported"]
    path: Path | None = None


def resolve_image(image: str, base_dir: Path | None) -> ImageSource:
    """Resolve ``picture.image``: ``data:`` URIs and ``http(s)://`` URLs in any
    letter case, ``file:`` URLs percent-decoded, ``~`` expanded, relative
    paths against ``base_dir`` (the folder of the JSON file; the current
    directory when ``None``)."""
    source = image.strip()
    low = source.lower()
    if low.startswith("data:"):
        return ImageSource("data")
    if low.startswith(("http://", "https://")):
        return ImageSource("url")
    if low.startswith("file:"):
        path = Path(unquote(urlparse(source).path)).expanduser()
    elif _URL_RE.match(source):
        return ImageSource("unsupported")
    else:
        path = Path(source).expanduser()
    if not path.is_absolute():
        path = (base_dir if base_dir is not None else Path.cwd()) / path
    return ImageSource("file", path)


def _read_source(source: str, base_dir: Path | None, what: str, warnings: list[str]) -> bytes | None:
    try:
        low = source.strip().lower()
        if low.startswith("data:"):
            header, _, payload = source.strip().partition(",")
            if ";base64" in header.lower():
                return base64.b64decode(payload, validate=False)
            return urllib.parse.unquote_to_bytes(payload)
        if low.startswith(("http://", "https://")):
            request = urllib.request.Request(source.strip(), headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=URL_TIMEOUT) as response:
                raw = response.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                warnings.append(f"{what}: {source} is larger than {MAX_BYTES // 2**20} MB; left out.")
                return None
            return raw
        resolved = resolve_image(source, base_dir)
        if resolved.kind == "unsupported" or resolved.path is None:
            warnings.append(f"{what}: {_shorten(source)!r} is not a file path, http(s) URL or "
                            "data: URI; left out.")
            return None
        path = resolved.path
        if not path.is_file():
            warnings.append(f"{what}: image file not found: {path}")
            return None
        if path.stat().st_size > MAX_BYTES:
            warnings.append(f"{what}: {path} is larger than {MAX_BYTES // 2**20} MB; left out.")
            return None
        return path.read_bytes()
    except (OSError, ValueError, binascii.Error, http.client.HTTPException) as exc:
        # (a server that breaks the protocol raises HTTPException, not OSError)
        warnings.append(f"{what}: could not load image {_shorten(source)!r} "
                        f"({exc.__class__.__name__}: {_shorten(str(exc), 200)}).")
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
        warnings.append(f"{what}: the image {_shorten(picture.image)!r} is empty; the picture "
                        "is left out.")
        return None
    if is_svg_source(picture.image, raw):
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            warnings.append(f"{what}: {_shorten(picture.image)!r} is not UTF-8 SVG; the picture "
                            "is left out.")
            return None
        return svg_from_text(text, what, warnings)
    name = "" if picture.image.startswith("data:") else picture.image.strip()
    return prepare_raster(raw, monochrome, what, warnings, name=name)
