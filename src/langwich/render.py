"""Lean PDF renderer for langwich worksheets.

Monochrome, picture-forward design built for e-paper devices and
black-and-white print:

- One task per page — a task never runs across a page break it doesn't own.
- The vocabulary needed for a page is repeated small and grey along the
  bottom edge of that page (inline pairs, not a table).
- Pictures span the full content width and as much page height as the
  task leaves free; image prompts request high-contrast black-and-white
  artwork unless colour output was actively accepted.
"""

from __future__ import annotations

import io
import re
import sys
import urllib.request
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    Image as RLImage,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from langwich.generate import ExerciseInstance, _strip_article
from langwich.text import PictureScene, SourceText


# ---------------------------------------------------------------------------
# Design tokens — monochrome, high contrast for e-paper and b/w print
# ---------------------------------------------------------------------------

INK = colors.HexColor("#111111")
GREY = colors.HexColor("#5f6368")
GREY_SOFT = colors.HexColor("#8a8f98")
BORDER = colors.HexColor("#c9cdd3")
BG_LIGHT = colors.HexColor("#f2f3f5")

PAGE_W, PAGE_H = A4
MARGIN = 2 * cm
CONTENT_W = PAGE_W - 2 * MARGIN

# Vertical geometry. Task pages reserve a band above the bottom margin for
# the per-page vocabulary; reference pages (grammar, solutions) use the
# full height.
FRAME_TOP_Y = PAGE_H - 1.8 * cm
VOCAB_BAND_BOTTOM = 1.4 * cm
VOCAB_BAND_H = 2.0 * cm
VOCAB_BAND_TOP = VOCAB_BAND_BOTTOM + VOCAB_BAND_H
TASK_FRAME_BOTTOM = VOCAB_BAND_TOP + 0.2 * cm
TASK_FRAME_H = FRAME_TOP_Y - TASK_FRAME_BOTTOM
REF_FRAME_BOTTOM = 1.5 * cm

_TASK_WORD = {"en": "Task", "de": "Aufgabe", "fr": "Exercice", "es": "Ejercicio"}
_VOCAB_WORD = {"en": "Vocabulary", "de": "Vokabeln", "fr": "Vocabulaire",
               "es": "Vocabulario"}

# Appended to every image-generation prompt so the artwork survives
# monochrome screens; colour phrasing is used only after the user actively
# accepted colour output.
_MONO_PROMPT_SUFFIX = (
    "Render as high-contrast black-and-white line art with bold outlines "
    "and solid blacks; avoid fine grey gradients and low-contrast shading — "
    "the picture must stay crisp on a monochrome e-paper display or in "
    "black-and-white print."
)
_COLOR_PROMPT_SUFFIX = (
    "Use a bold, high-contrast composition with clearly distinguishable "
    "colours that stays legible in print."
)


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "title", fontName="Helvetica-Bold", fontSize=24,
            textColor=INK, spaceAfter=3 * mm, leading=28,
        ),
        "subtitle": ParagraphStyle(
            "subtitle", fontName="Helvetica", fontSize=10,
            textColor=GREY, spaceAfter=5 * mm,
        ),
        "kicker": ParagraphStyle(
            "kicker", fontName="Helvetica-Bold", fontSize=8.5,
            textColor=GREY_SOFT, spaceAfter=1.5 * mm, leading=11,
        ),
        "section": ParagraphStyle(
            "section", fontName="Helvetica-Bold", fontSize=17,
            textColor=INK, spaceAfter=2 * mm, leading=21,
        ),
        "instruction": ParagraphStyle(
            "instruction", fontName="Helvetica-Oblique", fontSize=10.5,
            textColor=GREY, spaceAfter=4 * mm, leading=14,
        ),
        "body": ParagraphStyle(
            "body", fontName="Helvetica", fontSize=10.5,
            textColor=INK, spaceAfter=2 * mm, leading=14,
        ),
        "item": ParagraphStyle(
            "item", fontName="Helvetica", fontSize=11,
            textColor=INK, spaceAfter=4 * mm, leading=16,
            leftIndent=6 * mm,
        ),
        "small": ParagraphStyle(
            "small", fontName="Helvetica", fontSize=8,
            textColor=GREY, leading=10,
        ),
        "reading": ParagraphStyle(
            "reading", fontName="Helvetica", fontSize=10.5,
            textColor=INK, spaceAfter=2 * mm, leading=15,
        ),
        "picture_prompt": ParagraphStyle(
            "picture_prompt", fontName="Helvetica-Oblique", fontSize=8,
            textColor=GREY, spaceAfter=2 * mm, leading=10,
        ),
    }


def _humanize_topic(slug: str) -> str:
    return slug.replace("-", " ").replace("_", " ").title()


# ---------------------------------------------------------------------------
# Per-page vocabulary
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_INFLECTION_SUFFIXES = ("n", "en", "e", "s", "es", "er", "st", "nt")


def _relevant_vocab(text: SourceText, searchable: str) -> list[tuple[str, str]]:
    """Vocabulary pairs (term, translation) that occur in ``searchable``.

    Single-word terms match exactly or with a light inflection suffix;
    multi-word terms match as a substring.
    """
    if not text.vocabulary or not searchable:
        return []
    low = searchable.lower()
    tokens = set(_WORD_RE.findall(low))
    pairs: list[tuple[str, str]] = []
    for v in text.vocabulary.items:
        stem = _strip_article(v.term).lower()
        if len(stem) < 2:
            continue
        if " " in stem:
            hit = stem in low
        else:
            hit = any(
                t == stem or (t.startswith(stem) and t[len(stem):] in _INFLECTION_SUFFIXES)
                for t in tokens
            )
        if hit:
            pairs.append((v.term, v.translation))
    return pairs


def _exercise_searchable(ex: ExerciseInstance) -> str:
    """All text a learner sees (or needs) on an exercise page."""
    parts: list[str] = [ex.context_text, " ".join(ex.word_bank)]

    def walk(obj) -> None:
        if isinstance(obj, str):
            parts.append(obj)
        elif isinstance(obj, dict):
            for value in obj.values():
                walk(value)
        elif isinstance(obj, (list, tuple)):
            for value in obj:
                walk(value)

    walk(ex.items)
    walk(ex.solution)
    return " ".join(p for p in parts if p)


def _draw_vocab_band(canvas, pairs: list[tuple[str, str]], source_lang: str) -> None:
    """Inline vocabulary pairs, small and grey, in the lower page band.

    Pairs sit side by side separated by a middle dot — no table.
    """
    if not pairs:
        return
    canvas.saveState()
    canvas.setStrokeColor(BORDER)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, VOCAB_BAND_TOP, PAGE_W - MARGIN, VOCAB_BAND_TOP)

    label = _VOCAB_WORD.get(source_lang, _VOCAB_WORD["en"]).upper()
    canvas.setFont("Helvetica-Bold", 6.5)
    canvas.setFillColor(GREY_SOFT)
    canvas.drawString(MARGIN, VOCAB_BAND_TOP - 11, label)

    font, size, leading = "Helvetica", 7.5, 9.5
    sep = "    ·    "
    entries = [f"{term} – {translation}" for term, translation in pairs]

    lines: list[str] = []
    current = ""
    max_lines = 3
    for entry in entries:
        candidate = f"{current}{sep}{entry}" if current else entry
        if stringWidth(candidate, font, size) <= CONTENT_W:
            current = candidate
        else:
            lines.append(current)
            current = entry
            if len(lines) == max_lines:
                current = ""
                lines[-1] += "  …"
                break
    if current:
        lines.append(current)

    canvas.setFont(font, size)
    canvas.setFillColor(GREY)
    y = VOCAB_BAND_TOP - 24
    for line in lines[:max_lines]:
        canvas.drawString(MARGIN, y, line)
        y -= leading
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Header / footer
# ---------------------------------------------------------------------------

def _make_on_page(text: SourceText, vocab_pairs: list[tuple[str, str]]):
    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica-Bold", 8)
        canvas.setFillColor(GREY)
        canvas.drawString(MARGIN, PAGE_H - 1.2 * cm,
                          f"langwich  |  {_humanize_topic(text.topic)}  |  {text.cefr_level}")
        canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 1.2 * cm,
                               f"{text.source_lang.upper()} → {text.target_lang.upper()}")
        canvas.setStrokeColor(INK)
        canvas.setLineWidth(0.8)
        canvas.line(MARGIN, PAGE_H - 1.4 * cm, PAGE_W - MARGIN, PAGE_H - 1.4 * cm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(GREY)
        canvas.drawCentredString(PAGE_W / 2, 0.9 * cm, f"– {doc.page} –")
        canvas.restoreState()
        _draw_vocab_band(canvas, vocab_pairs, text.source_lang)
    return on_page


# ---------------------------------------------------------------------------
# Component builders
# ---------------------------------------------------------------------------

def _rule(thickness: float = 1.1, space_after: float = 4 * mm) -> HRFlowable:
    return HRFlowable(width="100%", thickness=thickness, color=INK,
                      spaceBefore=0, spaceAfter=space_after, lineCap="butt")


def _text_box(text_content: str, styles: dict, width: float,
              accent_bar: bool = False) -> list:
    """Render text in a box: light background by default, or a clean
    black accent bar on the left (crisper on e-paper) for reading text."""
    para = Paragraph(text_content.replace("\n", "<br/>"), styles["reading"])
    t = Table([[para]], colWidths=[width - 6 * mm])
    if accent_bar:
        style = [
            ("LINEBEFORE", (0, 0), (0, -1), 1.6, INK),
            ("TOPPADDING", (0, 0), (-1, -1), 1 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]
    else:
        style = [
            ("BACKGROUND", (0, 0), (-1, -1), BG_LIGHT),
            ("BOX", (0, 0), (-1, -1), 0.5, BORDER),
            ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
        ]
    t.setStyle(TableStyle(style))
    return [t, Spacer(1, 3 * mm)]


def _writing_lines(count: int = 3, width: float = CONTENT_W) -> list:
    elements = []
    for _ in range(count):
        t = Table([[""]],  colWidths=[width], rowHeights=[8 * mm])
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, BORDER),
        ]))
        elements.append(t)
    return elements


def _stack_height(flowables: list, width: float) -> float:
    total = 0.0
    for f in flowables:
        _, h = f.wrap(width, PAGE_H)
        total += h + f.getSpaceBefore() + f.getSpaceAfter()
    return total


# ---------------------------------------------------------------------------
# Picture loading & rendering
# ---------------------------------------------------------------------------

def _prepare_image_bytes(raw: bytes, monochrome: bool) -> io.BytesIO:
    """Boost images for monochrome output: grayscale + autocontrast."""
    if monochrome:
        try:
            from PIL import Image as PILImage, ImageOps
            img = PILImage.open(io.BytesIO(raw))
            img = ImageOps.autocontrast(img.convert("L"), cutoff=1)
            buf = io.BytesIO()
            img.save(buf, "PNG")
            buf.seek(0)
            return buf
        except Exception:
            pass
    return io.BytesIO(raw)


def _load_image(source: str, monochrome: bool) -> io.BytesIO | None:
    """Load an image from a local path or an (open-access) URL."""
    try:
        if source.startswith(("http://", "https://")):
            request = urllib.request.Request(
                source, headers={"User-Agent": "langwich/0.1 (worksheet generator)"}
            )
            with urllib.request.urlopen(request, timeout=30) as response:
                raw = response.read()
        else:
            raw = Path(source).read_bytes()
        return _prepare_image_bytes(raw, monochrome)
    except Exception as exc:
        print(f"Warning: could not load image '{source}': {exc}", file=sys.stderr)
        return None


def _picture_flowables(scene: PictureScene, styles: dict, width: float,
                       box_h: float, monochrome: bool) -> list:
    """The picture itself — an embedded image if available, otherwise a
    full-size placeholder with a high-contrast generation prompt."""
    elements: list = []
    if scene.image:
        data = _load_image(scene.image, monochrome)
        if data is not None:
            reader = ImageReader(data)
            iw, ih = reader.getSize()
            img_h = box_h - (8 * mm if scene.image_credit else 3 * mm)
            scale = min(width / iw, img_h / ih)
            data.seek(0)
            img = RLImage(data, width=iw * scale, height=ih * scale)
            img.hAlign = "CENTER"
            elements.append(img)
            if scene.image_credit:
                elements.append(Spacer(1, 1.5 * mm))
                elements.append(Paragraph(
                    f"Image: {scene.image_credit}", styles["picture_prompt"]
                ))
            elements.append(Spacer(1, 3 * mm))
            return elements

    suffix = _MONO_PROMPT_SUFFIX if monochrome else _COLOR_PROMPT_SUFFIX
    prompt = f"{scene.description.rstrip('.')}. {suffix}"
    prompt_para = Paragraph(f"<b>Image prompt:</b> {prompt}",
                            styles["picture_prompt"])
    _, prompt_h = prompt_para.wrap(width, PAGE_H)
    box_inner_h = max(box_h - prompt_h - 6 * mm, 4 * cm)
    t = Table([["[Picture placeholder — generate with the prompt below]"]],
              colWidths=[width - 6 * mm], rowHeights=[box_inner_h])
    t.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1, INK),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TEXTCOLOR", (0, 0), (-1, -1), GREY),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 2 * mm))
    elements.append(prompt_para)
    elements.append(Spacer(1, 2 * mm))
    return elements


# ---------------------------------------------------------------------------
# Exercise renderers — items only; title/instruction come from _task_header
# ---------------------------------------------------------------------------

def _render_fib(ex: ExerciseInstance, styles: dict, text: SourceText,
                avail_h: float, monochrome: bool) -> list:
    elements: list = []

    if ex.word_bank:
        bank_text = "      ".join(f"<b>{w}</b>" for w in ex.word_bank)
        elements.extend(_text_box(bank_text, styles, CONTENT_W))

    if ex.context_text:
        elements.extend(_text_box(ex.context_text, styles, CONTENT_W))

    for item in ex.items:
        line = f"<b>{item['number']}.</b>  {item['sentence']}"
        if "hint" in item:
            line += f"  <i>{item['hint']}</i>"
        if "choices" in item:
            choices = "  /  ".join(item["choices"])
            line += f"  [ {choices} ]"
        if "translation" in item:
            line += f"<br/><i><font size='9' color='#5f6368'>{item['translation']}</font></i>"
        elements.append(Paragraph(line, styles["item"]))

    return elements


def _render_picture(ex: ExerciseInstance, styles: dict, text: SourceText,
                    avail_h: float, monochrome: bool) -> list:
    question_elements: list = []
    for item in ex.items:
        if "question" in item:
            question_elements.append(Paragraph(
                f"<b>{item.get('number', '')}.</b>  {item['question']}", styles["item"]
            ))
            question_elements.extend(_writing_lines(1))
        elif "instruction" in item:
            num = item.get("number", "")
            prefix = f"<b>{num}.</b>  " if num else ""
            question_elements.append(Paragraph(
                f"{prefix}{item['instruction']}", styles["item"]
            ))
            if item.get("lines"):
                question_elements.extend(_writing_lines(item["lines"]))
        elif "text" in item:
            question_elements.extend(_text_box(item["text"], styles, CONTENT_W))

    elements: list = []
    if text.picture_scene:
        # The picture takes every point the questions leave free on the page.
        questions_h = _stack_height(question_elements, CONTENT_W)
        box_h = max(avail_h - questions_h - 8 * mm, 5 * cm)
        box_h = min(box_h, avail_h - 2 * cm)
        elements.extend(_picture_flowables(
            text.picture_scene, styles, CONTENT_W, box_h, monochrome
        ))

    elements.extend(question_elements)
    return elements


def _render_media(ex: ExerciseInstance, styles: dict, text: SourceText,
                  avail_h: float, monochrome: bool) -> list:
    elements: list = []

    if ex.context_text:
        elements.extend(_text_box(f"<b>{ex.context_text}</b>", styles, CONTENT_W))

    for item in ex.items:
        elements.append(Paragraph(
            f"<b>{item['number']}.</b>  {item['task']}", styles["item"]
        ))
        elements.extend(_writing_lines(item.get("lines", 1)))
        elements.append(Spacer(1, 2 * mm))

    return elements


def _render_word_connections(ex: ExerciseInstance, styles: dict, text: SourceText,
                             avail_h: float, monochrome: bool) -> list:
    elements: list = []

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
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
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
            words = "      ".join(f"<b>{w}</b>" for w in item["words"])
            elements.extend(_text_box(words, styles, CONTENT_W))
            for cat in item["categories"]:
                elements.append(Paragraph(f"<b>{cat}:</b>", styles["body"]))
                elements.extend(_writing_lines(1))
                elements.append(Spacer(1, 2 * mm))

        elif "left_column" in item and "right_column" in item:
            rows = []
            for i, (l, r) in enumerate(
                zip(item["left_column"], item["right_column"]), 1
            ):
                rows.append([f"{i}. {l}  +", f"{r}  =  _______________"])

            t = Table(rows, colWidths=[CONTENT_W * 0.4, CONTENT_W * 0.6])
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 10.5),
                ("TEXTCOLOR", (0, 0), (-1, -1), INK),
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
    "media": _render_media,
}


def _renderer_for(ex: ExerciseInstance):
    if ex.node_id.startswith("fib"):
        return EXERCISE_RENDERERS["fib"]
    if ex.node_id.startswith("pic"):
        return EXERCISE_RENDERERS["picture"]
    if ex.node_id.startswith("wc"):
        return EXERCISE_RENDERERS["word_connections"]
    if ex.node_id.startswith("media"):
        return EXERCISE_RENDERERS["media"]
    return None


def _task_header(index: int, total: int, ex: ExerciseInstance,
                 styles: dict, text: SourceText) -> list:
    word = _TASK_WORD.get(text.source_lang, _TASK_WORD["en"]).upper()
    return [
        Paragraph(f"{word} {index} / {total}", styles["kicker"]),
        Paragraph(ex.title, styles["section"]),
        _rule(1.1, 3 * mm),
        Paragraph(ex.instruction, styles["instruction"]),
    ]


# ---------------------------------------------------------------------------
# Grammar reference page
# ---------------------------------------------------------------------------

def _render_grammar_page(text: SourceText, styles: dict) -> list:
    if not text.grammar or not text.grammar.phenomena:
        return []

    elements: list = []
    elements.append(Paragraph("Grammar Reference", styles["section"]))
    elements.append(_rule(1.1, 4 * mm))

    for p in text.grammar.phenomena:
        # Sentence case, not .title() — "passé composé" must not become
        # "Passé Composé" and "il y a" not "Il Y A".
        name = p.name[:1].upper() + p.name[1:]
        elements.append(Paragraph(f"<b>{name}</b>", styles["body"]))
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
    elements.append(_rule(2.0, 5 * mm))
    elements.extend(_text_box(text.content, styles, CONTENT_W, accent_bar=True))
    return elements


# ---------------------------------------------------------------------------
# Solution page
# ---------------------------------------------------------------------------

def _render_solutions(exercises: list[ExerciseInstance], styles: dict) -> list:
    if not any(ex.solution for ex in exercises):
        return []

    elements: list = []
    elements.append(Paragraph("Solutions", styles["section"]))
    elements.append(_rule(1.1, 4 * mm))

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

def _page_template(template_id: str, text: SourceText,
                   vocab_pairs: list[tuple[str, str]],
                   with_vocab_band: bool) -> PageTemplate:
    bottom = TASK_FRAME_BOTTOM if with_vocab_band else REF_FRAME_BOTTOM
    frame = Frame(MARGIN, bottom, CONTENT_W, FRAME_TOP_Y - bottom, id=template_id)
    return PageTemplate(
        id=template_id,
        frames=[frame],
        onPage=_make_on_page(text, vocab_pairs if with_vocab_band else []),
    )


def render_worksheet(
    text: SourceText,
    exercises: list[ExerciseInstance],
    output_path: str | Path,
    monochrome: bool = True,
) -> Path:
    """Render a complete worksheet PDF.

    ``monochrome`` (the default) assumes a black-and-white device or
    printer: embedded images are converted to high-contrast grayscale and
    image prompts request black-and-white artwork. Pass ``False`` only when
    the user actively accepted colour output.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    styles = _styles()
    story: list = []
    templates: list[PageTemplate] = []

    renderable = [(ex, _renderer_for(ex)) for ex in exercises]
    renderable = [(ex, r) for ex, r in renderable if r is not None]
    total = len(renderable)

    # Page 1: reading text, with the vocabulary occurring in it below.
    templates.append(_page_template(
        "reading", text, _relevant_vocab(text, text.content), True,
    ))
    story.extend(_render_reading_page(text, styles))

    # One task per page: each exercise gets its own page (and page
    # template, which carries exactly the vocabulary that page needs).
    for i, (ex, renderer) in enumerate(renderable, 1):
        template_id = f"task{i}"
        vocab_pairs = _relevant_vocab(text, _exercise_searchable(ex))
        templates.append(_page_template(template_id, text, vocab_pairs, True))

        header = _task_header(i, total, ex, styles, text)
        avail_h = TASK_FRAME_H - _stack_height(header, CONTENT_W)
        story.append(NextPageTemplate(template_id))
        story.append(PageBreak())
        story.extend(header)
        story.extend(renderer(ex, styles, text, avail_h, monochrome))

    # Reference pages (grammar, solutions) — full height, no vocab band.
    templates.append(_page_template("ref", text, [], False))
    switched_to_ref = False
    for section in (
        _render_grammar_page(text, styles),
        _render_solutions([ex for ex, _ in renderable], styles),
    ):
        if section:
            if not switched_to_ref:
                story.append(NextPageTemplate("ref"))
                switched_to_ref = True
            story.append(PageBreak())
            story.extend(section)

    doc = BaseDocTemplate(
        str(output),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=1.8 * cm,
        bottomMargin=REF_FRAME_BOTTOM,
    )
    doc.addPageTemplates(templates)
    doc.build(story)
    return output
