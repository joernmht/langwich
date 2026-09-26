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
    ClozeTask,
    DialogueTask,
    DrawTask,
    LabelTask,
    MatchTask,
    MediaSearchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    QuestionsTask,
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


def answer_key(pt: PlannedTask, ws: Worksheet) -> list[str]:
    task = pt.task
    lang, ui = ws.source_lang, ws.ui

    if isinstance(task, MatchTask):
        n = len(task.pairs) + len(task.extra)
        order = pt.right_order if pt.right_order is not None else list(range(n))
        return [letter(order.index(i)) for i in range(len(task.pairs))]

    if isinstance(task, TrueFalseTask):
        verdicts: list[str] = []
        for item in task.items:
            word = t("true" if item.answer else "false", lang, ui)
            verdicts.append(
                f"{word} – {item.correction}" if not item.answer and item.correction else word)
        return verdicts

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

    if isinstance(task, ClozeTask):
        if task.text is not None:
            return [gap_answer(g) for g in safe_gaps(task.text)]
        return [" … ".join(gap_answer(g) for g in safe_gaps(item)) for item in task.items or []]

    if isinstance(task, TransformTask):
        return [item.answer for item in task.items]

    if isinstance(task, WordBuildingTask):
        return [item.answer for item in task.items]

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

    if isinstance(task, (WritingTask, MediaSearchTask, DrawTask)):
        return []

    return []  # pragma: no cover - every kind is handled above
