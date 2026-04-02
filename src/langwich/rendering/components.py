"""Reusable PDF components — info boxes, writing lines, drawing areas, etc.

All functions return lists of ReportLab ``Flowable`` objects that can be
appended to a PDF story.
"""

from __future__ import annotations

from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.platypus import (
    Flowable,
    HRFlowable,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from langwich.rendering.styles import (
    BORDER_GREY,
    BRAND_ACCENT_SOFT,
    BRAND_DARK,
    BRAND_LIGHT,
    SPACE_SM,
    body_style,
)


def info_box(text: str, width: float | None = None) -> list[Flowable]:
    """Render text inside a rounded, lightly shaded box.

    Used for reading passages, word banks, and informational callouts.
    """
    para = Paragraph(text, body_style())
    table = Table(
        [[para]],
        colWidths=[width or 16 * cm],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.75, BORDER_GREY),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("ROUNDEDCORNERS", [6, 6, 6, 6]),
    ]))
    return [table, Spacer(1, SPACE_SM)]


def writing_lines(count: int = 3, width: float | None = None) -> list[Flowable]:
    """Render a set of evenly-spaced horizontal writing lines."""
    flowables: list[Flowable] = []
    line_width = width or 16 * cm
    for _ in range(count):
        flowables.append(Spacer(1, 0.6 * cm))
        flowables.append(
            HRFlowable(
                width=line_width,
                thickness=0.5,
                color=BORDER_GREY,
                spaceAfter=2,
            )
        )
    return flowables


class DrawingBoxFlowable(Flowable):
    """A bordered rectangular area for drawing/sketching tasks."""

    def __init__(self, width: float, height: float) -> None:
        super().__init__()
        self.width = width
        self.height = height

    def draw(self) -> None:
        self.canv.setStrokeColor(BORDER_GREY)
        self.canv.setLineWidth(0.75)
        self.canv.setFillColor(colors.white)
        self.canv.roundRect(0, 0, self.width, self.height, radius=6, fill=1, stroke=1)


def drawing_box(height_cm: float = 8, width: float | None = None) -> Flowable:
    """Return a bordered drawing area flowable."""
    return DrawingBoxFlowable(
        width=width or 16 * cm,
        height=height_cm * cm,
    )


def section_divider() -> list[Flowable]:
    """A thin horizontal rule to separate exercise sections."""
    return [
        Spacer(1, SPACE_SM),
        HRFlowable(width="100%", thickness=1, color=BORDER_GREY, spaceAfter=SPACE_SM),
    ]
