"""The design rubric (langwich.quality): deterministic tests of story craft and
exercise design.

Four groups:

1. **The catalogue** — every rule says what good looks like and why; every
   task kind has a ``KindDesign``. A new kind of task fails here until it
   declares how its items are counted, how many it should have and how the
   learner checks the answer, and until a real task of that kind exists to
   hold the declaration against.
2. **One broken worksheet per rule** — the brief's own example
   (``prompt.MINI_EXAMPLE``) has no findings; each mutation breaks one thing,
   and exactly that rule must report it. A rule without a mutation fails the
   suite, so no rule goes untested.
3. **The corpus** — every bundled example is held to the rubric. ``ACCEPTED``
   lists the findings that are known and tolerated, each with a reason; the
   test fails on any finding that is not listed *and* on any listed finding
   that no longer occurs. The list can only shrink: that is the ratchet.
4. **Determinism** — the same worksheet gives the same report: twice in a
   row, with the JSON keys in another order, and in fresh interpreters with
   different hash seeds. The module imports nothing that could make it
   otherwise (no random, no clock, no files, no network).

To hold a new worksheet to the rubric: ``langwich validate FILE --quality``.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from langwich import answers, quality
from langwich.cli import main
from langwich.model import STAGES, TASK_KINDS, Worksheet, load_worksheet, worksheet_from_dict
from langwich.plan import plan
from langwich.prompt import LEVELS, MINI_EXAMPLE, repair_prompt
from langwich.quality import (
    DIMENSIONS,
    KIND_DESIGN,
    RULES,
    SENTENCE_WORDS,
    assess,
    has_direct_speech,
    is_named,
    measure,
    name_keys,
    speech_share,
)
from langwich.validate import CHECKS, Report, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = sorted((REPO_ROOT / "examples").glob("*.json"))
KINDS_FIXTURE = REPO_ROOT / "tests" / "fixtures" / "kinds_showcase.json"

#: Findings in the bundled examples that are known and tolerated:
#: example stem -> {(code, JSON pointer, message): why it is accepted}. The
#: message is part of the key because several findings can share a pointer
#: (two long sentences in one scene): an entry covers exactly one finding, so
#: a second one at the same place is still reported. Keep it empty if you can;
#: an entry that no longer occurs must be removed (the test says so), which is
#: what makes this a ratchet.
ACCEPTED: dict[str, dict[tuple[str, str, str], str]] = {}

Mutation = Callable[[dict[str, Any]], None]


def _codes(data: dict[str, Any]) -> set[str]:
    return {f.code for f in assess(worksheet_from_dict(data)).findings}


def _mini() -> dict[str, Any]:
    return copy.deepcopy(MINI_EXAMPLE)


def _task(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    return next(t for t in data["tasks"] if t["id"] == task_id)


def _scene(data: dict[str, Any], index: int) -> dict[str, Any]:
    return data["story"]["scenes"][index]


# ---------------------------------------------------------------------------
# 1. The catalogue
# ---------------------------------------------------------------------------


def test_every_rule_says_what_and_why() -> None:
    assert RULES
    for code, rule in RULES.items():
        assert code == code.lower() and " " not in code, code
        assert rule.dimension in DIMENSIONS, code
        assert len(rule.title) > 15 and len(rule.why) > 15, code
        assert not rule.title.endswith("."), code


def test_rule_codes_do_not_collide_with_the_validator() -> None:
    # findings and validator warnings share one repair prompt: a code means one thing
    assert not set(RULES) & set(CHECKS)


def test_every_dimension_has_rules() -> None:
    for dimension in DIMENSIONS:
        assert sum(r.dimension == dimension for r in RULES.values()) >= 10, dimension


def test_every_task_kind_has_a_design() -> None:
    assert set(KIND_DESIGN) == set(TASK_KINDS)
    for kind, design in KIND_DESIGN.items():
        low, high = design.items
        assert 1 <= low <= high, kind
        assert design.response in ("closed", "guided", "open"), kind
        assert design.unit, kind


def _specimens() -> list[tuple[Worksheet, Any]]:
    """Every task of the bundled examples, the brief's example and the
    all-kinds render fixture, with its planned form."""
    sheets = [load_worksheet(p) for p in [*EXAMPLES, KINDS_FIXTURE]]
    sheets.append(worksheet_from_dict(MINI_EXAMPLE))
    return [(ws, pt) for ws in sheets for pt in plan(ws).tasks]


def test_every_kind_design_is_held_against_a_real_task() -> None:
    """A design is a claim about real tasks: for every kind there is a task
    whose item count is in the declared range, and the declared response
    agrees with the answer key langwich prints."""
    in_range: set[str] = set()
    for ws, pt in _specimens():
        task = pt.task
        design = KIND_DESIGN[task.kind]
        n = design.count(task, ws)
        assert isinstance(n, int) and n >= 0
        if design.items[0] <= n <= design.items[1]:
            in_range.add(task.kind)
        key = answers.answer_key(pt, ws)
        if task.kind == "label":
            scene = ws.scene(task.scene)
            if not (scene and scene.picture and scene.picture.has_visual):
                continue  # printed as "draw and label": the learner's own drawing
        if design.response == "closed":
            assert key, f"a closed {task.kind} task ({task.id}) has no answer key"
        if design.response == "open":
            assert not key, f"an open {task.kind} task ({task.id}) has an answer key"
    assert in_range == set(TASK_KINDS), sorted(set(TASK_KINDS) - in_range)


def test_the_level_limits_are_the_briefs() -> None:
    # A1 "4–8 words", A2 "5–12 words", B1 "up to ~15 words": the rubric's limits
    # are the upper ends of the brief's level table
    assert set(SENTENCE_WORDS) == set(LEVELS)
    for level in ("A1", "A2", "B1"):
        assert str(SENTENCE_WORDS[level]) in LEVELS[level].sentences, level
    limits = [SENTENCE_WORDS[level] for level in LEVELS]
    assert limits == sorted(limits)


def test_the_briefs_own_example_meets_the_rubric() -> None:
    """The example every LLM is shown must itself be a well-made sheet."""
    report = assess(worksheet_from_dict(MINI_EXAMPLE))
    assert report.findings == []
    assert report.ok
    assert report.summary().startswith("Design rubric: no findings")


# ---------------------------------------------------------------------------
# 2. One broken worksheet per rule
# ---------------------------------------------------------------------------


def _third_scene(d: dict[str, Any]) -> None:
    scenes = d["story"]["scenes"]
    scenes.append({**copy.deepcopy(scenes[1]), "id": "s3", "beat": "resolution"})
    scenes[1]["beat"] = "development"
    scenes[2].pop("picture", None)


def _swap_beats(d: dict[str, Any]) -> None:
    _scene(d, 0)["beat"], _scene(d, 1)["beat"] = "resolution", "setup"


def _hide_protagonist(d: dict[str, Any]) -> None:
    scene = _scene(d, 1)
    scene["text"] = scene["text"].replace("Mias", "Ihre").replace("Mia", "sie")


def _no_speech(d: dict[str, Any]) -> None:
    for scene in d["story"]["scenes"]:
        scene["text"] = scene["text"].replace("„", "").replace("“", "")


def _long_sentence(d: dict[str, Any]) -> None:
    _scene(d, 0)["text"] += (
        " Mia zieht ihre Stiefel an und nimmt ihren Rucksack und geht mit Jan und den "
        "anderen Gästen langsam über den nassen Sand, weil das Wasser um ein Uhr wieder "
        "zurückkommt."
    )


def _no_language_work(d: dict[str, Any]) -> None:
    d["tasks"] = [t for t in d["tasks"] if t["stage"] not in ("form", "practice")]


def _too_many_of_one_kind(d: dict[str, Any]) -> None:
    for n in range(4):
        d["tasks"].append({**copy.deepcopy(_task(d, "t2")), "id": f"x{n}", "title": f"Again {n}"})


def _other_warm_up_words(d: dict[str, Any]) -> None:
    _task(d, "t1")["pairs"] = [
        {"left": "staunen", "right": "to be amazed"},
        {"left": "der Stiefel", "right": "boot"},
        {"left": "der Schlick", "right": "mud"},
        {"left": "die Sandbank", "right": "sandbank"},
    ]


def _ebbe_in_two_tasks(d: dict[str, Any]) -> None:
    writing = _task(d, "t7")
    writing["must_use"].remove("die Ebbe")
    writing["model_answer"] = writing["model_answer"].replace(
        "Am Morgen war Ebbe, und wir", "Am Morgen war kein Wasser da, und wir")
    assert "Ebbe" not in writing["model_answer"]


def _watt_never_written(d: dict[str, Any]) -> None:
    cloze = _task(d, "t5")
    cloze["text"] = cloze["text"].replace("{{Watt}}", "Watt")
    _task(d, "t7")["must_use"].remove("das Watt")


def _practice_without_names(d: dict[str, Any]) -> None:
    cloze = _task(d, "t5")
    cloze["text"] = cloze["text"].replace("Mia", "die Frau")


def _quote_the_story(d: dict[str, Any]) -> None:
    _task(d, "t2")["items"][2]["statement"] = "Heute will sie zu Fuß zur Insel Neuwerk gehen."


def _question_without_answer(d: dict[str, Any]) -> None:
    d["tasks"].append({
        "id": "t8", "kind": "questions", "stage": "detail", "scene": "s1",
        "title": "Why the hurry?",
        "items": [{"question": "Warum müssen sie vor ein Uhr auf der Insel sein?"}],
    })


def _all_true(d: dict[str, Any]) -> None:
    for item in _task(d, "t2")["items"]:
        item["answer"] = True
        item.pop("correction", None)


def _same_correction(d: dict[str, Any]) -> None:
    item = _task(d, "t2")["items"][0]
    item["correction"] = item["statement"]


def _two_options(d: dict[str, Any]) -> None:
    item = _task(d, "t3")["items"][0]
    item["options"] = item["options"][:2]


def _long_right_option(d: dict[str, Any]) -> None:
    item = _task(d, "t3")["items"][1]
    item["answer"] = "um halb eins, kurz bevor das Wasser zurückkommt"
    item["options"] = ["um zehn Uhr", item["answer"], "um ein Uhr"]


def _right_is_always_longest(d: dict[str, Any]) -> None:
    _task(d, "t3")["items"] = [
        {"question": "Warum ruft Jan „Stopp!“?",
         "options": ["Mia läuft zu den Seehunden hin.", "Mia verliert einen Stiefel.",
                     "Mia geht zu langsam."],
         "answer": "Mia läuft zu den Seehunden hin."},
        {"question": "Wann stehen sie vor dem Leuchtturm?",
         "options": ["um zehn Uhr", "um halb eins am Mittag", "um ein Uhr"],
         "answer": "um halb eins am Mittag"},
        {"question": "Was ist eine Stunde später mit dem Weg?",
         "options": ["Er ist trocken.", "Er ist wieder unter Wasser.", "Er ist voller Leute."],
         "answer": "Er ist wieder unter Wasser."},
    ]


def _dense_cloze(d: dict[str, Any]) -> None:
    _task(d, "t5")["text"] = "Die {{Ebbe}} und die {{Flut}} im {{Watt}} bei der {{Insel}}."


def _same_word_twice(d: dict[str, Any]) -> None:
    cloze = _task(d, "t5")
    cloze["text"] = cloze["text"].replace("{{Flut}}", "{{Ebbe}}")


def _answer_in_plain_sight(d: dict[str, Any]) -> None:
    _task(d, "t5")["text"] += " Die Flut kommt bald."


def _add(task: dict[str, Any]) -> Mutation:
    return lambda d: d["tasks"].append(task)


def _crowd_the_markers(d: dict[str, Any]) -> None:
    labels = _scene(d, 1)["picture"]["labels"]
    labels[1]["x"], labels[1]["y"] = labels[0]["x"] + 0.01, labels[0]["y"]


#: rule code -> a mutation of the clean example that breaks exactly this rule.
MUTANTS: dict[str, Mutation] = {
    # story
    "beat-missing": lambda d: _scene(d, 0).pop("beat"),
    "beat-order": _swap_beats,
    "no-turn": _third_scene,
    "no-resolution": lambda d: _scene(d, 1).update(beat="complication"),
    "protagonist-absent": _hide_protagonist,
    "character-unused": lambda d: d["story"]["characters"].append(
        {"id": "emma", "name": "Emma", "role": "Mia's sister in Leeds"}),
    "logline-without-protagonist": lambda d: d["story"].update(
        logline="A nurse on holiday wants to walk to an island before the water returns."),
    "no-direct-speech": _no_speech,
    "scene-unbalanced": lambda d: _scene(d, 1).update(text=" ".join([_scene(d, 1)["text"]] * 3)),
    "sentence-length": _long_sentence,
    "translation-missing": lambda d: _scene(d, 0).pop("translation"),
    "fact-repeats-story": lambda d: d["facts"][0].update(
        text="Vor ihr liegt nur nasser, grauer Sand – das Watt."),
    "fact-unanchored": lambda d: d["facts"][0].pop("scene"),
    "fact-too-long": lambda d: d["facts"][0].update(
        text="Das Watt ist groß. Es ist nass. Es ist grau. Viele Tiere leben dort."),
    "cover-incomplete": lambda d: d.pop("standfirst"),
    "series-without-teaser": lambda d: d.update(
        series={"id": "mia", "title": "Mia am Meer", "episode": 1}),
    # lesson
    "no-warm-up": lambda d: _task(d, "t1").update(stage="gist", scene="s1"),
    "no-language-work": _no_language_work,
    "scene-unchecked": lambda d: _task(d, "t2").update(scene="s2"),
    "task-variety": _too_many_of_one_kind,
    "target-not-pretaught": _other_warm_up_words,
    "target-thinly-practised": _ebbe_in_two_tasks,
    "target-never-produced": _watt_never_written,
    "grammar-unpractised": lambda d: _task(d, "t4").pop("grammar"),
    "grammar-few-examples": lambda d: d["grammar"][0].update(
        examples=d["grammar"][0]["examples"][:1]),
    "practice-leaves-story": _practice_without_names,
    "comprehension-quotes-story": _quote_the_story,
    "labels-unused": lambda d: d["tasks"].remove(_task(d, "t6")),
    "answer-missing": _question_without_answer,
    # items
    "item-count": lambda d: _task(d, "t2").update(items=_task(d, "t2")["items"][:2]),
    "tf-one-sided": _all_true,
    "tf-correction-same": _same_correction,
    "mc-few-options": _two_options,
    "mc-answer-stands-out": _long_right_option,
    "mc-longest-is-right": _right_is_always_longest,
    "match-no-spare": lambda d: _task(d, "t1").update(extra=[]),
    "match-trivial-pair": lambda d: _task(d, "t1")["pairs"][0].update(right="Watt"),
    "cloze-too-dense": _dense_cloze,
    "bank-distractors": lambda d: _task(d, "t5").update(distractors=[]),
    "bank-word-twice": _same_word_twice,
    "distractor-stands-out": lambda d: _task(d, "t5").update(distractors=["Sonne", "langsam"]),
    "answer-shown-in-task": _answer_in_plain_sight,
    "lines-too-few": lambda d: _task(d, "t7").update(lines=3),
    "writing-scaffold": lambda d: _task(d, "t7").pop("starter"),
    "must-use-unseen": lambda d: _task(d, "t7")["must_use"].append("der Strandkorb"),
    "transform-no-change": _add({
        "id": "t8", "kind": "transform", "stage": "form", "scene": "s2",
        "title": "Yesterday on the mudflats",
        "items": [
            {"prompt": "Mia geht zur Insel.", "cue": "gestern", "answer": "Mia geht zur Insel."},
            {"prompt": "Jan ruft laut.", "cue": "gestern", "answer": "Jan hat laut gerufen."},
            {"prompt": "Die Flut kommt.", "cue": "gestern", "answer": "Die Flut ist gekommen."},
        ],
    }),
    "word-building-unrelated": _add({
        "id": "t8", "kind": "word_building", "stage": "form", "scene": "s2",
        "title": "Words from the coast",
        "items": [
            {"parts": ["der Sand", "die Bank"], "answer": "der Leuchtturm"},
            {"parts": ["das Watt", "der Führer"], "answer": "der Wattführer"},
            {"parts": ["der See", "der Hund"], "answer": "der Seehund"},
        ],
    }),
    "media-search-thin": _add({
        "id": "t8", "kind": "media_search", "stage": "epilogue", "title": "Jan's homework",
        "queries": ["https://www.example.org/wattwanderung", "Wattwanderung Neuwerk"],
        "questions": ["Wie lange dauert der Weg?"],
    }),
    "label-crowded": _crowd_the_markers,
    "title-generic": lambda d: _task(d, "t2").update(title="Exercise 2"),
}


def _longest_in(right: int, of: int) -> dict[str, Any]:
    """The clean example with ``of`` questions; in ``right`` of them the right
    option is the longest one."""
    data = _mini()
    items = []
    for n in range(of):
        longest = n < right
        items.append({
            "question": f"Frage {n + 1}?",
            "options": ["eine lange Antwort hier" if longest else "kurz", "mittel lang", "mittellang"],
            "answer": "eine lange Antwort hier" if longest else "kurz",
        })
    _task(data, "t3")["items"] = items
    return data


@pytest.mark.parametrize(("right", "of", "reported"), [
    (2, 3, False), (3, 3, True),
    (2, 4, False), (3, 4, True),
    (3, 5, False), (4, 5, True),
    (3, 6, False), (4, 6, True),
    (2, 2, False),  # two questions are no pattern
])
def test_the_longest_option_rule_allows_half_rounded_up(right: int, of: int, reported: bool) -> None:
    codes = _codes(_longest_in(right, of))
    assert ("mc-longest-is-right" in codes) is reported
    assert "rounded up" in RULES["mc-longest-is-right"].title


def test_the_lines_suggestion_is_the_fewest_lines_that_pass() -> None:
    data = _mini()
    _task(data, "t7").update(min_words=60, max_words=100, lines=9)
    finding = next(f for f in assess(worksheet_from_dict(data)).findings
                   if f.code == "lines-too-few")
    assert '"lines" to 10 or more' in finding.message
    _task(data, "t7").update(lines=10)
    assert "lines-too-few" not in _codes(data)


def test_every_rule_has_a_mutant() -> None:
    assert set(MUTANTS) == set(RULES)


@pytest.mark.parametrize("code", list(RULES))
def test_the_rule_reports_its_mutant(code: str) -> None:
    data = _mini()
    assert _codes(data) == set()
    MUTANTS[code](data)
    report = assess(worksheet_from_dict(data))
    hits = [f for f in report.findings if f.code == code]
    assert hits, f"{code} did not fire; got {sorted({f.code for f in report.findings})}"
    for finding in hits:
        assert finding.where.startswith("/"), finding
        assert finding.dimension == RULES[code].dimension
        # a finding is a repair instruction: it says what is wrong and what to do
        assert len(finding.message) > 40 and finding.message.rstrip().endswith((".", "?")), finding


#: More ways to break a rule than the one in MUTANTS.
VARIANTS: list[tuple[str, Mutation]] = [
    ("translation-missing", lambda d: _scene(d, 0).update(translation="Saturday.")),
    ("title-generic", lambda d: _task(d, "t2").pop("title")),
    ("title-generic", lambda d: _task(d, "t2").update(title=_task(d, "t3")["title"])),
    ("title-generic", lambda d: _task(d, "t2").update(title="Übung 2:")),
    ("writing-scaffold", lambda d: _task(d, "t7").pop("model_answer")),
    ("writing-scaffold", lambda d: _task(d, "t7").pop("min_words")),
    ("writing-scaffold", lambda d: _task(d, "t7").update(min_words=5, max_words=400, lines=40)),
    ("writing-scaffold", lambda d: _task(d, "t7").update(must_use=["die Ebbe", "die Flut"])),
    ("tf-one-sided", lambda d: [i.update(answer=False, correction="Das stimmt nicht so.")
                                for i in _task(d, "t2")["items"]]),
    ("bank-distractors", lambda d: _task(d, "t5").update(
        distractors=["Sonne", "Schlick", "Stiefel", "Strand", "Sand", "Pferd"])),
    ("distractor-stands-out", lambda d: _task(d, "t5").update(distractors=["nass"])),
    ("item-count", lambda d: _task(d, "t1").update(pairs=_task(d, "t1")["pairs"][:3])),
    ("beat-order", lambda d: _scene(d, 0).update(beat="development")),
    ("cover-incomplete", lambda d: d["story"].pop("setting")),
    ("cover-incomplete", lambda d: d["story"]["characters"][1].pop("role")),
    ("cover-incomplete", lambda d: d["story"]["characters"].pop()),
    ("lines-too-few", _add({
        "id": "t8", "kind": "questions", "stage": "detail", "scene": "s1",
        "title": "Why the hurry?",
        "items": [{"question": "Warum müssen sie vor ein Uhr auf der Insel sein?", "lines": 1,
                   "answer": "Um ein Uhr kommt die Flut zurück, und dann fließt wieder Wasser "
                             "in den Prielen, sodass der Weg zur Insel verschwindet."}],
    })),
    ("answer-missing", _add({
        "id": "t8", "kind": "dialogue", "stage": "practice", "scene": "s2",
        "title": "On the island", "bank": False,
        "lines": [
            {"speaker": "Jan", "text": "Wir sind da, Mia!"},
            {"speaker": "Mia", "cue": "Say you are tired but happy."},
            {"speaker": "Jan", "text": "Dann trinken wir jetzt einen Tee."},
            {"speaker": "Mia", "cue": "Ask when the water comes back.",
             "answer": "Wann kommt das Wasser zurück?"},
            {"speaker": "Jan", "cue": "Answer her.", "answer": "Um ein Uhr."},
        ],
    })),
    ("media-search-thin", _add({
        "id": "t8", "kind": "media_search", "stage": "epilogue", "title": "Jan's homework",
        "queries": ["Wattwanderung Neuwerk", "Gezeiten Nordsee"],
        "questions": ["Wie lange dauert der Weg?"],
    })),
]


@pytest.mark.parametrize(("code", "mutation"), VARIANTS, ids=lambda v: v if isinstance(v, str) else "")
def test_the_rule_reports_its_variants(code: str, mutation: Mutation) -> None:
    data = _mini()
    mutation(data)
    assert code in _codes(data)


def _diary(d: dict[str, Any]) -> None:
    d["frame"] = "diary"
    for scene in d["story"]["scenes"]:
        scene["text"] = scene["text"].replace("Mias", "Meine").replace("Mia", "ich")
    d["story"]["logline"] = "Mia keeps a diary of her walk to the island."


#: Things that look like a problem and are none: the rule must stay quiet.
NOT_A_FINDING: list[tuple[str, Mutation]] = [
    # a first-person frame need not name its narrator
    ("protagonist-absent", _diary),
    ("character-unused", _diary),
    # the base form in brackets is a hint, not the answer in plain sight
    ("answer-shown-in-task", lambda d: _task(d, "t4").update(items=[
        "Im Watt {{müssen::müssen}} wir immer bei der Gruppe bleiben.",
        "Ihr {{dürft::dürfen}} die Seehunde nicht stören.",
        "Um ein Uhr {{muss::müssen}} jeder auf der Insel sein.",
    ])),
    # a personal question has no model answer
    ("answer-missing", _add({
        "id": "t8", "kind": "questions", "stage": "production", "title": "And you?",
        "items": [{"question": "Warst du schon einmal am Meer?", "lines": 3}],
    })),
    # two of three true is a mix
    ("tf-one-sided", lambda d: _task(d, "t2")["items"][0].update(answer=True)),
    # mixed capitals among the answers: a lower-case spare word reveals nothing
    ("distractor-stands-out", lambda d: _task(d, "t5").update(
        text=_task(d, "t5")["text"].replace("laufen langsam", "laufen {{langsam}}"),
        distractors=["Sonne", "nass"])),
    # the right option may be the longest now and then
    ("mc-longest-is-right", lambda d: _task(d, "t3")["items"][1].update(
        options=["um zehn Uhr", "um halb eins am Mittag", "um ein Uhr"],
        answer="um halb eins am Mittag")),
]


@pytest.mark.parametrize(("code", "mutation"), NOT_A_FINDING,
                         ids=lambda v: v if isinstance(v, str) else "")
def test_the_rule_stays_quiet(code: str, mutation: Mutation) -> None:
    data = _mini()
    mutation(data)
    assert code not in _codes(data)


# -- the helpers the story rules stand on -----------------------------------


@pytest.mark.parametrize("text", [
    "„Jetzt ist Ebbe“, sagt Jan.",
    "“It's low tide now,” says Jan.",
    "« Il est tard », dit Paula.",
    "»Kom nu«, siger Ole.",
    "— A minha avó tirou esta fotografia aqui.",
    "—¿Algo más? —pregunta Amparo.",
    "– To jest krasnal – mówi Ola.",
    "‘Waar is mijn fiets?’ vraagt Jonas.",
    'She said "stop" twice.',
])
def test_direct_speech_is_seen_in_every_convention(text: str) -> None:
    assert has_direct_speech(text)
    assert speech_share(text) > 0


@pytest.mark.parametrize("text", [
    "Mia steht am Strand und staunt.",
    "Het is zo'n mooie dag, vindt Jonas.",
    "L'île est loin - très loin.",
    "Um halb eins – es ist schon spät – stehen sie vor dem Leuchtturm.",
])
def test_narration_is_not_direct_speech(text: str) -> None:
    assert not has_direct_speech(text)
    assert speech_share(text) == 0


def test_speech_share_is_a_share() -> None:
    assert speech_share("") == 0
    assert speech_share("„Komm!“") == 1
    half = speech_share("„Jetzt ist Ebbe“, sagt der Wattführer Jan.")
    assert 0.3 < half < 0.6


@pytest.mark.parametrize(("name", "keys"), [
    ("Hannah", ["Hannah"]),
    ("Frau Berger", ["Berger"]),
    ("la abuela Pepa", ["Pepa"]),
    ("Dona Amélia", ["Amélia"]),
    ("Onkel Marco", ["Marco"]),
    ("Jean-Luc Moreau", ["Jean-Luc", "Moreau"]),
    ("Frau", ["Frau"]),
])
def test_name_keys(name: str, keys: list[str]) -> None:
    assert name_keys(name) == keys


@pytest.mark.parametrize(("name", "text", "lang", "named"), [
    ("Frau Berger", "Die Chefin, Frau Berger, lacht.", "de", True),
    ("Frau Berger", "Eine Frau lacht.", "de", False),
    ("Lena", "Lenas Kaffee ist zu bitter.", "de", True),
    ("Lena", "Der Lenker ist kaputt.", "de", False),
    ("Marta", "Ola daje Marcie mapę.", "pl", True),  # the dative of Marta
    ("Marta", "Ola idzie do domu.", "pl", False),
    ("Marta", "Ola szuka Marty.", "pl", True),
    ("Marta", "Ola widzi Martę.", "pl", True),
    ("Pavel", "Jana volá Pavla.", "cs", True),
    ("Tomáš", "Jana mluví s Tomášem.", "cs", True),
    ("la abuela Pepa", "La abuela abre las bolsas.", "es", False),
    ("la abuela Pepa", "—¡Gambas! —dice Pepa.", "es", True),
])
def test_is_named(name: str, text: str, lang: str, named: bool) -> None:
    character = worksheet_from_dict(MINI_EXAMPLE).story.characters[0].model_copy(
        update={"name": name})
    assert is_named(character, text, lang) is named


# ---------------------------------------------------------------------------
# 3. The corpus
# ---------------------------------------------------------------------------


def test_there_are_examples() -> None:
    assert EXAMPLES


def test_accepted_findings_name_real_examples_and_rules() -> None:
    stems = {p.stem for p in EXAMPLES}
    for stem, accepted in ACCEPTED.items():
        assert stem in stems, f"ACCEPTED lists '{stem}', which is not a bundled example"
        for (code, where, message), why in accepted.items():
            assert code in RULES, code
            assert where.startswith("/") and message and len(why) > 20, (code, where)


def _against_accepted(
    findings: list[quality.Finding], accepted: dict[tuple[str, str, str], str],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    """(findings that are not accepted, accepted entries that no longer occur).
    Counted, not just looked up: one entry covers one finding."""
    found = Counter((f.code, f.where, f.message) for f in findings)
    listed = Counter(list(accepted))  # the keys: a dict's values would be read as counts
    return sorted((found - listed).elements()), sorted((listed - found).elements())


def test_an_accepted_finding_does_not_hide_another_at_the_same_place() -> None:
    data = _mini()
    long_one = (" Mia zieht ihre Stiefel an und nimmt ihren Rucksack und geht mit Jan und den "
                "anderen Gästen langsam über den nassen Sand, weil das Wasser um ein Uhr wieder "
                "zurückkommt.")
    _scene(data, 0)["text"] += long_one
    first = [f for f in assess(worksheet_from_dict(data)).findings if f.code == "sentence-length"]
    assert len(first) == 1
    accepted = {(first[0].code, first[0].where, first[0].message): "tolerated for this test only"}
    assert _against_accepted(first, accepted) == ([], [])
    # a second over-long sentence in the same scene: same code, same pointer
    _scene(data, 0)["text"] += long_one.replace("Mia", "Dann").replace("Stiefel", "Schuhe")
    both = [f for f in assess(worksheet_from_dict(data)).findings if f.code == "sentence-length"]
    assert len(both) == 2 and both[0].where == both[1].where
    new, fixed = _against_accepted(both, accepted)
    assert len(new) == 1 and "Schuhe" in new[0][2] and fixed == []
    # the same finding twice is two findings
    assert len(_against_accepted([first[0], first[0]], accepted)[0]) == 1
    # and an entry whose finding is gone has to go
    assert _against_accepted([], accepted) == ([], list(accepted))


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_bundled_examples_meet_the_rubric(path: Path) -> None:
    report = assess(load_worksheet(path))
    new, fixed = _against_accepted(report.findings, ACCEPTED.get(path.stem, {}))
    assert not new, (
        f"{path.name} has findings the rubric does not accept "
        f"(see 'langwich validate {path.relative_to(REPO_ROOT)} --quality'):\n"
        + "\n".join(f"  {where} [{code}] {message}" for code, where, message in new)
    )
    assert not fixed, (
        f"{path.name} no longer has these findings; remove them from ACCEPTED: {fixed}"
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_measures_of_the_examples_are_plausible(path: Path) -> None:
    ws = load_worksheet(path)
    m = measure(ws)
    assert m["level"] == ws.cefr_level
    assert m["scenes"] == len(ws.story.scenes) and m["tasks"] == len(ws.tasks)
    assert m["closed_tasks"] + m["guided_tasks"] + m["open_tasks"] == m["tasks"]
    assert 0 <= m["speech_share"] <= 1
    assert m["scenes_with_speech"] <= m["scenes"]
    assert m["words_per_sentence"] <= SENTENCE_WORDS[ws.cefr_level]
    assert m["items"] >= m["tasks"]
    # a sheet for self-study: most of it can be checked against the key
    assert m["closed_tasks"] * 2 >= m["tasks"]


def test_findings_become_repair_instructions() -> None:
    data = _mini()
    MUTANTS["mc-answer-stands-out"](data)
    MUTANTS["match-no-spare"](data)
    ws = worksheet_from_dict(data)
    report = assess(ws)
    issues = report.issues()
    assert {i.level for i in issues} == {"warning"}
    text = repair_prompt(Report(validate(ws).issues + issues, ws), json.dumps(data))
    assert "[mc-answer-stands-out]" in text and "[match-no-spare]" in text
    assert "`/tasks/0/extra`" in text


def test_report_shape() -> None:
    data = _mini()
    MUTANTS["tf-one-sided"](data)
    report = assess(worksheet_from_dict(data))
    assert not report.ok
    assert report.failed() == ["tf-one-sided"]
    assert report.failed("story") == [] and report.failed("items") == ["tf-one-sided"]
    good, total = report.passed("items")
    assert total - good == 1
    out = report.to_dict()
    assert json.loads(json.dumps(out)) == out
    assert out["finding_count"] == 1 and out["findings"][0]["dimension"] == "items"
    assert sum(v["total"] for v in out["rules"].values()) == len(RULES)
    assert "1 finding (" in report.summary()


# -- the command line ---------------------------------------------------------


def _write(tmp_path: Path, data: dict[str, Any]) -> Path:
    path = tmp_path / "sheet.json"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_cli_quality_clean(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write(tmp_path, _mini())
    assert main(["validate", str(path), "--quality", "--strict"]) == 0
    out = capsys.readouterr().out
    assert "OK: no problems found." in out
    assert "Design rubric: no findings" in out


def test_cli_quality_findings(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _mini()
    MUTANTS["match-no-spare"](data)
    path = _write(tmp_path, data)
    assert main(["validate", str(path)]) == 0
    assert "Design rubric" not in capsys.readouterr().out
    # findings are not errors: the sheet renders, the exit status says so
    assert main(["validate", str(path), "--quality"]) == 0
    out = capsys.readouterr().out
    assert "Design rubric: 1 finding" in out and "/tasks/0/extra  [match-no-spare]" in out
    assert main(["validate", str(path), "--quality", "--strict"]) == 1
    capsys.readouterr()
    assert main(["validate", str(path), "--strict"]) == 0


def test_cli_quality_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _mini()
    MUTANTS["match-no-spare"](data)
    path = _write(tmp_path, data)
    assert main(["validate", str(path), "--json"]) == 0
    assert "quality" not in json.loads(capsys.readouterr().out)
    assert main(["validate", str(path), "--quality", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["issues"] == []  # the validator's own report is unchanged
    assert report["quality"]["finding_count"] == 1
    assert report["quality"]["findings"][0]["code"] == "match-no-spare"
    assert report["quality"]["metrics"]["tasks"] == len(data["tasks"])


def test_cli_quality_prompt(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _mini()
    MUTANTS["match-no-spare"](data)
    path = _write(tmp_path, data)
    assert main(["validate", str(path), "--prompt"]) == 0
    assert "nothing to repair" in capsys.readouterr().err
    assert main(["validate", str(path), "--quality", "--prompt"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("# Fix this langwich/3 worksheet") and "[match-no-spare]" in out
    assert main(["validate", str(path), "--quality", "--prompt", "--strict"]) == 1


def test_cli_quality_waits_for_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _mini()
    data["source_lang"] = data["target_lang"]
    path = _write(tmp_path, data)
    assert main(["validate", str(path), "--quality"]) == 1
    out = capsys.readouterr().out
    assert "[same-language]" in out and "Design rubric: not run" in out
    assert main(["validate", str(path), "--quality", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["quality"] is None


# ---------------------------------------------------------------------------
# 4. Determinism
# ---------------------------------------------------------------------------


def _reordered(value: Any) -> Any:
    """The same JSON with every object's keys in reverse order."""
    if isinstance(value, dict):
        return {key: _reordered(value[key]) for key in reversed(list(value))}
    if isinstance(value, list):
        return [_reordered(item) for item in value]
    return value


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_same_sheet_gets_the_same_report(path: Path) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    first = assess(worksheet_from_dict(data)).to_dict()
    assert assess(worksheet_from_dict(copy.deepcopy(data))).to_dict() == first
    assert assess(worksheet_from_dict(_reordered(data))).to_dict() == first


def test_the_report_does_not_depend_on_the_hash_seed() -> None:
    code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "from langwich.model import load_worksheet\n"
        "from langwich.quality import assess\n"
        "out = {p.name: assess(load_worksheet(p)).to_dict()\n"
        "       for p in sorted(Path(sys.argv[1]).glob('*.json'))}\n"
        "print(json.dumps(out, ensure_ascii=True, sort_keys=False))\n"
    )
    outputs = []
    for seed in ("0", "1", "4242"):
        env = {**os.environ, "PYTHONHASHSEED": seed,
               "PYTHONPATH": str(REPO_ROOT / "src"), "PYTHONIOENCODING": "utf-8"}
        result = subprocess.run(
            [sys.executable, "-c", code, str(REPO_ROOT / "examples")],
            capture_output=True, text=True, env=env, check=True,
        )
        outputs.append(result.stdout)
    assert outputs[0] == outputs[1] == outputs[2]
    assert json.loads(outputs[0])


def test_the_rubric_imports_nothing_that_varies() -> None:
    """No randomness, no clock, no files, no network: by construction."""
    tree = ast.parse(Path(quality.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    allowed = {"__future__", "collections", "dataclasses", "difflib", "re", "typing",
               "unicodedata", "langwich"}
    assert imported <= allowed, sorted(imported - allowed)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    assert not names & {"open", "random", "time", "datetime", "os", "hash", "id", "set"} - {"set"}


def test_findings_come_in_a_stable_order() -> None:
    data = _mini()
    for code in ("title-generic", "match-no-spare", "beat-missing", "tf-one-sided"):
        MUTANTS[code](data)
    codes = [f.code for f in assess(worksheet_from_dict(data)).findings]
    # story rules first, then the lesson, then the tasks in worksheet order
    assert codes.index("beat-missing") < codes.index("match-no-spare")
    assert codes == [f.code for f in assess(worksheet_from_dict(_reordered(data))).findings]


def test_stages_and_kinds_are_the_contracts() -> None:
    # the rubric reads stages by name; a renamed stage must fail here, not silently pass
    used = {"warm_up", "gist", "detail", "picture", "form", "practice", "production"}
    assert used <= set(STAGES)


# ---------------------------------------------------------------------------
# The documentation is generated from the rules
# ---------------------------------------------------------------------------


def _export_rubric() -> Any:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "export_rubric", REPO_ROOT / "scripts" / "export_rubric.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_rubric_documentation_is_up_to_date() -> None:
    script = _export_rubric()
    committed = (REPO_ROOT / "docs" / "quality.md").read_text(encoding="utf-8")
    assert committed == script.rubric_text(), (
        "docs/quality.md is stale — run 'python scripts/export_rubric.py' and commit the result"
    )
    for code in RULES:
        assert f"| `{code}` |" in committed
    for kind in TASK_KINDS:
        assert f"| `{kind}` |" in committed
    assert script.main(["--check"]) == 0
