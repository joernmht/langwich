"""The answer key, independent of any renderer.

:func:`answer_key` returns one display string per numbered item (or per gap
of a gap passage) in the order the learner sees them — using the planner's
shuffles, so letters and numbers match the task page. An empty list means
the task has open answers (writing, drawing, searching, questions without
model answers); the renderer then prints the model answer or a
"answers will vary" note.
"""

from __future__ import annotations

from langwich import markup
from langwich.locale import t
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
    TransformItem,
    TransformTask,
    TrueFalseTask,
    WordBuildingTask,
    Worksheet,
    WritingTask,
)
from langwich.plan import LETTERS, PlannedTask


def letter(index: int, upper: bool = True) -> str:
    """``0 → A``, ``25 → Z``, ``26 → AA`` … (never runs out)."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = LETTERS[rem] + out
    return out if upper else out.lower()


def gap_answer(gap: markup.Gap) -> str:
    """A gap's answer as printed in the key: all accepted variants."""
    return " / ".join(gap.accepted)


def safe_gaps(text: str) -> list[markup.Gap]:
    """The gaps of ``text``; malformed markup (``{{}}``) yields no gaps."""
    try:
        return markup.gaps(text)
    except ValueError:
        return []


def cloze_texts(task: ClozeTask) -> list[str]:
    return [task.text] if task.text is not None else list(task.items or [])


def transform_answer(item: TransformItem) -> str:
    """What the learner writes: the frame's gap answer(s), else the rewritten sentence."""
    if item.frame is not None:
        gaps = safe_gaps(item.frame)
        if gaps:
            return " … ".join(gap_answer(g) for g in gaps)
    return item.answer or ""


def transform_sentence(item: TransformItem) -> str:
    """The complete new sentence: the frame with its gap filled, else the answer."""
    if item.frame is not None:
        try:
            return markup.fill(item.frame)
        except ValueError:
            return markup.GAP_RE.sub(" ", item.frame)
    return item.answer or ""


#: The mark that opens a Spanish question or exclamation (¿Dónde …? ¡Qué …!).
_ES_OPENING = {"?": "¿", "!": "¡"}


def scramble_sentence(chunks: list[str], end: str = "", lang: str = "") -> str:
    """The sentence that scramble tiles make in this order: joined by spaces
    (none after an elision such as l' or d'), the first letter upper-cased,
    ``end`` at the end — a Spanish question or exclamation opens with ¿ or ¡,
    and French puts a non-breaking space before ? and !."""
    text = ""
    for chunk in (c.strip() for c in chunks):
        if chunk:
            text += (" " if text and not text.endswith(("'", "’")) else "") + chunk
    text = _upper_first(text)
    base = lang.split("-", 1)[0].lower()  # es-MX → es
    if base == "es" and end in _ES_OPENING and not text.startswith(_ES_OPENING[end]):
        text = _ES_OPENING[end] + text
    if base == "fr" and end in ("?", "!"):
        end = "\u00a0" + end
    return text + end


def _upper_first(text: str) -> str:
    """``text`` with its first letter upper-cased, after any opening marks
    (a sentence that starts with a number stays as it is)."""
    for k, ch in enumerate(text):
        if ch.isalpha():
            return text[:k] + ch.upper() + text[k + 1:]
        if ch.isalnum():
            break
    return text


def answer_key(pt: PlannedTask, ws: Worksheet) -> list[str]:
    task = pt.task
    lang, ui = ws.source_lang, ws.ui

    if isinstance(task, MatchTask):
        n = len(task.pairs) + len(task.extra)
        order = pt.right_order if pt.right_order is not None else list(range(n))
        return [letter(order.index(i)) for i in range(len(task.pairs))]

    if isinstance(task, TrueFalseTask):
        return _key_true_false(pt, ws)

    if isinstance(task, MultipleChoiceTask):
        choices: list[str] = []
        for i, choice in enumerate(task.items):
            options = pt.option_orders[i] if pt.option_orders else list(choice.options)
            choices.append(f"{letter(options.index(choice.answer), upper=False)} – {choice.answer}")
        return choices

    if isinstance(task, OrderEventsTask):
        shown = pt.events if pt.events is not None else list(task.events)
        return [str(task.events.index(e) + 1) for e in shown]

    if isinstance(task, QuestionsTask):
        answers = [item.answer for item in task.items]
        if not any(answers):
            return []
        return [a or t("open_answer", lang, ui) for a in answers]

    if isinstance(task, ClassifyTask):
        return _key_classify(pt, ws)

    if isinstance(task, FindInTextTask):
        return _key_find_in_text(pt, ws)

    if isinstance(task, GappedTextTask):
        return _key_gapped_text(pt, ws)

    if isinstance(task, ClozeTask):
        if task.text is not None:
            return [gap_answer(g) for g in safe_gaps(task.text)]
        return [" … ".join(gap_answer(g) for g in safe_gaps(item)) for item in task.items or []]

    if isinstance(task, TransformTask):
        return [transform_answer(item) for item in task.items]

    if isinstance(task, ScrambleTask):
        return _key_scramble(pt, ws)

    if isinstance(task, WordBuildingTask):
        return [item.answer for item in task.items]

    if isinstance(task, TableTask):
        return _key_table(pt, ws)

    if isinstance(task, ProofreadTask):
        return _key_proofread(pt, ws)

    if isinstance(task, LabelTask):
        scene = ws.scene(task.scene)
        picture = scene.picture if scene else None
        if picture is None or not picture.has_visual or not picture.labels:
            return []  # "draw and label": the learner's own drawing
        return [lb.term for lb in sorted(picture.labels, key=lambda lb: lb.n)]

    if isinstance(task, DialogueTask):
        lines: list[str] = []
        has_model = False
        for line in task.lines:
            if line.text is not None:
                gaps = safe_gaps(line.text)
                if gaps:
                    lines.append(" … ".join(gap_answer(g) for g in gaps))
                    has_model = True
            else:
                lines.append(line.answer or t("open_answer", lang, ui))
                has_model = has_model or bool(line.answer)
        return lines if has_model else []

    if isinstance(task, CrosswordTask):
        return _key_crossword(pt, ws)

    if isinstance(task, (WritingTask, MediaSearchTask, DrawTask)):
        return []

    return []  # pragma: no cover - every kind is handled above


def _key_true_false(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """true / false (with the correction) / not in the text, per statement."""
    task = pt.task
    assert isinstance(task, TrueFalseTask)
    lang, ui = ws.source_lang, ws.ui
    verdicts: list[str] = []
    for item in task.items:
        if item.answer == "not_given":
            verdicts.append(t("not_given", lang, ui))
            continue
        word = t("true" if item.answer is True else "false", lang, ui)
        verdicts.append(
            f"{word} – {item.correction}" if item.answer is False and item.correction else word)
    return verdicts


def _key_scramble(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The sentence of each scramble item (and its other correct orders)."""
    task = pt.task
    assert isinstance(task, ScrambleTask)
    sentences: list[str] = []
    for item in task.items:
        orders: list[str] = []
        for chunks in [item.chunks, *item.alternatives]:
            sentence = scramble_sentence(chunks, item.end, ws.target_lang)
            if sentence not in orders:
                orders.append(sentence)
        sentences.append(" / ".join(orders))
    return sentences


def _key_classify(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The category of each displayed row (grid), or each category's words (columns)."""
    return []  # (spine stub: the classify implementation fills this in)


def _key_table(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The gap answers of a table, row by row."""
    return []  # (spine stub: the table implementation fills this in)


def _key_gapped_text(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The letter of the sentence that fills each gap."""
    return []  # (spine stub: the gapped_text implementation fills this in)


def _key_find_in_text(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """Each word or phrase to find (with its explanation)."""
    return []  # (spine stub: the find_in_text implementation fills this in)


def _key_proofread(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """'wrong → correct' per mistake, in text order (the arrow never starts a line)."""
    task = pt.task
    assert isinstance(task, ProofreadTask)
    return [f"{gap.hint}\u00a0→ {gap_answer(gap)}" if gap.hint else gap_answer(gap)
            for gap in safe_gaps(task.text)]


def _key_crossword(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The answers in clue order (across, then down)."""
    return []  # (spine stub: the crossword implementation fills this in)
