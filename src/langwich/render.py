"""PDF renderer for langwich worksheets.

A single, consistent design system turns the generated exercises into a sheet
that reads like a finished teaching resource: a story to read, a numbered
sequence of exercises that develop from it, reference pages, and an answer key.

Layout rules that keep it clean:

* every exercise is kept together (header never orphans at a page break);
* one shared type scale and palette — no ad-hoc fonts or colours;
* generous, uniform spacing so nothing collides or overlaps.
"""

from __future__ import annotations

from pathlib import Path

from reportlab import rl_config
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from langwich.generate import ExerciseInstance
from langwich.text import SourceText

# Reproducible output: fix the PDF creation date and document id so that the
# same input always yields byte-identical PDFs (no embedded timestamp/random id).
rl_config.invariant = 1


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------

INK = colors.HexColor("#1C1C1A")       # primary text
MUTED = colors.HexColor("#565049")      # secondary text
FAINT = colors.HexColor("#8C857A")      # captions / least important
ACCENT = colors.HexColor("#1F5468")     # single brand accent (denim blue)
ACCENT_DK = colors.HexColor("#143847")
TINT = colors.HexColor("#F1ECE1")       # accent-tinted panel
PAPER = colors.HexColor("#FBF9F4")      # subtle card background
HAIRLINE = colors.HexColor("#D9D2C5")   # rules and borders
WRITE_LINE = colors.HexColor("#C7BFB0")

PAGE_W, PAGE_H = A4
MARGIN = 1.9 * cm
CONTENT_W = PAGE_W - 2 * MARGIN


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

# A textbook look: serif (Times) for everything the learner reads, a sans
# (Helvetica) reserved for small structural labels — rubric tags, chips, the
# wordmark — the way printed coursebooks set instructions apart from content.
SERIF = "Times-Roman"
SERIF_B = "Times-Bold"
SERIF_I = "Times-Italic"
SANS = "Helvetica"
SANS_B = "Helvetica-Bold"


def _styles() -> dict[str, ParagraphStyle]:
    def S(name: str, **kw) -> ParagraphStyle:
        opts: dict = dict(fontName=SERIF, textColor=INK)
        opts.update(kw)
        return ParagraphStyle(name, **opts)

    return {
        "eyebrow": S("eyebrow", fontName=SANS_B, fontSize=8, textColor=ACCENT,
                     spaceAfter=2 * mm, leading=10),
        "title": S("title", fontName=SERIF_B, fontSize=24, leading=27,
                   spaceAfter=3 * mm),
        "meta": S("meta", fontName=SANS, fontSize=9, textColor=MUTED, leading=13,
                  spaceAfter=2 * mm),
        "section": S("section", fontName=SERIF_B, fontSize=14, leading=17),
        "ex_title": S("ex_title", fontName=SERIF_B, fontSize=12.5, leading=15),
        "ex_meta": S("ex_meta", fontName=SANS, fontSize=7.5, textColor=FAINT,
                     leading=11),
        "rubric": S("rubric", fontName=SERIF_I, fontSize=10, textColor=MUTED,
                    leading=13),
        "body": S("body", fontSize=10.5, leading=15, spaceAfter=1 * mm),
        "item": S("item", fontSize=10.5, leading=16, spaceAfter=3.2 * mm),
        "reading": S("reading", fontSize=11, leading=16.5, spaceAfter=2.5 * mm,
                     alignment=TA_JUSTIFY),
        "readnum": S("readnum", fontName=SANS_B, fontSize=7.5, textColor=ACCENT,
                     leading=16.5),
        "bank": S("bank", fontName=SERIF_B, fontSize=10.5, textColor=ACCENT_DK,
                  leading=17, alignment=TA_CENTER, splitLongWords=0),
        "caption": S("caption", fontName=SANS, fontSize=8, textColor=FAINT,
                     leading=11, alignment=TA_CENTER),
        "prompt": S("prompt", fontName=SANS, fontSize=7.5, textColor=FAINT,
                    leading=10),
        "sol_h": S("sol_h", fontName=SERIF_B, fontSize=9.5, leading=13,
                   spaceBefore=2 * mm, spaceAfter=0.8 * mm),
        "sol": S("sol", fontSize=8.5, textColor=MUTED, leading=12.5),
        "grammar_name": S("grammar_name", fontName=SERIF_B, fontSize=10.5,
                          textColor=ACCENT_DK, leading=14),
    }


# ---------------------------------------------------------------------------
# Running header / footer
# ---------------------------------------------------------------------------

def _furniture(canvas, doc, text: SourceText) -> None:
    canvas.saveState()
    # Footer rule + page number + wordmark
    canvas.setStrokeColor(HAIRLINE)
    canvas.setLineWidth(0.5)
    canvas.line(MARGIN, 1.25 * cm, PAGE_W - MARGIN, 1.25 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(FAINT)
    canvas.drawString(MARGIN, 0.85 * cm, "langwich")
    canvas.drawRightString(
        PAGE_W - MARGIN, 0.85 * cm,
        f"{text.topic.title()} · {text.cefr_level} · "
        f"{text.source_lang.upper()}–{text.target_lang.upper()}",
    )
    canvas.drawCentredString(PAGE_W / 2, 0.85 * cm, f"{doc.page}")
    # Running header from page 2
    if doc.page > 1:
        canvas.setFont("Helvetica-Bold", 7.5)
        canvas.setFillColor(FAINT)
        canvas.drawString(MARGIN, PAGE_H - 1.15 * cm, "LANGWICH WORKSHEET")
        canvas.setStrokeColor(HAIRLINE)
        canvas.line(MARGIN, PAGE_H - 1.3 * cm, PAGE_W - MARGIN, PAGE_H - 1.3 * cm)
    canvas.restoreState()


# ---------------------------------------------------------------------------
# Shared flowables
# ---------------------------------------------------------------------------

def _rule(color=HAIRLINE, width=0.7, space_before=0.0, space_after=2.5 * mm) -> Table:
    t = Table([[""]], colWidths=[CONTENT_W], rowHeights=[0.1])
    t.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, -1), width, color),
        ("TOPPADDING", (0, 0), (-1, -1), space_before),
        ("BOTTOMPADDING", (0, 0), (-1, -1), space_after),
    ]))
    return t


def _writing_lines(count: int, width: float = CONTENT_W, indent: float = 0.0) -> list:
    rows = [[""] for _ in range(count)]
    t = Table(rows, colWidths=[width - indent], rowHeights=[8.5 * mm] * count)
    t.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, WRITE_LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), indent),
    ]))
    return [t]


_NUMW = 9 * mm  # width of the exercise-number block


def _exercise_header(ex: ExerciseInstance, index: int, styles: dict) -> list:
    """A textbook-style exercise band: numbered tab + shaded title bar, then the
    rubric — the way a printed coursebook opens each exercise."""
    num = Paragraph(f'<font color="white"><b>{index}</b></font>',
                    ParagraphStyle("num", fontName=SERIF_B, fontSize=13,
                                   alignment=TA_CENTER, textColor=colors.white))
    band = Table([[num, Paragraph(ex.title, styles["ex_title"])]],
                 colWidths=[_NUMW, CONTENT_W - _NUMW], rowHeights=[8.6 * mm])
    band.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ACCENT),
        ("BACKGROUND", (1, 0), (1, 0), TINT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, 0), "CENTER"),
        ("LEFTPADDING", (1, 0), (1, 0), 3.5 * mm),
        ("LINEBELOW", (0, 0), (-1, -1), 1.0, ACCENT),
    ]))

    chips = []
    if ex.focus:
        chips.append(ex.focus)
    chips.append("&#8226;" * ex.difficulty + "&#183;" * (5 - ex.difficulty))
    if ex.estimated_minutes:
        chips.append(f"~{ex.estimated_minutes} min")
    meta = "&nbsp;&nbsp;·&nbsp;&nbsp;".join(chips)

    sub = Table([["", [Paragraph(meta, styles["ex_meta"]),
                       Paragraph(ex.instruction, styles["rubric"])]]],
                colWidths=[_NUMW, CONTENT_W - _NUMW])
    sub.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (1, 0), (1, 0), 3.5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4 * mm),
    ]))
    return [band, sub]


def _word_bank(words: list[str], styles: dict) -> list:
    text = ("&nbsp;&nbsp;&nbsp;<font color='#C7BFB0'>·</font>&nbsp;&nbsp;&nbsp;"
            ).join(words)
    label = Paragraph("WORD BANK", ParagraphStyle(
        "wbl", fontName="Helvetica-Bold", fontSize=7.5, textColor=ACCENT,
        alignment=TA_CENTER, spaceAfter=1.5 * mm))
    inner = Paragraph(text, styles["bank"])
    box = Table([[label], [inner]], colWidths=[CONTENT_W])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), TINT),
        ("BOX", (0, 0), (-1, -1), 0.6, HAIRLINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [4, 4, 4, 4]),
    ]))
    return [box, Spacer(1, 4 * mm)]


def _picture_box(prompt: str, caption: str, styles: dict) -> list:
    box = Table([[Paragraph(
        "<font color='#8C857A'><i>Picture area — paste or draw the scene here</i></font>",
        ParagraphStyle("ph", fontSize=9, alignment=TA_CENTER, textColor=FAINT))]],
        colWidths=[CONTENT_W], rowHeights=[6.6 * cm])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("BOX", (0, 0), (-1, -1), 1, HAIRLINE),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [5, 5, 5, 5]),
    ]))
    out: list = [box]
    if caption:
        out.append(Spacer(1, 1.5 * mm))
        out.append(Paragraph(caption, styles["caption"]))
    out.append(Spacer(1, 1.5 * mm))
    out.append(Paragraph(f"<b>Image prompt:</b> {prompt}", styles["prompt"]))
    out.append(Spacer(1, 4 * mm))
    return out


# ---------------------------------------------------------------------------
# Exercise body renderers
# ---------------------------------------------------------------------------

def _render_fib(ex: ExerciseInstance, styles: dict) -> list:
    out: list = []
    if ex.word_bank:
        out.extend(_word_bank(ex.word_bank, styles))
    for it in ex.items:
        line = f"<b>{it['number']}.</b>&nbsp;&nbsp;{it['sentence']}"
        if "hint" in it:
            line += f"&nbsp;&nbsp;<font color='#565049'><i>{it['hint']}</i></font>"
        if "choices" in it:
            opts = "&nbsp;&nbsp;/&nbsp;&nbsp;".join(it["choices"])
            line += (f"<br/><font color='#1F5468' size='9'>"
                     f"&nbsp;&nbsp;&nbsp;&nbsp;{opts}</font>")
        if "translation" in it:
            line += (f"<br/><font color='#8C857A' size='8.5'><i>"
                     f"{it['translation']}</i></font>")
        out.append(Paragraph(line, styles["item"]))
    return out


def _numbered_answer_table(items: list[dict], styles: dict,
                           label_for) -> Table:
    rows = []
    for it in items:
        n = it.get("number", "")
        label = label_for(it)
        rows.append([Paragraph(f"<b>{n}.</b>&nbsp;&nbsp;{label}", styles["item"]), ""])
    t = Table(rows, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
    t.setStyle(TableStyle([
        ("LINEBELOW", (1, 0), (1, -1), 0.4, WRITE_LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 1.6 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
        ("LEFTPADDING", (1, 0), (1, -1), 4 * mm),
    ]))
    return t


def _render_picture(ex: ExerciseInstance, styles: dict, show_picture: bool) -> list:
    out: list = []
    if show_picture and ex.picture_prompt:
        out.extend(_picture_box(ex.picture_prompt, ex.picture_caption, styles))

    if ex.node_id in ("pic_color_query", "pic_position", "pic_object_naming"):
        def label(it: dict) -> str:
            return it.get("term", "")
        out.append(_numbered_answer_table(ex.items, styles, label))

    elif ex.node_id == "pic_element_marking":
        names = ex.items[0].get("mark", []) if ex.items else []
        chips = "&nbsp;&nbsp;&nbsp;&nbsp;".join(
            f"<font color='#1F5468'>&#8226;</font>&nbsp;{n}" for n in names)
        out.append(Paragraph(chips, styles["item"]))

    elif ex.node_id == "pic_scene_description":
        lines = ex.items[0].get("write_lines", 5) if ex.items else 5
        out.extend(_writing_lines(lines))

    elif ex.node_id == "pic_fib":
        for it in ex.items:
            if "text" in it:
                out.append(_panel(it["text"], styles))
    return out


def _reading_panel(content: str, styles: dict) -> Table:
    """The reading passage, boxed, with margin paragraph numbers — textbook style."""
    paras = [p.strip() for p in content.split("\n\n") if p.strip()]
    rows = []
    for i, p in enumerate(paras, 1):
        rows.append([Paragraph(str(i), styles["readnum"]),
                     Paragraph(p.replace("\n", "<br/>"), styles["reading"])])
    t = Table(rows, colWidths=[7 * mm, CONTENT_W - 7 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("BOX", (0, 0), (-1, -1), 0.8, HAIRLINE),
        ("LINEAFTER", (0, 0), (0, -1), 0.5, HAIRLINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("LEFTPADDING", (0, 0), (0, -1), 2 * mm),
        ("RIGHTPADDING", (0, 0), (0, -1), 2.5 * mm),
        ("LEFTPADDING", (1, 0), (1, -1), 5 * mm),
        ("RIGHTPADDING", (1, 0), (1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
    ]))
    return t


def _panel(content: str, styles: dict) -> Table:
    para = Paragraph(content.replace("\n", "<br/>"), styles["reading"])
    t = Table([[para]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), PAPER),
        ("BOX", (0, 0), (-1, -1), 0.6, HAIRLINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4 * mm),
        ("ROUNDEDCORNERS", (0, 0), (-1, -1), [4, 4, 4, 4]),
    ]))
    return t


def _render_word_connections(ex: ExerciseInstance, styles: dict) -> list:
    out: list = []
    it = ex.items[0] if ex.items else {}

    if ex.node_id == "wc_translation" and "left" in it:
        left, right = it["left"], it["right"]
        rows = []
        for i in range(max(len(left), len(right))):
            ltxt = f"<b>{left[i]['number']}.</b>&nbsp;&nbsp;{left[i]['term']}" if i < len(left) else ""
            rtxt = f"<b>{right[i]['letter']}.</b>&nbsp;&nbsp;{right[i]['term']}" if i < len(right) else ""
            rows.append([Paragraph(ltxt, styles["body"]),
                         Paragraph(rtxt, styles["body"])])
        t = Table(rows, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
        t.setStyle(_match_style())
        out.append(t)

    elif ex.node_id == "wc_compound" and "left" in it:
        left, right = it["left"], it["right"]
        rows = []
        for i in range(max(len(left), len(right))):
            ltxt = f"<b>{i + 1}.</b>&nbsp;&nbsp;{left[i]}" if i < len(left) else ""
            rtxt = f"<b>{chr(65 + i)}.</b>&nbsp;&nbsp;{right[i]}" if i < len(right) else ""
            rows.append([Paragraph(ltxt, styles["body"]), Paragraph(rtxt, styles["body"])])
        t = Table(rows, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
        t.setStyle(_match_style())
        out.append(t)
        out.append(Spacer(1, 3 * mm))
        out.append(Paragraph("Write the compound words you built:", styles["body"]))
        out.extend(_writing_lines(max(2, (len(left) + 1) // 2)))

    elif ex.node_id in ("wc_synonym", "wc_antonym"):
        out.append(_numbered_answer_table(ex.items, styles, lambda it: it.get("term", "")))

    elif ex.node_id == "wc_category" and "words" in it:
        out.extend(_word_bank(it["words"], styles))
        for cat in it["categories"]:
            out.append(Paragraph(f"<b>{cat}</b>", styles["body"]))
            out.extend(_writing_lines(1))
            out.append(Spacer(1, 1.5 * mm))
    return out


def _match_style() -> TableStyle:
    return TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.2 * mm),
        ("LINEBELOW", (0, 0), (-1, -1), 0.4, HAIRLINE),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (1, -1), 8 * mm),
    ])


def _render_comprehension(ex: ExerciseInstance, styles: dict) -> list:
    out: list = []
    if ex.node_id == "comp_questions":
        for it in ex.items:
            out.append(Paragraph(
                f"<b>{it['number']}.</b>&nbsp;&nbsp;{it['prompt']}", styles["item"]))
            out.extend(_writing_lines(2))
            out.append(Spacer(1, 1.5 * mm))
    elif ex.node_id == "comp_true_false":
        for it in ex.items:
            line = (f"<b>{it['number']}.</b>&nbsp;&nbsp;{it['text']}"
                    "&nbsp;&nbsp;&nbsp;&nbsp;"
                    "<font color='#565049'>(&nbsp;&nbsp;) true"
                    "&nbsp;&nbsp;&nbsp;(&nbsp;&nbsp;) false</font>")
            out.append(Paragraph(line, styles["item"]))
    elif ex.node_id == "comp_sequence":
        for it in ex.items:
            line = (f"<font color='#565049'>(&nbsp;&nbsp;&nbsp;)</font>"
                    f"&nbsp;&nbsp;<b>{it['letter']}.</b>&nbsp;&nbsp;{it['text']}")
            out.append(Paragraph(line, styles["item"]))
    return out


def _render_body(ex: ExerciseInstance, styles: dict, show_picture: bool) -> list:
    if ex.node_id.startswith("fib"):
        return _render_fib(ex, styles)
    if ex.node_id.startswith("pic"):
        return _render_picture(ex, styles, show_picture)
    if ex.node_id.startswith("wc"):
        return _render_word_connections(ex, styles)
    if ex.node_id.startswith("comp"):
        return _render_comprehension(ex, styles)
    return []


# ---------------------------------------------------------------------------
# Story / reference / solution pages
# ---------------------------------------------------------------------------

def _render_cover(text: SourceText, styles: dict, total_minutes: int) -> list:
    out: list = [
        Paragraph("LANGWICH&nbsp;&nbsp;·&nbsp;&nbsp;LANGUAGE WORKSHEET", styles["eyebrow"]),
        Paragraph(text.title, styles["title"]),
    ]
    meta = (f"{text.topic.title()}&nbsp;&nbsp;·&nbsp;&nbsp;Level {text.cefr_level}"
            f"&nbsp;&nbsp;·&nbsp;&nbsp;{text.source_lang.upper()} → "
            f"{text.target_lang.upper()}")
    if total_minutes:
        meta += f"&nbsp;&nbsp;·&nbsp;&nbsp;~{total_minutes} min"
    out.append(Paragraph(meta, styles["meta"]))
    out.append(_rule(ACCENT, 1.4, space_after=4 * mm))
    # Lead with the facts (in the target language), then the story — one text box.
    out.extend(_render_facts(text, styles))
    out.append(Paragraph("READING TEXT", styles["eyebrow"]))
    out.append(_reading_panel(text.content, styles))
    out.append(Spacer(1, 5 * mm))
    return out


def _render_grammar(text: SourceText, styles: dict) -> list:
    if not text.grammar or not text.grammar.phenomena:
        return []
    out: list = [Paragraph("Grammar in this story", styles["section"]),
                 Spacer(1, 2 * mm)]
    for p in text.grammar.phenomena:
        block = [Paragraph(p.name.title(), styles["grammar_name"]),
                 Paragraph(p.description, styles["rubric"])]
        for ex in p.examples:
            block.append(Paragraph(f"<font color='#1F5468'>•</font>&nbsp;&nbsp;"
                                   f"<i>{ex}</i>", styles["body"]))
        card = Table([[block]], colWidths=[CONTENT_W])
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TINT),
            ("LINEBEFORE", (0, 0), (0, -1), 2.5, ACCENT),
            ("LEFTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
        ]))
        out.append(KeepTogether([card, Spacer(1, 3 * mm)]))
    return out


def _render_facts(text: SourceText, styles: dict) -> list:
    """A light lead-in (not a boxed panel) so the page has a single text box.

    Facts are written in the target language, so they double as a first read
    before the story.
    """
    if not text.facts:
        return []
    out: list = [Paragraph("FACTS &amp; CULTURE", styles["eyebrow"])]
    for f in text.facts:
        line = f"<font color='#1F5468'>&#8226;</font>&nbsp;&nbsp;{f.text}"
        if f.source:
            line += f"&nbsp;<font color='#8C857A' size='8'>({f.source})</font>"
        out.append(Paragraph(line, styles["body"]))
    out.append(Spacer(1, 4 * mm))
    return out


def _render_vocabulary(text: SourceText, styles: dict) -> list:
    if not text.vocabulary or not text.vocabulary.items:
        return []
    out: list = [Paragraph("Vocabulary", styles["section"]), Spacer(1, 2 * mm)]
    by_pos: dict[str, list] = {}
    for v in text.vocabulary.items:
        by_pos.setdefault(v.pos, []).append(v)

    for pos in sorted(by_pos):
        items = by_pos[pos]
        rows = []
        for v in items:
            extra = ""
            if v.synonym:
                extra += f"  <font color='#8C857A'>≈ {v.synonym}</font>"
            if v.antonym:
                extra += f"  <font color='#8C857A'>≠ {v.antonym}</font>"
            rows.append([Paragraph(f"<b>{v.term}</b>", styles["sol"]),
                         Paragraph(f"{v.translation}{extra}", styles["sol"])])
        tbl = Table(rows, colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.58])
        tbl.setStyle(TableStyle([
            ("TEXTCOLOR", (1, 0), (1, -1), MUTED),
            ("TOPPADDING", (0, 0), (-1, -1), 1.1 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.1 * mm),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, HAIRLINE),
        ]))
        block = [Paragraph(pos.upper(), styles["eyebrow"]), tbl, Spacer(1, 3 * mm)]
        out.append(KeepTogether(block))
    return out


def _render_solutions(exercises: list[ExerciseInstance], styles: dict) -> list:
    sols = [ex for ex in exercises if ex.solution]
    if not sols:
        return []
    out: list = [Paragraph("Answer Key", styles["section"]), Spacer(1, 2 * mm)]
    for idx, ex in enumerate(exercises, 1):
        if not ex.solution:
            continue
        lines = [Paragraph(f"{idx}.&nbsp;&nbsp;{ex.title}", styles["sol_h"])]
        for s in ex.solution:
            lines.append(Paragraph(_solution_line(s), styles["sol"]))
        out.append(KeepTogether(lines + [Spacer(1, 1.5 * mm)]))
    return out


def _solution_line(s: dict) -> str:
    if "answer" in s:
        return f"{s.get('number', '')}. {s['answer']}"
    if "answers" in s:
        return ", ".join(s["answers"])
    if "synonym" in s:
        return f"{s.get('number', '')}. {s['term']} ≈ {s['synonym']}"
    if "antonym" in s:
        return f"{s.get('number', '')}. {s['term']} ≠ {s['antonym']}"
    if "compound" in s:
        return f"{s['left']} + {s['right']} = {s['compound']}"
    if "words" in s:
        return f"<b>{s.get('category', '')}:</b> {', '.join(s['words'])}"
    if "sequence" in s:
        order = "  ".join(f"{i}.{ltr}" for i, ltr in enumerate(s["sequence"], 1))
        return f"Correct order:  {order}"
    if "letter" in s:
        return f"{s['number']} → {s['letter']}"
    return ""


# ---------------------------------------------------------------------------
# Main render
# ---------------------------------------------------------------------------

def render_worksheet(
    text: SourceText,
    exercises: list[ExerciseInstance],
    output_path: str | Path,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    styles = _styles()
    total_minutes = sum(ex.estimated_minutes for ex in exercises)
    story: list = []

    story.extend(_render_cover(text, styles, total_minutes))

    # Exercises — numbered, kept together, picture shown only once.
    picture_shown = False
    for idx, ex in enumerate(exercises, 1):
        show_picture = ex.node_id.startswith("pic") and not picture_shown
        if show_picture:
            picture_shown = True
        header = _exercise_header(ex, idx, styles)
        body = _render_body(ex, styles, show_picture)
        # Keep the header with the first body element; let long bodies flow.
        head_chunk = header + body[:1]
        story.append(KeepTogether(head_chunk))
        story.extend(body[1:])
        story.append(Spacer(1, 6 * mm))

    # Reference + answer key, each starting fresh.
    refs: list = []
    refs.extend(_render_grammar(text, styles))
    vocab = _render_vocabulary(text, styles)
    if vocab:
        if refs:
            refs.append(Spacer(1, 5 * mm))
        refs.extend(vocab)
    if refs:
        story.append(PageBreak())
        story.extend(refs)

    sols = _render_solutions(exercises, styles)
    if sols:
        story.append(PageBreak())
        story.extend(sols)

    doc = BaseDocTemplate(
        str(output), pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=1.7 * cm, bottomMargin=1.6 * cm,
        title=text.title, author="langwich",
    )
    frame = Frame(MARGIN, 1.5 * cm, CONTENT_W, PAGE_H - 3.2 * cm, id="main")
    doc.addPageTemplates([PageTemplate(
        id="main", frames=[frame],
        onPage=lambda c, d, _t=text: _furniture(c, d, _t),
    )])
    doc.build(story)
    return output
