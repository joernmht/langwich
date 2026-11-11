"""The design rubric: deterministic checks of story craft and exercise design.

``langwich validate`` answers "will this sheet work?" — the file matches the
contract, nothing is broken, no answer is given away. This module answers the
next question, "is it a well-made lesson?", as far as that can be *measured*:
every rule is a pure function of the worksheet JSON. No model, no network, no
randomness, no clock — the same file always gets the same findings, in the
same order. That makes the rubric usable as a test: for the bundled examples
(``tests/test_quality.py``), for a worksheet a changed brief produced, and for
a new kind of task.

Three dimensions:

* **story** — the shape of the story: beats, a protagonist who is there from
  the first scene to the last, direct speech, scenes of similar weight,
  sentences that fit the level, facts beside the story rather than inside it;
* **lesson** — the arc of the sheet: every phase present, every scene
  checked, the key words pre-taught, recycled and finally written by the
  learner, every grammar point practised, a mix of task kinds;
* **items** — the craft of the single task: enough items and not too many,
  true/false with both kinds, options of similar length, spare words in every
  word box, nothing in the task that shows its own answer, room to write.

Where a number comes from the authoring brief (``langwich prompt``) the rule
says so; the level table is read from :data:`langwich.prompt.LEVELS`, so the
rubric and the brief cannot drift apart. The other rules are common
item-writing practice (the right option must not be the longest one; a word
box needs spare words; a true/false task needs both kinds).

What no deterministic rule can see: whether the facts are true, whether the
language is natural, whether the reader wants to know how the story ends.
Those stay with the author and the reviewer.

New task kinds: :data:`KIND_DESIGN` holds one :class:`KindDesign` per kind —
how its items are counted, how many it should have, how the learner checks
the answer. A kind without an entry fails ``tests/test_quality.py``, so a new
exercise concept has to say what good looks like before it ships.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from langwich import locale, markup
from langwich.model import (
    TASK_KINDS,
    Character,
    ClozeTask,
    DialogueTask,
    DrawTask,
    LabelTask,
    MatchTask,
    MediaSearchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    QuestionsTask,
    Task,
    TransformTask,
    TrueFalseTask,
    WordBuildingTask,
    Worksheet,
    WritingTask,
)
from langwich.plan import strip_article
from langwich.prompt import LEVELS
from langwich.validate import (
    _NO_SPACE_LANGS,
    COPY_RATIO,
    Issue,
    _Checker,
    _norm_sentence,
    _sentences,
    _word_count,
)

Dimension = Literal["story", "lesson", "items"]
DIMENSIONS: tuple[Dimension, ...] = ("story", "lesson", "items")


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One rule of the rubric: what good looks like, and why."""

    dimension: Dimension
    title: str
    why: str


#: Every rule of the rubric: code -> rule. The order is the order of the
#: documentation; findings are reported in worksheet order.
RULES: dict[str, Rule] = {
    # -- story --------------------------------------------------------------
    "beat-missing": Rule(
        "story", "every scene names its beat",
        "the brief asks for one beat per scene; without it nothing can check the story's shape",
    ),
    "beat-order": Rule(
        "story", "the story opens with the setup and its beats never go backwards",
        "setup → development → complication → climax → resolution is the arc a reader follows",
    ),
    "no-turn": Rule(
        "story", "a story of three or more scenes has a complication or a climax",
        "without something going wrong there is a report, not a story",
    ),
    "no-resolution": Rule(
        "story", "the last scene resolves the story",
        "the learner reads to find out how it ends",
    ),
    "protagonist-absent": Rule(
        "story", "the protagonist is named in the first scene, the last scene and most others",
        "one person to follow from the goal to the payoff",
    ),
    "character-unused": Rule(
        "story", "every character on the cover is named in the story",
        "the cover introduces the cast; a name that never comes up is a loose end",
    ),
    "logline-without-protagonist": Rule(
        "story", "the logline names the protagonist",
        "the logline says who wants what; the first character it names is the one the "
        "story rules follow",
    ),
    "no-direct-speech": Rule(
        "story", "at least half of the scenes contain direct speech",
        "the brief asks for some direct speech in each scene: facts arrive through people, "
        "not through a narrator's lecture",
    ),
    "scene-unbalanced": Rule(
        "story", "no scene is more than twice as long as the shortest",
        "each scene is one sitting of reading followed by its tasks",
    ),
    "sentence-length": Rule(
        "story", "sentences fit the level: the mean stays under the level's limit and no "
                 "sentence is twice as long",
        "the brief's level table (A1 4–8 words, A2 5–12, B1 up to about 15)",
    ),
    "translation-missing": Rule(
        "story", "every scene has a complete translation",
        "the translations are printed with the solutions; a missing or cut-off one leaves the "
        "learner without a check",
    ),
    "fact-repeats-story": Rule(
        "story", "a 'Did you know?' fact tells something the story has not already told",
        "the brief: short, surprising, true, not already told by the story",
    ),
    "fact-unanchored": Rule(
        "story", "every fact is placed beside a scene",
        "a fact belongs next to the moment of the story it explains",
    ),
    "fact-too-long": Rule(
        "story", "a fact has at most three sentences",
        "a sidebar, not a second text to read",
    ),
    "cover-incomplete": Rule(
        "story", "the cover has a standfirst, a setting and at least two characters with roles",
        "the cover sets the stakes before the first line",
    ),
    "series-without-teaser": Rule(
        "story", "an episode of a series ends with a teaser for the next one",
        "the hook is what makes a series a series",
    ),
    # -- lesson -------------------------------------------------------------
    "no-warm-up": Rule(
        "lesson", "the sheet starts with a warm-up task",
        "the key words are met before the story needs them",
    ),
    "no-language-work": Rule(
        "lesson", "the sheet has a form or practice task",
        "understanding the story is not yet using its language",
    ),
    "scene-unchecked": Rule(
        "lesson", "every scene is followed by a comprehension or picture task about it",
        "read a little, check what happened, read on",
    ),
    "task-variety": Rule(
        "lesson", "a sheet of seven or more tasks uses at least five kinds, and none of them "
                  "for more than 40% of the tasks",
        "different kinds train different things; the same kind again and again is a drill",
    ),
    "target-not-pretaught": Rule(
        "lesson", "at least half of the key words appear in the warm-up",
        "the brief's first task: the key words with their meanings",
    ),
    "target-thinly-practised": Rule(
        "lesson", "every key word comes up in at least three tasks",
        "the brief asks for the story and three tasks; a word met once is not learned",
    ),
    "target-never-produced": Rule(
        "lesson", "every key word is written by the learner at least once",
        "recognising a word is not yet being able to use it",
    ),
    "grammar-unpractised": Rule(
        "lesson", "every grammar point is practised by a form or practice task that names it",
        "a grammar box without a task beside it is decoration",
    ),
    "grammar-few-examples": Rule(
        "lesson", "every grammar point has at least two examples",
        "the brief asks for two or three; one example is an instance, two show the pattern",
    ),
    "practice-leaves-story": Rule(
        "lesson", "practice clozes and dialogues name a character of the story",
        "practice continues the story in new sentences, it does not leave it",
    ),
    "comprehension-quotes-story": Rule(
        "lesson", "comprehension items paraphrase the story instead of quoting it",
        "a statement copied from the text tests finding, not understanding",
    ),
    "labels-unused": Rule(
        "lesson", "a picture with labels has a label task",
        "numbered markers without a task are numbers on a picture",
    ),
    "answer-missing": Rule(
        "lesson", "every task the learner can get wrong has an answer in the key",
        "a sheet for self-study is only as good as its answer key",
    ),
    # -- items --------------------------------------------------------------
    "item-count": Rule(
        "items", "a task has a sensible number of items for its kind",
        "too few is not practice, too many is a chore; the ranges are in KIND_DESIGN",
    ),
    "tf-one-sided": Rule(
        "items", "a true/false task has both kinds, and neither makes up more than three "
                 "quarters",
        "a pattern the learner can guess needs no reading",
    ),
    "tf-correction-same": Rule(
        "items", "the correction of a false statement differs from the statement",
        "the answer key must show what is true instead",
    ),
    "mc-few-options": Rule(
        "items", "a multiple-choice question has at least three options",
        "with two options a guess is right half the time",
    ),
    "mc-answer-stands-out": Rule(
        "items", "the right option is not far longer than every wrong one",
        "the longest, most careful option is the first thing a test-wise learner ticks",
    ),
    "mc-longest-is-right": Rule(
        "items", "across a task of three or more questions the right option is the "
                 "longest in at most half of them, rounded up (2 of 3, 2 of 4, 3 of 5)",
        "the same cue, as a pattern over the whole task; one more than chance allows, so "
        "that a short task is not reported for a coincidence",
    ),
    "match-no-spare": Rule(
        "items", "a matching task has at least one spare answer",
        "otherwise the last pair is free",
    ),
    "match-trivial-pair": Rule(
        "items", "the two sides of a pair are not the same word",
        "a pair that matches itself teaches nothing",
    ),
    "cloze-too-dense": Rule(
        "items", "a gap text keeps at least five words of context per gap (three in a "
                 "form drill)",
        "a gap is filled from its context; without context it is a guess",
    ),
    "bank-distractors": Rule(
        "items", "a word box has at least one spare word, and fewer spare words than gaps",
        "one spare word keeps the last gap honest; too many turn the box into noise",
    ),
    "bank-word-twice": Rule(
        "items", "each word-box word fills exactly one gap",
        "the box shows a word once; needing it twice leaves a gap without a word",
    ),
    "distractor-stands-out": Rule(
        "items", "a spare word does not differ from every answer by its capital letter",
        "the brief: capitals and endings reveal nothing",
    ),
    "answer-shown-in-task": Rule(
        "items", "a gap's answer does not stand elsewhere in the same task",
        "the brief: the answer appears nowhere else in the task",
    ),
    "lines-too-few": Rule(
        "items", "there is room to write: a line per twelve words of a model answer, a line "
                 "per ten words of a text",
        "the sheet is worked through with a pen",
    ),
    "writing-scaffold": Rule(
        "items", "a writing task has a starter, three or more words to use, a word range "
                 "that fits the level and a model answer",
        "a blank page is the hardest task on the sheet; the scaffold makes it doable",
    ),
    "must-use-unseen": Rule(
        "items", "the words a writing task asks for have come up on the sheet: in the "
                 "story, a fact, the word list, a grammar box or another task",
        "the learner can only use what the sheet has taught",
    ),
    "transform-no-change": Rule(
        "items", "a transformed sentence differs from its prompt",
        "otherwise there is nothing to do",
    ),
    "word-building-unrelated": Rule(
        "items", "a built word contains its parts",
        "the learner assembles the answer from what is given",
    ),
    "media-search-thin": Rule(
        "items", "a media search gives search terms, not links, and at least two questions",
        "links rot; search terms in the target language are the task",
    ),
    "label-crowded": Rule(
        "items", "the markers of a picture do not sit on top of each other",
        "a number has to point at one thing",
    ),
    "title-generic": Rule(
        "items", "every task has its own title that belongs to the story",
        "the brief: 'Thursday: a second chance', never 'Exercise 3'",
    ),
}


# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

#: Beats in story order.
BEAT_ORDER: tuple[str, ...] = (
    "setup", "development", "complication", "climax", "resolution", "epilogue",
)
#: Frames told in the first person: the narrator need not be named.
FIRST_PERSON_FRAMES: frozenset[str] = frozenset({"diary", "letters"})
#: Mean words per sentence a level allows; no sentence may be twice as long.
#: A1–B1 are the upper ends of the brief's level table; B2–C2 continue it.
SENTENCE_WORDS: dict[str, int] = {"A1": 8, "A2": 12, "B1": 15, "B2": 20, "C1": 25, "C2": 30}
assert set(SENTENCE_WORDS) == set(LEVELS)
SCENE_RATIO = 2.0
SPEECH_SCENES = 0.5
FACT_SENTENCES = 3
#: A translation shorter than half or longer than twice the text is not one.
TRANSLATION_RATIO = (0.5, 2.0)

MIN_KINDS, MIN_KINDS_FROM = 5, 7
KIND_SHARE = 0.4
PRETAUGHT_SHARE = 0.5
TARGET_TASKS = 3
GRAMMAR_EXAMPLES = 2

TF_SHARE = 0.75
MC_OPTIONS = 3
#: The right option stands out when it is this much longer than the longest
#: wrong one, and by at least this many characters.
MC_RATIO, MC_CHARS = 1.5, 10
CONTEXT_WORDS, CONTEXT_WORDS_FORM = 5, 3
WORDS_PER_ANSWER_LINE = 12
WORDS_PER_TEXT_LINE = 10
MUST_USE_MIN = 3
#: How far a writing task's word range may leave the level's range.
WRITING_LOW, WRITING_HIGH = 0.5, 1.5
MARKER_DISTANCE = 0.05

#: Languages that put case endings on names. In the first group a name
#: changes its last letters (Marta, Marty, Marcie; Marek, Marka); in the
#: second the nominative ending falls away as well (Jonas, Jono); in the third
#: endings are added to the whole name (Mia, Mialle; Pekka, Pekan).
_CASE_ENDING = frozenset({"pl", "cs", "sk", "sl", "hr", "sr", "bs", "ru", "uk", "bg"})
_CASE_ENDING_S = frozenset({"lt", "lv", "el", "is", "la"})
_CASE_SUFFIX = frozenset({"fi", "et", "hu", "tr"})
#: Letters a name loses before a case ending (Marta → Marty, Игорь → Игоря).
_FINAL_VOWELS = frozenset("aeiouyáéíóúýąęěůäöüőűаеёиоуыэюяіїєьй")
#: Polish and Czech soften the last consonant before the -e of the dative and
#: locative: Marta → Marcie, Monika → Monice, Olga → Oldze / Olze, Petra → Petře.
_SOFTENED: dict[str, tuple[str, ...]] = {
    "t": ("ci",), "d": ("dzi",), "k": ("c",), "g": ("dz", "z"), "r": ("rz", "ř"),
    "n": ("ni",), "s": ("si",), "z": ("zi",), "w": ("wi",), "m": ("mi",), "b": ("bi",),
    "p": ("pi",), "f": ("fi",), "ł": ("l",), "h": ("z",),
}
#: Titles and family words that are part of a name but do not identify it.
_HONORIFICS = frozenset({
    "herr", "frau", "fräulein", "onkel", "tante", "oma", "opa", "signor", "signora",
    "signorina", "madame", "monsieur", "mademoiselle", "mme", "dona", "dom", "don", "doña",
    "señor", "señora", "senhor", "senhora", "sr", "sra", "mr", "mrs", "ms", "miss", "dr",
    "prof", "professor", "pan", "pani", "paní", "pán", "slečna", "meneer", "mevrouw", "hr",
    "fru", "tía", "tío", "abuela", "abuelo", "avó", "avô", "nonna", "nonno", "zia", "zio",
    "tia", "tio", "mamie", "papi", "oom", "babcia", "dziadek", "ciocia", "wujek", "babička",
    "děda", "teta", "strýc", "mormor", "morfar", "farmor", "farfar", "uncle", "aunt",
    "grandma", "grandpa", "sir", "lady",
})
_GENERIC_TITLE_RE = re.compile(
    r"^\W*(?:exercise|task|activity|übung|aufgabe|exercice|activité|ejercicio|actividad|"
    r"tarea|esercizio|attività|exercício|atividade|oefening|opdracht|ćwiczenie|zadanie|"
    r"cvičení|úkol|øvelse|opgave|övning|uppgift)\s*\d*\W*$",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://|www\.|\.(?:com|org|net|de|fr|es|it|pt|nl|pl|cz|dk)/", re.I)
#: Characters that open or close direct speech; an apostrophe is not one.
_QUOTE_CHARS = "„“”\"«»‹›"
_SPEECH_DASH_RE = re.compile(r"(?m)^\s*(?:[—–―]\s*|-\s+)\S")


# ---------------------------------------------------------------------------
# Task kinds: what good looks like
# ---------------------------------------------------------------------------


def _gaps(text: str | None) -> list[markup.Gap]:
    if not text:
        return []
    try:
        return markup.gaps(text)
    except ValueError:
        return []


def _cloze_texts(task: ClozeTask) -> list[str]:
    return [task.text] if task.text is not None else list(task.items or [])


def _labels_of(task: LabelTask, ws: Worksheet) -> int:
    scene = ws.scene(task.scene)
    return len(scene.picture.labels) if scene and scene.picture else 0


def _dialogue_slots(task: DialogueTask) -> int:
    return sum(len(_gaps(line.text)) if line.text is not None else 1 for line in task.lines)


@dataclass(frozen=True)
class KindDesign:
    """What a task kind asks of the learner, and how much of it is right.

    ``response`` says how the learner checks the work: ``closed`` — one right
    answer in the key; ``guided`` — a model answer to compare with; ``open`` —
    nothing to compare (a search, a drawing). ``unit`` names what ``count``
    counts, and ``items`` is the sensible range of it for one task.
    """

    response: Literal["closed", "guided", "open"]
    unit: str
    items: tuple[int, int]
    count: Callable[[Any, Worksheet], int]


#: One entry per task kind (checked against ``TASK_KINDS`` below and in the
#: tests). The ranges follow the brief's "Item quality" section where it gives
#: numbers (true/false 3–5 statements, order 4–6 events, 4–8 labels) with one
#: item of slack, and common practice elsewhere.
KIND_DESIGN: dict[str, KindDesign] = {
    "match": KindDesign("closed", "pairs", (4, 12), lambda t, ws: len(t.pairs)),
    "true_false": KindDesign("closed", "statements", (3, 6), lambda t, ws: len(t.items)),
    "multiple_choice": KindDesign("closed", "questions", (2, 6), lambda t, ws: len(t.items)),
    "order_events": KindDesign("closed", "events", (4, 7), lambda t, ws: len(t.events)),
    "questions": KindDesign("guided", "questions", (1, 6), lambda t, ws: len(t.items)),
    "cloze": KindDesign(
        "closed", "gaps", (3, 12),
        lambda t, ws: sum(len(_gaps(text)) for text in _cloze_texts(t)),
    ),
    "transform": KindDesign("closed", "sentences", (3, 8), lambda t, ws: len(t.items)),
    "word_building": KindDesign("closed", "words", (3, 8), lambda t, ws: len(t.items)),
    "label": KindDesign("closed", "labels", (4, 8), _labels_of),
    "writing": KindDesign("guided", "texts", (1, 1), lambda t, ws: 1),
    "dialogue": KindDesign(
        "guided", "gaps and lines to write", (3, 12), lambda t, ws: _dialogue_slots(t),
    ),
    "media_search": KindDesign("open", "search terms", (2, 4), lambda t, ws: len(t.queries)),
    "draw": KindDesign("open", "words to label", (3, 8), lambda t, ws: len(t.labels)),
}
assert set(KIND_DESIGN) == set(TASK_KINDS), "every task kind needs a KindDesign"


# ---------------------------------------------------------------------------
# Findings and report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    code: str
    where: str
    message: str

    @property
    def dimension(self) -> Dimension:
        return RULES[self.code].dimension


@dataclass
class QualityReport:
    findings: list[Finding]
    #: Deterministic measures of the sheet (see :func:`measure`).
    metrics: dict[str, Any]

    @property
    def ok(self) -> bool:
        return not self.findings

    def failed(self, dimension: Dimension | None = None) -> list[str]:
        """Codes of the rules with findings, in rule order."""
        hit = {f.code for f in self.findings}
        return [code for code, rule in RULES.items()
                if code in hit and dimension in (None, rule.dimension)]

    def passed(self, dimension: Dimension) -> tuple[int, int]:
        """(rules without findings, rules) of one dimension."""
        total = sum(1 for rule in RULES.values() if rule.dimension == dimension)
        return total - len(self.failed(dimension)), total

    def summary(self) -> str:
        parts = []
        for dimension in DIMENSIONS:
            good, total = self.passed(dimension)
            parts.append(f"{dimension} {good}/{total}")
        n = len(self.findings)
        head = "no findings" if not n else f"{n} finding{'s' if n != 1 else ''}"
        return f"Design rubric: {head} ({', '.join(parts)} rules pass)."

    def issues(self) -> list[Issue]:
        """The findings as validator warnings, for reports and repair prompts."""
        return [Issue("warning", f.code, f.where, f.message) for f in self.findings]

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "finding_count": len(self.findings),
            "rules": {d: dict(zip(("passed", "total"), self.passed(d))) for d in DIMENSIONS},
            "metrics": self.metrics,
            "findings": [
                {"code": f.code, "dimension": f.dimension, "where": f.where,
                 "message": f.message}
                for f in self.findings
            ],
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fold(text: str) -> str:
    """Lower case without accents, for comparisons that ignore both."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _q(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"'{text}'"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def has_direct_speech(text: str) -> bool:
    """True when ``text`` has quotation marks or a line that opens with a dash."""
    if any(c in text for c in _QUOTE_CHARS):
        return True
    if "‘" in text and "’" in text:
        return True
    return bool(_SPEECH_DASH_RE.search(text))


def speech_share(text: str) -> float:
    """The share of the words of ``text`` that are direct speech (0–1).

    Quotation marks of any style switch speech on and off; ``‘…’`` pairs
    count from the opening mark to the closing one; a line that opens with a
    dash counts as speech up to its end. An estimate: a speech tag after a
    dash line ("— …, said Rui.") is counted with it.
    """
    total = _word_count(text)
    if not total:
        return 0.0
    spoken = 0
    for line in text.splitlines():
        if _SPEECH_DASH_RE.match(line):
            spoken += _word_count(line)
            continue
        inside, start = False, 0
        for at, char in enumerate(line):
            if char in _QUOTE_CHARS:
                if inside:
                    spoken += _word_count(line[start:at])
                inside, start = not inside, at + 1
        spoken += sum(_word_count(m.group(1)) for m in re.finditer(r"‘([^‘]*)’", line))
    return min(1.0, spoken / total)


def name_keys(name: str) -> list[str]:
    """The words of a character's name that identify the person: 'Frau Berger'
    → ['Berger'], 'la abuela Pepa' → ['Pepa'], 'Hannah' → ['Hannah']."""
    words = re.findall(r"[^\W\d_]+(?:[-'’][^\W\d_]+)*", name)
    capitalised = [w for w in words if w[:1].isupper()]
    keys = [w for w in capitalised if w.casefold().rstrip(".") not in _HONORIFICS]
    return keys or capitalised or words or [name]


def _name_forms(key: str, lang: str) -> list[str]:
    """Regular expressions for the forms a name takes in ``lang``.

    Deliberately narrow: a short name must not be found in every word that
    starts like it ('Mia' in 'Miasto', 'Tom' in 'To je …'). Where a language
    is not listed, a name is matched as written, with a genitive -s.
    """
    esc = re.escape
    inflecting = lang in _CASE_SUFFIX or lang in _CASE_ENDING or lang in _CASE_ENDING_S
    if inflecting and len(key) <= 2:
        return [esc(key)]  # 'Jo' is not every 'Ja', 'Al' not every 'Ale': as written only
    if lang in _CASE_SUFFIX:
        forms = [esc(key) + r"\w{0,5}"]
        if len(key) >= 5:  # consonant gradation: Pekka → Pekan
            forms.append(esc(key[:-2]) + r"\w{1,6}")
        if key[-1] in "ae":  # Hungarian lengthens the vowel: Anna → Annának
            forms.append(esc(key[:-1]) + ("á" if key[-1] == "a" else "é") + r"\w{0,5}")
        return forms
    if lang not in _CASE_ENDING and lang not in _CASE_ENDING_S:
        return [esc(key) + "(?:['’]?s)?"]
    last = key[-1].lower()
    if last in _FINAL_VOWELS:
        # the ending replaces the vowel: Marta → Marty, Martou; Mia → Mii, Mię;
        # Kowalski → Kowalskiego. The shorter the stem, the shorter the ending
        # it may take, or 'Маша' would be found in 'Машина'.
        stem = key[:-1]
        longest = 1 if len(stem) <= 2 else 2 if len(stem) <= 4 else 4
        forms = [esc(key), esc(stem) + rf"\w{{1,{longest}}}"]
        soft = _SOFTENED.get(stem[-1:].lower())
        if soft:
            forms.append(esc(stem[:-1]) + "(?:" + "|".join(soft) + ")e")
        return forms
    # the ending follows the consonant: Tom → Toma, Tomem, Tomowi
    forms = [esc(key) + r"\w{0,3}"]
    if len(key) >= 4 and key[-2].lower() == "e" and key[-3].lower() not in _FINAL_VOWELS:
        forms.append(esc(key[:-2] + key[-1]) + r"\w{1,3}")  # Marek → Marka, Pavel → Pavla
    if lang in _CASE_ENDING_S and len(key) >= 5:
        forms.append(esc(key[:-2]) + r"\w{1,3}")  # Jonas → Jono, Marcus → Marci
    return forms


def _name_pattern(key: str, lang: str) -> re.Pattern[str]:
    return re.compile(r"(?<!\w)(?:" + "|".join(_name_forms(key, lang)) + r")(?!\w)")


def is_named(character: Character, text: str, lang: str) -> bool:
    """True when ``text`` names ``character``: the whole name as a word, or any
    of its identifying words in a form the language allows."""
    name = character.name
    if lang in _NO_SPACE_LANGS:
        return name in text  # no word boundaries to look for
    if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", text):
        return True
    return any(_name_pattern(key, lang).search(text) for key in name_keys(name))


def _similar(a: str, b: str) -> bool:
    """Two sentences that are almost the same (the validator's copy test)."""
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return (sm.real_quick_ratio() >= COPY_RATIO and sm.quick_ratio() >= COPY_RATIO
            and sm.ratio() >= COPY_RATIO)


def _first_upper(word: str) -> bool:
    return word[:1].isupper()


# ---------------------------------------------------------------------------
# The rubric
# ---------------------------------------------------------------------------


class _Rubric:
    def __init__(self, ws: Worksheet):
        self.ws = ws
        self.lang = locale.base_lang(ws.target_lang)
        self.counts_words = self.lang not in _NO_SPACE_LANGS
        self.findings: list[Finding] = []
        self.words = _Checker(ws, None)  # the validator's word search
        self.scenes = ws.story.scenes
        self.story_sentences = [
            (sentence, _norm_sentence(sentence))
            for scene in self.scenes for sentence in _sentences(scene.text)
        ]
        self.story_sentences = [(s, n) for s, n in self.story_sentences if len(n.split()) >= 4]

    def find(self, code: str, where: str, message: str) -> None:
        assert code in RULES, code
        self.findings.append(Finding(code, where, message))

    # -- story ----------------------------------------------------------------

    def protagonist(self) -> Character | None:
        """The first character the logline names — the logline says who wants
        what — or, when it names nobody, the first one on the cover."""
        cast = self.ws.story.characters
        logline = self.ws.story.logline
        codes = (locale.base_lang(self.ws.source_lang), self.lang)
        for character in cast:
            if any(is_named(character, logline, code) for code in codes):
                return character
        return cast[0] if cast else None

    def check_beats(self) -> None:
        scenes = self.scenes
        missing = [i for i, s in enumerate(scenes) if s.beat is None]
        for i in missing:
            self.find(
                "beat-missing", f"/story/scenes/{i}/beat",
                f"scene '{scenes[i].id}' has no beat. Set \"beat\" to its part in the story: "
                + ", ".join(BEAT_ORDER) + ".",
            )
        if missing:
            return
        ranks = [BEAT_ORDER.index(s.beat or "setup") for s in scenes]
        if ranks[0] != 0:
            self.find(
                "beat-order", "/story/scenes/0/beat",
                f"the first scene has the beat '{scenes[0].beat}'; a story opens with 'setup': "
                "who is where, and what do they want?",
            )
        for i in range(1, len(scenes)):
            if ranks[i] < ranks[i - 1]:
                self.find(
                    "beat-order", f"/story/scenes/{i}/beat",
                    f"scene '{scenes[i].id}' has the beat '{scenes[i].beat}' after "
                    f"'{scenes[i - 1].beat}': the story goes backwards. Keep the order "
                    + " → ".join(BEAT_ORDER) + ".",
                )
        beats = {s.beat for s in scenes}
        if len(scenes) >= 3 and not beats & {"complication", "climax"}:
            self.find(
                "no-turn", "/story/scenes",
                "no scene has the beat 'complication' or 'climax'. Let something go wrong in "
                "the middle of the story — because of a choice or a real-world constraint — "
                "and set that scene's beat.",
            )
        if scenes[-1].beat not in ("resolution", "epilogue"):
            self.find(
                "no-resolution", f"/story/scenes/{len(scenes) - 1}/beat",
                f"the last scene has the beat '{scenes[-1].beat}'. End the story: the last "
                "scene resolves what the first one set up (beat 'resolution').",
            )

    def check_cast(self) -> None:
        ws, lang = self.ws, self.lang
        cast = ws.story.characters
        hero = self.protagonist()
        first_person = ws.frame in FIRST_PERSON_FRAMES
        if hero is not None and not first_person:
            named = [is_named(hero, s.text, lang) for s in self.scenes]
            gaps = []
            if not named[0]:
                gaps.append("the first scene")
            if not named[-1]:
                gaps.append("the last scene")
            if sum(named) * 2 < len(named):
                gaps.append(f"{len(named) - sum(named)} of {len(named)} scenes")
            if gaps:
                self.find(
                    "protagonist-absent", "/story/scenes",
                    f"the protagonist, {hero.name}, is not named in " + " and ".join(gaps)
                    + ". Name them where the story begins and where it ends, and in most "
                    "scenes between: the learner follows one person.",
                )
        story = "\n".join(s.text for s in self.scenes)
        for i, character in enumerate(cast):
            if first_person and character is hero:
                continue
            if not is_named(character, story, lang):
                self.find(
                    "character-unused", f"/story/characters/{i}",
                    f"{character.name} is on the cover but is not named in any scene. Use the "
                    "name in the story, or remove the character.",
                )
        source = locale.base_lang(ws.source_lang)
        if hero is not None and not any(
                is_named(hero, ws.story.logline, code) for code in (source, lang)):
            self.find(
                "logline-without-protagonist", "/story/logline",
                "the logline names none of the characters. One sentence: who wants what, "
                f"and what stands in the way — starting with the protagonist ({hero.name}?).",
            )
        problems = []
        if not ws.standfirst:
            problems.append("a standfirst (the stakes, and what the learner will find out)")
        if not ws.story.setting:
            problems.append("story.setting (the place and the time)")
        if len(cast) < 2:
            problems.append("a second character (someone the protagonist talks to)")
        without_role = [c.name for c in cast if not c.role]
        if without_role:
            problems.append("a role for " + ", ".join(without_role))
        if problems:
            self.find(
                "cover-incomplete", "/story",
                "the cover is incomplete; add " + "; ".join(problems) + ".",
            )
        if ws.series is not None and not ws.series.next:
            self.find(
                "series-without-teaser", "/series/next",
                "this is an episode of a series, but series.next is empty. End with one or "
                "two sentences in the target language that make the learner want the next "
                "episode.",
            )

    def check_prose(self) -> None:
        ws, scenes = self.ws, self.scenes
        speaking = [has_direct_speech(s.text) for s in scenes]
        if sum(speaking) < len(scenes) * SPEECH_SCENES:
            silent = ", ".join(f"'{s.id}'" for s, yes in zip(scenes, speaking) if not yes)
            self.find(
                "no-direct-speech", "/story/scenes",
                f"only {sum(speaking)} of {len(scenes)} scenes contain direct speech (none in "
                f"{silent}). Let the characters say things to each other, in the target "
                "language's quotation marks: that is how facts arrive in a story.",
            )
        if not self.counts_words:
            return
        lengths = [_word_count(s.text) for s in scenes]
        if len(scenes) >= 2 and min(lengths) and max(lengths) > SCENE_RATIO * min(lengths):
            long_, short = lengths.index(max(lengths)), lengths.index(min(lengths))
            self.find(
                "scene-unbalanced", f"/story/scenes/{long_}/text",
                f"scene '{scenes[long_].id}' has {max(lengths)} words, scene "
                f"'{scenes[short].id}' only {min(lengths)}. Move a paragraph, or split the long "
                "scene: each scene is one sitting of reading before its tasks.",
            )
        cap = SENTENCE_WORDS[ws.cefr_level]
        counts: list[int] = []
        for i, scene in enumerate(scenes):
            for sentence in _sentences(scene.text):
                n = _word_count(sentence)
                if not n:
                    continue
                counts.append(n)
                if n > 2 * cap:
                    self.find(
                        "sentence-length", f"/story/scenes/{i}/text",
                        f"the sentence {_q(sentence)} has {n} words; at {ws.cefr_level} no "
                        f"sentence should have more than {2 * cap}. Split it in two.",
                    )
        if counts and sum(counts) / len(counts) > cap:
            self.find(
                "sentence-length", "/story/scenes",
                f"the story's sentences have {sum(counts) / len(counts):.1f} words on "
                f"average; at {ws.cefr_level} the average should stay at {cap} or below. "
                "Shorten the long ones.",
            )

    def check_translations(self) -> None:
        low, high = TRANSLATION_RATIO
        source_counts = locale.base_lang(self.ws.source_lang) not in _NO_SPACE_LANGS
        for i, scene in enumerate(self.scenes):
            where = f"/story/scenes/{i}/translation"
            if not scene.translation:
                self.find(
                    "translation-missing", where,
                    f"scene '{scene.id}' has no translation. Add a faithful one in the "
                    "learner's language; it is printed with the solutions.",
                )
                continue
            if not (self.counts_words and source_counts):
                continue
            words, translated = _word_count(scene.text), _word_count(scene.translation)
            if words and not low * words <= translated <= high * words:
                self.find(
                    "translation-missing", where,
                    f"the translation of scene '{scene.id}' has {translated} words for "
                    f"{words} words of text: it looks cut off or padded. Translate the whole "
                    "scene, and nothing else.",
                )

    def check_facts(self) -> None:
        for i, fact in enumerate(self.ws.facts):
            where = f"/facts/{i}"
            if not fact.scene:
                self.find(
                    "fact-unanchored", f"{where}/scene",
                    f"the fact {_q(fact.text, 40)} has no scene. Set \"scene\" to the scene it "
                    "explains, so it is printed beside it.",
                )
            sentences = [s for s in _sentences(fact.text) if _word_count(s)]
            if len(sentences) > FACT_SENTENCES:
                self.find(
                    "fact-too-long", f"{where}/text",
                    f"the fact {_q(fact.text, 40)} has {len(sentences)} sentences; keep a "
                    f"'Did you know?' box to {FACT_SENTENCES} at most, or make two facts of it.",
                )
            for sentence in sentences:
                norm = _norm_sentence(sentence)
                if len(norm.split()) < 4:
                    continue
                hit = next((s for s, n in self.story_sentences if _similar(norm, n)), None)
                if hit:
                    self.find(
                        "fact-repeats-story", f"{where}/text",
                        f"the fact repeats the story sentence {_q(hit)}. A 'Did you know?' "
                        "box adds something true that the story has not told.",
                    )
                    break

    # -- lesson ---------------------------------------------------------------

    def check_arc(self) -> None:
        ws = self.ws
        stages = {t.stage for t in ws.tasks}
        if "warm_up" not in stages:
            self.find(
                "no-warm-up", "/tasks",
                "no task has the stage 'warm_up'. Start with a match task: the key words on "
                "the left, their meanings on the right, one or two spare meanings.",
            )
        if not stages & {"form", "practice"}:
            self.find(
                "no-language-work", "/tasks",
                "no task has the stage 'form' or 'practice'. Add a task that practises the "
                "grammar point (form) and a word-box cloze that continues the story in new "
                "sentences (practice).",
            )
        checked = {
            ref for t in ws.tasks if t.stage in ("gist", "detail", "picture")
            for ref in t.scene_ids
        }
        for i, scene in enumerate(self.scenes):
            if scene.id not in checked:
                self.find(
                    "scene-unchecked", f"/story/scenes/{i}",
                    f"no gist, detail or picture task is about scene '{scene.id}'. Add a "
                    "comprehension task for it (true_false, multiple_choice, questions), or "
                    "list the scene in a task about several scenes.",
                )
        kinds = Counter(t.kind for t in ws.tasks)
        n = len(ws.tasks)
        if n >= MIN_KINDS_FROM:
            if len(kinds) < MIN_KINDS:
                self.find(
                    "task-variety", "/tasks",
                    f"the {n} tasks use only {_plural(len(kinds), 'kind')} "
                    f"({', '.join(sorted(kinds))}); use at least {MIN_KINDS}. 'langwich "
                    "kinds' lists all of them.",
                )
            kind, count = max(kinds.items(), key=lambda kv: (kv[1], kv[0]))
            if count > KIND_SHARE * n:
                self.find(
                    "task-variety", "/tasks",
                    f"{count} of {n} tasks are '{kind}' tasks. Turn some into another kind: "
                    "no kind should make up more than 40% of the sheet.",
                )
        for i, scene in enumerate(self.scenes):
            picture = scene.picture
            if picture and picture.labels and not any(
                isinstance(t, LabelTask) and t.scene == scene.id for t in ws.tasks
            ):
                self.find(
                    "labels-unused", f"/story/scenes/{i}/picture/labels",
                    f"the picture of scene '{scene.id}' has {_plural(len(picture.labels), 'label')} "
                    "but no label task. Add a task with \"kind\": \"label\", \"stage\": "
                    f"\"picture\" and \"scene\": \"{scene.id}\".",
                )

    def _written_texts(self, task: Task) -> list[str]:
        """The target-language words the learner writes in ``task``."""
        if isinstance(task, ClozeTask):
            return [a for text in _cloze_texts(task) for g in _gaps(text) for a in g.accepted]
        if isinstance(task, DialogueTask):
            out = [a for line in task.lines for g in _gaps(line.text) for a in g.accepted]
            return out + [line.answer or "" for line in task.lines if line.text is None]
        if isinstance(task, LabelTask):
            scene = self.ws.scene(task.scene)
            return [lb.term for lb in scene.picture.labels] if scene and scene.picture else []
        if isinstance(task, WordBuildingTask):
            return [item.answer for item in task.items]
        if isinstance(task, TransformTask):
            return [item.answer for item in task.items]
        if isinstance(task, WritingTask):
            return list(task.must_use)
        if isinstance(task, DrawTask):
            return list(task.labels)
        return []

    def check_target_words(self) -> None:
        ws, words = self.ws, self.words
        seen: set[str] = set()
        target: list[tuple[int, str]] = []
        for k, term in enumerate(ws.vocabulary.target):
            if term.casefold() in seen:
                continue  # the validator reports the repeat
            seen.add(term.casefold())
            if strip_article(term, self.lang) and ws.vocab_item(term) is not None:
                target.append((k, term))
        if not target:
            return
        shown = [(t, [x for x in words.task_texts(t) if x]) for t in ws.tasks]
        warm_up = [text for t, texts in shown if t.stage == "warm_up" for text in texts]
        pretaught = [term for _, term in target if words.occurs(term, warm_up)]
        if len(pretaught) < PRETAUGHT_SHARE * len(target):
            self.find(
                "target-not-pretaught", "/vocabulary/target",
                f"only {len(pretaught)} of the {len(target)} key words appear in a warm-up "
                "task. Put the key words into the warm-up match task (left: the word, right: "
                "its meaning), so the learner meets them before the story.",
            )
        for k, term in target:
            where = f"/vocabulary/target/{k}"
            used = [t.id for t, texts in shown if words.occurs(term, texts)]
            # one task is the validator's warning (target-underused); the rubric asks for
            # what the brief asks for
            if 2 <= len(used) < TARGET_TASKS:
                self.find(
                    "target-thinly-practised", where,
                    f"the key word '{term}' comes up in only {len(used)} tasks "
                    f"({', '.join(used)}). Use every key word in at least {TARGET_TASKS}: the "
                    "warm-up, a gap or a label, and the writing task's must_use.",
                )
            written = [t.id for t in ws.tasks if words.occurs(term, self._written_texts(t))]
            if len(used) >= 2 and not written:
                self.find(
                    "target-never-produced", where,
                    f"the learner reads the key word '{term}' but never writes it. Make it a "
                    "gap answer, a label, or a must_use word of the writing task.",
                )

    def check_grammar(self) -> None:
        ws = self.ws
        practised = {t.grammar for t in ws.tasks if t.stage in ("form", "practice")}
        for i, gp in enumerate(ws.grammar):
            where = f"/grammar/{i}"
            if gp.id not in practised:
                self.find(
                    "grammar-unpractised", where,
                    f"no form or practice task has \"grammar\": \"{gp.id}\", so nothing "
                    f"practises '{gp.name}'. Add a form task for it (a cloze with base_form "
                    "hints, a transform or a word_building) and set its \"grammar\".",
                )
            if len(gp.examples) < GRAMMAR_EXAMPLES:
                self.find(
                    "grammar-few-examples", f"{where}/examples",
                    f"'{gp.name}' has {_plural(len(gp.examples), 'example')}; give "
                    f"{GRAMMAR_EXAMPLES} or 3 sentences that show the pattern — with words the "
                    "task beside it does not ask for.",
                )

    def check_story_link(self) -> None:
        ws, lang = self.ws, self.lang
        cast = ws.story.characters
        for i, task in enumerate(ws.tasks):
            where = f"/tasks/{i}"
            if (cast and task.stage == "practice"
                    and isinstance(task, (ClozeTask, DialogueTask))):
                texts = self.words.task_texts(task)
                if isinstance(task, DialogueTask):
                    texts = texts + [line.speaker for line in task.lines]
                text = "\n".join(texts)
                if not any(is_named(c, text, lang) for c in cast):
                    self.find(
                        "practice-leaves-story", where,
                        f"this practice task names none of the story's characters "
                        f"({', '.join(c.name for c in cast)}). Let it continue the story: the "
                        "next morning, a message, a moment the story skipped.",
                    )
            if task.stage not in ("gist", "detail"):
                continue
            quoted: list[tuple[str, str]] = []
            if isinstance(task, TrueFalseTask):
                quoted = [(f"{where}/items/{j}/statement", item.statement)
                          for j, item in enumerate(task.items) if item.answer]
            elif isinstance(task, MultipleChoiceTask):
                quoted = [(f"{where}/items/{j}/answer", item.answer)
                          for j, item in enumerate(task.items)]
            elif isinstance(task, OrderEventsTask):
                quoted = [(f"{where}/events/{j}", event)
                          for j, event in enumerate(task.events)]
            for pointer, text in quoted:
                norm = _norm_sentence(text)
                if len(norm.split()) < 4:
                    continue
                hit = next((s for s, n in self.story_sentences if _similar(norm, n)), None)
                if hit:
                    self.find(
                        "comprehension-quotes-story", pointer,
                        f"{_q(text)} is almost the story sentence {_q(hit)}: the learner can "
                        "find it without understanding it. Say the same thing in other words.",
                    )

    def check_answers(self) -> None:
        for i, task in enumerate(self.ws.tasks):
            where = f"/tasks/{i}"
            if isinstance(task, QuestionsTask) and task.stage in (
                    "gist", "detail", "picture", "form", "practice"):
                for j, item in enumerate(task.items):
                    if not item.answer:
                        self.find(
                            "answer-missing", f"{where}/items/{j}/answer",
                            f"the question {_q(item.question)} is about the story but has no "
                            "model answer. Add \"answer\": one or two sentences in the target "
                            "language for the answer key.",
                        )
            elif isinstance(task, DialogueTask):
                for j, line in enumerate(task.lines):
                    if line.text is None and not line.answer:
                        self.find(
                            "answer-missing", f"{where}/lines/{j}/answer",
                            f"the learner writes {line.speaker}'s line, but there is no model "
                            "answer. Add \"answer\": what the character could say.",
                        )

    # -- items ----------------------------------------------------------------

    def check_counts(self) -> None:
        for i, task in enumerate(self.ws.tasks):
            design = KIND_DESIGN[task.kind]
            n = design.count(task, self.ws)
            low, high = design.items
            if isinstance(task, LabelTask) and n == 0:
                continue  # the validator's error: a label task without labels
            if not low <= n <= high:
                wanted = str(low) if low == high else f"{low}–{high}"
                self.find(
                    "item-count", f"/tasks/{i}",
                    f"this {task.kind} task has {n} {design.unit}; use {wanted}. "
                    + ("Add some, or fold the task into another one."
                       if n < low else "Cut it down, or make two tasks of it."),
                )

    def check_true_false(self, i: int, task: TrueFalseTask) -> None:
        where = f"/tasks/{i}"
        n, true = len(task.items), sum(item.answer for item in task.items)
        if n >= 3 and (true in (0, n) or max(true, n - true) > TF_SHARE * n):
            self.find(
                "tf-one-sided", f"{where}/items",
                f"{true} of the {n} statements are true. Mix them: at least one of each kind, "
                "and neither more than three quarters — a pattern can be guessed.",
            )
        for j, item in enumerate(task.items):
            if (not item.answer and item.correction
                    and _norm_sentence(item.correction) == _norm_sentence(item.statement)):
                self.find(
                    "tf-correction-same", f"{where}/items/{j}/correction",
                    f"the correction of {_q(item.statement)} is the statement itself. Write "
                    "the true version.",
                )

    def check_multiple_choice(self, i: int, task: MultipleChoiceTask) -> None:
        where = f"/tasks/{i}"
        longest = 0
        judged = 0
        for j, item in enumerate(task.items):
            if len(item.options) < MC_OPTIONS:
                self.find(
                    "mc-few-options", f"{where}/items/{j}/options",
                    f"the question {_q(item.question)} has {len(item.options)} options; give "
                    f"{MC_OPTIONS}: one right, two plausible but wrong.",
                )
                continue
            wrong = max(len(o) for o in item.options if o != item.answer)
            right = len(item.answer)
            judged += 1
            if right > wrong:
                longest += 1
            if right > MC_RATIO * wrong and right - wrong >= MC_CHARS:
                self.find(
                    "mc-answer-stands-out", f"{where}/items/{j}",
                    f"the right option {_q(item.answer)} is far longer than the wrong ones "
                    f"({right} characters; the longest wrong one has {wrong}). Shorten it or "
                    "lengthen the others: all options should look alike.",
                )
        allowed = (judged + 1) // 2  # half, rounded up: see the rule
        if judged >= 3 and longest > allowed:
            self.find(
                "mc-longest-is-right", f"{where}/items",
                f"in {longest} of {judged} questions the right option is the longest one. "
                f"Rewrite options so that this holds for {allowed} at most: lengthen a wrong "
                "option here, shorten the right one there.",
            )

    def check_match(self, i: int, task: MatchTask) -> None:
        where = f"/tasks/{i}"
        if not task.extra:
            self.find(
                "match-no-spare", f"{where}/extra",
                "the matching task has no spare answer, so the last pair is free. Add one or "
                "two plausible but wrong entries to \"extra\".",
            )
        source = locale.base_lang(self.ws.source_lang)
        for j, pair in enumerate(task.pairs):
            left = _fold(strip_article(pair.left, self.lang))
            right = _fold(strip_article(strip_article(pair.right, source), self.lang))
            if left and left == right:
                self.find(
                    "match-trivial-pair", f"{where}/pairs/{j}",
                    f"'{pair.left}' is matched with '{pair.right}': the same word on both "
                    "sides. Pair it with a short explanation, or choose another word.",
                )

    def _visible(self, text: str) -> str:
        """A gap text as printed, with every gap blank. Hints are left out: a
        base form that happens to be the answer ('werden' for 'sie werden') is
        the validator's business, not a second copy of the answer."""
        try:
            parts = markup.split(text)
        except ValueError:
            return ""
        return "".join(" ___ " if isinstance(part, markup.Gap) else part for part in parts)

    def check_gap_task(self, i: int, task: ClozeTask | DialogueTask) -> None:
        where = f"/tasks/{i}"
        if isinstance(task, ClozeTask):
            texts = [(f"{where}/text" if task.text is not None else f"{where}/items/{j}", text)
                     for j, text in enumerate(_cloze_texts(task))]
            banked = task.hint == "word_bank"
            form = task.hint == "base_form"
        else:
            texts = [(f"{where}/lines/{j}/text", line.text)
                     for j, line in enumerate(task.lines) if line.text]
            banked, form = task.bank, False
        gaps = [(pointer, gap) for pointer, text in texts for gap in _gaps(text)]
        if not gaps:
            return
        if isinstance(task, ClozeTask) and self.counts_words:
            words = sum(_word_count(markup.fill(text)) for _, text in texts
                        if not markup.has_unbalanced_braces(text))
            floor = CONTEXT_WORDS_FORM if form else CONTEXT_WORDS
            if words < floor * len(gaps):
                self.find(
                    "cloze-too-dense", where,
                    f"{len(gaps)} gaps in {words} words: fewer than {floor} words per gap. "
                    "Close some gaps or write longer sentences — a gap is filled from its "
                    "context.",
                )
        if banked:
            spare = len(task.distractors)
            if not spare or spare >= len(gaps):
                self.find(
                    "bank-distractors", f"{where}/distractors",
                    f"the word box has {_plural(spare, 'spare word')} for {len(gaps)} gaps. "
                    + ("Add 2–3 distractors, so the last gap is not free by elimination."
                       if not spare else "Keep 2–3 distractors: fewer spare words than gaps."),
                )
            seen: dict[str, str] = {}
            for pointer, gap in gaps:
                key = gap.answer.casefold()
                if key in seen:
                    self.find(
                        "bank-word-twice", pointer,
                        f"'{gap.answer}' fills two gaps, but the word box shows it once. "
                        "Change one of the sentences so that each word fits exactly one gap.",
                    )
                else:
                    seen[key] = pointer
            answers = [gap.answer for _, gap in gaps]
            cases = {_first_upper(a) for a in answers}
            if len(cases) == 1:
                for k, word in enumerate(task.distractors):
                    if word and _first_upper(word) not in cases:
                        self.find(
                            "distractor-stands-out", f"{where}/distractors/{k}",
                            f"the spare word '{word}' is the only one that "
                            + ("starts with a capital" if _first_upper(word)
                               else "starts in lower case")
                            + ", so it can be ruled out at a glance. Choose a distractor of "
                            "the same word class and form as the answers.",
                        )
        visible = "\n".join(self._visible(text) for _, text in texts)
        reported: set[str] = set()
        for pointer, gap in gaps:
            answer = gap.answer
            key = answer.casefold()
            if key in reported or len(answer) < 4 or not answer.replace(" ", "").isalpha():
                continue
            if re.search(rf"(?<!\w){re.escape(answer)}(?!\w)", visible, re.IGNORECASE):
                reported.add(key)
                self.find(
                    "answer-shown-in-task", pointer,
                    f"the answer '{answer}' also stands elsewhere in this task, in plain "
                    "sight. Reword that place, or gap another word.",
                )

    def check_room(self, i: int, task: Task) -> None:
        if not self.counts_words:
            return
        where = f"/tasks/{i}"
        if isinstance(task, QuestionsTask):
            for j, item in enumerate(task.items):
                words = _word_count(item.answer or "")
                if item.lines and words > item.lines * WORDS_PER_ANSWER_LINE:
                    need = -(-words // WORDS_PER_ANSWER_LINE)  # the fewest lines that pass
                    self.find(
                        "lines-too-few", f"{where}/items/{j}/lines",
                        f"the model answer to {_q(item.question, 40)} has {words} words, but "
                        f"there {'is' if item.lines == 1 else 'are'} only "
                        f"{_plural(item.lines, 'line')} to write on. Set \"lines\": {need}, or "
                        "shorten the answer.",
                    )
        elif isinstance(task, WritingTask) and task.lines and task.max_words:
            if task.max_words > task.lines * WORDS_PER_TEXT_LINE:
                need = -(-task.max_words // WORDS_PER_TEXT_LINE)
                self.find(
                    "lines-too-few", f"{where}/lines",
                    f"up to {task.max_words} words on {_plural(task.lines, 'line')}: that "
                    f"does not fit in handwriting. Set \"lines\" to {need} or more: at most "
                    f"{WORDS_PER_TEXT_LINE} words per line (the brief suggests about 8).",
                )

    def check_writing(self, i: int, task: WritingTask) -> None:
        where = f"/tasks/{i}"
        missing = []
        if not task.starter:
            missing.append("a \"starter\" (the first words, in the target language)")
        if len(task.must_use) < MUST_USE_MIN:
            missing.append(f"{MUST_USE_MIN} or more key words in \"must_use\"")
        if not task.model_answer:
            missing.append("a \"model_answer\"")
        low, high = LEVELS[self.ws.cefr_level].writing
        if self.counts_words:
            if task.min_words is None or task.max_words is None:
                missing.append(
                    f"\"min_words\" and \"max_words\" (at {self.ws.cefr_level} about {low}–{high})")
            elif task.max_words > WRITING_HIGH * high or task.min_words < WRITING_LOW * low:
                missing.append(
                    f"a word range that fits {self.ws.cefr_level} (about {low}–{high} words, "
                    f"not {task.min_words}–{task.max_words})")
        if missing:
            self.find(
                "writing-scaffold", where,
                "the writing task needs " + "; ".join(missing) + ".",
            )
        taught = [scene.text for scene in self.scenes] + [f.text for f in self.ws.facts]
        for other in self.ws.tasks:
            if other is not task:
                taught += self.words.task_texts(other)
        for gp in self.ws.grammar:
            taught += [gp.rule or "", *gp.examples]
            if gp.table is not None:
                taught += [" ".join(row) for row in gp.table.rows]
        for k, word in enumerate(task.must_use):
            if not strip_article(word, self.lang):
                continue
            if self.ws.vocab_item(word) is None and not self.words.occurs(word, taught):
                self.find(
                    "must-use-unseen", f"{where}/must_use/{k}",
                    f"the learner must use '{word}', but the sheet never shows it: not in "
                    "the story, a fact, the word list, a grammar box or another task. Ask for "
                    "a word the sheet teaches, or add it to vocabulary.items.",
                )

    def check_small_kinds(self, i: int, task: Task) -> None:
        where = f"/tasks/{i}"
        if isinstance(task, TransformTask):
            for j, item in enumerate(task.items):
                if _norm_sentence(item.prompt) == _norm_sentence(item.answer):
                    self.find(
                        "transform-no-change", f"{where}/items/{j}",
                        f"the answer to {_q(item.prompt)} is the prompt itself. Give the "
                        "transformed sentence, or a cue that changes something.",
                    )
        elif isinstance(task, WordBuildingTask):
            for j, built in enumerate(task.items):
                answer = _fold(built.answer)
                at = 0
                for part in built.parts:
                    stem = re.sub(r"[^\w]", "", _fold(strip_article(part, self.lang)))[:4]
                    stem = stem[: max(2, len(stem) - 1)] if len(stem) > 3 else stem
                    found = answer.find(stem, at) if stem else at
                    if found < 0:
                        self.find(
                            "word-building-unrelated", f"{where}/items/{j}",
                            f"the answer '{built.answer}' does not contain the part "
                            f"'{part}'. The learner builds the word from the parts given, in "
                            "their order.",
                        )
                        break
                    at = found + 1
        elif isinstance(task, MediaSearchTask):
            links = [q for q in task.queries if _URL_RE.search(q)]
            if links:
                self.find(
                    "media-search-thin", f"{where}/queries",
                    f"{_q(links[0])} is a link, not a search term. Give words to search for "
                    "in the target language: links stop working.",
                )
            if len(task.questions) < 2:
                self.find(
                    "media-search-thin", f"{where}/questions",
                    "a media search needs at least two questions: what should the learner "
                    "find out or note down?",
                )

    def check_pictures(self) -> None:
        for i, scene in enumerate(self.scenes):
            labels = scene.picture.labels if scene.picture else []
            placed = [lb for lb in labels if lb.x is not None and lb.y is not None]
            for a in range(len(placed)):
                for b in range(a + 1, len(placed)):
                    one, two = placed[a], placed[b]
                    dx, dy = (one.x or 0) - (two.x or 0), (one.y or 0) - (two.y or 0)
                    if (dx * dx + dy * dy) ** 0.5 < MARKER_DISTANCE:
                        self.find(
                            "label-crowded", f"/story/scenes/{i}/picture/labels",
                            f"the markers {one.n} ('{one.term}') and {two.n} ('{two.term}') "
                            "sit on top of each other. Move one, or label objects that are "
                            "apart.",
                        )

    def check_titles(self) -> None:
        seen: dict[str, int] = {}
        for i, task in enumerate(self.ws.tasks):
            where = f"/tasks/{i}/title"
            title = (task.title or "").strip()
            if not title:
                self.find(
                    "title-generic", where,
                    f"this {task.kind} task has no title. Give it one that belongs to the "
                    "story, in the learner's language.",
                )
            elif _GENERIC_TITLE_RE.match(title):
                self.find(
                    "title-generic", where,
                    f"the title '{title}' says nothing. Name the moment of the story the "
                    "task is about, like 'Thursday: a second chance'.",
                )
            elif title.casefold() in seen:
                self.find(
                    "title-generic", where,
                    f"the title '{title}' is already the title of task "
                    f"{seen[title.casefold()] + 1}. Every task has its own.",
                )
            else:
                seen[title.casefold()] = i

    def run(self) -> list[Finding]:
        self.check_beats()
        self.check_cast()
        self.check_prose()
        self.check_translations()
        self.check_facts()
        self.check_arc()
        self.check_target_words()
        self.check_grammar()
        self.check_story_link()
        self.check_answers()
        self.check_counts()
        for i, task in enumerate(self.ws.tasks):
            if isinstance(task, TrueFalseTask):
                self.check_true_false(i, task)
            elif isinstance(task, MultipleChoiceTask):
                self.check_multiple_choice(i, task)
            elif isinstance(task, MatchTask):
                self.check_match(i, task)
            elif isinstance(task, (ClozeTask, DialogueTask)):
                self.check_gap_task(i, task)
            if isinstance(task, WritingTask):
                self.check_writing(i, task)
            self.check_room(i, task)
            self.check_small_kinds(i, task)
        self.check_pictures()
        self.check_titles()
        return self.findings


# ---------------------------------------------------------------------------
# Measures
# ---------------------------------------------------------------------------


def measure(ws: Worksheet) -> dict[str, Any]:
    """Deterministic measures of a worksheet, for comparing one sheet (or one
    version of the brief) with another. Nothing here is judged."""
    scenes = ws.story.scenes
    story = "\n".join(s.text for s in scenes)
    sentences = [n for s in scenes for n in map(_word_count, _sentences(s.text)) if n]
    words = sum(_word_count(s.text) for s in scenes)
    kinds = Counter(t.kind for t in ws.tasks)
    responses = Counter(KIND_DESIGN[t.kind].response for t in ws.tasks)
    items = sum(KIND_DESIGN[t.kind].count(t, ws) for t in ws.tasks)
    return {
        "level": ws.cefr_level,
        "scenes": len(scenes),
        "story_words": words,
        "sentences": len(sentences),
        "words_per_sentence": round(sum(sentences) / len(sentences), 1) if sentences else 0.0,
        "longest_sentence": max(sentences, default=0),
        "speech_share": round(speech_share(story), 2),
        "scenes_with_speech": sum(has_direct_speech(s.text) for s in scenes),
        "facts": len(ws.facts),
        "target_words": len(ws.vocabulary.target),
        "tasks": len(ws.tasks),
        "task_kinds": len(kinds),
        "items": items,
        "closed_tasks": responses["closed"],
        "guided_tasks": responses["guided"],
        "open_tasks": responses["open"],
    }


def assess(ws: Worksheet) -> QualityReport:
    """Hold a (schema-valid) worksheet to the design rubric."""
    return QualityReport(findings=_Rubric(ws).run(), metrics=measure(ws))
