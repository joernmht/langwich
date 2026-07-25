"""HTML worksheet renderer — the default engine.

Builds the worksheet as a single HTML document with print CSS (paged
media) and converts it to PDF with WeasyPrint. The HTML file is written
next to the PDF so the design can be inspected and tweaked in a browser.

Design goals, shared with the ReportLab fallback in ``render.py``:
- one task per page,
- the vocabulary a page needs repeated small and grey along its bottom
  edge (a running footer element, so it follows overflow pages too),
- full-width pictures with high-contrast prompts,
- monochrome, high-contrast styling for e-paper and b/w print —
  with narrow side margins and an editorial look: big numerals,
  solid-black kicker chips, two-column serif reading text, drop cap.
"""

from __future__ import annotations

import base64
import html
import re
from pathlib import Path

from langwich.generate import ExerciseInstance
from langwich.render import (
    _COLOR_PROMPT_SUFFIX,
    _MONO_PROMPT_SUFFIX,
    _TASK_WORD,
    _VOCAB_WORD,
    _exercise_searchable,
    _humanize_topic,
    _load_image,
    _relevant_vocab,
    _renderer_for,
)
from langwich.text import PictureScene, SourceText

_READING_WORD = {"en": "Reading", "de": "Lesetext", "fr": "Lecture", "es": "Lectura"}

# A4 297mm minus 17mm top and 27mm bottom page margins.
_CONTENT_H_MM = 253

_CSS = """
@page {
  size: A4;
  margin: 17mm 12mm 27mm 12mm;
  @top-center { content: element(pageheader); width: 100%; vertical-align: bottom; }
  @bottom-center { content: element(vocab); width: 100%; vertical-align: top; }
  @bottom-right-corner { content: counter(page); font-size: 7pt; color: #999;
                         vertical-align: top; padding-top: 3mm; }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: "Helvetica Neue", Helvetica, Arial, "DejaVu Sans", sans-serif;
       color: #111; font-size: 10.5pt; line-height: 1.45; }

/* Running page furniture ------------------------------------------------ */
.pageheader { position: running(pageheader); width: 100%;
              font-size: 7.5pt; font-weight: bold; letter-spacing: 0.18em;
              color: #555; text-transform: uppercase;
              border-bottom: 1.4pt solid #111; padding-bottom: 1.6mm; }
.pageheader .right { float: right; letter-spacing: 0.12em; }
.vocab { position: running(vocab); width: 100%;
         border-top: 0.5pt solid #aaa; padding-top: 1.6mm;
         font-size: 7.5pt; line-height: 1.45; color: #777; }
.vocab.empty { border-top: none; }
.vocab .label { display: block; font-size: 6pt; font-weight: bold;
                letter-spacing: 0.22em; color: #999; text-transform: uppercase;
                margin-bottom: 0.8mm; }
.vocab b { font-weight: 600; color: #555; }
.vocab .sep { color: #bbb; padding: 0 1.2mm; }

/* Pages ------------------------------------------------------------------ */
section.page { break-after: page; }
section.page:last-child { break-after: auto; }

.kicker { display: inline-block; background: #111; color: #fff;
          font-size: 7pt; font-weight: bold; letter-spacing: 0.22em;
          text-transform: uppercase; padding: 1.1mm 2.6mm 0.9mm; }

/* Cover / reading page --------------------------------------------------- */
.cover h1 { font-size: 30pt; line-height: 1.08; letter-spacing: -0.01em;
            margin: 4mm 0 3mm; }
.cover .meta { font-size: 9pt; color: #666; letter-spacing: 0.08em;
               text-transform: uppercase; margin-bottom: 4mm; }
.titlebar { border-top: 2.6pt solid #111; border-bottom: 0.6pt solid #111;
            height: 1.8mm; margin-bottom: 6mm; }
.reading { font-family: Georgia, "DejaVu Serif", serif; font-size: 10pt;
           line-height: 1.55; text-align: justify; hyphens: auto;
           column-count: 2; column-gap: 8mm;
           column-rule: 0.4pt solid #ccc; }
.reading p { margin-bottom: 3.2mm; }
.reading p:first-child::first-line { font-weight: bold; }

/* Task pages ------------------------------------------------------------- */
.task-head { display: flex; align-items: flex-start; gap: 5mm;
             border-bottom: 0.6pt solid #111; padding-bottom: 3mm;
             margin-bottom: 5mm; }
.task-num { font-size: 44pt; font-weight: 800; line-height: 0.9;
            color: #d9d9d9; letter-spacing: -0.03em; }
.task-titles h2 { font-size: 19pt; line-height: 1.1; margin: 1.6mm 0 1.6mm; }
.instruction { font-style: italic; color: #666; font-size: 10pt; }

/* Components ------------------------------------------------------------- */
.bank { margin-bottom: 4.5mm; }
.chip { display: inline-block; border: 0.75pt solid #111; padding: 1mm 2.6mm;
        margin: 0 1.6mm 1.6mm 0; font-weight: bold; font-size: 9.5pt; }
.context { border-left: 1.8pt solid #111; padding: 1mm 0 1mm 4mm;
           margin-bottom: 4.5mm; font-family: Georgia, "DejaVu Serif", serif;
           line-height: 1.55; }
.searchbox { border: 0.75pt solid #111; padding: 2.4mm 3.5mm;
             margin-bottom: 4.5mm; font-weight: bold; }
.qa { margin: 0 0 3.2mm 2mm; font-size: 11pt; line-height: 1.5; }
.qa .qnum { font-weight: 800; padding-right: 1.5mm; }
.qa .hint { font-style: italic; color: #666; }
.qa .qtrans { display: block; font-size: 9pt; color: #777;
              font-style: italic; margin-left: 6mm; }
.blank { display: inline-block; width: 27mm; border-bottom: 0.9pt solid #111;
         height: 1em; vertical-align: baseline; }
.write-line { height: 8.5mm; border-bottom: 0.5pt dotted #888;
              margin: 0 0 0.5mm 2mm; }
.write-block { margin-bottom: 3mm; }

/* Matching --------------------------------------------------------------- */
table.match { width: 100%; border-collapse: collapse; margin-bottom: 4mm; }
table.match td { padding: 2.2mm 0; border-bottom: 0.4pt dotted #999;
                 font-size: 10.5pt; }
table.match td.r { text-align: right; }
table.match td.gap { width: 22%; }

/* Picture ---------------------------------------------------------------- */
figure.pic { margin-bottom: 3mm; text-align: center; }
figure.pic img { border: 1.5pt solid #111; }
figure.pic figcaption { font-size: 7.5pt; color: #777; font-style: italic;
                        margin-top: 1.4mm; text-align: left; }
.placeholder { border: 1.2pt dashed #555; display: flex; align-items: center;
               justify-content: center; color: #888; font-size: 9pt;
               margin-bottom: 2mm; }
.prompt { font-size: 8pt; color: #777; font-style: italic; line-height: 1.35;
          margin-bottom: 3mm; }
.prompt b { font-style: normal; color: #555; }

/* Reference pages -------------------------------------------------------- */
.ref h2 { font-size: 19pt; border-bottom: 0.6pt solid #111;
          padding-bottom: 2.5mm; margin: 1.5mm 0 5mm; }
.phenomenon { margin-bottom: 5mm; }
.phenomenon h3 { font-size: 11.5pt; margin-bottom: 1mm; }
.phenomenon .desc { font-style: italic; color: #666; font-size: 10pt;
                    margin-bottom: 1.6mm; }
.phenomenon .ex { border-left: 1.2pt solid #111; padding-left: 3.5mm;
                  margin: 0 0 1.4mm 1mm; font-family: Georgia, "DejaVu Serif", serif;
                  font-style: italic; font-size: 10pt; }
.solutions { column-count: 2; column-gap: 10mm; font-size: 9pt; }
.solutions .sol-block { break-inside: avoid; margin-bottom: 3.5mm; }
.solutions h3 { font-size: 9.5pt; margin-bottom: 1mm; }
.solutions div { color: #444; line-height: 1.5; }
"""


def _esc(value) -> str:
    return html.escape(str(value))


def _blankify(sentence: str) -> str:
    """Escape text and turn runs of underscores into styled blanks."""
    return re.sub(r"_{3,}", '<span class="blank"></span>', _esc(sentence))


def _vocab_band(pairs: list[tuple[str, str]], source_lang: str) -> str:
    if not pairs:
        return '<div class="vocab empty"></div>'
    label = _esc(_VOCAB_WORD.get(source_lang, _VOCAB_WORD["en"]))
    entries = '<span class="sep">·</span>'.join(
        f"<b>{_esc(term)}</b> – {_esc(translation)}" for term, translation in pairs
    )
    return f'<div class="vocab"><span class="label">{label}</span>{entries}</div>'


def _writing_lines(count: int) -> str:
    return ('<div class="write-block">'
            + '<div class="write-line"></div>' * max(count, 1)
            + "</div>")


# ---------------------------------------------------------------------------
# Picture
# ---------------------------------------------------------------------------

_CONTENT_W_MM = 186  # A4 210mm minus 12mm side margins


def _image_data_uri(source: str, monochrome: bool) -> tuple[str, float, float] | None:
    """Return (data URI, pixel width, pixel height) for an image source."""
    data = _load_image(source, monochrome)
    if data is None:
        return None
    raw = data.getvalue()
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        mime = "image/png"
    elif raw[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif raw[:6] in (b"GIF87a", b"GIF89a"):
        mime = "image/gif"
    else:
        mime = "image/png"
    from reportlab.lib.utils import ImageReader
    width, height = ImageReader(data).getSize()
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}", width, height


def _figure_height_mm(ex: ExerciseInstance) -> int:
    """Height budget for the picture: everything the questions leave free."""
    per_item = 0
    for item in ex.items:
        if "text" in item:
            per_item += 40
        else:
            per_item += 15 + 8 * (max(item.get("lines", 1), 1) - 1)
    free = _CONTENT_H_MM - 42 - 22 - per_item
    return max(70, min(free, 165))


def _picture_html(scene: PictureScene, ex: ExerciseInstance, monochrome: bool) -> str:
    height = _figure_height_mm(ex)
    if scene.image:
        loaded = _image_data_uri(scene.image, monochrome)
        if loaded:
            uri, px_w, px_h = loaded
            # Size the frame to the image so the border hugs it exactly —
            # no letterboxing inside the frame.
            scale = min(_CONTENT_W_MM / px_w, height / px_h)
            disp_w, disp_h = px_w * scale, px_h * scale
            caption = (f"<figcaption>Image: {_esc(scene.image_credit)}</figcaption>"
                       if scene.image_credit else "")
            return (f'<figure class="pic">'
                    f'<img src="{uri}" style="width:{disp_w:.1f}mm;height:{disp_h:.1f}mm"/>'
                    f"{caption}</figure>")

    suffix = _MONO_PROMPT_SUFFIX if monochrome else _COLOR_PROMPT_SUFFIX
    prompt = f"{scene.description.rstrip('.')}. {suffix}"
    return (
        f'<div class="placeholder" style="height:{height}mm">'
        f"[Picture placeholder — generate with the prompt below]</div>"
        f'<p class="prompt"><b>Image prompt:</b> {_esc(prompt)}</p>'
    )


# ---------------------------------------------------------------------------
# Exercise bodies
# ---------------------------------------------------------------------------

def _fib_html(ex: ExerciseInstance, text: SourceText, monochrome: bool) -> str:
    parts: list[str] = []
    if ex.word_bank:
        chips = "".join(f'<span class="chip">{_esc(w)}</span>' for w in ex.word_bank)
        parts.append(f'<div class="bank">{chips}</div>')
    if ex.context_text:
        ctx = _esc(ex.context_text).replace("\n", "<br/>")
        parts.append(f'<div class="context">{ctx}</div>')
    for item in ex.items:
        line = f'<span class="qnum">{_esc(item["number"])}.</span> {_blankify(item["sentence"])}'
        if "hint" in item:
            line += f'  <span class="hint">{_esc(item["hint"])}</span>'
        if "choices" in item:
            line += "  [ " + "  /  ".join(_esc(c) for c in item["choices"]) + " ]"
        if "translation" in item:
            line += f'<span class="qtrans">{_esc(item["translation"])}</span>'
        parts.append(f'<div class="qa">{line}</div>')
    return "".join(parts)


def _picture_ex_html(ex: ExerciseInstance, text: SourceText, monochrome: bool) -> str:
    parts: list[str] = []
    if text.picture_scene:
        parts.append(_picture_html(text.picture_scene, ex, monochrome))
    for item in ex.items:
        if "question" in item:
            parts.append(
                f'<div class="qa"><span class="qnum">{_esc(item.get("number", ""))}.</span> '
                f'{_esc(item["question"])}</div>'
            )
            parts.append(_writing_lines(1))
        elif "instruction" in item:
            num = item.get("number", "")
            prefix = f'<span class="qnum">{_esc(num)}.</span> ' if num else ""
            parts.append(f'<div class="qa">{prefix}{_blankify(item["instruction"])}</div>')
            if item.get("lines"):
                parts.append(_writing_lines(item["lines"]))
        elif "text" in item:
            ctx = _blankify(item["text"]).replace("\n", "<br/>")
            parts.append(f'<div class="context">{ctx}</div>')
    return "".join(parts)


def _media_html(ex: ExerciseInstance, text: SourceText, monochrome: bool) -> str:
    parts: list[str] = []
    if ex.context_text:
        parts.append(f'<div class="searchbox">{_esc(ex.context_text)}</div>')
    for item in ex.items:
        parts.append(
            f'<div class="qa"><span class="qnum">{_esc(item["number"])}.</span> '
            f'{_esc(item["task"])}</div>'
        )
        parts.append(_writing_lines(item.get("lines", 1)))
    return "".join(parts)


def _wc_html(ex: ExerciseInstance, text: SourceText, monochrome: bool) -> str:
    parts: list[str] = []
    for item in ex.items:
        if "left" in item and "right" in item:
            left, right = item["left"], item["right"]
            rows = []
            for i in range(max(len(left), len(right))):
                l_text = (f"{_esc(left[i]['number'])}. {_esc(left[i]['term'])}"
                          if i < len(left) else "")
                r_text = (f"{_esc(right[i]['letter'])}. {_esc(right[i]['term'])}"
                          if i < len(right) else "")
                rows.append(f'<tr><td>{l_text}</td><td class="gap"></td>'
                            f'<td class="r">{r_text}</td></tr>')
            parts.append(f'<table class="match">{"".join(rows)}</table>')
            if item.get("format") == "compound":
                parts.append('<div class="qa"><b>Write the compound words:</b></div>')
                parts.append(_writing_lines(len(right)))

        elif "words" in item and "categories" in item:
            chips = "".join(f'<span class="chip">{_esc(w)}</span>' for w in item["words"])
            parts.append(f'<div class="bank">{chips}</div>')
            for cat in item["categories"]:
                parts.append(f'<div class="qa"><b>{_esc(cat)}:</b></div>')
                parts.append(_writing_lines(1))

        elif "left_column" in item and "right_column" in item:
            rows = []
            for i, (l, r) in enumerate(zip(item["left_column"], item["right_column"]), 1):
                rows.append(
                    f'<tr><td>{i}. {_esc(l)}  +</td>'
                    f'<td>{_esc(r)}  =  <span class="blank" style="width:45mm"></span></td></tr>'
                )
            parts.append(f'<table class="match">{"".join(rows)}</table>')

        elif "term" in item:
            parts.append(
                f'<div class="qa"><span class="qnum">{_esc(item["number"])}.</span> '
                f'{_esc(item["term"])}  →  <span class="blank" style="width:45mm"></span></div>'
            )
    return "".join(parts)


_BODY_BUILDERS = {
    "fib": _fib_html,
    "picture": _picture_ex_html,
    "word_connections": _wc_html,
    "media": _media_html,
}


def _body_builder_for(ex: ExerciseInstance):
    renderer = _renderer_for(ex)
    if renderer is None:
        return None
    for key, builder in _BODY_BUILDERS.items():
        if renderer.__name__ == f"_render_{key}" or key in renderer.__name__:
            return builder
    return None


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

def _cover_page(text: SourceText) -> str:
    reading_word = _READING_WORD.get(text.source_lang, _READING_WORD["en"])
    paragraphs = "".join(f"<p>{_esc(p)}</p>" for p in text.paragraphs)
    vocab = _vocab_band(_relevant_vocab(text, text.content), text.source_lang)
    return f"""
<section class="page cover">
  {vocab}
  <span class="kicker">{_esc(reading_word)}</span>
  <h1>{_esc(text.title)}</h1>
  <div class="meta">{_esc(_humanize_topic(text.topic))} · {_esc(text.cefr_level)} ·
    {_esc(text.source_lang.upper())} → {_esc(text.target_lang.upper())}</div>
  <div class="titlebar"></div>
  <div class="reading" lang="{_esc(text.target_lang)}">{paragraphs}</div>
</section>"""


def _task_page(index: int, total: int, ex: ExerciseInstance, text: SourceText,
               body: str) -> str:
    word = _TASK_WORD.get(text.source_lang, _TASK_WORD["en"])
    vocab = _vocab_band(_relevant_vocab(text, _exercise_searchable(ex)),
                        text.source_lang)
    return f"""
<section class="page task">
  {vocab}
  <header class="task-head">
    <div class="task-num">{index:02d}</div>
    <div class="task-titles">
      <span class="kicker">{_esc(word)} {index} / {total}</span>
      <h2>{_esc(ex.title)}</h2>
      <p class="instruction">{_esc(ex.instruction)}</p>
    </div>
  </header>
  {body}
</section>"""


def _grammar_page(text: SourceText) -> str:
    if not text.grammar or not text.grammar.phenomena:
        return ""
    blocks = []
    for p in text.grammar.phenomena:
        # Sentence case, not .title() — "passé composé" must not become
        # "Passé Composé".
        name = p.name[:1].upper() + p.name[1:]
        examples = "".join(f'<div class="ex">{_esc(e)}</div>' for e in p.examples)
        blocks.append(
            f'<div class="phenomenon"><h3>{_esc(name)}</h3>'
            f'<div class="desc">{_esc(p.description)}</div>{examples}</div>'
        )
    return (f'<section class="page ref"><div class="vocab empty"></div>'
            f"<h2>Grammar Reference</h2>{''.join(blocks)}</section>")


def _solution_lines(sol: dict) -> str:
    if "answer" in sol:
        return f"{sol.get('number', '')}. {sol['answer']}"
    if "answers" in sol:
        return ", ".join(sol["answers"])
    if "synonym" in sol:
        return f"{sol.get('number', '')}. {sol['term']} → {sol['synonym']}"
    if "antonym" in sol:
        return f"{sol.get('number', '')}. {sol['term']} → {sol['antonym']}"
    if "words" in sol:
        return f"{sol.get('category', '')}: {', '.join(sol['words'])}"
    if "compound" in sol:
        return f"{sol.get('parts', '')} = {sol['compound']}"
    if "letter" in sol:
        return f"{sol['number']} → {sol['letter']}"
    return ""


def _solutions_page(exercises: list[ExerciseInstance]) -> str:
    if not any(ex.solution for ex in exercises):
        return ""
    blocks = []
    for ex in exercises:
        if not ex.solution:
            continue
        lines = "".join(f"<div>{_esc(_solution_lines(s))}</div>"
                        for s in ex.solution if _solution_lines(s))
        blocks.append(f'<div class="sol-block"><h3>{_esc(ex.title)}</h3>{lines}</div>')
    return (f'<section class="page ref"><div class="vocab empty"></div>'
            f'<h2>Solutions</h2><div class="solutions">{"".join(blocks)}</div></section>')


# ---------------------------------------------------------------------------
# Document assembly & PDF conversion
# ---------------------------------------------------------------------------

def build_html(text: SourceText, exercises: list[ExerciseInstance],
               monochrome: bool = True) -> str:
    renderable = [(ex, _body_builder_for(ex)) for ex in exercises]
    renderable = [(ex, b) for ex, b in renderable if b is not None]
    total = len(renderable)

    pages = [_cover_page(text)]
    for i, (ex, builder) in enumerate(renderable, 1):
        pages.append(_task_page(i, total, ex, text, builder(ex, text, monochrome)))
    pages.append(_grammar_page(text))
    pages.append(_solutions_page([ex for ex, _ in renderable]))

    header = (
        f'<div class="pageheader"><span class="right">'
        f"{_esc(text.source_lang.upper())} → {_esc(text.target_lang.upper())}</span>"
        f"langwich · {_esc(_humanize_topic(text.topic))} · {_esc(text.cefr_level)}</div>"
    )

    return (
        f'<!DOCTYPE html><html lang="{_esc(text.source_lang)}"><head>'
        f'<meta charset="utf-8"/><title>{_esc(text.title)}</title>'
        f"<style>{_CSS}</style></head><body>{header}{''.join(pages)}</body></html>"
    )


def render_worksheet_html(
    text: SourceText,
    exercises: list[ExerciseInstance],
    output_path: str | Path,
    monochrome: bool = True,
) -> Path:
    """Render the worksheet via HTML + WeasyPrint.

    Writes ``<output>.html`` next to the PDF and raises ``ImportError`` /
    ``OSError`` if WeasyPrint (or its system libraries: Pango) is
    unavailable — callers fall back to the ReportLab renderer then.
    """
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    document = build_html(text, exercises, monochrome)
    html_path = output.with_suffix(".html")
    html_path.write_text(document, encoding="utf-8")

    from weasyprint import HTML  # deferred: import needs Pango system libs

    HTML(string=document).write_pdf(str(output))
    return output
