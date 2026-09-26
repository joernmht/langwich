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

_ARTICLES = (
    "der ", "die ", "das ", "den ", "dem ", "des ", "ein ", "eine ",
    "le ", "la ", "les ", "l'", "l’", "un ", "une ", "des ",
    "el ", "los ", "las ", "una ", "unos ", "unas ",
    "il ", "lo ", "gli ", "i ", "uno ",
    "o ", "a ", "os ", "as ", "um ", "uma ",
    "the ", "an ", "de ", "het ", "een ",
    "to ",
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


def strip_article(term: str) -> str:
    low = term.lower()
    for art in _ARTICLES:
        if low.startswith(art) and len(term) > len(art):
            return term[len(art):].strip()
    return term.strip()


def _norm(s: str) -> str:
    return strip_article(s).casefold()


def term_pattern(item: VocabItem) -> re.Pattern[str]:
    """Regex that finds an occurrence of a vocabulary item in running text."""
    alts: list[str] = []
    stem = strip_article(item.term)
    # The base form may be inflected in the text ('trocknen' -> 'trocknet'),
    # so long stems match by prefix; plurals and listed forms are already
    # surface forms and only get a short ending ('Tassen', not 'Tassenhalter').
    if " " in stem:
        alts.append(re.escape(stem))
    elif len(stem) >= 6:
        alts.append(re.escape(stem[: len(stem) - 2]) + r"\w{0,4}")
    else:
        alts.append(re.escape(stem) + r"\w{0,2}")
    forms: list[str] = []
    if item.plural:
        forms.append(strip_article(item.plural))
    if item.forms:
        forms.extend(f.strip() for f in re.split(r"[,;/]", item.forms) if f.strip())
    for w in forms:
        w = re.sub(r"^(ist|hat|a|est|ha|è|é)\s+", "", w)  # 'ist gewachsen' -> 'gewachsen'
        alts.append(re.escape(w) + (r"\w{0,2}" if " " not in w else ""))
    return re.compile(r"(?<!\w)(?:" + "|".join(alts) + r")(?!\w)", re.IGNORECASE)


def tested_terms(ws: Worksheet) -> set[str]:
    """Normalised words that some task asks the learner to produce or match.
    These are never glossed next to the story (the gloss would be the answer)."""
    out: set[str] = {_norm(t) for t in ws.vocabulary.target}
    for task in ws.tasks:
        if isinstance(task, MatchTask):
            out.update(_norm(p.left) for p in task.pairs)
            out.update(_norm(p.right) for p in task.pairs)
        elif isinstance(task, LabelTask):
            scene = ws.scene(task.scene)
            if scene and scene.picture:
                out.update(_norm(lb.term) for lb in scene.picture.labels)
        elif isinstance(task, WordBuildingTask):
            out.update(_norm(i.answer) for i in task.items)
        elif isinstance(task, ClozeTask):
            texts = [task.text] if task.text is not None else list(task.items or [])
            for text in texts:
                out.update(_norm(g.answer) for g in markup.gaps(text))
        elif isinstance(task, DialogueTask):
            for line in task.lines:
                if line.text:
                    out.update(_norm(g.answer) for g in markup.gaps(line.text))
    return out


def _is_tested(item: VocabItem, tested: set[str]) -> bool:
    stem = _norm(item.term)
    if stem in tested:
        return True
    # an inflected answer ('geröstet', 'beliebte') still counts as the item
    pat = term_pattern(item)
    return any(pat.fullmatch(t) for t in tested)


def _glosses(ws: Worksheet, tested: set[str]) -> dict[str, list[Gloss]]:
    per_scene: dict[str, list[Gloss]] = {s.id: [] for s in ws.story.scenes}
    used: set[str] = set()
    candidates = [v for v in ws.vocabulary.items if not _is_tested(v, tested)]
    for scene in ws.story.scenes:
        found: list[tuple[int, Gloss]] = []
        for item in candidates:
            key = item.term.casefold()
            if key in used:
                continue
            m = term_pattern(item).search(scene.text)
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
        pt.option_orders = [
            _shuffle_not_identity(item.options, _rng(seed, task.id, "options", str(i)))
            for i, item in enumerate(task.items)
        ]
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
