"""HTML for the 20 task kinds.

Each renderer returns :class:`Parts`: the main column, the side-column notes
(word boxes; grammar sidebars are added by the builder) and optional
full-width content shown above the body (pictures). Items are numbered in
the gutter; blanks within a task share one width, sized from its longest
answer; writing lines are solid and 9 mm apart.
"""

from __future__ import annotations

import itertools
import math
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langwich import crossword, markup
from langwich.answers import cloze_texts, letter, safe_gaps
from langwich.model import (
    ClassifyTask,
    ClozeTask,
    CrosswordTask,
    DialogueTask,
    DrawTask,
    FindInTextTask,
    GappedTextTask,
    LabelTask,
    MatchTask,
    MediaSearchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    ProofreadTask,
    QuestionsTask,
    ScrambleTask,
    TableTask,
    TransformTask,
    TrueFalseTask,
    WordBuildingTask,
    WritingTask,
)
from langwich.plan import PlannedTask
from langwich.render import metrics
from langwich.render.css import GUTTER_W
from langwich.render.html import esc, esc_nw, trailing_punctuation

if TYPE_CHECKING:
    from langwich.render.html import Builder


@dataclass
class Parts:
    main: str
    aside: list[str] = field(default_factory=list)
    pre: str = ""
    #: the task works best when all of it is in view (a word box beside its items)
    keep: bool = False
    #: the task only works when all of it is in view (match, order, label, draw)
    keep_hard: bool = False

    def __post_init__(self) -> None:
        if self.keep_hard:
            self.keep = True


def _item(n: int | str, content: str, cls: str = "c", attrs: str = "") -> str:
    return f'<div class="it"><span class="n">{n}</span><div class="{cls}"{attrs}>{content}</div></div>'


def gapped_html(
    b: Builder,
    text: str,
    width: float,
    hint: str = "none",
    numbers: Iterator[int] | None = None,
) -> str:
    """Text with ``{{gaps}}`` turned into blanks of ``width`` mm.

    A blank sits flush after an elision (l', d', qu'), and closing
    punctuation right after it moves into the unbreakable gap, so neither
    'l' e____' nor a full stop alone at the start of a line can happen.
    """
    try:
        parts = markup.split(text)
    except ValueError:
        b.warn(f"malformed gap markup in {text[:40]!r}…; printed as is.")
        return esc(text)
    out: list[str] = []
    skip = 0  # characters of the next text part already printed inside a gap
    for idx, part in enumerate(parts):
        if isinstance(part, str):
            out.append(esc(part[skip:]).replace("\n", "<br>"))
            skip = 0
            continue
        before = parts[idx - 1] if idx else ""
        after_part = parts[idx + 1] if idx + 1 < len(parts) else ""
        prev = before if isinstance(before, str) else ""
        nxt = after_part if isinstance(after_part, str) else ""
        num = f'<span class="gn">{next(numbers)}</span>' if numbers is not None else ""
        inner = (f'<span class="fl">{esc(part.answer[:1])}</span>' if hint == "first_letter"
                 else "&nbsp;")
        after = ""
        if part.hint and hint in ("base_form", "translation", "dialogue"):
            after = f'\u00a0<span class="hint">({esc(part.hint)})</span>'
        punct = trailing_punctuation(nxt)
        skip = len(punct)
        classes = ["gap"]
        if prev[-1:] in ("'", "’"):
            classes.append("el")
        if punct and not after:
            classes.append("pu")
        tail = esc(punct.replace(" ", "\u00a0"))
        out.append(f'<span class="{" ".join(classes)}">{num}<span class="blank" '
                   f'style="width:{width:.1f}mm">{inner}</span>{after}{tail}</span>')
    return "".join(out)


def bank_counts(answers: list[str]) -> dict[str, int]:
    """How many gaps each word-box word fills (casefolded)."""
    return dict(Counter(a.casefold() for a in answers))


def unique_words(words: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for w in words:
        if w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return out


# ---------------------------------------------------------------------------
# Kinds
# ---------------------------------------------------------------------------


def _match(b: Builder, pt: PlannedTask, task: MatchTask) -> Parts:
    right = pt.right_column if pt.right_order is not None else (
        [p.right for p in task.pairs] + list(task.extra))
    left_tl = b.column_is_target([p.left for p in task.pairs])
    right_tl = b.column_is_target([p.right for p in task.pairs])
    aside = b.has_aside(pt, False)
    width = b.main_width(aside)
    table_w = width if (b.epaper or aside) else min(width, 150.0)
    term_w = f' style="width:{(table_w - GUTTER_W - 14 - 7) * 0.46:.1f}mm"'
    term_cls = "term" if left_tl else "term src"
    rows = []
    for i in range(max(len(task.pairs), len(right))):
        if i < len(task.pairs):
            term = b.tl(task.pairs[i].left) if left_tl else esc(task.pairs[i].left)
            cells = (f'<td class="n">{i + 1}</td><td class="{term_cls}"{term_w}>{term}</td>'
                     '<td class="bx"><span></span></td>')
        else:
            cells = f'<td class="n"></td><td class="term"{term_w}></td><td class="bx"></td>'
        if i < len(right):
            value = b.tl(right[i]) if right_tl else esc(right[i])
            cells += (f'<td class="l">{letter(i)}</td>'
                      f'<td class="opt{" tl" if right_tl else ""}">{value}</td>')
        else:
            cells += '<td class="l"></td><td class="opt"></td>'
        rows.append(f"<tr>{cells}</tr>")
    return Parts(f'<table class="match" style="width:{table_w:.1f}mm">{"".join(rows)}</table>',
                 keep_hard=True)


def _true_false(b: Builder, pt: PlannedTask, task: TrueFalseTask) -> Parts:
    boxes = (f'<span class="cks"><span class="ck"><span class="bxs"></span>{esc(b.t("true"))}</span>'
             f'<span class="ck"><span class="bxs"></span>{esc(b.t("false"))}</span></span>')
    items = "".join(
        f'<div class="it"><span class="n">{i}</span><div class="c">{b.tl(item.statement)}</div>'
        f'{boxes}<span class="corr"></span></div>'
        for i, item in enumerate(task.items, 1)
    )
    return Parts(f'<div class="items tf">{items}</div>')


def _multiple_choice(b: Builder, pt: PlannedTask, task: MultipleChoiceTask) -> Parts:
    avail = b.main_width(b.has_aside(pt, False)) - GUTTER_W
    items = []
    for i, item in enumerate(task.items):
        order = pt.option_orders[i] if pt.option_orders else list(item.options)
        n = len(order)
        widest = max(metrics.width_mm(o, "serif", 11.0) for o in order) + 10.0 + 5.0
        row = n <= 4 and widest * n <= avail
        opts = "".join(
            f'<div class="op"><span class="bxs"></span><span class="lt">{letter(j, upper=False)}</span>'
            f'<span class="ot">{b.tl(o)}</span></div>'
            for j, o in enumerate(order)
        )
        style = f' style="grid-template-columns:repeat({n}, 1fr)"' if row else ""
        klass = "opts row" if row else "opts col"
        items.append(_item(i + 1, f'{b.tl(item.question, "p", "q")}<div class="{klass}"{style}>{opts}</div>'))
    return Parts(f'<div class="items mc">{"".join(items)}</div>')


def _order_events(b: Builder, pt: PlannedTask, task: OrderEventsTask) -> Parts:
    events = pt.events if pt.events is not None else list(task.events)
    rows = "".join(f'<div class="ev"><span class="bx"></span>{b.tl(e)}</div>' for e in events)
    return Parts(f'<div class="events">{rows}</div>', keep_hard=True)


def _questions(b: Builder, pt: PlannedTask, task: QuestionsTask) -> Parts:
    items = "".join(
        _item(i, b.tl(item.question, "p", "q") + b.lines(item.lines))
        for i, item in enumerate(task.items, 1)
    )
    return Parts(f'<div class="items qs">{items}</div>')


def _cloze(b: Builder, pt: PlannedTask, task: ClozeTask) -> Parts:
    texts = cloze_texts(task)
    answers = [g.answer for text in texts for g in safe_gaps(text)]
    bank = pt.bank if task.hint == "word_bank" and pt.bank else None
    width = b.blank_width(answers, b.has_aside(pt, bool(bank)))
    if task.text is not None:
        counter = itertools.count(1)
        paras = [p for p in task.text.split("\n\n") if p.strip()]
        body = "".join(f"<p>{gapped_html(b, p.strip(), width, task.hint, counter)}</p>" for p in paras)
        main = f'<div class="passage tl"{b.lang_attr()}>{body}</div>'
    else:
        items = "".join(
            _item(i, gapped_html(b, text, width, task.hint), "c tl", b.lang_attr())
            for i, text in enumerate(task.items or [], 1)
        )
        main = f'<div class="items gapped">{items}</div>'
    boxes = [b.word_box(unique_words(bank), counts=bank_counts(answers))] if bank else []
    return Parts(main, boxes, keep=bool(bank))


def _transform(b: Builder, pt: PlannedTask, task: TransformTask) -> Parts:
    items = []
    for i, item in enumerate(task.items, 1):
        cue = f"→ {esc(item.cue)}" if item.cue else "→"
        items.append(_item(
            i, f'{b.tl(item.prompt, "p", "q")}<div class="wl"><span class="cue">{cue}</span>'
               '<span class="line"></span></div>'))
    return Parts(f'<div class="items tr">{"".join(items)}</div>')


def _word_building(b: Builder, pt: PlannedTask, task: WordBuildingTask) -> Parts:
    k = max(len(item.parts) for item in task.items)
    part_w = [
        max(metrics.width_mm(item.parts[j], "serif", 11.0) for item in task.items if j < len(item.parts))
        + 2.5
        for j in range(k)
    ]
    op_w = 8.0
    used = GUTTER_W + sum(part_w) + op_w * k
    avail = b.main_width(b.has_aside(pt, False))
    line_w = min(70.0, max(30.0, avail - used))
    template = [GUTTER_W]
    for j, width in enumerate(part_w):
        if j:
            template.append(op_w)
        template.append(width)
    template += [op_w, line_w]
    style = "grid-template-columns:" + " ".join(f"{x:.1f}mm" for x in template)
    rows = []
    for i, item in enumerate(task.items, 1):
        cells = [f'<span class="n" style="grid-column:1">{i}</span>']
        col = 2
        for j in range(k):
            if j:
                op = "+" if j < len(item.parts) else ""
                cells.append(f'<span class="op" style="grid-column:{col}">{op}</span>')
                col += 1
            part = esc(item.parts[j]) if j < len(item.parts) else ""
            cells.append(f'<span class="pt tl" style="grid-column:{col}"{b.lang_attr()}>{part}</span>')
            col += 1
        cells.append(f'<span class="op" style="grid-column:{col}">=</span>'
                     f'<span class="ln" style="grid-column:{col + 1}"></span>')
        rows.append(f'<div class="wbi" style="{style}">{"".join(cells)}</div>')
    return Parts(f'<div class="wb">{"".join(rows)}</div>')


def _label(b: Builder, pt: PlannedTask, task: LabelTask) -> Parts:
    scene = b.ws.scene(task.scene)
    labels = sorted(scene.picture.labels, key=lambda lb: lb.n) if scene and scene.picture else []
    prepared = b.label_picture(task)
    if prepared is None or scene is None:
        # "draw and label": the learner writes these labels, articles included
        terms = [lb.term for lb in labels] or pt.bank or []
        box = f'<div class="draw-words">{b.word_box(terms, row=True)}</div>' if terms else ""
        return Parts(f'{b.frame_html(pt)}{box}', keep_hard=True)
    fields = "".join(
        f'<div class="fld"><span>{lb.n}</span><span class="line"></span></div>' for lb in labels
    )
    grid = f'<div class="name-grid">{fields}</div>' if fields else ""
    bank = ""
    if task.bank and pt.bank:
        bank = f'<div class="label-bank">{b.word_box(pt.bank, row=True)}</div>'
    return Parts(grid + bank, pre=b.figure_html(scene, prepared, max_h=b.hints.shrink_for(pt.number)),
                 keep_hard=True)


def _writing(b: Builder, pt: PlannedTask, task: WritingTask) -> Parts:
    if task.lines:
        count = task.lines
    elif task.max_words:
        count = math.ceil(task.max_words / 10)
    elif task.min_words:
        count = math.ceil(task.min_words / 10) + 2
    else:
        count = 8
    if task.starter and not task.lines:
        count += 1
    count = max(1, min(count, 40))
    parts = [f'<p class="prompt">{esc(task.prompt)}</p>']
    if task.must_use:
        words = "".join(f'<span class="w"><span class="tick"></span>{esc(w)}</span>'
                        for w in task.must_use)
        parts.append(f'<div class="usewords"><span class="cap">{esc(b.t("use_words"))}</span>'
                     f'<span class="tl"{b.lang_attr()}>{words}</span></div>')
    parts.append(b.lines(count, task.starter))
    return Parts(f'<div class="writing">{"".join(parts)}</div>')


def _dialogue(b: Builder, pt: PlannedTask, task: DialogueTask) -> Parts:
    gaps = [g.answer for line in task.lines if line.text for g in safe_gaps(line.text)]
    width = b.blank_width(gaps, b.has_aside(pt, bool(pt.bank)))
    counter = itertools.count(1)
    # one grid per line (so pages can break between lines); the speaker
    # column is as wide as the longest name, within reason
    speaker_w = min(max(metrics.width_mm(f"{line.speaker}:", "sans-bold", 10.0) for line in task.lines)
                    + 3.5, 42.0)
    style = f' style="grid-template-columns:{GUTTER_W:.1f}mm {speaker_w:.1f}mm 1fr"'
    rows = []
    for line in task.lines:
        if line.text is not None:
            active = bool(safe_gaps(line.text))
            num = str(next(counter)) if active else ""
            text = gapped_html(b, line.text, width, "dialogue")
        else:
            num = str(next(counter))
            cue = (f'<span class="cue"{b.src_attr()}>({esc(line.cue)})</span>'
                   if line.cue else "")
            text = f'{cue}<div class="line"></div>'
        rows.append(f'<div class="dl"{style}><span class="dn">{num}</span>'
                    f'<span class="sp">{esc(line.speaker)}:</span>'
                    f'<div class="dt tl"{b.lang_attr()}>{text}</div></div>')
    boxes = [b.word_box(unique_words(pt.bank), counts=bank_counts(gaps))] if pt.bank else []
    return Parts(f'<div class="dlg">{"".join(rows)}</div>', boxes, keep=bool(boxes))


def _media_search(b: Builder, pt: PlannedTask, task: MediaSearchTask) -> Parts:
    sep = '<span class="sep">·</span>'
    queries = sep.join(esc_nw(q) for q in task.queries)
    search = (f'<div class="search"><span class="cap">{esc(b.t("search_for"))}</span>'
              f'<span class="q tl"{b.lang_attr()}>{queries}</span></div>')
    items = "".join(_item(i, b.tl(q, "p", "q") + b.lines(2)) for i, q in enumerate(task.questions, 1))
    return Parts(f'{search}<div class="items ms">{items}</div>')


def _draw(b: Builder, pt: PlannedTask, task: DrawTask) -> Parts:
    labels = ""
    if task.labels:
        labels = f'<div class="draw-words">{b.word_box(list(task.labels), row=True)}</div>'
    return Parts(f'<p class="prompt">{esc(task.prompt)}</p>{b.frame_html(pt)}{labels}', keep_hard=True)


#: classify grid (mm): a tick column is as wide as its heading on one line,
#: or as its longest word when the headings must wrap to leave the items
#: room, within these bounds (CLASSIFY_PAD: the space around a heading); the
#: item column keeps at least CLASSIFY_TEXT_MIN.
CLASSIFY_COL_MIN = 13.0
CLASSIFY_COL_MAX = 30.0
CLASSIFY_PAD = 4.5
CLASSIFY_TEXT_MIN = 40.0
#: classify grid: at most this many rows are always kept on one page.
CLASSIFY_KEEP_ROWS = 10


def _classify(b: Builder, pt: PlannedTask, task: ClassifyTask) -> Parts:
    # The categories head the columns: serif when they are target-language
    # words (der/die/das, names count as such), else sans.
    target = b.column_is_target(task.categories)
    face, size = ("serif-bold", 10.0) if target else ("sans-bold", 9.5)
    klass = "cat tl" if target else "cat"
    attr = b.lang_attr() if target else ""
    heads = "".join(f'<th class="{klass}"{attr}>{esc(c)}</th>' for c in task.categories)
    avail = b.main_width(b.has_aside(pt, False)) - GUTTER_W
    k = len(task.categories)
    if task.layout == "columns":
        # the word box, then a column per category with as many lines as the
        # fullest category needs and one more, so the lines tell nothing
        box = b.word_box(pt.bank or [item.text for item in task.items], row=True)
        rows = max(Counter(item.answer for item in task.items).values()) + 1
        body = f'<tr>{"<td><span></span></td>" * k}</tr>' * rows
        return Parts(f'<div class="cls-sort">{box}<table class="cls cols" style="width:'
                     f'{avail:.1f}mm"><thead><tr>{heads}</tr></thead><tbody>{body}</tbody>'
                     "</table></div>", keep_hard=True)
    # The headings stay on one line while every item still fits on one; else
    # they wrap between words and the items get the room. The item column is
    # only as wide as the longest item, so the boxes stay near the words.
    def column(heading_w: float) -> float:
        return min(max(heading_w + CLASSIFY_PAD, CLASSIFY_COL_MIN), CLASSIFY_COL_MAX)

    widest = max(metrics.width_mm(item.text, "serif", 11.0) for item in task.items) + 4.0
    whole = [column(metrics.width_mm(c, face, size)) for c in task.categories]
    words = [column(max((metrics.width_mm(w, face, size) for w in c.split()), default=0.0))
             for c in task.categories]
    col_ws = whole if avail - sum(whole) >= widest else words
    room = avail - CLASSIFY_TEXT_MIN
    if sum(col_ws) > room:  # (many long headings: they hyphenate)
        col_ws = [max(w * room / sum(col_ws), CLASSIFY_COL_MIN) for w in col_ws]
    text_w = min(max(widest, CLASSIFY_TEXT_MIN), avail - sum(col_ws))
    order = pt.row_order if pt.row_order is not None else list(range(len(task.items)))
    ticks = '<td class="bx"><span></span></td>' * k
    body = "".join(
        f'<tr><td class="n">{n}</td><td class="t tl"{b.lang_attr()}>'
        f"{esc(task.items[j].text)}</td>{ticks}</tr>"
        for n, j in enumerate(order, 1)
    )
    cols = "".join(f'<col style="width:{w:.1f}mm">' for w in [GUTTER_W, text_w, *col_ws])
    width = GUTTER_W + text_w + sum(col_ws)
    table = (f'<table class="cls grid" style="width:{width:.1f}mm"><colgroup>{cols}</colgroup>'
             f'<thead><tr><th></th><th></th>{heads}</tr></thead><tbody>{body}</tbody></table>')
    rows_kept = len(task.items) <= CLASSIFY_KEEP_ROWS
    return Parts(table, keep_hard=rows_kept, keep=True)


#: find_in_text (mm): the arrow column between a clue and its line, and the
#: least widths of the clue column and of the line when they share a row.
FIND_ARROW_W = 6.0
FIND_CLUE_MIN = 45.0
FIND_LINE_MIN = 40.0


def _find_in_text(b: Builder, pt: PlannedTask, task: FindInTextTask) -> Parts:
    # Clue → line on one row while every clue fits on two lines and the line
    # still holds the longest answer in handwriting (about 1.2 × its width in
    # type); else the line goes below the clue. The clue column is as wide as
    # the widest clue needs (+ 3 mm padding), the same for every row, so the
    # lines align.
    target = task.clue_lang == "target"
    face = "serif" if target else "sans"
    avail = b.main_width(b.has_aside(pt, False)) - GUTTER_W
    widest = max(metrics.width_mm(item.answer, "serif", 11.0) for item in task.items)
    line_min = max(FIND_LINE_MIN, widest * 1.2 + 6.0)
    wanted = max(metrics.width_mm(item.clue, face, 11.0) for item in task.items) + 3.0
    clue_w = min(wanted, avail - FIND_ARROW_W - line_min)
    beside = clue_w >= min(wanted, FIND_CLUE_MIN) and all(
        metrics.line_count(item.clue, clue_w - 3.0, face, 11.0) <= 2 for item in task.items)
    columns = f"grid-template-columns:{clue_w:.1f}mm {FIND_ARROW_W:.1f}mm 1fr"
    meaning = (f'<span class="cue">{esc(b.t("kind.find_in_text.explain_cap"))}</span>'
               '<span class="line"></span>') if task.explain else ""
    items = []
    for i, item in enumerate(task.items, 1):
        clue = b.tl(item.clue, "p", "q") if target else f'<p class="q src">{esc(item.clue)}</p>'
        if beside:
            body = (f'<div class="fr" style="{columns}">{clue}<span class="ar">→</span>'
                    '<span class="line"></span></div>')
            lines = meaning
        else:
            body = clue
            lines = '<span class="cue">→</span><span class="line"></span>' + meaning
        if lines:
            body += f'<div class="fl">{lines}</div>'
        items.append(_item(i, body))
    return Parts(f'<div class="items fit">{"".join(items)}</div>')


def _gapped_text(b: Builder, pt: PlannedTask, task: GappedTextTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the gapped_text renderer)


def _scramble(b: Builder, pt: PlannedTask, task: ScrambleTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the scramble renderer)


def _table(b: Builder, pt: PlannedTask, task: TableTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the table renderer)


def _proofread(b: Builder, pt: PlannedTask, task: ProofreadTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the proofread renderer)


#: Crossword cell size (mm). On e-paper a grid of more than
#: CROSSWORD_EPAPER_ROWS rows gets the small cells, so its clues still fit
#: below it on the page; a grid too wide for the column shrinks to fit.
CROSSWORD_CELL = 7.0
CROSSWORD_CELL_SMALL = 6.0
CROSSWORD_EPAPER_ROWS = 12


def _crossword(b: Builder, pt: PlannedTask, task: CrosswordTask) -> Parts:
    grid = pt.crossword
    if grid is None or not grid.placed:
        b.warn(f"task {pt.number}: no crossword answer could be placed; the grid is left out.")
        return Parts("", keep_hard=True)
    if grid.unplaced:
        left_out = ", ".join(f"'{task.entries[i].answer}'" for i in grid.unplaced)
        b.warn(f"task {pt.number}: the crossword grid leaves out {left_out} (no crossing "
               "found; see 'langwich validate').")
    avail = b.main_width(b.has_aside(pt, False)) - GUTTER_W
    cell = CROSSWORD_CELL
    if b.epaper and grid.rows > CROSSWORD_EPAPER_ROWS:
        cell = CROSSWORD_CELL_SMALL
    cell = min(cell, math.floor(avail / grid.cols * 10) / 10)
    numbers = {(p.row, p.col): p.number for p in grid.placed}
    holes = crossword.enclosed(grid)
    rows = []
    for r in range(grid.rows):
        cells = []
        for c in range(grid.cols):
            if (r, c) in holes:
                cells.append('<td class="bk"></td>')
            elif (r, c) not in grid.cells:
                cells.append("<td></td>")
            elif (r, c) in numbers:
                cells.append(f'<td class="x"><span class="cn">{numbers[(r, c)]}</span></td>')
            else:
                cells.append('<td class="x"></td>')
        rows.append(f"<tr>{''.join(cells)}</tr>")
    # (the target's lang and dir: a right-to-left grid runs its across words leftwards)
    table = (f'<table class="cwg"{b.lang_attr()} style="--cell:{cell:.1f}mm;'
             f'width:{cell * grid.cols:.1f}mm">{"".join(rows)}</table>')
    target = task.clue_lang == "target"
    lists = []
    for across in (True, False):
        items = "".join(
            _item(p.number, esc(task.entries[p.index].clue), "c tl" if target else "c src",
                  b.lang_attr() if target else "")
            for p in grid.placed if p.across == across
        )
        if items:
            cap = esc(b.t("across" if across else "down"))
            lists.append(f'<div class="cwl"><span class="cap">{cap}</span>'
                         f'<div class="items">{items}</div></div>')
    return Parts(f'<div class="cw">{table}<div class="cwc">{"".join(lists)}</div></div>',
                 keep_hard=True)


_RENDERERS = {
    "match": _match,
    "true_false": _true_false,
    "multiple_choice": _multiple_choice,
    "order_events": _order_events,
    "questions": _questions,
    "classify": _classify,
    "find_in_text": _find_in_text,
    "gapped_text": _gapped_text,
    "cloze": _cloze,
    "transform": _transform,
    "scramble": _scramble,
    "word_building": _word_building,
    "table": _table,
    "proofread": _proofread,
    "label": _label,
    "writing": _writing,
    "dialogue": _dialogue,
    "crossword": _crossword,
    "media_search": _media_search,
    "draw": _draw,
}


# ---------------------------------------------------------------------------
# Instructions and answer-key labels that depend on a task's fields
# ---------------------------------------------------------------------------
#
# Each kind that needs one has its own function; the tables below route to
# them. A default instruction is used only when the task has none of its own.


def _instruction_true_false(b: Builder, task: TrueFalseTask) -> str | None:
    return None


def _instruction_classify(b: Builder, task: ClassifyTask) -> str | None:
    return b.t("kind.classify.columns") if task.layout == "columns" else None


def _instruction_find_in_text(b: Builder, task: FindInTextTask) -> str | None:
    return b.t("kind.find_in_text.explain") if task.explain else None


def _instruction_cloze(b: Builder, task: ClozeTask) -> str | None:
    return None


def _instruction_transform(b: Builder, task: TransformTask) -> str | None:
    return None


def _instruction_proofread(b: Builder, task: ProofreadTask) -> str | None:
    return None


_INSTRUCTIONS: dict[str, Callable[[Builder, Any], str | None]] = {
    "true_false": _instruction_true_false,
    "classify": _instruction_classify,
    "find_in_text": _instruction_find_in_text,
    "cloze": _instruction_cloze,
    "transform": _instruction_transform,
    "proofread": _instruction_proofread,
}


def default_instruction(b: Builder, pt: PlannedTask) -> str | None:
    """The built-in instruction for a task without its own, when it depends
    on the task's fields (``None``: the kind's plain default)."""
    fn = _INSTRUCTIONS.get(pt.task.kind)
    return fn(b, pt.task) if fn else None


def _suffix_transform(b: Builder, task: TransformTask) -> str:
    return ""


_SUFFIXES: dict[str, Callable[[Builder, Any], str]] = {
    "transform": _suffix_transform,
}


def instruction_suffix(b: Builder, pt: PlannedTask) -> str:
    """HTML appended to the instruction (a word limit), or ``""``."""
    fn = _SUFFIXES.get(pt.task.kind)
    return fn(b, pt.task) if fn else ""


def _key_labels_classify(b: Builder, pt: PlannedTask, count: int) -> tuple[bool, list[str] | None]:
    """No numbers for the columns layout: each entry names its category."""
    assert isinstance(pt.task, ClassifyTask)
    return (True, None) if pt.task.layout == "columns" else (False, None)


def _key_labels_crossword(b: Builder, pt: PlannedTask, count: int) -> tuple[bool, list[str] | None]:
    """'1 →' / '2 ↓': the clue number and direction of each answer (Literata,
    second in the sans stack, has both arrows)."""
    grid = pt.crossword
    if grid is None or len(grid.placed) != count:
        return False, None
    return True, [f"{p.number}\u00a0{'→' if p.across else '↓'}" for p in grid.placed]


_KEY_LABELS: dict[str, Callable[[Builder, PlannedTask, int], tuple[bool, list[str] | None]]] = {
    "classify": _key_labels_classify,
    "crossword": _key_labels_crossword,
}


def key_labels(b: Builder, pt: PlannedTask, count: int) -> tuple[bool, list[str] | None]:
    """``(True, labels)`` when a kind numbers its answer-key entries itself
    (``labels`` ``None``: no numbers); ``(False, None)`` for the default."""
    fn = _KEY_LABELS.get(pt.task.kind)
    return fn(b, pt, count) if fn else (False, None)


def render_task(b: Builder, pt: PlannedTask) -> Parts:
    return _RENDERERS[pt.task.kind](b, pt, pt.task)  # type: ignore[operator]
