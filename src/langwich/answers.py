"""The answer key, independent of any renderer.

:func:`answer_key` returns one display string per numbered item (or per gap
of a gap passage) in the order the learner sees them — using the planner's
shuffles, so letters and numbers match the task page. An empty list means
the task has open answers (writing, drawing, searching, questions without
model answers); the renderer then prints the model answer or a
"answers will vary" note. :func:`answer_key_runs` gives the same entries
split into runs by language, so that a renderer can tag the words in the
learner's language (a verdict, "not in the text") apart from the answers.
"""

from __future__ import annotations

import re

from langwich import crossword, markup
from langwich.locale import base_lang, quoted, t
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
from langwich.plan import LETTERS, NO_SPACE_LANGS, PlannedTask


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

#: Chinese and Japanese end a sentence with full-width marks.
_FULL_WIDTH_ENDS = {".": "。", "?": "？", "!": "！"}
_FULL_WIDTH_LANGS = frozenset({"zh", "ja"})

#: The elided words that the next word follows without a space (l'homme,
#: dell'acqua), by language. An apostrophe at the end of any other word is
#: followed by a space: Jonas' Schürze, my parents' house, un po' di.
_ELISION = {
    "fr": re.compile(r"(?<!\w)(?:[cçdjlmnst]|qu|jusqu|lorsqu|puisqu|quoiqu|presqu|quelqu)['’]$",
                     re.IGNORECASE),
    "ca": re.compile(r"(?<!\w)[dlmnst]['’]$", re.IGNORECASE),
    "pt": re.compile(r"(?<!\w)d['’]$", re.IGNORECASE),  # (copo d'água)
    "it": re.compile(
        r"(?<!\w)(?:[cdlmnstv]|gl|un|dell|dall|nell|sull|all|coll|dagl|degl|negl|sugl|quest"
        r"|quell|bell|sant|tutt|anch|dov|com|cos|quand|mezz|senz|nient|nessun|alcun|ciascun"
        r"|qualcun)['’]$",
        re.IGNORECASE,
    ),
}


def scramble_end(end: str, lang: str = "") -> str:
    """The end mark of a scramble item as printed: full width (。？！) in
    Chinese and Japanese."""
    if base_lang(lang) in _FULL_WIDTH_LANGS:
        return _FULL_WIDTH_ENDS.get(end, end)
    return end


def scramble_sentence(chunks: list[str], end: str = "", lang: str = "") -> str:
    """The sentence that scramble tiles make in this order: joined by spaces
    (none after an elision such as l', d' or dell', none at all in a
    language written without spaces), the first letter upper-cased, ``end``
    at the end — a Spanish question or exclamation opens with ¿ or ¡,
    French puts a non-breaking space before ? and !, Chinese and Japanese
    end with 。？！."""
    base = base_lang(lang)  # es-MX → es
    elision = _ELISION.get(base)
    space = "" if base in NO_SPACE_LANGS else " "
    text = ""
    for chunk in (c.strip() for c in chunks):
        if chunk:
            glued = not text or (elision is not None and elision.search(text))
            text += ("" if glued else space) + chunk
    text = _upper_first(text, base)
    end = scramble_end(end, base)
    if base == "es" and end in _ES_OPENING and not text.startswith(_ES_OPENING[end]):
        text = _ES_OPENING[end] + text
    if base == "fr" and end in ("?", "!"):
        end = "\u00a0" + end
    return text + end


def _upper_first(text: str, lang: str = "") -> str:
    """``text`` with its first letter upper-cased, after any opening marks
    (a sentence that starts with a number stays as it is): Turkish and Azeri
    i → İ, Dutch ij → IJ."""
    base = base_lang(lang)
    for k, ch in enumerate(text):
        if ch.isalpha():
            if base in crossword.DOTTED_I_LANGS and ch == "i":
                return text[:k] + "İ" + text[k + 1:]
            if base == "nl" and text[k:k + 2] == "ij":
                return text[:k] + "IJ" + text[k + 2:]
            return text[:k] + ch.upper() + text[k + 1:]
        if ch.isalnum():
            break
    return text


#: One run of an answer-key entry: its text, and whether it is in the
#: learner's (source) language rather than the target language.
KeyRun = tuple[str, bool]


def answer_key(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """One display string per entry (see the module docstring)."""
    return [key_text(runs) for runs in answer_key_runs(pt, ws)]


def key_text(runs: list[KeyRun]) -> str:
    """An answer-key entry as one string."""
    return "".join(text for text, _ in runs)


def answer_key_runs(pt: PlannedTask, ws: Worksheet) -> list[list[KeyRun]]:
    """The entries of :func:`answer_key`, each as its runs by language: a
    verdict ('false – '), 'not in the text' and 'answers will vary' are in
    the learner's language, the rest in the target language (an
    explanation in the language of its clues)."""
    task = pt.task
    if isinstance(task, TrueFalseTask):
        return _key_true_false(pt, ws)
    if isinstance(task, FindInTextTask):
        return _key_find_in_text(pt, ws)
    if isinstance(task, QuestionsTask):
        return _key_open(ws, [item.answer for item in task.items])
    if isinstance(task, DialogueTask):
        return _key_dialogue(pt, ws)
    return [[(entry, False)] for entry in _target_key(pt, ws)]


def _runs(*parts: KeyRun) -> list[KeyRun]:
    """``parts`` without the empty ones, neighbours in one language merged."""
    out: list[KeyRun] = []
    for text, source in parts:
        if not text:
            continue
        if out and out[-1][1] == source:
            out[-1] = (out[-1][0] + text, source)
        else:
            out.append((text, source))
    return out


def _key_open(ws: Worksheet, answers: list[str | None]) -> list[list[KeyRun]]:
    """Model answers, 'answers will vary' where there is none; no key at
    all without any model answer."""
    if not any(answers):
        return []
    open_answer = t("open_answer", ws.source_lang, ws.ui)
    return [_runs((a, False)) if a else _runs((open_answer, True)) for a in answers]


def _key_dialogue(pt: PlannedTask, ws: Worksheet) -> list[list[KeyRun]]:
    """The gaps of each line with gaps, the model answer of each line the
    learner writes; no key when nothing has an answer."""
    task = pt.task
    assert isinstance(task, DialogueTask)
    answers: list[str | None] = []
    for line in task.lines:
        if line.text is None:
            answers.append(line.answer)
        elif gaps := safe_gaps(line.text):  # (a line without gaps has no number)
            answers.append(" … ".join(gap_answer(g) for g in gaps))
    return _key_open(ws, answers)


def _target_key(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The key of a kind whose entries are all in the target language."""
    task = pt.task

    if isinstance(task, MatchTask):
        n = len(task.pairs) + len(task.extra)
        order = pt.right_order if pt.right_order is not None else list(range(n))
        return [letter(order.index(i)) for i in range(len(task.pairs))]

    if isinstance(task, MultipleChoiceTask):
        choices: list[str] = []
        for i, choice in enumerate(task.items):
            options = pt.option_orders[i] if pt.option_orders else list(choice.options)
            choices.append(f"{letter(options.index(choice.answer), upper=False)} – {choice.answer}")
        return choices

    if isinstance(task, OrderEventsTask):
        shown = pt.events if pt.events is not None else list(task.events)
        return [str(task.events.index(e) + 1) for e in shown]

    if isinstance(task, ClassifyTask):
        return _key_classify(pt, ws)

    if isinstance(task, GappedTextTask):
        return _key_gapped_text(pt, ws)

    if isinstance(task, ClozeTask):
        if task.hint == "choice":
            return _key_choice(pt, task)
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

    if isinstance(task, CrosswordTask):
        return _key_crossword(pt, ws)

    if isinstance(task, (WritingTask, MediaSearchTask, DrawTask)):
        return []

    return []  # pragma: no cover - every kind is handled above


def _key_true_false(pt: PlannedTask, ws: Worksheet) -> list[list[KeyRun]]:
    """true / false (with the correction) / not in the text, per statement, and
    the words of the story that prove it: ``false – Sie soll … „Am Freitag …“``."""
    task = pt.task
    assert isinstance(task, TrueFalseTask)
    lang, ui = ws.source_lang, ws.ui
    verdicts: list[list[KeyRun]] = []
    for item in task.items:
        if item.answer == "not_given":
            verdicts.append(_runs((t("not_given", lang, ui), True)))
            continue
        word = t("true" if item.answer is True else "false", lang, ui)
        shown = [item.correction] if item.answer is False and item.correction else []
        quote = quoted_passage(item.quote or "", ws.target_lang)
        if quote:
            shown.append(quote)
        if shown:
            verdicts.append(_runs((f"{word} – ", True), (" ".join(shown), False)))
        else:
            verdicts.append(_runs((word, True)))
    return verdicts


#: Quote marks that open and close a passage (the story's own „…“ around
#: direct speech included), and the double ones among them.
_OPENING_QUOTES = "„“”«»‚‘’‹›\"'"
_CLOSING_QUOTES = "“”«»‘’‹›\"'"
_DOUBLE_QUOTES = "„“”«»\""


def quoted_passage(text: str, lang: str) -> str:
    """Words of the story in the quote marks of ``lang`` (``„…“`` in German),
    without the marks of a passage that is one quotation already
    (``„Um sieben.“``, but not ``„Morgen“, sagt er. „Um sieben.“``); ``""``
    for no words."""
    text = text.strip()
    inner = text[1:-1]
    if (len(text) > 1 and text[0] in _OPENING_QUOTES and text[-1] in _CLOSING_QUOTES
            and not any(mark in inner for mark in _DOUBLE_QUOTES)):
        text = inner.strip()
    return quoted(text, lang) if text else ""


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
    task = pt.task
    assert isinstance(task, ClassifyTask)
    if task.layout == "columns":
        # one entry per category, in category order: 'Lena: der Hafen, die Fähre'
        # (a no-break space: a line never ends with a category's name)
        key = []
        for category in task.categories:
            words = [i.text for i in task.items if i.answer == category]
            key.append(f"{category}:\u00a0{', '.join(words) or '–'}")
        return key
    order = pt.row_order if pt.row_order is not None else list(range(len(task.items)))
    return [task.items[k].answer for k in order]


def _key_table(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The gap answers of a table, row by row (the order of the gap numbers);
    open (null) cells are the learner's own answers and have no entry."""
    task = pt.task
    assert isinstance(task, TableTask)
    return [gap_answer(g) for row in task.rows for cell in row if cell for g in safe_gaps(cell)]


def _key_choice(pt: PlannedTask, task: ClozeTask) -> list[str]:
    """The right option of each choice gap (of each item, joined by ' … '):
    the word the learner circles, or with the options below the text the
    ticked letter and its word ('b – ist')."""
    shown = iter(pt.gap_options or [])
    per_text: list[list[str]] = []
    for text in cloze_texts(task):
        answers = []
        for gap in safe_gaps(text):
            options = next(shown, [gap.answer])
            if task.choice_layout == "below" and gap.answer in options:
                # (the letter and the word never part at a line end: no-break
                # spaces, and a word joiner, as a line may break after a dash)
                index = options.index(gap.answer)
                answers.append(f"{letter(index, upper=False)}\u00a0–\u2060\u00a0{gap.answer}")
            else:
                answers.append(gap.answer)
        per_text.append(answers)
    if task.text is not None:
        return per_text[0]
    return [" … ".join(answers) for answers in per_text]


def _key_gapped_text(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The letter of the sentence that fills each gap."""
    task = pt.task
    assert isinstance(task, GappedTextTask)
    gaps = safe_gaps(task.text)
    shown = pt.slot_options
    if shown is None:
        shown = [g.answer for g in gaps] + list(task.extra)
    return [letter(shown.index(g.answer)) for g in gaps]


def _key_find_in_text(pt: PlannedTask, ws: Worksheet) -> list[list[KeyRun]]:
    """Each word or phrase to find (with its explanation, in the language of
    the clues)."""
    task = pt.task
    assert isinstance(task, FindInTextTask)
    open_answer = t("open_answer", ws.source_lang, ws.ui)
    key: list[list[KeyRun]] = []
    for item in task.items:
        if item.explanation:
            key.append(_runs((item.answer, False),
                             (f" – {item.explanation}", task.clue_lang == "source")))
        elif task.explain:
            key.append(_runs((item.answer, False), (f" – {open_answer}", True)))
        else:
            key.append(_runs((item.answer, False)))
    return key


def _key_proofread(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """'wrong → correct' per mistake, in text order (the arrow never starts a line)."""
    task = pt.task
    assert isinstance(task, ProofreadTask)
    return [f"{gap.hint}\u00a0→ {gap_answer(gap)}" if gap.hint else gap_answer(gap)
            for gap in safe_gaps(task.text)]


def _key_crossword(pt: PlannedTask, ws: Worksheet) -> list[str]:
    """The answers in clue order (across, then down), in the target
    language's capitals; words the grid could not take have no clue."""
    task = pt.task
    assert isinstance(task, CrosswordTask)
    grid = pt.crossword or crossword.layout([e.answer for e in task.entries])
    return [crossword.printed(task.entries[p.index].answer, ws.target_lang) for p in grid.placed]
