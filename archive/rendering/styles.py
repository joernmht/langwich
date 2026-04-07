"""Cupertino-style PDF typography and colour definitions.

Design principles
─────────────────
- Clean, modern sans-serif typography (Helvetica family)
- Generous whitespace — optimised for e-paper legibility
- Muted colour palette: dark grey text, soft accent colours
- Consistent spacing scale based on 4pt increments
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT

# ── Colour Palette ───────────────────────────────────────────────────

BRAND_DARK = colors.HexColor("#1D1D1F")       # Near-black for body text
BRAND_GREY = colors.HexColor("#6E6E73")        # Secondary text
BRAND_LIGHT = colors.HexColor("#F5F5F7")       # Background fills
BRAND_ACCENT = colors.HexColor("#0071E3")       # Links, highlights
BRAND_ACCENT_SOFT = colors.HexColor("#E8F0FE")  # Light accent bg
BORDER_GREY = colors.HexColor("#D2D2D7")        # Borders, rules
WHITE = colors.white


# ── Spacing Scale (in points) ───────────────────────────────────────

SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 20
SPACE_XL = 32


# ── Typography ───────────────────────────────────────────────────────

def title_style() -> ParagraphStyle:
    """Large section title — exercise headers."""
    return ParagraphStyle(
        "langwichTitle",
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=24,
        textColor=BRAND_DARK,
        spaceAfter=SPACE_MD,
        alignment=TA_LEFT,
    )


def subtitle_style() -> ParagraphStyle:
    """Sub-section title."""
    return ParagraphStyle(
        "langwichSubtitle",
        fontName="Helvetica-Bold",
        fontSize=14,
        leading=18,
        textColor=BRAND_DARK,
        spaceAfter=SPACE_SM,
        alignment=TA_LEFT,
    )


def instruction_style() -> ParagraphStyle:
    """Exercise instructions text — slightly emphasised."""
    return ParagraphStyle(
        "langwichInstruction",
        fontName="Helvetica-Oblique",
        fontSize=11,
        leading=15,
        textColor=BRAND_GREY,
        spaceAfter=SPACE_SM,
        alignment=TA_LEFT,
    )


def body_style() -> ParagraphStyle:
    """Standard body text."""
    return ParagraphStyle(
        "langwichBody",
        fontName="Helvetica",
        fontSize=11,
        leading=15,
        textColor=BRAND_DARK,
        spaceAfter=SPACE_XS,
        alignment=TA_LEFT,
    )


def header_style() -> ParagraphStyle:
    """Page header — brand name + metadata."""
    return ParagraphStyle(
        "langwichHeader",
        fontName="Helvetica-Bold",
        fontSize=9,
        leading=12,
        textColor=BRAND_GREY,
        alignment=TA_LEFT,
    )


def footer_style() -> ParagraphStyle:
    """Page footer — page numbers, date."""
    return ParagraphStyle(
        "langwichFooter",
        fontName="Helvetica",
        fontSize=8,
        leading=10,
        textColor=BRAND_GREY,
        alignment=TA_CENTER,
    )
