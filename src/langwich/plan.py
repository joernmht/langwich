"""Turn a worksheet into the lesson arc.

The order is fixed by pedagogy, not by the order tasks appear in the JSON:

1. **Before you read** — every ``warm_up`` task (pre-teach the key words,
   make a prediction).
2. **The story, scene by scene** — each scene is followed by the tasks
   anchored to it (the *last* scene a task references), sorted by stage:
   ``gist`` → ``detail`` → ``form`` → ``practice`` → ``picture``. Tasks
   without a scene are whole-story tasks and follow the last scene.
3. **Your turn** — every ``production`` task, always after the story.
4. **Take it further** — ``epilogue`` tasks (e.g. in-story homework).

The planner also makes every random choice (column order, option order,
word banks) from a seed, so the task page and the answer key agree and the
same input always produces the same worksheet.
"""

from __future__ import annotations

import hashlib
import random
import re
from dataclasses import dataclass, field
from typing import Literal

from langwich import markup
from langwich.model import (
    STAGES,
    ClozeTask,
    DialogueTask,
    Fact,
    GrammarPoint,
    LabelTask,
    MatchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    Scene,
    Task,
    VocabItem,
    WordBuildingTask,
    Worksheet,
)

Phase = Literal["before", "story", "your_turn", "further"]

_STAGE_RANK = {s: i for i, s in enumerate(STAGES)}

#: Articles (and the English infinitive marker) stripped before matching a
#: vocabulary term against running text, per target language.
ARTICLES: dict[str, tuple[str, ...]] = {
    "de": ("der ", "die ", "das ", "den ", "dem ", "des ", "ein ", "eine ", "einen "),
    "fr": ("le/la ", "le ", "la ", "les ", "l'", "l’", "un ", "une ", "des ", "du "),
    "es": ("el/la ", "el ", "la ", "los ", "las ", "un ", "una ", "unos ", "unas "),
    "it": ("il ", "lo ", "la ", "l'", "l’", "i ", "gli ", "le ", "un ", "uno ", "una ", "un'"),
    "pt": ("o ", "a ", "os ", "as ", "um ", "uma ", "uns ", "umas "),
    "en": ("the ", "a ", "an ", "to "),
    "nl": ("de ", "het ", "een "),
}
# Without a known language only unambiguous articles are stripped ('de',
# 'a', 'o', 'i' are also prepositions or words in other languages).
_SAFE_ARTICLES: tuple[str, ...] = tuple(dict.fromkeys(
    a for arts in ARTICLES.values() for a in arts if a not in ("de ", "a ", "o ", "i ", "as ")
))

_REFLEXIVE_PREFIXES = ("s'", "s’", "se ", "sich ")

#: Infinitive endings stripped to get a verb stem that also finds
#: conjugated forms ('trocknen' -> 'trockn' finds 'trocknet').
_VERB_ENDINGS: dict[str, tuple[str, ...]] = {
    "de": ("en", "n"),
    "fr": ("oir", "er", "ir", "re"),
    "es": ("arse", "erse", "irse", "ar", "er", "ir"),
    "pt": ("ar", "er", "ir"),
    "it": ("are", "ere", "ire", "rre"),
}

_PRONOUNS_AND_AUXILIARIES = re.compile(
    r"^(?:(?:ich|du|er|sie|es|wir|ihr|je|j'|j’|tu|il|elle|on|nous|vous|ils|elles|"
    r"yo|tú|él|ella|usted|nosotros|vosotros|ellos|ellas|io|lui|lei|noi|voi|loro|"
    r"eu|ele|ela|nós|eles|elas)\s+)?"
    r"(?:(?:ist|hat|sind|haben|bin|habe|a|ai|as|ont|est|sont|suis|avons|avez|"
    r"ha|he|has|han|hemos|habéis|è|sono|ho|hanno|abbiamo|tem|têm|foi)\s+)?",
    re.IGNORECASE,
)

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

MAX_GLOSSES_PER_SCENE = 12


@dataclass
class Gloss:
    item: VocabItem
    match: str | None  # surface form in the scene text (to underline), if found


@dataclass
class Sidebar:
    grammar: GrammarPoint | None = None
    fact: Fact | None = None


@dataclass
class PlannedTask:
    number: int
    task: Task
    phase: Phase
    anchor: str | None
    #: match — display order of the right column, as indices into
    #: ``[p.right for p in pairs] + extra``.
    right_order: list[int] | None = None
    #: multiple_choice — display order of each item's options.
    option_orders: list[list[str]] | None = None
    #: order_events — events in display (shuffled) order.
    events: list[str] | None = None
    #: word bank for cloze (hint=word_bank), label (bank=True), dialogue (bank=True).
    bank: list[str] | None = None
    sidebars: list[Sidebar] = field(default_factory=list)

    @property
    def right_column(self) -> list[str]:
        assert isinstance(self.task, MatchTask) and self.right_order is not None
        values = [p.right for p in self.task.pairs] + list(self.task.extra)
        return [values[i] for i in self.right_order]

    def letter_for_pair(self, pair_index: int) -> str:
        """Letter shown next to the right-hand partner of ``pairs[pair_index]``."""
        assert self.right_order is not None
        return LETTERS[self.right_order.index(pair_index)]

    def event_number(self, event: str) -> int:
        """Correct position (1-based) of a displayed event."""
        assert isinstance(self.task, OrderEventsTask)
        return self.task.events.index(event) + 1


@dataclass
class SceneBlock:
    number: int
    scene: Scene
    glosses: list[Gloss]
    sidebars: list[Sidebar]
    tasks: list[PlannedTask]


@dataclass
class Plan:
    worksheet: Worksheet
    seed: int
    before: list[PlannedTask]
    scenes: list[SceneBlock]
    your_turn: list[PlannedTask]
    further: list[PlannedTask]
    loose_facts: list[Fact]
    reference_grammar: list[GrammarPoint]

    @property
    def tasks(self) -> list[PlannedTask]:
        out = list(self.before)
        for block in self.scenes:
            out.extend(block.tasks)
        return out + self.your_turn + self.further


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def default_seed(ws: Worksheet) -> int:
    digest = hashlib.sha256(ws.model_dump_json(by_alias=True).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _rng(seed: int, *parts: str) -> random.Random:
    return random.Random(":".join([str(seed), *parts]))


def _shuffle_not_identity(values: list, rng: random.Random) -> list:
    out = list(values)
    rng.shuffle(out)
    if len(out) > 2 and out == list(values):
        out = out[1:] + out[:1]
    return out


def strip_article(term: str, lang: str | None = None) -> str:
    """The term without a leading article (language-aware when ``lang`` is given)."""
    low = term.lower()
    articles = ARTICLES.get((lang or "").split("-")[0].lower(), _SAFE_ARTICLES)
    for art in articles:
        if low.startswith(art) and len(term) > len(art):
            return term[len(art):].strip()
    return term.strip()


def _norm(s: str, lang: str | None = None) -> str:
    return strip_article(s, lang).casefold()


_ACCENT_CLASSES = {
    "e": "[eéèêë]", "a": "[aàâáã]", "i": "[iîïí]", "o": "[oôóõ]", "u": "[uùûúü]",
}


def _flex(stem: str, lang: str) -> str:
    """Escaped stem; in Romance languages vowels also match their accented
    variants, because inflection moves accents (complet -> complète)."""
    if lang not in ("fr", "es", "it", "pt"):
        return re.escape(stem)
    return "".join(_ACCENT_CLASSES.get(ch.lower(), re.escape(ch)) for ch in stem)


def _stem_alternative(stem: str, pos: str, lang: str) -> list[str]:
    """Regex alternatives for the base form of a vocabulary item."""
    if " " in stem or pos not in ("noun", "verb", "adjective"):
        return [re.escape(stem)]  # phrases and function words: exact
    if pos == "noun":
        # nouns gain endings (Tassen, Bohnen, tomates) but never lose letters
        return [re.escape(stem) + r"\w{0,3}"]
    if pos == "adjective":
        base = stem[:-1] if lang in ("fr", "es", "it", "pt") and stem[-1:] in "aeo" else stem
        return [_flex(base, lang) + r"\w{0,3}"] if len(base) >= 3 else [re.escape(stem)]
    # verbs
    for prefix in _REFLEXIVE_PREFIXES:
        if stem.lower().startswith(prefix):
            stem = stem[len(prefix):]
            break
    endings = _VERB_ENDINGS.get(lang)
    if endings is None:  # unknown language: a conservative prefix match
        return [re.escape(stem[:-1]) + r"\w{0,4}"] if len(stem) >= 6 else [re.escape(stem)]
    base = stem
    for ending in endings:
        if stem.lower().endswith(ending) and len(stem) - len(ending) >= 3:
            base = stem[: len(stem) - len(ending)]
            break
    if base == stem:
        return [re.escape(stem)]
    alts = [_flex(base, lang) + r"\w{0,5}"]
    if lang == "de":
        alts.append("ge" + re.escape(base) + r"\w{0,3}")  # rösten -> geröstet
    return alts


def term_pattern(item: VocabItem, lang: str | None = None) -> re.Pattern[str]:
    """Regex that finds an occurrence of a vocabulary item in running text.

    Nouns match with short endings, verbs by stem (plus regular German
    participles), adjectives with agreement endings, everything else
    exactly. Plurals and listed irregular forms are matched as written.
    """
    code = (lang or "").split("-")[0].lower()
    stem = strip_article(item.term, lang)
    alts = _stem_alternative(stem, item.pos, code)
    forms: list[str] = []
    if item.plural:
        forms.append(strip_article(item.plural, lang))
    if item.forms:
        forms.extend(f.strip() for f in re.split(r"[,;/]", item.forms) if f.strip())
    for w in forms:
        w = _PRONOUNS_AND_AUXILIARIES.sub("", w).strip()  # 'il a disparu' -> 'disparu'
        if not w:
            continue
        if " " in w or len(w) < 3:
            alts.append(re.escape(w))  # 'ri' must not find 'rien'
        else:
            alts.append(re.escape(w) + r"\w{0,2}")
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.IGNORECASE)


def tested_terms(ws: Worksheet) -> set[str]:
    """Normalised words that some task asks the learner to produce or match.
    These are never glossed next to the story (the gloss would be the answer)."""
    lang = ws.target_lang
    out: set[str] = {_norm(t, lang) for t in ws.vocabulary.target}
    for task in ws.tasks:
        if isinstance(task, MatchTask):
            out.update(_norm(p.left, lang) for p in task.pairs)
            out.update(_norm(p.right, lang) for p in task.pairs)
        elif isinstance(task, LabelTask):
            scene = ws.scene(task.scene)
            if scene and scene.picture:
                out.update(_norm(lb.term, lang) for lb in scene.picture.labels)
        elif isinstance(task, WordBuildingTask):
            out.update(_norm(i.answer, lang) for i in task.items)
        elif isinstance(task, ClozeTask):
            texts = [task.text] if task.text is not None else list(task.items or [])
            for text in texts:
                out.update(_norm(g.answer, lang) for g in markup.gaps(text))
        elif isinstance(task, DialogueTask):
            for line in task.lines:
                if line.text:
                    out.update(_norm(g.answer, lang) for g in markup.gaps(line.text))
    return out


def _is_tested(item: VocabItem, tested: set[str], lang: str) -> bool:
    stem = _norm(item.term, lang)
    if stem in tested:
        return True
    # an inflected answer ('geröstet', 'beliebte') still counts as the item
    pat = term_pattern(item, lang)
    return any(pat.fullmatch(t) for t in tested)


def _glosses(ws: Worksheet, tested: set[str]) -> dict[str, list[Gloss]]:
    per_scene: dict[str, list[Gloss]] = {s.id: [] for s in ws.story.scenes}
    used: set[str] = set()
    lang = ws.target_lang
    candidates = [v for v in ws.vocabulary.items if not _is_tested(v, tested, lang)]
    for scene in ws.story.scenes:
        found: list[tuple[int, Gloss]] = []
        for item in candidates:
            key = item.term.casefold()
            if key in used:
                continue
            m = term_pattern(item, lang).search(scene.text)
            if m:
                found.append((m.start(), Gloss(item, m.group(0))))
            elif item.scene == scene.id:
                found.append((len(scene.text), Gloss(item, None)))
        found.sort(key=lambda x: x[0])
        for _, g in found[:MAX_GLOSSES_PER_SCENE]:
            per_scene[scene.id].append(g)
            used.add(g.item.term.casefold())
    return per_scene


def _gaps_of(task: Task) -> list[markup.Gap]:
    if isinstance(task, ClozeTask):
        texts = [task.text] if task.text is not None else list(task.items or [])
        return [g for text in texts for g in markup.gaps(text)]
    if isinstance(task, DialogueTask):
        return [g for line in task.lines if line.text for g in markup.gaps(line.text)]
    return []


def _dedupe(words: list[str]) -> list[str]:
    seen: set[str] = set()
    out = []
    for w in words:
        if w.casefold() not in seen:
            seen.add(w.casefold())
            out.append(w)
    return out


def _prepare(pt: PlannedTask, ws: Worksheet, seed: int) -> None:
    task = pt.task
    if isinstance(task, MatchTask):
        n = len(task.pairs) + len(task.extra)
        pt.right_order = _shuffle_not_identity(list(range(n)), _rng(seed, task.id, "right"))
    elif isinstance(task, MultipleChoiceTask):
        # Shuffle each item's options, but never let the right answer sit in
        # the same position three times in a row (a pattern learners spot).
        orders: list[list[str]] = []
        positions: list[int] = []
        for i, item in enumerate(task.items):
            rng = _rng(seed, task.id, "options", str(i))
            order = _shuffle_not_identity(item.options, rng)
            for _ in range(12):
                pos = order.index(item.answer)
                if len(positions) >= 2 and positions[-1] == positions[-2] == pos:
                    order = _shuffle_not_identity(item.options, rng)
                    continue
                break
            positions.append(order.index(item.answer))
            orders.append(order)
        pt.option_orders = orders
    elif isinstance(task, OrderEventsTask):
        pt.events = _shuffle_not_identity(task.events, _rng(seed, task.id, "events"))
    elif isinstance(task, ClozeTask) and task.hint == "word_bank":
        words = _dedupe([g.answer for g in _gaps_of(task)] + list(task.distractors))
        _rng(seed, task.id, "bank").shuffle(words)
        pt.bank = words
    elif isinstance(task, DialogueTask) and task.bank:
        words = _dedupe([g.answer for g in _gaps_of(task)])
        _rng(seed, task.id, "bank").shuffle(words)
        pt.bank = words
    elif isinstance(task, LabelTask) and task.bank:
        scene = ws.scene(task.scene)
        if scene and scene.picture and scene.picture.labels:
            words = _dedupe([lb.term for lb in scene.picture.labels])
            _rng(seed, task.id, "bank").shuffle(words)
            pt.bank = words


def _phase(task: Task) -> Phase:
    if task.stage == "warm_up":
        return "before"
    if task.stage == "production":
        return "your_turn"
    if task.stage == "epilogue":
        return "further"
    return "story"


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


def plan(ws: Worksheet, seed: int | None = None) -> Plan:
    seed = default_seed(ws) if seed is None else seed
    scene_order = {s.id: i for i, s in enumerate(ws.story.scenes)}
    last_scene = ws.story.scenes[-1].id

    before: list[tuple[int, Task]] = []
    your_turn: list[tuple[int, Task]] = []
    further: list[tuple[int, Task]] = []
    by_scene: dict[str, list[tuple[int, Task]]] = {s.id: [] for s in ws.story.scenes}

    for idx, task in enumerate(ws.tasks):
        phase = _phase(task)
        if phase == "before":
            before.append((idx, task))
        elif phase == "your_turn":
            your_turn.append((idx, task))
        elif phase == "further":
            further.append((idx, task))
        else:
            known = [s for s in task.scene_ids if s in scene_order]
            anchor = max(known, key=scene_order.__getitem__) if known else last_scene
            by_scene[anchor].append((idx, task))

    number = 0

    def make(entries: list[tuple[int, Task]], phase: Phase, anchor: str | None) -> list[PlannedTask]:
        nonlocal number
        out = []
        for _, task in entries:
            number += 1
            pt = PlannedTask(number=number, task=task, phase=phase, anchor=anchor)
            _prepare(pt, ws, seed)
            out.append(pt)
        return out

    planned_before = make(before, "before", None)
    blocks: list[SceneBlock] = []
    tested = tested_terms(ws)
    glosses = _glosses(ws, tested)
    for i, scene in enumerate(ws.story.scenes):
        entries = sorted(by_scene[scene.id], key=lambda e: (_STAGE_RANK[e[1].stage], e[0]))
        blocks.append(SceneBlock(
            number=i + 1, scene=scene, glosses=glosses[scene.id], sidebars=[],
            tasks=make(entries, "story", scene.id),
        ))
    planned_turn = make(your_turn, "your_turn", None)
    planned_further = make(further, "further", None)

    all_tasks = planned_before + [t for b in blocks for t in b.tasks] + planned_turn + planned_further
    block_by_id = {b.scene.id: b for b in blocks}

    # Grammar: beside the first task that references it; else beside the
    # first form/practice task of its scene; else beside its scene; else
    # in the back matter.
    reference_grammar: list[GrammarPoint] = []
    for gp in ws.grammar:
        target = next((pt for pt in all_tasks if pt.task.grammar == gp.id), None)
        if target is None and gp.scene in block_by_id:
            block = block_by_id[gp.scene]
            target = next((pt for pt in block.tasks if pt.task.stage in ("form", "practice")), None)
            if target is None:
                block.sidebars.append(Sidebar(grammar=gp))
                continue
        if target is None:
            reference_grammar.append(gp)
        else:
            target.sidebars.append(Sidebar(grammar=gp))

    loose_facts: list[Fact] = []
    for fact in ws.facts:
        if fact.scene in block_by_id:
            block_by_id[fact.scene].sidebars.append(Sidebar(fact=fact))
        else:
            loose_facts.append(fact)

    return Plan(
        worksheet=ws, seed=seed, before=planned_before, scenes=blocks,
        your_turn=planned_turn, further=planned_further,
        loose_facts=loose_facts, reference_grammar=reference_grammar,
    )
