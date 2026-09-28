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
import re
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
    choices: Iterator[list[str]] | None = None,
) -> str:
    """Text with ``{{gaps}}`` turned into blanks of ``width`` mm — or, with
    ``choices`` (the options of each gap in turn), into the options in
    brackets (see :func:`_choice_gap`).

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
        if choices is not None:
            out.append(_choice_gap(next(choices, [part.answer]), num, punct))
            continue
        classes = ["gap"]
        if prev[-1:] in ("'", "’"):
            classes.append("el")
        if punct and not after:
            classes.append("pu")
        tail = esc(punct.replace(" ", "\u00a0"))
        out.append(f'<span class="{" ".join(classes)}">{num}<span class="blank" '
                   f'style="width:{width:.1f}mm">{inner}</span>{after}{tail}</span>')
    return "".join(out)


def _choice_gap(options: list[str], num: str, punct: str) -> str:
    """An inline choice gap, ``(ist / sind / bist)``: the learner circles
    one option. An option never breaks; a line may break after a slash, and
    the brackets, the gap number and closing punctuation stay with their
    options."""
    last = len(options) - 1
    pieces = []
    for j, option in enumerate(options):
        before = f'{num}<span class="bo">(</span>' if j == 0 else ""
        after = ('<span class="bc">)</span>' + esc(punct.replace(" ", "\u00a0")) if j == last
                 else '<span class="sl">\u00a0/</span>')
        pieces.append(f'<span class="co">{before}<span class="o">{esc(option)}</span>{after}</span>')
    return f'<span class="choice">{" ".join(pieces)}</span>'


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
    # with "justify", a captioned line for the words of the story below the
    # correction line (every statement gets both lines: the learner does not
    # know yet which statements are false)
    evidence = (f'<div class="wl evd"><span class="cue">{esc(b.t("evidence"))}</span>'
                '<span class="line"></span></div>') if task.justify else ""
    just = " just" if task.justify else ""  # (more room between statements)
    if not task.not_given:
        labels = "".join(f'<span class="ck"><span class="bxs"></span>{esc(b.t(key))}</span>'
                         for key in ("true", "false"))
        boxes = f'<span class="cks">{labels}</span>'
        items = "".join(
            f'<div class="it"><span class="n">{i}</span><div class="c">{b.tl(item.statement)}</div>'
            f'{boxes}<span class="corr"></span>{evidence}</div>'
            for i, item in enumerate(task.items, 1)
        )
        return Parts(f'<div class="items tf{just}">{items}</div>')
    # three boxes: a table whose head row names the columns once instead of
    # taking width on every line (a page break repeats it); the task stays
    # whole where it can, one statement never splits
    width = f' style="width:{tf_column_width(b):.1f}mm"'
    heads = "".join(f'<th class="h"{width}>{esc(b.t(key))}</th>'
                    for key in ("true", "false", "not_given"))
    boxes = '<td class="b"><span class="bxs"></span></td>' * 3
    rows = "".join(
        f'<tbody><tr><td class="n">{i}</td><td class="c">{b.tl(item.statement)}</td>{boxes}</tr>'
        '<tr><td></td><td class="corr" colspan="4"></td></tr>'
        + (f'<tr><td></td><td colspan="4">{evidence}</td></tr>' if evidence else "")
        + "</tbody>"
        for i, item in enumerate(task.items, 1)
    )
    return Parts(f'<table class="tf3{just}"><thead><tr><th class="n"></th><th></th>{heads}</tr>'
                 f"</thead>{rows}</table>", keep=True)


#: Size (pt) of the column heads of a true_false task with three boxes, on A4
#: and on e-paper (the CSS below "true_false+" sets the same).
TF_HEAD_PT = {"a4": 8.0, "epaper": 8.5}


def tf_column_width(b: Builder) -> float:
    """Width (mm) of each box column of a true_false task with three boxes:
    every head ('true', 'false', 'not in the text') on at most two lines,
    no word broken, at least 1 mm clear on either side."""
    size = TF_HEAD_PT["epaper" if b.epaper else "a4"]
    heads = [b.t(key) for key in ("true", "false", "not_given")]
    longest = max(metrics.width_mm(w, "sans-bold", size) for h in heads for w in h.split())
    width = max(12.0, math.ceil((longest + 2.0) * 2) / 2)
    while width < 30.0 and any(metrics.line_count(h, width - 2.0, "sans-bold", size) > 2
                               for h in heads):
        width += 0.5
    return width


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
    items = []
    for i, item in enumerate(task.items, 1):
        if task.question_lang == "source":
            question = f'<p class="q src"{b.src_attr()}>{esc(item.question)}</p>'
        else:
            question = b.tl(item.question, "p", "q")
        # the starter is printed on the first answer line, so it needs one
        count = max(item.lines, 1) if item.starter else item.lines
        items.append(_item(i, question + b.lines(count, item.starter)))
    return Parts(f'<div class="items qs">{"".join(items)}</div>')


def _cloze(b: Builder, pt: PlannedTask, task: ClozeTask) -> Parts:
    if task.hint == "choice":
        return _cloze_choice(b, pt, task)
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


#: Options under a choice text (see "cloze choice" in css.py), in mm: the
#: tick box and the letter before an option, the space between two options,
#: the gap number before the options of an item with several gaps, and the
#: longest blank (the learner ticks a box below; nothing is written in it).
_OPTION_LEAD = 10.4
_OPTION_GAP = 5.0
_ITEM_GAP_NUMBER = 6.0
_CHOICE_BLANK = 24.0


def _choice_columns(options: list[list[str]], avail: float) -> list[float] | None:
    """Widths (mm) of the option columns under a choice text, the same for
    every gap so that the options a, b, c … line up: all as wide as the
    widest option, or each as wide as its own widest; ``None`` when not even
    that fits ``avail`` mm."""
    k = max((len(opts) for opts in options), default=0)
    own = [  # (with 1 mm to spare for the measurement)
        _OPTION_LEAD + 1.0 + max(metrics.width_mm(opts[j], "serif", 11.0)
                                 for opts in options if j < len(opts))
        for j in range(k)
    ]
    gaps = _OPTION_GAP * (k - 1)
    if k and max(own) * k + gaps <= avail:
        return [max(own) + (_OPTION_GAP if j < k - 1 else 0.0) for j in range(k)]
    if k and sum(own) + gaps <= avail:
        return [w + (_OPTION_GAP if j < k - 1 else 0.0) for j, w in enumerate(own)]
    return None


def _choice_rows(
    b: Builder, rows: list[tuple[str, list[str]]], columns: list[float] | None, avail: float,
    num_w: float = 0.0, small: bool = False,
) -> str:
    """The tick boxes under a choice text: one row per gap, with its number
    (none when ``num_w`` is 0; ``small``: set like the gap numbers in the
    text) and its options a, b, c … in the multiple_choice option styles.
    The options stand in the shared ``columns``; without them a row gets
    columns of its own when it fits ``avail`` mm, else one option per line."""
    out = []
    for label, options in rows:
        opts = "".join(
            f'<div class="op"><span class="bxs"></span><span class="lt">{letter(j, upper=False)}'
            f'</span><span class="ot">{b.tl(o)}</span></div>'
            for j, o in enumerate(options)
        )
        tracks = [f"{num_w:.1f}mm"] if num_w else []
        number = ""
        if num_w:
            inner = f'<span class="{"gn" if small else "nn"}">{label}</span>' if label else ""
            number = f'<span class="n">{inner}</span>'
        own = columns or _choice_columns([options], avail)
        if own is None:
            tracks.append("1fr")
            opts = f'<div class="chw">{opts}</div>'
        else:
            tracks += [f"{w:.1f}mm" for w in own]
        out.append(f'<div class="chr" style="grid-template-columns:{" ".join(tracks)}">'
                   f"{number}{opts}</div>")
    return f'<div class="chs">{"".join(out)}</div>'


def _cloze_choice(b: Builder, pt: PlannedTask, task: ClozeTask) -> Parts:
    """A cloze with hint 'choice'. inline: every gap is its options in
    brackets, and the learner circles one; below: numbered blanks, and under
    the text (under each item) one row of tick boxes a, b, c … per gap."""
    texts = cloze_texts(task)
    units = [safe_gaps(text) for text in texts]
    options = pt.gap_options or [[g.answer] for unit in units for g in unit]
    shown = iter(options)
    below = task.choice_layout == "below"
    aside = b.has_aside(pt, False)
    # (as wide for every gap: sized from all options, not from the answers)
    width = min(b.blank_width([o for opts in options for o in opts], aside), _CHOICE_BLANK)
    if task.text is not None:
        counter = itertools.count(1)
        paras = [p.strip() for p in task.text.split("\n\n") if p.strip()]
        body = "".join(
            f"<p>{gapped_html(b, p, width, task.hint, counter, None if below else shown)}</p>"
            for p in paras
        )
        main = f'<div class="passage tl"{b.lang_attr()}>{body}</div>'
        if below and options:
            avail = b.main_width(aside) - GUTTER_W
            rows = [(str(n), opts) for n, opts in enumerate(options, 1)]
            main += _choice_rows(b, rows, _choice_columns(options, avail), avail, GUTTER_W)
    else:
        # (an item with several gaps numbers them, 1, 2 … within the item)
        num_w = _ITEM_GAP_NUMBER if any(len(unit) > 1 for unit in units) else 0.0
        avail = b.main_width(aside) - GUTTER_W - num_w
        columns = _choice_columns(options, avail)
        items = []
        for i, (text, unit) in enumerate(zip(texts, units), 1):
            mine = [next(shown, [g.answer]) for g in unit]
            if below:
                several = len(unit) > 1
                rows = [(str(n) if several else "", opts) for n, opts in enumerate(mine, 1)]
                numbers = itertools.count(1) if several else None
                content = (gapped_html(b, text, width, task.hint, numbers)
                           + _choice_rows(b, rows, columns, avail, num_w, small=True))
            else:
                content = gapped_html(b, text, width, task.hint, None, iter(mine))
            items.append(_item(i, content, "c tl", b.lang_attr()))
        main = f'<div class="items gapped">{"".join(items)}</div>'
    return Parts(main, keep=below)


def _transform(b: Builder, pt: PlannedTask, task: TransformTask) -> Parts:
    # the blanks of the frames share one width: the longest answer as
    # handwriting (wider than print), so no blank gives its answer's length away
    answers = [g.answer for item in task.items if item.frame for g in safe_gaps(item.frame)]
    width = frame_blank_width(b, answers, b.has_aside(pt, False)) if answers else 0.0
    items = []
    for i, item in enumerate(task.items, 1):
        prompt = b.tl(item.prompt, "p", "q")
        keyword = (item.keyword or "").strip()
        if keyword:
            # the key word at the right end of the prompt's row, in capitals
            prompt = (f'<div class="kwr">{prompt}<span class="kw"{b.lang_attr()}>'
                      f"{esc(keyword)}</span></div>")
        cue = f"→ {esc(item.cue)}" if item.cue else "→"
        if item.frame is not None:
            # the new sentence with its gap as a blank, instead of a line
            second = (f'<div class="frm"><span class="cue">{cue}</span><span class="tl"'
                      f"{b.lang_attr()}>{gapped_html(b, item.frame, width)}</span></div>")
        else:
            second = f'<div class="wl"><span class="cue">{cue}</span><span class="line"></span></div>'
        items.append(_item(i, prompt + second))
    return Parts(f'<div class="items tr">{"".join(items)}</div>')


def frame_blank_width(b: Builder, answers: list[str], with_aside: bool) -> float:
    """Width (mm) of the blank in a transform frame: the longest answer a
    fifth wider than print (it is handwritten, often several words), at least
    30 mm, at most a whole line (a clause to write may need one)."""
    widest = max(metrics.width_mm(a, "serif", 11.0) for a in answers)
    avail = b.main_width(with_aside) - GUTTER_W - 8.0  # (the arrow, the full stop)
    return round(min(max(widest * 1.2 + 6.0, 30.0), avail), 1)


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
    # with "paragraphs": one numbered block of lines per point, at least three
    # lines each (the starter, if any, on an extra first line)
    blocks = [count]
    if task.paragraphs and len(task.points) > 1:
        head = 1 if task.starter else 0
        per = max(3, math.ceil((count - head) / len(task.points)))
        blocks = [per + head] + [per] * (len(task.points) - 1)
    numbered = len(blocks) > 1
    parts = [f'<p class="prompt">{esc(task.prompt)}</p>']
    # who the text is for, and its register as a small tag
    meta = ""
    if task.audience:
        meta += f'<span class="cap">{esc(b.t("audience"))}</span>{esc(task.audience)}'
    if task.register_:
        meta += f'<span class="reg">{esc(b.t(f"register.{task.register_}"))}</span>'
    if meta:
        parts.append(f'<p class="wmeta">{meta}</p>')
    if task.input:
        # the text to answer or work from, as it would look: paragraphs and line breaks kept
        paras = "".join("<p>" + esc(p.strip()).replace("\n", "<br>") + "</p>"
                        for p in task.input.split("\n\n") if p.strip())
        source = task.input_lang == "source"
        attr = b.src_attr() if source else b.lang_attr()
        parts.append(f'<div class="box input {"src" if source else "tl"}"{attr}>{paras}</div>')
    if task.points:
        points = "".join(
            '<li><span class="tick"></span>'
            + (f'<span class="pn">{k}</span>' if numbered else "")
            + f"{esc(p.point)}</li>"
            for k, p in enumerate(task.points, 1)
        )
        parts.append(f'<div class="points"><span class="cap">{esc(b.t("points"))}</span>'
                     f"<ul>{points}</ul></div>")
    if task.must_use:
        words = "".join(f'<span class="w"><span class="tick"></span>{esc(w)}</span>'
                        for w in task.must_use)
        parts.append(f'<div class="usewords"><span class="cap">{esc(b.t("use_words"))}</span>'
                     f'<span class="tl"{b.lang_attr()}>{words}</span></div>')
    parts.append(_writing_space(b, blocks, task.starter, task.output_lang == "source"))
    return Parts(f'<div class="writing">{"".join(parts)}</div>')


def _writing_space(b: Builder, blocks: list[int], starter: str | None, source: bool) -> str:
    """Writing lines: one block per count in ``blocks`` (numbered when there
    are several); the starter, in the language the learner writes, on the
    first line."""
    attr, face = (b.src_attr(), "src") if source else (b.lang_attr(), "tl")
    numbered = len(blocks) > 1
    out = []
    for k, count in enumerate(blocks):
        num = f'<span class="pn">{k + 1}</span>' if numbered else ""
        if k == 0 and starter:
            first = f'<div class="starter {face}"{attr}>{num}{esc(starter)}</div>'
        else:
            first = f"<div>{num}</div>"
        klass = "lines numbered" if numbered else "lines"
        out.append(f'<div class="{klass}">{first}{"<div></div>" * (count - 1)}</div>')
    return "".join(out)


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
    caption = f'{b.t("search_for")} · {b.t(f"media.{task.media}")}'
    # A query that fits beside the caption stays on one line, and a line
    # breaks only after a separator, so no line starts with one.
    size = 8.5 if b.epaper else 7.5  # the caption: capitals, letter-spaced .1em
    cap_w = (metrics.width_mm(caption.upper(), "sans-bold", size)
             + len(caption) * 0.1 * size * metrics.PT_TO_MM)
    room = b.main_width(b.has_aside(pt, False)) - 8.0 - cap_w - 4.0  # box padding, gap
    queries = '<span class="sep">·</span><wbr>'.join(
        f'<span class="nw">{esc_nw(q)}</span>' if metrics.width_mm(q) <= room else esc_nw(q)
        for q in task.queries
    )
    search = (f'<div class="search"><span class="cap">{esc(caption)}</span>'
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


#: The box a learner writes a letter in, in place of a removed sentence (mm).
_SLOT_W = 7.0


def _gapped_text(b: Builder, pt: PlannedTask, task: GappedTextTask) -> Parts:
    """The passage with a numbered box for a letter in place of each removed
    sentence, then the removed and the extra sentences, lettered A, B, C …
    in the planner's order (``pt.slot_options``)."""
    counter = itertools.count(1)
    paras = [p.strip() for p in task.text.split("\n\n") if p.strip()]
    body = "".join(f"<p>{gapped_html(b, p, _SLOT_W, numbers=counter)}</p>" for p in paras)
    shown = pt.slot_options
    if shown is None:
        shown = [g.answer for g in safe_gaps(task.text)] + list(task.extra)
    rows = "".join(f'<div><span class="l">{letter(k)}</span>{b.tl(s)}</div>'
                   for k, s in enumerate(shown))
    main = (f'<div class="passage tl"{b.lang_attr()}>{body}</div>'
            f'<div class="gts">{rows}</div>')
    return Parts(main, keep=True)


def _scramble(b: Builder, pt: PlannedTask, task: ScrambleTask) -> Parts:
    tiles = pt.tiles if pt.tiles is not None else [list(item.chunks) for item in task.items]
    line_w = b.main_width(b.has_aside(pt, False)) - GUTTER_W - 4.0  # the end mark
    items = []
    for i, (item, shown) in enumerate(zip(task.items, tiles), 1):
        row = " ".join(f'<span class="tile">{esc(c.strip())}</span>' for c in shown)
        cue = f'<p class="cue"{b.src_attr()}>{esc(item.cue)}</p>' if item.cue else ""
        # handwriting takes about half as much room again as the print, so
        # a long sentence gets more than one line; the last one ends in 'end'
        printed = metrics.width_mm(" ".join(item.chunks) + item.end, "serif", 11.0)
        count = min(max(1, math.ceil(printed * 1.5 / line_w)), 4)
        end = f'<span class="end">{esc(item.end)}</span>' if item.end else ""
        lines = '<div class="sl"><span class="line"></span></div>' * (count - 1)
        lines += f'<div class="sl"><span class="line"></span>{end}</div>'
        items.append(_item(
            i, f'<div class="tiles tl"{b.lang_attr()}>{row}</div>{cue}'
               f'<div class="sls tl"{b.lang_attr()}>{lines}</div>'))
    return Parts(f'<div class="items scr">{"".join(items)}</div>')


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


def _draft_html(b: Builder, text: str, marked: bool, numbers: Iterator[int]) -> str:
    """One paragraph of a proofread draft, every mistake in its wrong form.

    ``marked``: the wrong form is underlined and followed by its number; its
    last word, the number and closing punctuation never split at a line end.
    """
    try:
        parts = markup.split(text)
    except ValueError:
        b.warn(f"malformed gap markup in {text[:40]!r}…; printed as is.")
        return esc(text)
    out: list[str] = []
    skip = 0  # characters of the next text part already printed with a mistake
    for idx, part in enumerate(parts):
        if isinstance(part, str):
            out.append(esc(part[skip:]).replace("\n", "<br>"))
            skip = 0
            continue
        wrong = part.hint or part.answer  # (no wrong form: the validator reports it)
        if not marked:
            out.append(esc(wrong))
            continue
        after = parts[idx + 1] if idx + 1 < len(parts) else ""
        punct = trailing_punctuation(after) if isinstance(after, str) else ""
        skip = len(punct)
        tail = esc(punct.replace(" ", "\u00a0"))
        head, space, last = wrong.rpartition(" ")
        lead = f"<u>{esc(head)} </u>" if space else ""
        out.append(f'{lead}<span class="nw"><u>{esc(last)}</u>'
                   f'<span class="gn">{next(numbers)}</span>{tail}</span>')
    return "".join(out)


def _proofread(b: Builder, pt: PlannedTask, task: ProofreadTask) -> Parts:
    gaps = safe_gaps(task.text)
    counter = itertools.count(1)
    paras = [p.strip() for p in task.text.split("\n\n") if p.strip()]
    body = "".join(f"<p>{_draft_html(b, p, task.marked, counter)}</p>" for p in paras)
    draft = f'<div class="draft tl"{b.lang_attr()}>{body}</div>'
    # Below the draft, one numbered field per mistake: marked, for the
    # correction; unmarked, a row 'wrong → correct' for each one the learner
    # finds. Handwriting takes about half as much room again as the print.
    written = [g.answer for g in gaps] + ([] if task.marked else [g.hint or "" for g in gaps])
    widest = max((metrics.width_mm(w, "serif", 11.0) for w in written), default=0.0)
    line_w = max(widest * 1.5 + 4.0, 28.0)
    if task.marked:
        cell_w = GUTTER_W + line_w
        cells = [f'<div class="fld"><span>{n}</span><span class="line"></span></div>'
                 for n in range(1, len(gaps) + 1)]
    else:
        cell_w = GUTTER_W + 2 * line_w + 8.0  # the arrow
        cells = [f'<div class="fx"><span>{n}</span><span class="line"></span>'
                 '<span class="ar">→</span><span class="line"></span></div>'
                 for n in range(1, len(gaps) + 1)]
    fixes = ""
    if cells:
        avail = b.main_width(b.has_aside(pt, False))
        cols = max(1, min(4, len(cells), int((avail + 7.0) // (cell_w + 7.0))))  # 7 mm apart
        cols = math.ceil(len(cells) / math.ceil(len(cells) / cols))  # 6 in 3 + 3, not 4 + 2
        # one grid per row, so that a page breaks between rows (never after
        # the first one or before the last one, see the CSS)
        style = f' style="grid-template-columns:repeat({cols}, 1fr)"'
        rows = "".join(f'<div class="fr"{style}>{"".join(cells[k:k + cols])}</div>'
                       for k in range(0, len(cells), cols))
        fixes = f'<div class="fixes">{rows}</div>'
    return Parts(f'<div class="proof">{draft}{fixes}</div>', keep=True)


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
    """Three boxes name the third one; 'justify' asks for the words of the story."""
    if not (task.not_given or task.justify):
        return None
    text = b.t("kind.true_false.not_given" if task.not_given else "kind.true_false.instruction")
    return f'{text} {b.t("kind.true_false.justify")}' if task.justify else text


def _instruction_classify(b: Builder, task: ClassifyTask) -> str | None:
    return None


def _instruction_find_in_text(b: Builder, task: FindInTextTask) -> str | None:
    return None


def _instruction_cloze(b: Builder, task: ClozeTask) -> str | None:
    if task.hint == "choice":
        below = task.choice_layout == "below"
        return b.t("kind.cloze.choice_below" if below else "kind.cloze.choice")
    return None


def _instruction_transform(b: Builder, task: TransformTask) -> str | None:
    """Key words: complete the second sentence with the word in capitals.
    (Frames without a key word keep the plain 'rewrite as shown'.)"""
    if any(item.keyword and item.keyword.strip() for item in task.items):
        return b.t("kind.transform.keyword")
    return None


def _instruction_proofread(b: Builder, task: ProofreadTask) -> str | None:
    if task.marked:
        return b.t("kind.proofread.instruction")
    return b.t("kind.proofread.count", n=len(safe_gaps(task.text)))


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
    """The word limit of the answers ('max_words') after the instruction's
    last sentence, capitalised, unless the task's own instruction states the
    number already."""
    if task.max_words is None:
        return ""
    if task.instruction and re.search(rf"(?<!\d){task.max_words}(?!\d)", task.instruction):
        return ""
    limit = b.t("kind.transform.max", max=task.max_words)
    return f' <span class="len">{esc(limit[:1].upper() + limit[1:])}</span>'


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
