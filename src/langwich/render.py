"""Lean PDF renderer for langwich worksheets.

Modern, clean design using ReportLab. Renders exercises generated from the
exercise graph into a printable A4 worksheet.
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Circle, Drawing, Line, Polygon
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from langwich.generate import ExerciseInstance
from langwich.text import SourceText


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

TEXT_DARK = colors.HexColor("#1a1a2e")
TEXT_GREY = colors.HexColor("#6b7280")
ACCENT = colors.HexColor("#2563eb")
ACCENT_LIGHT = colors.HexColor("#eff6ff")
BORDER = colors.HexColor("#e5e7eb")
BG_LIGHT = colors.HexColor("#f9fafb")

PAGE_W, PAGE_H = A4
MARGIN = 2 * cm
CONTENT_W = PAGE_W - 2 * MARGIN


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=20,
            textColor=TEXT_DARK, spaceAfter=4 * mm, leading=24,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName="Helvetica", fontSize=10,
            textColor=TEXT_GREY, spaceAfter=8 * mm,
        ),
        "section": ParagraphStyle(
            "section", fontName="Helvetica-Bold", fontSize=13,
            textColor=ACCENT, spaceBefore=6 * mm, spaceAfter=3 * mm, leading=16,
        ),
        "instruction": ParagraphStyle(
            "instruction", fontName="Helvetica-Oblique", fontSize=10,
            textColor=TEXT_GREY, spaceAfter=3 * mm, leading=13,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=10.5,
            textColor=TEXT_DARK, spaceAfter=2 * mm, leading=14,
        ),
        "item": ParagraphStyle(
            "item", fontName="Helvetica", fontSize=10.5,
            textColor=TEXT_DARK, spaceAfter=4 * mm, leading=15,
            leftIndent=6 * mm,
        ),
        "word_bank": ParagraphStyle(
            "word_bank", fontName="Helvetica-Bold", fontSize=10,
            textColor=ACCENT, spaceAfter=4 * mm, leading=13,
            borderColor=ACCENT_LIGHT, borderWidth=0,
        ),
        "small": ParagraphStyle(
            "small", fontName="Helvetica", fontSize=8,
            textColor=TEXT_GREY, leading=10,
        ),
        "reading": ParagraphStyle(
            "reading", fontName="Helvetica", fontSize=10,
            textColor=TEXT_DARK, spaceAfter=2 * mm, leading=14,
            leftIndent=3 * mm, rightIndent=3 * mm,
        ),
        "picture_prompt": ParagraphStyle(
            "picture_prompt", fontName="Helvetica-Oblique", fontSize=8,
            textColor=TEXT_GREY, spaceAfter=2 * mm, leading=10,
        ),
    }


def _humanize_topic(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Header / footer
# ---------------------------------------------------------------------------

def _header_footer(canvas, doc, text: SourceText):
    canvas.saveState()
    # Header
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(TEXT_GREY)
    canvas.drawString(MARGIN, PAGE_H - 1.2 * cm,
                      f"langwich  |  {_humanize_topic(text.topic)}  |  {text.cefr_level}")
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 1.2 * cm,
                           f"{text.source_lang.upper()} → {text.target_lang.upper()}")
    # Header rule
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, PAGE_H - 1.4 * cm, PAGE_W - MARGIN, PAGE_H - 1.4 * cm)
    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.drawCentredString(PAGE_W / 2, 1 * cm, f"– {doc.page} –")
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------

def _text_box(text_content: str, styles: dict, width: float) -> list:
    """Render text in a light background box."""
    para = Paragraph(text_content.replace("\n", "<br/>"), styles["reading"])
    t = Table([[para]], colWidths=[width - 6 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [3, 3, 3, 3]),
    ]))
    return [t, Spacer(1, 3 * mm)]


def _writing_lines(count: int = 3, width: float = CONTENT_W) -> list:
    """Render horizontal writing lines."""
    elements = []
    for _ in range(count):
        t = Table([[""]],  colWidths=[width], rowHeights=[8 * mm])
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
        ]))
        elements.append(t)
    return elements


def _picture_placeholder(prompt: str, styles: dict, width: float) -> list:
    """Render a picture placeholder box with the generation prompt."""
    elements = []
    # Bordered box for the picture
    t = Table([["[Picture placeholder — generate with the prompt below]"]],
              colWidths=[width - 6 * mm], rowHeights=[8 * cm])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, BORDER),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_GREY),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 2 * mm))
    elements.append(Paragraph(
        f"<b>Image prompt:</b> {prompt}", styles["picture_prompt"]
    ))
    elements.append(Spacer(1, 3 * mm))
    return elements


def _qr_flowable(url: str, size: float = 22 * mm) -> Drawing:
    """QR code as a platypus flowable."""
    widget = QrCodeWidget(url)
    x0, y0, x1, y1 = widget.getBounds()
    d = Drawing(size, size,
                transform=[size / (x1 - x0), 0, 0, size / (y1 - y0), 0, 0])
    d.add(widget)
    return d


def _resource_box(resource: dict, styles: dict, width: float) -> list:
    """Culture-library resource card: title + description + QR code."""
    url = resource.get("url", "")
    title = resource.get("title", "")
    desc = resource.get("description", "")
    scan_label = resource.get("scan_label", "Scan to open:")

    text_parts = [f"<b>{title}</b>"]
    if desc:
        text_parts.append(f"<font size='8.5' color='#6b7280'>{desc}</font>")
    text_parts.append(f"<font size='7' color='#2563eb'>{url}</font>")
    info = Paragraph("<br/>".join(text_parts), styles["body"])
    scan = Paragraph(f"<font size='6.5' color='#6b7280'>{scan_label}</font>",
                     styles["small"])

    qr_size = 20 * mm
    t = Table([[info, [scan, Spacer(1, 1 * mm), _qr_flowable(url, qr_size)]]],
              colWidths=[width - qr_size - 14 * mm, qr_size + 8 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (1, 0), (1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [3, 3, 3, 3]),
    ]))
    return [t, Spacer(1, 3 * mm)]


def _star_points(cx: float, cy: float, r_outer: float, r_inner: float) -> list[float]:
    pts: list[float] = []
    for i in range(10):
        r = r_outer if i % 2 == 0 else r_inner
        angle = math.pi / 2 + i * math.pi / 5
        pts.extend([cx + r * math.cos(angle), cy + r * math.sin(angle)])
    return pts


def _stars_drawing(count: int = 5, size: float = 7 * mm) -> Drawing:
    """Row of outline stars for the learner to colour in."""
    gap = size * 0.25
    d = Drawing(count * (size + gap), size)
    for i in range(count):
        cx = i * (size + gap) + size / 2
        d.add(Polygon(
            _star_points(cx, size / 2, size / 2, size / 5),
            strokeColor=ACCENT, strokeWidth=0.8, fillColor=None,
        ))
    return d


def _clock_drawing(time_str: str, size: float = 20 * mm) -> Drawing:
    """Analogue clock face showing HH:MM."""
    hh, mm_ = (int(p) for p in time_str.split(":"))
    r = size / 2
    d = Drawing(size, size)
    d.add(Circle(r, r, r - 1, strokeColor=TEXT_DARK, strokeWidth=1,
                 fillColor=colors.white))
    for i in range(12):
        angle = math.pi / 2 - i * math.pi / 6
        x1 = r + (r - 2) * math.cos(angle)
        y1 = r + (r - 2) * math.sin(angle)
        x2 = r + (r - 4.5) * math.cos(angle)
        y2 = r + (r - 4.5) * math.sin(angle)
        d.add(Line(x1, y1, x2, y2, strokeColor=TEXT_DARK, strokeWidth=0.7))
    minute_angle = math.pi / 2 - (mm_ / 60.0) * 2 * math.pi
    hour_angle = math.pi / 2 - ((hh % 12 + mm_ / 60.0) / 12.0) * 2 * math.pi
    d.add(Line(r, r, r + (r - 6) * math.cos(minute_angle),
               r + (r - 6) * math.sin(minute_angle),
               strokeColor=TEXT_DARK, strokeWidth=1))
    d.add(Line(r, r, r + (r * 0.5) * math.cos(hour_angle),
               r + (r * 0.5) * math.sin(hour_angle),
               strokeColor=TEXT_DARK, strokeWidth=1.6))
    d.add(Circle(r, r, 1, fillColor=TEXT_DARK, strokeColor=TEXT_DARK))
    return d


def _letter_grid(grid: list[list[str]], width: float) -> Table:
    """Monospaced letter grid for word-search puzzles."""
    n_cols = len(grid[0])
    cell = min(6.5 * mm, (width - 10 * mm) / n_cols)
    t = Table([list(row) for row in grid],
              colWidths=[cell] * n_cols, rowHeights=[cell] * len(grid))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "Courier-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_DARK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOX", (0, 0), (-1, -1), 0.8, TEXT_DARK),
        ("INNERGRID", (0, 0), (-1, -1), 0.15, BORDER),
    ]))
    t.hAlign = "CENTER"
    return t


def _crossword_table(cw: dict, width: float) -> Table:
    """Empty crossword grid with clue numbers in the start cells."""
    w, h = cw["width"], cw["height"]
    cells = cw["cells"]  # "r,c" -> letter (not shown)
    numbers = cw["numbers"]  # "r,c" -> clue number
    cell = min(7 * mm, (width - 10 * mm) / max(w, 1))

    data = [["" for _ in range(w)] for _ in range(h)]
    for key, n in numbers.items():
        r, c = (int(p) for p in key.split(","))
        data[r][c] = str(n)

    style: list = [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 5.5),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_GREY),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 0.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 1),
    ]
    for r in range(h):
        for c in range(w):
            if f"{r},{c}" in cells:
                style.append(("BOX", (c, r), (c, r), 0.6, TEXT_DARK))
                style.append(("BACKGROUND", (c, r), (c, r), colors.white))

    t = Table(data, colWidths=[cell] * w, rowHeights=[cell] * h)
    t.setStyle(TableStyle(style))
    t.hAlign = "CENTER"
    return t


def _checkbox_rows(words: list[str], width: float) -> Table:
    """Words with empty tick boxes, two per row."""
    box, gap = 4.5 * mm, 2 * mm
    word_w = (width - 2 * (box + gap)) / 2 - 4 * mm
    rows, style = [], [
        ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_DARK),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]
    for i in range(0, len(words), 2):
        pair = words[i:i + 2]
        row = []
        for w in pair:
            row.extend(["", w])
        while len(row) < 4:
            row.extend(["", ""])
        rows.append(row)
    for r in range(len(rows)):
        for c in (0, 2):
            if rows[r][c + 1]:
                style.append(("BOX", (c, r), (c, r), 0.7, TEXT_DARK))
    t = Table(rows, colWidths=[box, word_w, box, word_w],
              rowHeights=[box + 2 * mm] * len(rows))
    t.setStyle(TableStyle(style))
    return t


def _chat_bubbles(count: int, width: float) -> list:
    """Alternating empty chat bubbles (left grey, right blue)."""
    elements: list = []
    bubble_w = width * 0.62
    for i in range(count):
        left = i % 2 == 0
        inner = Table([[""], [""]], colWidths=[bubble_w - 6 * mm],
                      rowHeights=[7 * mm, 7 * mm])
        inner.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (0, 0), 0.3, BORDER),
            ("LINEBELOW", (0, 1), (0, 1), 0.3, BORDER),
        ]))
        bg = BG_LIGHT if left else ACCENT_LIGHT
        bubble = Table([[inner]], colWidths=[bubble_w])
        bubble.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), bg),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("ROUNDEDCORNERS", (0, 0), (-1, -1), [4, 4, 4, 4]),
            ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
        ]))
        pad = width - bubble_w
        row = [[bubble, ""]] if left else [["", bubble]]
        widths = [bubble_w, pad] if left else [pad, bubble_w]
        outer = Table(row, colWidths=widths)
        outer.setStyle(TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        elements.append(outer)
        elements.append(Spacer(1, 2 * mm))
    return elements


def _frames_grid(spec: dict, styles: dict, width: float) -> list:
    """Empty sketch frames with caption lines (comic panels, storyboards)."""
    count = spec.get("count", 4)
    per_row = spec.get("per_row", 2)
    caption_lines = spec.get("caption_lines", 1)
    label = spec.get("frame_label", "")

    frame_w = (width - (per_row - 1) * 3 * mm) / per_row
    frame_h = max(28 * mm, min(45 * mm, frame_w * 0.75))

    elements: list = []
    for start in range(0, count, per_row):
        chunk = min(per_row, count - start)
        cells = []
        for i in range(chunk):
            content: list = []
            box = Table([[f"{label} {start + i + 1}".strip()]],
                        colWidths=[frame_w - 3 * mm], rowHeights=[frame_h])
            box.setStyle(TableStyle([
                ("BOX", (0, 0), (-1, -1), 0.7, TEXT_DARK),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 6.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_GREY),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]))
            content.append(box)
            for _ in range(caption_lines):
                line = Table([[""]], colWidths=[frame_w - 3 * mm],
                             rowHeights=[6 * mm])
                line.setStyle(TableStyle([
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
                ]))
                content.append(line)
            cells.append(content)
        while len(cells) < per_row:
            cells.append("")
        t = Table([cells], colWidths=[frame_w] * per_row)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 1 * mm),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3 * mm))
    return elements


def _fillable_table(spec: dict, styles: dict, width: float) -> Table:
    """Table with header row and (partially) empty cells to fill in."""
    headers = spec.get("headers", [])
    rows = spec.get("rows", [])
    row_h = spec.get("row_height", 8) * mm
    n_cols = max(len(headers), max((len(r) for r in rows), default=1))
    col_w = width / n_cols

    data = [headers] + [list(r) + [""] * (n_cols - len(r)) for r in rows]
    t = Table(data, colWidths=[col_w] * n_cols,
              rowHeights=[7 * mm] + [row_h] * len(rows))
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 9.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("TEXTCOLOR", (0, 1), (-1, -1), TEXT_DARK),
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT_LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]))
    return t


def _flashcards(cards: list[dict], styles: dict, width: float) -> list:
    """Cut-out flashcards: dashed borders, term big, translation small."""
    per_row = 2
    card_w = width / per_row
    elements: list = []
    for start in range(0, len(cards), per_row):
        chunk = cards[start:start + per_row]
        row = []
        for card in chunk:
            inner = [
                Paragraph(f"<para align='center'><b>{card['front']}</b></para>",
                          styles["body"]),
                Spacer(1, 4 * mm),
                Paragraph(f"<para align='center'><font size='8' color='#6b7280'>"
                          f"{card['back']}</font></para>", styles["small"]),
            ]
            row.append(inner)
        while len(row) < per_row:
            row.append("")
        t = Table([row], colWidths=[card_w] * per_row, rowHeights=[22 * mm])
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.5, TEXT_GREY, None, (2, 2)),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        elements.append(t)
    return elements


def _postcard(spec: dict, width: float) -> Table:
    """Postcard: message lines left, stamp box + address lines right."""
    message_lines = spec.get("message_lines", 6)
    address_lines = spec.get("address_lines", 3)
    left_w = width * 0.58
    right_w = width - left_w

    left_content: list = []
    for _ in range(message_lines):
        line = Table([[""]], colWidths=[left_w - 8 * mm], rowHeights=[8 * mm])
        line.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER)]))
        left_content.append(line)

    stamp = Table([[""]], colWidths=[16 * mm], rowHeights=[19 * mm])
    stamp.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.5, TEXT_GREY, None, (2, 2)),
    ]))
    stamp.hAlign = "RIGHT"
    right_content: list = [stamp, Spacer(1, 4 * mm)]
    for _ in range(address_lines):
        line = Table([[""]], colWidths=[right_w - 10 * mm], rowHeights=[8 * mm])
        line.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER)]))
        right_content.append(line)

    t = Table([[left_content, right_content]], colWidths=[left_w, right_w])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, TEXT_DARK),
        ("LINEAFTER", (0, 0), (0, 0), 0.4, BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
    ]))
    return t


def _tip_box(text_content: str, styles: dict, width: float) -> list:
    """Accent-coloured tip box."""
    para = Paragraph(f"<b>{text_content}</b>", ParagraphStyle(
        "tip", fontName="Helvetica", fontSize=9.5, textColor=ACCENT, leading=13,
    ))
    t = Table([[para]], colWidths=[width - 6 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), ACCENT_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, ACCENT),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [3, 3, 3, 3]),
    ]))
    return [t, Spacer(1, 2 * mm)]


# ---------------------------------------------------------------------------
# Exercise renderers
# ---------------------------------------------------------------------------

def _render_fib(ex: ExerciseInstance, styles: dict) -> list:
    elements: list = []
    elements.append(Paragraph(ex.title, styles["section"]))
    elements.append(Paragraph(ex.instruction, styles["instruction"]))

    if ex.word_bank:
        bank_text = "   ".join(f"<b>{w}</b>" for w in ex.word_bank)
        elements.extend(_text_box(bank_text, styles, CONTENT_W))

    for item in ex.items:
        text = f"<b>{item['number']}.</b>  {item['sentence']}"
        if "hint" in item:
            text += f"  <i>{item['hint']}</i>"
        if "choices" in item:
            choices = "  /  ".join(item["choices"])
            text += f"  [ {choices} ]"
        if "translation" in item:
            text += f"<br/><i><font size='9' color='#6b7280'>{item['translation']}</font></i>"
        elements.append(Paragraph(text, styles["item"]))

    return elements


_picture_rendered = False  # module-level flag to avoid duplicate placeholders


def _render_picture(ex: ExerciseInstance, styles: dict) -> list:
    global _picture_rendered
    elements: list = []
    elements.append(Paragraph(ex.title, styles["section"]))
    elements.append(Paragraph(ex.instruction, styles["instruction"]))

    if ex.picture_prompt and not _picture_rendered:
        elements.extend(_picture_placeholder(ex.picture_prompt, styles, CONTENT_W))
        _picture_rendered = True

    for item in ex.items:
        if "question" in item:
            elements.append(Paragraph(
                f"<b>{item.get('number', '')}.</b>  {item['question']}", styles["item"]
            ))
            elements.extend(_writing_lines(1))
        elif "instruction" in item:
            num = item.get("number", "")
            prefix = f"<b>{num}.</b>  " if num else ""
            elements.append(Paragraph(
                f"{prefix}{item['instruction']}", styles["item"]
            ))
            if "Beschreibe" in item["instruction"]:
                elements.extend(_writing_lines(5))
        elif "text" in item:
            elements.extend(_text_box(item["text"], styles, CONTENT_W))

    return elements


def _render_word_connections(ex: ExerciseInstance, styles: dict) -> list:
    elements: list = []
    elements.append(Paragraph(ex.title, styles["section"]))
    elements.append(Paragraph(ex.instruction, styles["instruction"]))

    for item in ex.items:
        if "left" in item and "right" in item:
            left = item["left"]
            right = item["right"]
            is_compound = item.get("format") == "compound"

            rows = []
            max_len = max(len(left), len(right))
            for i in range(max_len):
                l_text = f"{left[i]['number']}. {left[i]['term']}" if i < len(left) else ""
                r_text = f"{right[i]['letter']}. {right[i]['term']}" if i < len(right) else ""
                rows.append([l_text, "", r_text])

            t = Table(rows, colWidths=[CONTENT_W * 0.4, CONTENT_W * 0.2, CONTENT_W * 0.4])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_DARK),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
                ("ALIGN", (2, 0), (2, -1), "RIGHT"),
            ]))
            elements.append(t)

            if is_compound:
                elements.append(Spacer(1, 3 * mm))
                elements.append(Paragraph(
                    "<b>Write the compound words:</b>", styles["body"]
                ))
                elements.extend(_writing_lines(len(right)))

        elif "words" in item and "categories" in item:
            # Category grouping
            words = "   ".join(f"<b>{w}</b>" for w in item["words"])
            elements.extend(_text_box(words, styles, CONTENT_W))
            for cat in item["categories"]:
                elements.append(Paragraph(f"<b>{cat}:</b>", styles["body"]))
                elements.extend(_writing_lines(1))
                elements.append(Spacer(1, 2 * mm))

        elif "left_column" in item and "right_column" in item:
            # Compound matching
            rows = []
            for i, (left, right) in enumerate(
                zip(item["left_column"], item["right_column"]), 1
            ):
                rows.append([f"{i}. {left}  +", f"{right}  =  _______________"])

            t = Table(rows, colWidths=[CONTENT_W * 0.4, CONTENT_W * 0.6])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_DARK),
                ("TOPPADDING", (0, 0), (-1, -1), 2 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2 * mm),
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
            ]))
            elements.append(t)

        elif "term" in item:
            elements.append(Paragraph(
                f"<b>{item['number']}.</b>  {item['term']}  →  _______________",
                styles["item"],
            ))

    return elements


def _render_generic(ex: ExerciseInstance, styles: dict) -> list:
    """Data-driven renderer for the extended task families.

    Generators emit items built from small primitives (task lines, boxes,
    word banks, grids, bubbles, frames, tables ...); this walks the items
    and renders each primitive.
    """
    elements: list = []
    elements.append(Paragraph(ex.title, styles["section"]))
    if ex.instruction:
        elements.append(Paragraph(ex.instruction, styles["instruction"]))

    if ex.resource and ex.resource.get("url"):
        elements.extend(_resource_box(ex.resource, styles, CONTENT_W))

    if ex.word_bank:
        bank_text = "   ".join(f"<b>{w}</b>" for w in ex.word_bank)
        elements.extend(_text_box(bank_text, styles, CONTENT_W))

    pending_role_cards: list[dict] = []

    def flush_role_cards() -> None:
        if not pending_role_cards:
            return
        cells = []
        for card in pending_role_cards:
            cells.append(Paragraph(
                f"<b>{card.get('title', '')}</b><br/>{card.get('text', '')}",
                styles["body"],
            ))
        w = CONTENT_W / len(cells)
        t = Table([cells], colWidths=[w] * len(cells))
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("GRID", (0, 0), (-1, -1), 0.5, BORDER),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3 * mm),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3 * mm))
        pending_role_cards.clear()

    for item in ex.items:
        if "role_card" in item:
            pending_role_cards.append(item["role_card"])
            continue
        flush_role_cards()

        num = item.get("number", "")
        prefix = f"<b>{num}.</b>  " if num != "" else ""

        if "task" in item:
            if item["task"]:
                elements.append(Paragraph(f"{prefix}{item['task']}",
                                          styles["item"]))
            elif prefix:
                elements.append(Paragraph(prefix, styles["item"]))

        elif "label" in item:
            elements.append(Paragraph(f"<b>{item['label']}</b>", styles["body"]))

        elif "box" in item:
            elements.extend(_text_box(item["box"], styles, CONTENT_W))

        elif "bank" in item:
            bank_text = "   ".join(f"<b>{w}</b>" for w in item["bank"])
            elements.extend(_text_box(bank_text, styles, CONTENT_W))

        elif "tip" in item:
            elements.extend(_tip_box(item["tip"], styles, CONTENT_W))

        elif "grid" in item:
            elements.append(_letter_grid(item["grid"], CONTENT_W))
            elements.append(Spacer(1, 3 * mm))

        elif "crossword" in item:
            elements.append(_crossword_table(item["crossword"], CONTENT_W))
            elements.append(Spacer(1, 3 * mm))

        elif "clues_across" in item or "clues_down" in item:
            across = item.get("clues_across", [])
            down = item.get("clues_down", [])
            col_w = CONTENT_W / 2

            def clue_cell(label: str, clues: list[dict]) -> list:
                cell: list = [Paragraph(f"<b>{label}</b>", styles["body"])]
                for e in clues:
                    cell.append(Paragraph(
                        f"{e['number']}. {e['clue']}", styles["small"]))
                return cell

            t = Table([[clue_cell(item.get("across_label", "Across"), across),
                        clue_cell(item.get("down_label", "Down"), down)]],
                      colWidths=[col_w, col_w])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 2 * mm))

        elif "scramble" in item:
            elements.append(Paragraph(
                f"{prefix}<font face='Courier-Bold'>{item['scramble']}</font>"
                f"   <i>({item.get('hint', '')})</i>   "
                f"→  ____________________",
                styles["item"],
            ))

        elif "words_row" in item:
            words = "   –   ".join(item["words_row"])
            elements.append(Paragraph(f"{prefix}{words}", styles["item"]))
            if item.get("why"):
                elements.extend(_writing_lines(1))
                elements.append(Spacer(1, 1 * mm))

        elif "code" in item:
            elements.append(Paragraph(
                f"{prefix}<font face='Courier'>{item['code']}</font>"
                f"   →  ____________________",
                styles["item"],
            ))

        elif "key_table" in item:
            key = item["key_table"]
            key_text = "   ".join(f"<b>{k}</b>&nbsp;=&nbsp;{v}"
                                  for k, v in key.items())
            elements.extend(_text_box(key_text, styles, CONTENT_W))

        elif "chat" in item:
            elements.extend(_chat_bubbles(item["chat"], CONTENT_W))

        elif "post" in item:
            post = item["post"]
            elements.extend(_text_box(
                f"<b>{post.get('author', '')}</b><br/>{post.get('text', '')}",
                styles, CONTENT_W))

        elif "reply" in item:
            reply = item["reply"]
            elements.append(Paragraph(f"<b>{reply.get('label', '')}</b>",
                                      styles["body"]))
            elements.extend(_writing_lines(reply.get("lines", 2)))
            elements.append(Spacer(1, 2 * mm))

        elif "frames" in item:
            elements.extend(_frames_grid(item["frames"], styles, CONTENT_W))

        elif "table" in item:
            elements.append(_fillable_table(item["table"], styles, CONTENT_W))
            elements.append(Spacer(1, 3 * mm))

        elif "clock" in item:
            clock = _clock_drawing(item["clock"])
            line = Table([[""]], colWidths=[CONTENT_W - 34 * mm],
                         rowHeights=[8 * mm])
            line.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
            ]))
            numbered = Paragraph(prefix or "", styles["item"])
            t = Table([[numbered, clock, line]],
                      colWidths=[8 * mm, 24 * mm, CONTENT_W - 32 * mm])
            t.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ]))
            elements.append(t)
            elements.append(Spacer(1, 2 * mm))
            continue  # lines handled inline

        elif "cards" in item:
            elements.extend(_flashcards(item["cards"], styles, CONTENT_W))

        elif "postcard" in item:
            elements.append(_postcard(item["postcard"], CONTENT_W))
            elements.append(Spacer(1, 3 * mm))

        elif "acrostic" in item:
            for letter in item["acrostic"]:
                line = Table([[""]], colWidths=[CONTENT_W - 14 * mm],
                             rowHeights=[8 * mm])
                line.setStyle(TableStyle([
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
                ]))
                t = Table([[Paragraph(f"<b>{letter}</b>", styles["section"]),
                            line]],
                          colWidths=[10 * mm, CONTENT_W - 10 * mm])
                t.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]))
                elements.append(t)

        elif "dialogue_lines" in item:
            spec = item["dialogue_lines"]
            speakers = spec.get("speakers", ["A", "B"])
            for i in range(spec.get("turns", 8)):
                speaker = speakers[i % len(speakers)]
                line = Table([[""]], colWidths=[CONTENT_W - 14 * mm],
                             rowHeights=[8 * mm])
                line.setStyle(TableStyle([
                    ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
                ]))
                t = Table([[Paragraph(f"<b>{speaker}:</b>", styles["body"]),
                            line]],
                          colWidths=[10 * mm, CONTENT_W - 10 * mm])
                t.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ]))
                elements.append(t)

        elif "checkboxes" in item:
            elements.append(_checkbox_rows(item["checkboxes"], CONTENT_W))
            elements.append(Spacer(1, 2 * mm))

        if item.get("stars"):
            elements.append(_stars_drawing(item["stars"]))
            elements.append(Spacer(1, 2 * mm))

        lines = item.get("lines", 0)
        if lines:
            elements.extend(_writing_lines(lines))
            elements.append(Spacer(1, 1 * mm))

    flush_role_cards()
    return elements


EXERCISE_RENDERERS = {
    "fib": _render_fib,
    "picture": _render_picture,
    "word_connections": _render_word_connections,
}


# ---------------------------------------------------------------------------
# Vocabulary & Grammar reference pages
# ---------------------------------------------------------------------------

def _render_vocabulary_page(text: SourceText, styles: dict) -> list:
    if not text.vocabulary or not text.vocabulary.items:
        return []

    elements: list = []
    elements.append(Paragraph("Vocabulary Reference", styles["section"]))

    # Group by POS
    by_pos: dict[str, list] = {}
    for v in text.vocabulary.items:
        by_pos.setdefault(v.pos, []).append(v)

    for pos, items in sorted(by_pos.items()):
        elements.append(Paragraph(f"<b>{pos.upper()}</b>", styles["small"]))
        rows = []
        for v in items:
            extra = ""
            if v.synonym:
                extra += f"  (≈ {v.synonym})"
            if v.antonym:
                extra += f"  (≠ {v.antonym})"
            rows.append([v.term, v.translation + extra])

        t = Table(rows, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.55])
        t.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
            ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("TEXTCOLOR", (0, 0), (-1, -1), TEXT_DARK),
            ("TEXTCOLOR", (1, 0), (1, -1), TEXT_GREY),
            ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
            ("LINEBELOW", (0, 0), (-1, -1), 0.2, BORDER),
        ]))
        elements.append(t)
        elements.append(Spacer(1, 3 * mm))

    return elements


def _render_grammar_page(text: SourceText, styles: dict) -> list:
    if not text.grammar or not text.grammar.phenomena:
        return []

    elements: list = []
    elements.append(Paragraph("Grammar Reference", styles["section"]))

    for p in text.grammar.phenomena:
        elements.append(Paragraph(f"<b>{p.name.title()}</b>", styles["body"]))
        elements.append(Paragraph(p.description, styles["instruction"]))
        for ex in p.examples:
            elements.append(Paragraph(f"• <i>{ex}</i>", styles["item"]))
        elements.append(Spacer(1, 2 * mm))

    return elements


# ---------------------------------------------------------------------------
# Reading text page
# ---------------------------------------------------------------------------

def _render_reading_page(text: SourceText, styles: dict) -> list:
    elements: list = []
    elements.append(Paragraph(text.title, styles["title"]))
    elements.append(Paragraph(
        f"{_humanize_topic(text.topic)}  |  {text.cefr_level}  |  "
        f"{text.source_lang.upper()} → {text.target_lang.upper()}",
        styles["subtitle"],
    ))
    elements.extend(_text_box(text.content, styles, CONTENT_W))
    return elements


# ---------------------------------------------------------------------------
# Solution page
# ---------------------------------------------------------------------------

def _render_solutions(exercises: list[ExerciseInstance], styles: dict) -> list:
    elements: list = []
    elements.append(Paragraph("Solutions", styles["section"]))

    for ex in exercises:
        if not ex.solution:
            continue
        elements.append(Paragraph(f"<b>{ex.title}</b>", styles["body"]))
        for sol in ex.solution:
            if "answer" in sol:
                num = sol.get("number", "")
                elements.append(Paragraph(
                    f"{num}. {sol['answer']}", styles["small"]
                ))
            elif "answers" in sol:
                elements.append(Paragraph(
                    ", ".join(sol["answers"]), styles["small"]
                ))
            elif "synonym" in sol:
                elements.append(Paragraph(
                    f"{sol.get('number', '')}. {sol['term']} → {sol['synonym']}",
                    styles["small"],
                ))
            elif "antonym" in sol:
                elements.append(Paragraph(
                    f"{sol.get('number', '')}. {sol['term']} → {sol['antonym']}",
                    styles["small"],
                ))
            elif "words" in sol:
                elements.append(Paragraph(
                    f"{sol.get('category', '')}: {', '.join(sol['words'])}",
                    styles["small"],
                ))
            elif "compound" in sol:
                elements.append(Paragraph(
                    f"{sol.get('parts', '')} = {sol['compound']}",
                    styles["small"],
                ))
            elif "letter" in sol:
                elements.append(Paragraph(
                    f"{sol['number']} → {sol['letter']}", styles["small"]
                ))
            elif "note" in sol:
                elements.append(Paragraph(sol["note"], styles["small"]))
        elements.append(Spacer(1, 2 * mm))

    return elements


# ---------------------------------------------------------------------------
# Main render function
# ---------------------------------------------------------------------------

def render_worksheet(
    text: SourceText,
    exercises: list[ExerciseInstance],
    output_path: str | Path,
) -> Path:
    """Render a complete worksheet PDF."""
    global _picture_rendered
    _picture_rendered = False

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    styles = _styles()
    story: list = []

    # Page 1: Reading text
    story.extend(_render_reading_page(text, styles))
    story.append(Spacer(1, 4 * mm))

    # Exercises
    for ex in exercises:
        # Map node_id prefix to a specialized renderer; everything else
        # (puzzles, media, social, writing, ...) uses the generic renderer.
        if ex.node_id.startswith("fib"):
            renderer = EXERCISE_RENDERERS["fib"]
        elif ex.node_id.startswith("pic"):
            renderer = EXERCISE_RENDERERS["picture"]
        elif ex.node_id.startswith("wc"):
            renderer = EXERCISE_RENDERERS["word_connections"]
        else:
            renderer = _render_generic
        story.extend(renderer(ex, styles))
        story.append(Spacer(1, 6 * mm))

    # Vocabulary reference
    story.append(PageBreak())
    story.extend(_render_vocabulary_page(text, styles))

    # Grammar reference
    story.append(PageBreak())
    story.extend(_render_grammar_page(text, styles))

    # Solutions
    story.append(PageBreak())
    story.extend(_render_solutions(exercises, styles))

    # Build PDF
    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.8 * cm,
        bottomMargin=1.5 * cm,
    )

    frame = Frame(
        MARGIN, 1.5 * cm,
        CONTENT_W, PAGE_H - 3.3 * cm,
        id="main",
    )

    doc.addPageTemplates([
        PageTemplate(
            id="main",
            frames=[frame],
            onPage=lambda canvas, doc: _header_footer(canvas, doc, text),
        )
    ])

    doc.build(story)
    return output
