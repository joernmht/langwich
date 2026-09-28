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

from langwich import markup
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


def _classify(b: Builder, pt: PlannedTask, task: ClassifyTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the classify renderer)


def _find_in_text(b: Builder, pt: PlannedTask, task: FindInTextTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the find_in_text renderer)


def _gapped_text(b: Builder, pt: PlannedTask, task: GappedTextTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the gapped_text renderer)


def _scramble(b: Builder, pt: PlannedTask, task: ScrambleTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the scramble renderer)


#: Table cells (see the "table" rules in css.py), in mm: the padding
#: between two columns, the margins around a blank and some slack for the
#: measurements; a blank is at least _SHORT_BLANK long (only _MIN_BLANK in a
#: table too crowded for that), an open (null) cell's writing line _OPEN_W.
_COLUMN_GAP = 4.0
_BLANK_MARGINS = 1.6
_SLACK = 1.0
_SHORT_BLANK, _MIN_BLANK = 16.0, 10.0
_OPEN_W = 24.0


@dataclass
class _TableLine:
    """One line of a table cell (a cell breaks at ``\\n``), measured."""

    column: int
    cell: int  # the cell's index in reading order
    fixed: float = 0.0  # text, gap numbers, hints and punctuation (mm)
    gaps: int = 0
    side: float = 0.0  # the most beside one blank: its number, hint, punctuation


def _table_columns(
    b: Builder, task: TableTask, avail: float, ncols: int,
) -> tuple[list[float], list[float], int]:
    """Column widths and the blank width of each column (mm) for a table at
    most ``avail`` mm wide, and how many lines its tallest cell then takes
    (estimated).

    Each column needs room for its longest line (``need``), at least for its
    longest word, heading word, writing line and blank (``least``, a blank a
    little wider than its answer), and in any case for its words (``firm``:
    a word is never broken, a blank may get short). A table with open cells
    takes the full width, others about their natural width; spare room goes
    to the columns the learner writes in, missing room is taken where lines
    are long. The blanks of a task share one width (from its longest answer),
    cut down so that the lines of their column stay whole — those that can
    with a blank of at least _SHORT_BLANK; the others wrap, and their blanks
    get the width of the column.
    """
    form = not task.head
    cells = [(c, cell) for row in task.rows for c, cell in enumerate(row[:ncols])]
    gaps = [(c, g) for c, cell in cells if cell for g in safe_gaps(cell)]
    # a blank as wide as the column's longest answer asks (see Builder.blank_width),
    # and as narrow as it may get in a crowded table
    own = [18.0] * ncols
    tight = [_SHORT_BLANK] * ncols
    for c, gap in gaps:
        answer_w = metrics.width_mm(gap.answer, "serif", 11.0)
        own[c] = max(own[c], answer_w + 7.0)
        tight[c] = max(tight[c], answer_w + 3.0)
    number_w = metrics.width_mm(str(max(len(gaps), 1)), "sans-bold", 8.5 if b.epaper else 7.5)
    need = [0.0] * ncols
    least = [0.0] * ncols
    firm = [0.0] * ncols
    writes = [False] * ncols
    lines: list[_TableLine] = []

    def words(text: str, face: str, size: float) -> float:
        return max((metrics.width_mm(w, face, size) for w in text.split()), default=0.0)

    for c, heading in enumerate(task.head[:ncols]):
        need[c] = metrics.width_mm(heading, "serif-bold", 10.0)
        least[c] = firm[c] = words(heading, "serif-bold", 10.0)
    for k, (c, cell) in enumerate(cells):
        if cell is None:
            writes[c] = True
            need[c], least[c] = max(need[c], _OPEN_W), max(least[c], _OPEN_W)
            firm[c] = max(firm[c], _MIN_BLANK)
            continue
        face = "serif-bold" if form and c == 0 else "serif"
        try:
            parts = markup.split(cell)
        except ValueError:  # printed as is (see gapped_html)
            parts = [cell]
        line = _TableLine(c, k)
        lines.append(line)
        for idx, part in enumerate(parts):
            if isinstance(part, str):
                # (closing punctuation after a gap is set inside the gap)
                text = part[len(trailing_punctuation(part)):] if idx else part
                for n, chunk in enumerate(text.split("\n")):
                    if n:  # a line break in the cell
                        line = _TableLine(c, k)
                        lines.append(line)
                    line.fixed += metrics.width_mm(chunk, face, 11.0)
                    longest = words(chunk, face, 11.0)
                    least[c], firm[c] = max(least[c], longest), max(firm[c], longest)
                continue
            writes[c] = True
            nxt = parts[idx + 1] if idx + 1 < len(parts) else ""
            side = number_w + 0.6 + _BLANK_MARGINS + metrics.width_mm(
                trailing_punctuation(nxt) if isinstance(nxt, str) else "", "serif", 11.0)
            if part.hint and task.hint in ("base_form", "translation"):
                side += metrics.width_mm(f"\u00a0({part.hint})", "sans", 9.5)
            line.fixed += side
            line.gaps += 1
            line.side = max(line.side, side)
            least[c] = max(least[c], tight[c] + side)
            firm[c] = max(firm[c], _MIN_BLANK + side)
    for line in lines:
        need[line.column] = max(need[line.column], line.fixed + line.gaps * own[line.column])
    # (the outer columns have padding on their inner side only)
    pad = [_COLUMN_GAP / 2 * ((c > 0) + (c < ncols - 1)) + _SLACK for c in range(ncols)]
    need, least, firm = ([x + p for x, p in zip(xs, pad)] for xs in (need, least, firm))
    has_open = any(cell is None for _, cell in cells)
    target = avail if has_open else min(avail, max(sum(need) * 1.2, avail * 0.6))

    def squeeze(low: list[float], high: list[float]) -> list[float]:
        """From ``high`` down to ``target``, never below ``low``."""
        room, span = target - sum(low), sum(high) - sum(low)
        return [lo + room * (hi - lo) / span if span else lo for lo, hi in zip(low, high)]

    if sum(need) <= target:
        grow = [n if writes[c] else 0.0 for c, n in enumerate(need)]
        if not any(grow):
            grow = list(need)
        widths = [n + (target - sum(need)) * g / sum(grow) for n, g in zip(need, grow)]
    elif sum(least) <= target:
        widths = squeeze(least, need)
    elif sum(firm) <= target:
        widths = squeeze(firm, least)
    else:  # not even the longest words fit: every column gives up the same share
        widths = [f * target / sum(firm) for f in firm]
    inner = [w - p for w, p in zip(widths, pad)]
    blanks = [b.blank_width([gap.answer for _, gap in gaps], False)] * ncols
    for c in range(ncols):
        with_gaps = [line for line in lines if line.column == c and line.gaps]
        if not with_gaps:
            continue
        side = max(line.side for line in with_gaps)
        whole = [(inner[c] - line.fixed) / line.gaps for line in with_gaps]
        cap = min((w for w in whole if w >= _SHORT_BLANK), default=inner[c] - side)
        blanks[c] = max(min(blanks[c], cap), min(_MIN_BLANK, inner[c] - side))
    tallest: dict[int, int] = {}
    for line in lines:
        width = line.fixed + line.gaps * blanks[line.column]
        tallest[line.cell] = tallest.get(line.cell, 0) + max(
            1, math.ceil(width / max(inner[line.column], 1.0) - 0.01))
    return widths, blanks, max(tallest.values(), default=1)


def _table(b: Builder, pt: PlannedTask, task: TableTask) -> Parts:
    answers = [g.answer for row in task.rows for cell in row if cell for g in safe_gaps(cell)]
    bank = pt.bank if task.hint == "word_bank" and pt.bank else None
    ncols = max([len(task.head), *(len(row) for row in task.rows)])

    def columns(aside: bool) -> tuple[list[float], list[float], int]:
        return _table_columns(b, task, b.main_width(aside) - GUTTER_W, ncols)

    aside = b.has_aside(pt, bool(bank))
    widths, blanks, tallest = columns(aside)
    above = False
    if bank and aside and not b.has_aside(pt, False):
        # cells wrap beside the word box: the box goes above, the table gets the width
        full = columns(False)
        if full[2] < tallest:
            above = True
            widths, blanks, _ = full
    table_w = sum(widths)
    cols = "".join(f'<col style="width:{w:.1f}mm">' for w in widths)
    head = ""
    if task.head:
        headings = "".join(f"<th>{esc(h)}</th>" for h in task.head)
        head = f"<thead><tr>{headings}{'<th></th>' * (ncols - len(task.head))}</tr></thead>"
    counter = itertools.count(1)
    rows = []
    for row in task.rows:
        cells = []
        for c in range(ncols):
            cell = row[c] if c < len(row) else ""
            if cell is None:
                cells.append('<td class="open"><span class="wr">&nbsp;</span></td>')
                continue
            klass = [k for k, on in (("lab", not task.head and c == 0),
                                     ("gp", bool(safe_gaps(cell)))) if on]
            attr = f' class="{" ".join(klass)}"' if klass else ""
            cells.append(f"<td{attr}>{gapped_html(b, cell, blanks[c], task.hint, counter)}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    box = b.word_box(unique_words(bank), counts=bank_counts(answers)) if bank else ""
    main = f'<div class="gtab-bank" style="width:{table_w:.1f}mm">{box}</div>' if above else ""
    if task.caption:
        main += b.tl(task.caption, "div", "gcap")
    main += (f'<table class="gtab tl"{b.lang_attr()} style="width:{table_w:.1f}mm">'
             f'<colgroup>{cols}</colgroup>{head}<tbody>{"".join(rows)}</tbody></table>')
    return Parts(main, [box] if box and not above else [], keep=True)


def _proofread(b: Builder, pt: PlannedTask, task: ProofreadTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the proofread renderer)


def _crossword(b: Builder, pt: PlannedTask, task: CrosswordTask) -> Parts:
    return Parts('<div class="todo"></div>')  # (spine stub: the crossword renderer)


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
    return None


def _instruction_find_in_text(b: Builder, task: FindInTextTask) -> str | None:
    return None


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
    return False, None


def _key_labels_crossword(b: Builder, pt: PlannedTask, count: int) -> tuple[bool, list[str] | None]:
    return False, None


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
