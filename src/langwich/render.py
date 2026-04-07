"""Lean PDF renderer for langwich worksheets.

Modern, clean design using ReportLab. Renders exercises generated from the
exercise graph into a printable A4 worksheet.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
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


# ---------------------------------------------------------------------------
# Header / footer
# ---------------------------------------------------------------------------

def _header_footer(canvas, doc, text: SourceText):
    canvas.saveState()
    # Header
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(TEXT_GREY)
    canvas.drawString(MARGIN, PAGE_H - 1.2 * cm,
                      f"langwich  |  {text.topic.upper()}  |  {text.cefr_level}")
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
            for i, (l, r) in enumerate(
                zip(item["left_column"], item["right_column"]), 1
            ):
                rows.append([f"{i}. {l}  +", f"{r}  =  _______________"])

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
        f"{text.topic.title()}  |  {text.cefr_level}  |  "
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
        etype = ex.node_id.split("_")[0]
        # Map node_id prefix to exercise type key
        if ex.node_id.startswith("fib"):
            renderer = EXERCISE_RENDERERS["fib"]
        elif ex.node_id.startswith("pic"):
            renderer = EXERCISE_RENDERERS["picture"]
        elif ex.node_id.startswith("wc"):
            renderer = EXERCISE_RENDERERS["word_connections"]
        else:
            continue
        story.extend(renderer(ex, styles))
        story.append(Spacer(1, 6 * mm))

    # Vocabulary reference
    story.extend(_render_vocabulary_page(text, styles))

    # Grammar reference
    story.extend(_render_grammar_page(text, styles))

    # Solutions
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
