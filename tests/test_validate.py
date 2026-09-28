"""Tests for langwich.validate: one clean fixture plus one mutation per check."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from langwich.model import worksheet_from_dict
from langwich.validate import (
    CHECKS,
    ENVIRONMENT_CODES,
    MORE_CHECKS_NOTE,
    PICTURE_CODES,
    STORY_WORDS,
    Issue,
    Report,
    check_file,
    resolve_image,
    validate,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
LENA = REPO_ROOT / "examples" / "lena_01_en_de.json"

SVG = '<svg viewBox="0 0 100 60" xmlns="http://www.w3.org/2000/svg"><rect width="100" height="60"/></svg>'
BROKEN_SVG = SVG.replace("<rect", "<text>Kaffee & Kuchen</text><rect")
TEXT_SVG = SVG.replace("<rect", "<text x='5' y='9'>die Tasse</text><rect")
EXTERNAL_SVG = SVG.replace("<rect", "<image href='https://example.org/cup.png'/><rect")
#: A data: URI whose bytes are no image at all.
NOT_AN_IMAGE = "data:image/png;base64,bm90IGFuIGltYWdl"

#: 25 words, uses every must_use word of task t5.
MODEL_ANSWER = (
    "Mein Lieblingscafé ist klein und hell. Ich sitze gern am Fenster und trinke dort jeden "
    "Morgen einen Kaffee mit Milch. Die Kellnerin kennt mich schon und lacht."
)

#: A small but complete A1 worksheet that triggers no issue at all.
BASE: dict[str, Any] = {
    "schema": "langwich/3",
    "title": "Ein Tag im Café",
    "standfirst": "Anna works in a small café. Today she bakes a cake for her favourite guest.",
    "source_lang": "en",
    "target_lang": "de",
    "cefr_level": "A1",
    "topic": "coffee",
    "frame": "episode",
    "story": {
        "logline": "Anna, a young waitress, wants to make her quietest guest smile.",
        "setting": "a small café in Hamburg",
        "characters": [
            {"id": "anna", "name": "Anna", "role": "20, works in the café"},
            {"id": "kaya", "name": "Herr Kaya", "role": "a quiet regular"},
        ],
        "scenes": [
            {
                "id": "s1",
                "heading": "Am Morgen",
                "beat": "setup",
                "text": (
                    "Anna arbeitet im Café Sonne. Jeden Morgen kocht sie Kaffee für die Gäste. "
                    "Der Kaffee kommt aus Brasilien. Herr Kaya trinkt immer eine Tasse Tee. "
                    "Er sitzt am Fenster und liest die Zeitung."
                ),
                "translation": "Anna works in Café Sonne. …",
            },
            {
                "id": "s2",
                "heading": "Der Kuchen",
                "beat": "resolution",
                "text": (
                    "Heute backt Anna einen Kuchen mit Äpfeln. Der Kuchen riecht sehr gut. "
                    "Herr Kaya bestellt ein Stück und lächelt zum ersten Mal. Dann trinkt er "
                    "noch eine Tasse Kaffee. Anna ist glücklich. Am Abend putzt sie die Tische "
                    "und geht nach Hause."
                ),
                "picture": {
                    "svg": SVG,
                    "labels": [
                        {"n": 1, "term": "die Tasse", "x": 0.2, "y": 0.5},
                        {"n": 2, "term": "der Kuchen", "x": 0.6, "y": 0.5},
                    ],
                },
            },
        ],
    },
    "facts": [
        {"id": "f1", "scene": "s1", "text": "Brasilien produziert den meisten Kaffee der Welt."},
    ],
    "vocabulary": {
        "target": ["der Kaffee", "die Tasse", "der Kuchen", "trinken", "das Fenster"],
        "items": [
            {"term": "der Kaffee", "translation": "coffee", "pos": "noun"},
            {"term": "die Tasse", "translation": "cup", "pos": "noun", "plural": "die Tassen"},
            {"term": "der Kuchen", "translation": "cake", "pos": "noun"},
            {"term": "trinken", "translation": "to drink", "pos": "verb",
             "forms": "trinkt, trank, hat getrunken"},
            {"term": "das Fenster", "translation": "window", "pos": "noun"},
            {"term": "die Zeitung", "translation": "newspaper", "pos": "noun"},
            {"term": "glücklich", "translation": "happy", "pos": "adjective"},
        ],
    },
    "grammar": [
        {"id": "g1", "name": "Verb second", "scene": "s2",
         "explanation": "The verb is the second element of a German main clause.",
         "examples": ["Heute backt Anna einen Kuchen."]},
    ],
    "tasks": [
        {
            "id": "t1", "kind": "match", "stage": "warm_up",
            "pairs": [
                {"left": "der Kaffee", "right": "coffee"},
                {"left": "die Tasse", "right": "cup"},
                {"left": "der Kuchen", "right": "cake"},
                {"left": "trinken", "right": "to drink"},
                {"left": "das Fenster", "right": "window"},
            ],
            "extra": ["newspaper"],
        },
        {
            "id": "t2", "kind": "true_false", "stage": "gist", "scene": "s1",
            "items": [
                {"statement": "Anna arbeitet in einer Bäckerei.", "answer": False,
                 "correction": "Sie arbeitet im Café Sonne."},
                {"statement": "Herr Kaya sitzt am Fenster.", "answer": True},
            ],
        },
        {
            "id": "t3", "kind": "cloze", "stage": "practice", "scene": "s2", "grammar": "g1",
            "hint": "word_bank",
            "items": [
                "Mein Bruder trinkt gern {{Kaffee}} mit Milch.",
                "Die {{Tasse}} steht auf dem Tisch in der Küche.",
                "Zum Geburtstag gibt es einen großen {{Kuchen}}.",
            ],
            "distractors": ["Zeitung"],
        },
        {"id": "t4", "kind": "label", "stage": "picture", "scene": "s2"},
        {
            "id": "t5", "kind": "writing", "stage": "production",
            "prompt": "Write about your favourite café.",
            "must_use": ["der Kaffee", "trinken", "das Fenster"],
            "min_words": 20, "max_words": 40,
        },
    ],
}

Mutation = Callable[[dict[str, Any]], None]


def _issues(data: dict[str, Any], base_dir: Path | None = None) -> list[Issue]:
    return validate(worksheet_from_dict(data), base_dir=base_dir).issues


def _mutated(fn: Mutation) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    fn(data)
    return data


def _task(data: dict[str, Any], task_id: str) -> dict[str, Any]:
    return next(t for t in data["tasks"] if t["id"] == task_id)


def _add_task(task: dict[str, Any]) -> Mutation:
    return lambda d: d["tasks"].append(task)


def _set(path: str, value: Any) -> Mutation:
    """Set a value by a slash path ('story/scenes/0/id')."""

    def fn(d: dict[str, Any]) -> None:
        *parents, last = path.split("/")
        node: Any = d
        for p in parents:
            node = node[int(p)] if isinstance(node, list) else node[p]
        if isinstance(node, list):
            node[int(last)] = value
        else:
            node[last] = value

    return fn


def _chain(*fns: Mutation) -> Mutation:
    def fn(d: dict[str, Any]) -> None:
        for f in fns:
            f(d)

    return fn


def _drop_tasks(*ids: str) -> Mutation:
    return lambda d: d.__setitem__("tasks", [t for t in d["tasks"] if t["id"] not in ids])


# ---------------------------------------------------------------------------
# The clean fixture and the reference example
# ---------------------------------------------------------------------------


def test_base_fixture_has_no_issues() -> None:
    assert _issues(BASE) == []


def test_lena_example_has_no_errors() -> None:
    report = check_file(LENA)
    assert report.worksheet is not None
    assert report.errors == [], report.format_text()
    # Documented expectation: the reference example is also warning-free.
    assert report.warnings == [], report.format_text()


def test_every_issue_code_is_kebab_case() -> None:
    for code in CHECKS:
        assert code == code.lower() and " " not in code and "_" not in code


# ---------------------------------------------------------------------------
# One mutation per error / warning
# ---------------------------------------------------------------------------

DIALOGUE_DONE = {
    "id": "t9", "kind": "dialogue", "stage": "practice", "scene": "s2",
    "lines": [
        {"speaker": "Anna", "text": "Möchten Sie Kaffee?"},
        {"speaker": "Herr Kaya", "text": "Ja, gern."},
    ],
}

DIALOGUE_BANK = {
    "id": "t9", "kind": "dialogue", "stage": "practice", "scene": "s2", "bank": True,
    "lines": [
        {"speaker": "Anna", "text": "{{Möchten}} Sie noch ein Stück?"},
        {"speaker": "Herr Kaya", "text": "Ja, gern. Und bitte noch eine {{Tasse}} Tee."},
    ],
}

PASSIVE_GRAMMAR = {
    "id": "g2", "name": "Das Passiv", "rule": "werden + Partizip II",
    "explanation": "The passive: werden + past participle.",
    "table": {"head": ["", "werden"], "rows": [["er / sie / es", "wird … gefragt"],
                                               ["sie", "werden … gefragt"]]},
    "examples": ["Der Tisch wird gedeckt."],
}

PASSIVE_TASK = {
    "id": "t9", "kind": "cloze", "stage": "form", "scene": "s2", "grammar": "g2",
    "hint": "base_form",
    "items": ["Am Morgen {{wird::werden}} der Kuchen {{gebacken::backen}}.",
              "Danach {{werden::werden}} die Tische {{geputzt::putzen}}."],
}

CASES: list[tuple[str, Mutation, str | None]] = [
    # --- errors ---
    ("duplicate-id", _set("story/scenes/1/id", "s1"), "/story/scenes/1/id"),
    ("duplicate-id", _set("tasks/1/id", "t1"), "/tasks/1/id"),
    ("unknown-scene", _set("tasks/1/scene", "s9"), "/tasks/1/scene"),
    ("unknown-scene", _set("tasks/1/scene", ["s1", "s7"]), "/tasks/1/scene/1"),
    ("unknown-scene", _set("facts/0/scene", "s3"), "/facts/0/scene"),
    ("unknown-grammar", _set("tasks/2/grammar", "g7"), "/tasks/2/grammar"),
    ("target-not-in-items", _set("vocabulary/target/4", "Fenster"), "/vocabulary/target/4"),
    ("same-language", _set("source_lang", "de"), "/target_lang"),
    ("cloze-without-gaps", _set("tasks/2/items/1", "Die Tasse steht auf dem Tisch."),
     "/tasks/2/items/1"),
    ("cloze-without-gaps",
     _chain(_set("tasks/2/text", "Anna trinkt {Kaffee}."),
            lambda d: d["tasks"][2].pop("items")),
     "/tasks/2/text"),
    ("missing-gap-hint", _set("tasks/2/hint", "base_form"), "/tasks/2/items/0"),
    ("missing-gap-hint", _set("tasks/2/hint", "translation"), "/tasks/2/items/0"),
    ("missing-gap-hint", _set("tasks/2/hint", "choice"), "/tasks/2/items/0"),
    ("empty-gap", _set("tasks/2/items/0", "Mein Bruder trinkt {{ }} mit Milch."),
     "/tasks/2/items/0"),
    ("unbalanced-braces", _set("tasks/2/items/0", "Mein Bruder trinkt {{Kaffee}} mit {{Milch."),
     "/tasks/2/items/0"),
    ("unbalanced-braces", _set("tasks/2/items/0", "Mein Bruder trinkt {{{Kaffee}}} mit Milch."),
     "/tasks/2/items/0"),
    ("unbalanced-braces",
     _chain(_set("tasks/2/text", "Anna trinkt {{Kaffee\n\nund}} Tee. Die {{Tasse}} ist voll."),
            lambda d: d["tasks"][2].pop("items")),
     "/tasks/2/text"),
    ("markup-in-story", _set("story/scenes/0/text", BASE["story"]["scenes"][0]["text"]
                             + " Sie {{lächelt}}."), "/story/scenes/0/text"),
    ("label-without-labels", _add_task({"id": "t9", "kind": "label", "stage": "picture",
                                        "scene": "s1"}), "/tasks/5/scene"),
    ("duplicate-label-number", _set("story/scenes/1/picture/labels/1/n", 1),
     "/story/scenes/1/picture/labels/1/n"),
    ("label-without-position", _set("story/scenes/1/picture/labels/0/x", None),
     "/story/scenes/1/picture/labels/0"),
    ("image-not-found",
     _chain(lambda d: d["story"]["scenes"][1]["picture"].pop("svg"),
            _set("story/scenes/1/picture/image", "pictures/missing.jpg")),
     "/story/scenes/1/picture/image"),
    ("image-unreadable",
     _chain(lambda d: d["story"]["scenes"][1]["picture"].pop("svg"),
            _set("story/scenes/1/picture/image", NOT_AN_IMAGE)),
     "/story/scenes/1/picture/image"),
    ("svg-invalid", _set("story/scenes/1/picture/svg", BROKEN_SVG), "/story/scenes/1/picture/svg"),
    ("svg-invalid", _set("story/scenes/1/picture/svg", SVG[:-6]), "/story/scenes/1/picture/svg"),
    ("duplicate-match-partner", _set("tasks/0/pairs/1/left", "der Kaffee"),
     "/tasks/0/pairs/1/left"),
    ("duplicate-match-partner", _set("tasks/0/extra", ["cup"]), "/tasks/0/extra/0"),
    ("duplicate-event",
     _add_task({"id": "t9", "kind": "order_events", "stage": "gist",
                "events": ["Anna kocht Kaffee.", "Herr Kaya lächelt.", "anna kocht  Kaffee."]}),
     "/tasks/5/events/2"),
    ("dialogue-nothing-to-do", _add_task(DIALOGUE_DONE), "/tasks/5/lines"),
    ("word-range", _set("tasks/4/max_words", 10), "/tasks/4/min_words"),
    # --- warnings ---
    ("no-production", _drop_tasks("t5"), "/tasks"),
    ("no-comprehension", _drop_tasks("t2"), "/tasks"),
    ("task-without-scene", lambda d: d["tasks"][1].pop("scene"), "/tasks/1/scene"),
    ("task-without-scene", _set("tasks/2/scene", []), "/tasks/2/scene"),
    ("scene-count", lambda d: d["story"]["scenes"].pop(0), "/story/scenes"),
    ("story-length", _set("cefr_level", "B2"), "/story/scenes"),
    ("target-count", _set("vocabulary/target", ["der Kaffee", "die Tasse", "der Kuchen"]),
     "/vocabulary/target"),
    ("duplicate-target", lambda d: d["vocabulary"]["target"].append("die Tasse"),
     "/vocabulary/target/5"),
    ("target-underused",
     _chain(_set("tasks/4/must_use", ["der Kaffee", "trinken"]),
            _set("tasks/1/items/1/statement", "Herr Kaya sitzt an der Theke.")),
     "/vocabulary/target/4"),
    ("target-not-in-story",
     _chain(lambda d: d["vocabulary"]["target"].append("die Zeitung"),
            _set("story/scenes/0/text", BASE["story"]["scenes"][0]["text"].replace(
                "liest die Zeitung", "wartet")),
            _set("tasks/4/must_use", ["der Kaffee", "trinken", "das Fenster", "die Zeitung"])),
     "/vocabulary/target/5"),
    ("copies-story", _set("tasks/2/items/0", "Dann trinkt er noch eine {{Tasse}} Kaffee."),
     "/tasks/2/items/0"),
    ("copies-story",
     _chain(_set("tasks/2/items/0", "Dann trinkt er noch eine {{Tasse}} Kaffee."),
            _set("tasks/2/stage", "form")),
     "/tasks/2/items/0"),
    ("copies-story",
     _add_task({**DIALOGUE_BANK, "stage": "production", "lines": [
         {"speaker": "Anna", "text": "Heute backt Anna einen {{Kuchen}} mit Äpfeln."},
         {"speaker": "Herr Kaya", "text": "Wunderbar."},
     ]}),
     "/tasks/5/lines/0/text"),
    ("distractor-is-answer", _set("tasks/2/distractors", ["Kuchen"]), "/tasks/2/distractors/0"),
    ("distractor-is-answer", _add_task({**DIALOGUE_BANK, "distractors": ["Teller", "tasse"]}),
     "/tasks/5/distractors/1"),
    ("gap-starts-sentence", _add_task(DIALOGUE_BANK), "/tasks/5/lines/0/text"),
    ("gap-starts-sentence",
     _set("tasks/2/items/1", "Die Tasse ist leer. {{Heute}} trinkt Anna keinen Kaffee."),
     "/tasks/2/items/1"),
    ("hint-is-answer",
     _chain(_set("tasks/2/hint", "translation"),
            _set("tasks/2/items", ["Mein Bruder trinkt gern {{Kaffee::coffee}} mit Milch.",
                                   "Wir bestellen einen {{Espresso::espresso}}."])),
     "/tasks/2/items/1"),
    ("duplicate-item",
     lambda d: d["vocabulary"]["items"].append(
         {"term": "die  Zeitung", "translation": "paper", "pos": "noun"}),
     "/vocabulary/items/7/term"),
    ("duplicate-item",
     lambda d: d["vocabulary"]["items"].append(
         {"term": "Tasse", "translation": "cup", "pos": "noun"}),
     "/vocabulary/items/7/term"),
    ("pos-missing", lambda d: d["vocabulary"]["items"][5].pop("pos"), "/vocabulary/items/5/pos"),
    ("tf-missing-correction", lambda d: d["tasks"][1]["items"][0].pop("correction"),
     "/tasks/1/items/0"),
    ("model-answer-length",
     _set("tasks/4/model_answer", "Ich trinke Kaffee am Fenster."), "/tasks/4/model_answer"),
    ("model-answer-length",
     _set("tasks/4/model_answer", " ".join([MODEL_ANSWER] * 2)), "/tasks/4/model_answer"),
    ("model-answer-missing-must-use",
     _set("tasks/4/model_answer", MODEL_ANSWER.replace("am Fenster", "in der Ecke")),
     "/tasks/4/must_use/2"),
    ("picture-task-without-picture",
     _add_task({"id": "t9", "kind": "questions", "stage": "picture", "scene": "s1",
                "items": [{"question": "Was liegt auf dem Tisch?"}]}),
     "/tasks/5"),
    ("svg-text", _set("story/scenes/1/picture/svg", TEXT_SVG), "/story/scenes/1/picture/svg"),
    ("svg-external", _set("story/scenes/1/picture/svg", EXTERNAL_SVG),
     "/story/scenes/1/picture/svg"),
    ("svg-external",
     _set("story/scenes/1/picture/svg", SVG.replace("<rect", "<script>alert(1)</script><rect")),
     "/story/scenes/1/picture/svg"),
    ("ui-placeholders", _set("ui", {"kind.writing.length": "Schreibe {min[0]} Wörter."}),
     "/ui/kind.writing.length"),
    ("ui-placeholders", _set("ui", {"kind.writing.length": "Schreibe {minimum}–{max} Wörter."}),
     "/ui/kind.writing.length"),
    ("ui-placeholders", _set("ui", {"kind.writing.length": "Write {min.real.imag} words."}),
     "/ui/kind.writing.length"),
    ("ui-placeholders", _set("ui", {"solutions": "Lösungen {n}"}), "/ui/solutions"),
    ("bank-without-gaps", _add_task({**DIALOGUE_DONE, "bank": True, "lines": [
        {"speaker": "Anna", "text": "Möchten Sie Kaffee?"},
        {"speaker": "Herr Kaya", "text": None, "cue": "Say yes, please."},
    ]}), "/tasks/5/bank"),
    ("markup-outside-gaps", _set("tasks/1/items/1/statement", "Herr Kaya sitzt am {{Fenster}}."),
     "/tasks/1/items/1/statement"),
    ("no-facts", _set("facts", []), "/facts"),
    ("no-characters", _set("story/characters", []), "/story/characters"),
    ("review-unused", _set("series", {"id": "anna", "title": "Anna", "episode": 1,
                                      "review": ["der Kaffee", "das Fahrrad"]}),
     "/series/review/1"),
    ("missing-previously", _set("series", {"id": "anna", "title": "Anna", "episode": 2}),
     "/series/previously"),
    ("unknown-ui-key", _set("ui", {"solution": "Lösungen"}), "/ui/solution"),
    ("missing-ui-strings", _set("source_lang", "pl"), "/ui"),
    ("noun-without-article", _set("vocabulary/items/5/term", "Zeitung"),
     "/vocabulary/items/5/term"),
    ("noun-without-article", _set("story/scenes/1/picture/labels/0/term", "Tasse"),
     "/story/scenes/1/picture/labels/0/term"),
    ("label-draws-instead", lambda d: d["story"]["scenes"][1]["picture"].pop("svg"), "/tasks/3"),
    ("grammar-gives-away",
     _set("grammar/0/examples", ["Zum Geburtstag gibt es einen großen Kuchen."]), "/grammar/0"),
    # a single gap answer the learner has to produce, shown in an example
    ("grammar-gives-away",
     _chain(lambda d: d["grammar"].append({**PASSIVE_GRAMMAR,
                                           "examples": ["Das Brot wird gebacken."]}),
            _add_task(PASSIVE_TASK)),
     "/grammar/1"),
    # ... or in a table cell
    ("grammar-gives-away",
     _chain(lambda d: d["grammar"].append({**PASSIVE_GRAMMAR, "table": {
         "head": ["", "werden"], "rows": [["sie", "werden … geputzt"]]}}),
            _add_task(PASSIVE_TASK)),
     "/grammar/1"),
    # a table that conjugates the very verb the gap asks for
    ("grammar-gives-away",
     _chain(lambda d: d["grammar"].append({
         "id": "g2", "name": "Modalverben", "explanation": "Modal verbs.",
         "rule": "Modalverb … Infinitiv",
         "table": {"head": ["", "müssen"], "rows": [["ihr", "müsst"], ["er", "muss"]]}}),
            _add_task({"id": "t9", "kind": "cloze", "stage": "form", "scene": "s2",
                       "grammar": "g2", "hint": "base_form",
                       "items": ["Ihr {{müsst::müssen}} heute die Tische putzen."]})),
     "/grammar/1"),
    # a near-copy: two answers of one item in one example
    ("grammar-gives-away",
     _chain(lambda d: d["grammar"].append({
         **PASSIVE_GRAMMAR, "examples": ["Am Abend werden die Tische geputzt."]}),
            _add_task({**PASSIVE_TASK, "items": [
                "Danach {{werden::werden}} die Tische {{geputzt|gereinigt::putzen}}."]})),
     "/grammar/1"),
    # a table form inside a rewritten sentence
    ("grammar-gives-away",
     _chain(lambda d: d["grammar"].append({
         "id": "g2", "name": "Perfekt", "explanation": "The perfect tense.",
         "rule": "haben + Partizip II",
         "table": {"head": ["", "haben"], "rows": [["er / sie", "sie hat gebacken"]]}}),
            _add_task({"id": "t9", "kind": "transform", "stage": "form", "scene": "s2",
                       "grammar": "g2",
                       "items": [{"prompt": "Anna backt am Sonntag.", "cue": "Perfekt",
                                  "answer": "Anna hat gebacken, am Sonntag."}]})),
     "/grammar/1"),
    # in a word-box task only near-copies count
    ("grammar-gives-away",
     _set("grammar/0/examples", ["Mein Bruder trinkt gern Kaffee."]), "/grammar/0"),
]


@pytest.mark.parametrize(("code", "mutate", "where"), CASES,
                         ids=[f"{c[0]}-{i}" for i, c in enumerate(CASES)])
def test_mutation_triggers_code(
    code: str, mutate: Mutation, where: str | None, tmp_path: Path,
) -> None:
    issues = _issues(_mutated(mutate), base_dir=tmp_path)
    hits = [i for i in issues if i.code == code]
    assert hits, f"expected {code}, got {[(i.code, i.where) for i in issues]}"
    assert all(i.level == CHECKS[code][0] for i in hits)
    if where is not None:
        assert where in [i.where for i in hits]
    assert all(len(i.message) > 30 for i in hits)


#: Codes found while reading the file (see the check_file tests below).
FILE_CODES = {"contract", "legacy-format", "no-picture-attached", "wrapped-json", "normalized"}

#: Codes of the new kinds and extensions whose checks are not written yet;
#: each implementation removes its line here and exercises its codes.
PENDING_CODES = {
    "scramble-alternative", "scramble-punctuation", "scramble-capital",
    "category-unused",
    "tf-no-not-given", "tf-quote-missing", "tf-quote-not-in-story", "tf-not-given-correction",
    "writing-no-model-answer", "point-not-covered",
    "choice-options",
    "table-shape", "table-nothing-to-do", "table-too-wide",
    "gapped-text-gaps", "gapped-text-no-extra",
    "find-not-in-text",
    "frame-gaps", "keyword-not-used", "answer-too-long", "frame-and-answer",
    "answer-ignores-starter",
    "crossword-word", "crossword-layout", "clue-is-answer",
    "duplicate-entry",
    "task-count",
}


def test_every_check_is_exercised() -> None:
    covered = {c[0] for c in CASES} | FILE_CODES
    assert covered == set(CHECKS) - PENDING_CODES


def test_environment_and_picture_codes_are_checks() -> None:
    assert ENVIRONMENT_CODES <= set(CHECKS)
    assert PICTURE_CODES <= set(CHECKS)
    assert all(CHECKS[c][0] == "error" for c in PICTURE_CODES)


# ---------------------------------------------------------------------------
# Finer points
# ---------------------------------------------------------------------------


def test_target_mismatch_message_names_the_item_spelling() -> None:
    issues = _issues(_mutated(_set("vocabulary/target/4", "Fenster")))
    msg = next(i.message for i in issues if i.code == "target-not-in-items")
    assert "das Fenster" in msg


def test_unknown_scene_suggests_valid_ids() -> None:
    issues = _issues(_mutated(_set("tasks/1/scene", "S1")))
    msg = next(i.message for i in issues if i.code == "unknown-scene")
    assert "'s1'" in msg and "'s2'" in msg


def test_hinted_gaps_satisfy_base_form() -> None:
    data = _mutated(_chain(
        _set("tasks/2/hint", "base_form"),
        _set("tasks/2/items", ["Mein Bruder {{trinkt::trinken}} gern Kaffee."]),
    ))
    assert "missing-gap-hint" not in {i.code for i in _issues(data)}


def test_story_length_ranges_cover_all_levels() -> None:
    assert list(STORY_WORDS) == ["A1", "A2", "B1", "B2", "C1", "C2"]
    assert STORY_WORDS["B1"] == (220, 450)


def test_elided_articles_are_accepted_for_french() -> None:
    data = _mutated(_chain(
        _set("target_lang", "fr"),
        _set("vocabulary/items/5/term", "l’école"),
        _set("vocabulary/items/6/term", "l'hôtel"),
    ))
    data["vocabulary"]["items"][6]["pos"] = "noun"
    issues = _issues(data)
    flagged = [i.where for i in issues if i.code == "noun-without-article"]
    assert "/vocabulary/items/5/term" not in flagged
    assert "/vocabulary/items/6/term" not in flagged
    # German-style terms are not French articles
    assert "/vocabulary/items/0/term" in flagged


def test_no_article_check_for_english_targets() -> None:
    data = _mutated(_chain(_set("source_lang", "de"), _set("target_lang", "en")))
    assert "noun-without-article" not in {i.code for i in _issues(data)}


def _png(path: Path) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("L", (40, 30), 255).save(path, "PNG")
    return path


def _image_case(image: str) -> dict[str, Any]:
    return _mutated(_chain(lambda d: d["story"]["scenes"][1]["picture"].pop("svg"),
                           _set("story/scenes/1/picture/image", image)))


def _picture_codes(data: dict[str, Any], base_dir: Path) -> set[str]:
    return {i.code for i in _issues(data, base_dir=base_dir)} & (PICTURE_CODES | {"svg-text"})


def test_existing_image_and_urls_are_fine(tmp_path: Path) -> None:
    png = _png(tmp_path / "space dir" / "pic.png")
    for image in ("space dir/pic.png", "https://example.org/cafe.jpg",
                  "HTTPS://EXAMPLE.ORG/CAFE.JPG", str(png), png.as_uri(),
                  "data:image/svg+xml;utf8," + SVG):
        assert _picture_codes(_image_case(image), tmp_path) == set(), image


def test_image_resolution_matches_the_renderer(tmp_path: Path) -> None:
    assert resolve_image("HTTPS://example.org/x.png", tmp_path).kind == "url"
    assert resolve_image("data:image/png;base64,AAAA", tmp_path).kind == "data"
    assert resolve_image("ftp://example.org/x.png", tmp_path).kind == "unsupported"
    local = resolve_image("file:///tmp/space%20dir/pic.png", tmp_path)
    assert local.kind == "file" and local.path == Path("/tmp/space dir/pic.png")
    assert resolve_image("pics/a.jpg", tmp_path).path == tmp_path / "pics" / "a.jpg"
    assert resolve_image("~/a.jpg", tmp_path).path == Path.home() / "a.jpg"
    issues = _issues(_image_case("ftp://example.org/x.png"), base_dir=tmp_path)
    assert "image-not-found" in {i.code for i in issues}


def test_picture_problems_are_errors_only_when_the_picture_is_needed(tmp_path: Path) -> None:
    needed = _issues(_image_case("missing.jpg"), base_dir=tmp_path)
    assert [i.level for i in needed if i.code == "image-not-found"] == ["error"]
    # labels and label task removed: the picture is decoration, the renderer leaves it out
    data = _mutated(_chain(
        _drop_tasks("t4"),
        _set("story/scenes/1/picture", {"image": "missing.jpg"}),
    ))
    issues = _issues(data, base_dir=tmp_path)
    assert [i.level for i in issues if i.code == "image-not-found"] == ["warning"]
    # a picture-stage task makes it needed again
    data["tasks"].append({"id": "t9", "kind": "questions", "stage": "picture", "scene": "s2",
                          "items": [{"question": "Was steht auf dem Tisch?"}]})
    issues = _issues(data, base_dir=tmp_path)
    assert [i.level for i in issues if i.code == "image-not-found"] == ["error"]
    assert "'t9'" in next(i.message for i in issues if i.code == "image-not-found")


def test_missing_image_message_is_for_the_user_and_suggests_a_similar_file(tmp_path: Path) -> None:
    _png(tmp_path / "puesto.png")
    issue = next(i for i in _issues(_image_case("puesto.jpg"), base_dir=tmp_path)
                 if i.code == "image-not-found")
    assert "'puesto.png'" in issue.message and str(tmp_path) in issue.message
    assert "svg" not in issue.message  # never 'draw your own svg' for a photo


def test_unreadable_images(tmp_path: Path) -> None:
    (tmp_path / "notes.png").write_text("not an image", encoding="utf-8")
    (tmp_path / "empty.jpg").write_bytes(b"")
    good = _png(tmp_path / "cut.png").read_bytes()
    (tmp_path / "cut.png").write_bytes(good[: len(good) // 2])
    for name in ("notes.png", "empty.jpg", "cut.png"):
        issues = _issues(_image_case(name), base_dir=tmp_path)
        hits = [i for i in issues if i.code == "image-unreadable"]
        assert [i.level for i in hits] == ["error"], name
        assert "BytesIO" not in hits[0].message


def test_heic_photos_get_a_conversion_tip(tmp_path: Path) -> None:
    try:
        import pillow_heif  # noqa: F401
    except ImportError:
        pass
    else:
        pytest.skip("pillow-heif is installed, so HEIC photos are readable")
    (tmp_path / "IMG_4711.HEIC").write_bytes(b"\x00\x00\x00\x18ftypheic" + b"\x00" * 64)
    issue = next(i for i in _issues(_image_case("IMG_4711.HEIC"), base_dir=tmp_path)
                 if i.code == "image-unreadable")
    assert "JPEG" in issue.message and "pillow-heif" in issue.message


def test_svg_files_and_data_uris_are_parsed_as_svg(tmp_path: Path) -> None:
    # a broken file is the user's to fix, a broken data: URI in the JSON the LLM's
    (tmp_path / "broken.svg").write_text(BROKEN_SVG, encoding="utf-8")
    assert _picture_codes(_image_case("broken.svg"), tmp_path) == {"image-unreadable"}
    assert _picture_codes(_image_case("data:image/svg+xml;utf8," + BROKEN_SVG), tmp_path) == {
        "svg-invalid"}
    (tmp_path / "words.svg").write_text(TEXT_SVG, encoding="utf-8")
    assert _picture_codes(_image_case("words.svg"), tmp_path) == set()


def test_svg_invalid_message_locates_the_error() -> None:
    issues = _issues(_mutated(_set("story/scenes/1/picture/svg", BROKEN_SVG)))
    issue = next(i for i in issues if i.code == "svg-invalid")
    assert issue.level == "error" and "line 1" in issue.message and "&amp;" in issue.message


def test_svg_without_namespace_and_marker_numbers_are_fine() -> None:
    svg = "<svg viewBox='0 0 10 10'><text x='1' y='1'>1</text><use href='#a'/></svg>"
    issues = _issues(_mutated(_set("story/scenes/1/picture/svg", svg)))
    assert not {i.code for i in issues} & {"svg-invalid", "svg-text", "svg-external"}


def test_svg_text_is_fine_without_a_label_task() -> None:
    data = _mutated(_chain(_drop_tasks("t4"), _set("story/scenes/1/picture/svg", TEXT_SVG)))
    assert "svg-text" not in {i.code for i in _issues(data)}


def test_numbers_in_image_allow_labels_without_position() -> None:
    data = _mutated(_chain(
        _set("story/scenes/1/picture/labels/0/x", None),
        _set("story/scenes/1/picture/numbers_in_image", True),
    ))
    assert "label-without-position" not in {i.code for i in _issues(data)}


def test_german_participles_count_as_use() -> None:
    data = _mutated(_chain(
        lambda d: d["vocabulary"]["items"].append(
            {"term": "rösten", "translation": "to roast", "pos": "verb"}),
        lambda d: d["vocabulary"]["target"].append("rösten"),
        _set("story/scenes/1/text", BASE["story"]["scenes"][1]["text"]
             + " Die Bohnen sind frisch geröstet."),
        _set("tasks/2/items/2", "Der Kaffee wird jeden Tag frisch {{geröstet}}."),
        _set("tasks/4/must_use", ["der Kaffee", "trinken", "das Fenster", "rösten"]),
    ))
    codes = {(i.code, i.where) for i in _issues(data)}
    assert ("target-not-in-story", "/vocabulary/target/5") not in codes
    assert ("target-underused", "/vocabulary/target/5") not in codes


def test_comprehension_tasks_may_quote_the_story() -> None:
    copied = "Dann trinkt er noch eine {{Tasse}} Kaffee."
    for stage in ("gist", "detail"):
        data = _mutated(_chain(_set("tasks/2/items/0", copied), _set("tasks/2/stage", stage)))
        assert "copies-story" not in {i.code for i in _issues(data)}


def test_copies_story_message_names_the_stage() -> None:
    copied = "Dann trinkt er noch eine {{Tasse}} Kaffee."
    data = _mutated(_chain(_set("tasks/2/items/0", copied), _set("tasks/2/stage", "form")))
    issue = next(i for i in _issues(data) if i.code == "copies-story")
    assert issue.message.startswith("this form item")


def test_transform_answer_copying_the_story_is_flagged() -> None:
    task = {"id": "t9", "kind": "transform", "stage": "practice", "scene": "s2",
            "items": [{"prompt": "Er trinkt noch eine Tasse Kaffee. (dann)",
                       "answer": "Dann trinkt er noch eine Tasse Kaffee."}]}
    issues = _issues(_mutated(_add_task(task)))
    assert ("copies-story", "/tasks/5/items/0") in {(i.code, i.where) for i in issues}


def test_transform_frame_copying_the_story_is_flagged() -> None:
    task = {"id": "t9", "kind": "transform", "stage": "form", "scene": "s2",
            "items": [{"prompt": "Er trinkt noch eine Tasse Kaffee. (dann)", "keyword": "dann",
                       "frame": "{{Dann trinkt er}} noch eine Tasse Kaffee."}]}
    issues = _issues(_mutated(_add_task(task)))
    assert ("copies-story", "/tasks/5/items/0") in {(i.code, i.where) for i in issues}


def test_gap_markup_is_read_in_every_gap_field() -> None:
    tasks = [
        {"id": "t9", "kind": "table", "stage": "practice", "scene": "s1",
         "caption": "Die {{Karte}}", "head": ["Getränk", "Preis"],
         "rows": [["{{Kaffee}}", "2 Euro"], ["Tee", None]]},
        {"id": "t10", "kind": "proofread", "stage": "practice", "scene": "s2",
         "text": "Anna {{backt::backen}} einen Kuchen."},
        {"id": "t11", "kind": "gapped_text", "stage": "practice", "scene": "s2",
         "text": "Anna backt. {{Der Kuchen ist warm.}} Herr Kaya isst.",
         "extra": ["Es {{regnet}}."]},
        {"id": "t12", "kind": "transform", "stage": "form", "scene": "s2",
         "items": [{"prompt": "Anna backt.", "frame": "Anna {{hat gebacken}}."}]},
    ]
    data = _mutated(_chain(*(_add_task(t) for t in tasks)))
    outside = {i.where for i in _issues(data) if i.code == "markup-outside-gaps"}
    assert outside == {"/tasks/5/caption", "/tasks/7/extra/0"}


def test_missing_target_item_is_reported_once() -> None:
    issues = _issues(_mutated(_set("vocabulary/target/4", "Fenster")))
    at_four = {i.code for i in issues if i.where == "/vocabulary/target/4"}
    assert at_four == {"target-not-in-items"}


def test_whole_story_task_may_list_several_scenes() -> None:
    data = _mutated(_set("tasks/1/scene", ["s1", "s2"]))
    assert "task-without-scene" not in {i.code for i in _issues(data)}
    one_scene = _mutated(_chain(lambda d: d["story"]["scenes"].pop(0),
                                lambda d: d["tasks"][1].pop("scene"),
                                lambda d: d["facts"][0].pop("scene")))
    assert "task-without-scene" not in {i.code for i in _issues(one_scene)}


def test_model_answer_within_the_slack_is_fine() -> None:
    data = _mutated(_set("tasks/4/model_answer", MODEL_ANSWER))
    codes = {i.code for i in _issues(data)}
    assert not codes & {"model-answer-length", "model-answer-missing-must-use"}
    # 18 words for 20–40 is within 15 %
    short = " ".join(MODEL_ANSWER.split()[:17]) + " Fenster."
    assert "model-answer-length" not in {i.code for i in _issues(
        _mutated(_set("tasks/4/model_answer", short)))}


def test_must_use_matches_inflected_forms() -> None:
    answer = MODEL_ANSWER.replace("trinke", "trank").replace("am Fenster", "an den Fenstern")
    data = _mutated(_set("tasks/4/model_answer", answer))
    assert "model-answer-missing-must-use" not in {i.code for i in _issues(data)}


def test_true_statements_need_no_correction() -> None:
    data = _mutated(lambda d: d["tasks"][1]["items"][1].pop("correction", None))
    assert "tf-missing-correction" not in {i.code for i in _issues(data)}


@pytest.mark.parametrize("line", [
    "{{Anna}} bringt den Kuchen.",          # a character's name
    "{{Kuchen}} gibt es heute nicht.",      # a German noun
    "Ja. {{Herr}} Kaya lächelt.",           # capitalised in the story too
    "Möchten Sie {{Tee}} oder Kaffee?",     # not at the start
    "Heute nicht. {{noch}} mehr Kaffee?",   # lower case
])
def test_gap_at_sentence_start_that_gives_nothing_away(line: str) -> None:
    task = {**DIALOGUE_BANK, "lines": [{"speaker": "Anna", "text": line},
                                        {"speaker": "Herr Kaya", "text": "Danke."}]}
    data = _mutated(_add_task(task))
    assert "gap-starts-sentence" not in {i.code for i in _issues(data)}


def test_gap_after_opening_quote_or_question_mark_starts_a_sentence() -> None:
    for text in ("Er fragt: „{{Warum}} lächelt er?“", "Wirklich? {{Warum}} nicht?"):
        data = _mutated(_add_task({**DIALOGUE_BANK, "lines": [
            {"speaker": "Anna", "text": text}, {"speaker": "Herr Kaya", "text": "Danke."}]}))
        assert "gap-starts-sentence" in {i.code for i in _issues(data)}, text


def test_base_form_hint_equal_to_the_answer_is_fine() -> None:
    data = _mutated(_chain(
        _set("tasks/2/hint", "base_form"),
        _set("tasks/2/items", ["Die Gäste {{trinken::trinken}} gern Kaffee."]),
    ))
    assert "hint-is-answer" not in {i.code for i in _issues(data)}


def test_same_stem_with_other_article_and_meaning_is_not_a_duplicate() -> None:
    data = _mutated(lambda d: d["vocabulary"]["items"] + [])
    data["vocabulary"]["items"] += [
        {"term": "der See", "translation": "lake", "pos": "noun"},
        {"term": "die See", "translation": "sea", "pos": "noun"},
    ]
    assert "duplicate-item" not in {i.code for i in _issues(data)}


def test_pos_missing_suggests_noun_for_an_article() -> None:
    data = _mutated(lambda d: d["vocabulary"]["items"][5].pop("pos"))
    issue = next(i for i in _issues(data) if i.code == "pos-missing")
    assert "'die Zeitung'" in issue.message and '"pos": "noun"' in issue.message


def test_valid_ui_overrides_pass() -> None:
    ui = {"kind.writing.length": "Schreibe {min} bis {max} Wörter.",
          "kind.label.draw": "Zeichne „{scene}“.", "solutions": "Lösungen {:"}
    assert "ui-placeholders" not in {i.code for i in _issues(_mutated(_set("ui", ui)))}


def test_grammar_about_the_hinted_word_is_not_a_leak() -> None:
    data = _mutated(_chain(lambda d: d["grammar"].append(copy.deepcopy(PASSIVE_GRAMMAR)),
                           _add_task(PASSIVE_TASK)))
    assert "grammar-gives-away" not in {i.code for i in _issues(data)}


def test_short_function_words_alone_are_not_a_leak() -> None:
    data = _mutated(_chain(
        _set("grammar/0/examples", ["Heute backt sie einen Kuchen für die Gäste."]),
        _set("tasks/2/hint", "none"),
        _set("tasks/2/items", ["Mein Bruder trinkt {{die}} Milch.",
                               "Wir essen {{einen}} Apfel und trinken Tee."]),
    ))
    assert "grammar-gives-away" not in {i.code for i in _issues(data)}


def test_messages_use_the_worksheets_own_words() -> None:
    data = _mutated(_set("tasks/2/items/1", "Die Tasse steht auf dem Tisch."))
    message = next(i.message for i in _issues(data) if i.code == "cloze-without-gaps")
    assert "{{Kaffee}}" in message
    data = _mutated(_add_task({"id": "t9", "kind": "label", "stage": "picture", "scene": "s1"}))
    message = next(i.message for i in _issues(data) if i.code == "label-without-labels")
    assert '"der Kaffee"' in message


# ---------------------------------------------------------------------------
# Report and check_file
# ---------------------------------------------------------------------------


def test_report_properties_and_serialisation() -> None:
    issues = [
        Issue("error", "unknown-scene", "/tasks/1/scene", "there is no scene s9"),
        Issue("warning", "no-facts", "/facts", "add facts"),
    ]
    report = Report(issues, None)
    assert not report.ok
    assert report.errors == issues[:1] and report.warnings == issues[1:]
    data = report.to_dict()
    assert json.loads(json.dumps(data)) == data
    assert data["ok"] is False and data["error_count"] == 1 and data["warning_count"] == 1
    assert data["issues"][0] == {"level": "error", "code": "unknown-scene",
                                 "where": "/tasks/1/scene", "message": "there is no scene s9"}
    text = report.format_text()
    assert text.index("Errors") < text.index("Warnings")
    assert "[unknown-scene]" in text and "/facts" in text
    assert Report([], None).format_text().startswith("OK")
    assert Report(issues[1:], None).ok


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_check_file_ok(tmp_path: Path) -> None:
    report = check_file(_write(tmp_path, "ok.json", json.dumps(BASE, ensure_ascii=False)))
    assert report.ok and report.issues == [] and report.worksheet is not None


def test_check_file_resolves_images_next_to_the_json(tmp_path: Path) -> None:
    path = _write(tmp_path, "ws.json", json.dumps(_image_case("pic.png"), ensure_ascii=False))
    assert "image-not-found" in {i.code for i in check_file(path).issues}
    _png(tmp_path / "pic.png")
    assert check_file(path).issues == []


def test_svg_wins_over_image_like_in_the_renderer(tmp_path: Path) -> None:
    data = _mutated(_set("story/scenes/1/picture/image", "missing.png"))
    assert _picture_codes(data, tmp_path) == set()


def test_check_file_contract_errors(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    del data["title"]
    data["tasks"][0]["colour"] = "red"
    report = check_file(_write(tmp_path, "bad.json", json.dumps(data)))
    assert not report.ok and report.worksheet is None
    by_where = {i.where: i for i in report.issues}
    assert by_where["/title"].code == "contract"
    assert "'title'" in by_where["/title"].message
    assert "/tasks/0/colour" in by_where
    assert all(i.level == "error" for i in report.issues)


def test_check_file_legacy_hint(tmp_path: Path) -> None:
    legacy = {"title": "Kaffee", "content": "Kaffee wächst in den Tropen.", "vocabulary": []}
    report = check_file(_write(tmp_path, "v2.json", json.dumps(legacy)))
    codes = [i.code for i in report.issues]
    assert "contract" in codes and "legacy-format" in codes
    legacy_issue = next(i for i in report.issues if i.code == "legacy-format")
    assert "langwich prompt --from-json" in legacy_issue.message


def test_check_file_invalid_json_is_friendly(tmp_path: Path) -> None:
    report = check_file(_write(tmp_path, "broken.json", '{"title": "x",\n  "tasks": [1, 2,]\n}'))
    assert [i.code for i in report.issues] == ["contract"]
    assert "line 2" in report.issues[0].message


def test_check_file_missing_and_folder(tmp_path: Path) -> None:
    missing = check_file(tmp_path / "nope.json")
    assert missing.issues[0].code == "contract" and "not found" in missing.issues[0].message
    folder = check_file(tmp_path)
    assert folder.issues[0].code == "contract" and not folder.ok


def test_check_file_code_fence_and_bom(tmp_path: Path) -> None:
    fenced = "```json\n" + json.dumps(BASE, ensure_ascii=False) + "\n```\n"
    path = tmp_path / "fenced.json"
    path.write_text(fenced, encoding="utf-8-sig")
    report = check_file(path)
    assert report.ok and [i.code for i in report.issues] == ["wrapped-json"]
    assert "code fence" in report.issues[0].message


@pytest.mark.parametrize("wrap", [
    "Here is your worksheet:\n\n```json\n{}\n```\n",
    "```json\n{}\n```\n\nLet me know if you want changes!",
    "{}\n\nI hope this helps.",
    "Sure! {}",
], ids=["prose-before", "prose-after", "bare-prose-after", "prose-same-line"])
def test_check_file_extracts_json_from_chat_replies(tmp_path: Path, wrap: str) -> None:
    body = json.dumps(BASE, ensure_ascii=False, indent=2)
    report = check_file(_write(tmp_path, "chat.json", wrap.replace("{}", body)))
    assert report.ok and report.worksheet is not None
    assert [(i.code, i.level) for i in report.issues] == [("wrapped-json", "warning")]


def test_check_file_broken_json_in_chat_reply_points_into_the_file(tmp_path: Path) -> None:
    body = json.dumps(BASE, ensure_ascii=False, indent=2).replace('"A1",', '"A1",,', 1)
    text = "Here is your worksheet:\n\n```json\n" + body + "\n```\n"
    report = check_file(_write(tmp_path, "chat.json", text))
    (issue,) = report.issues
    line = text.splitlines().index('  "cefr_level": "A1",,') + 1
    assert issue.code == "contract" and f"line {line}," in issue.message
    assert "code fence" in issue.message


def test_trailing_comma_hint_only_after_a_comma(tmp_path: Path) -> None:
    trailing = check_file(_write(tmp_path, "a.json", '{"title": "x",\n  "tasks": [1, 2,]\n}'))
    assert "trailing comma" in trailing.issues[0].message
    missing = check_file(_write(tmp_path, "b.json", '{"title": "x",\n  "tasks": [1, 2\n}'))
    assert "trailing comma" not in missing.issues[0].message
    prose = check_file(_write(tmp_path, "c.json", "Sorry, I cannot do that."))
    assert "trailing comma" not in prose.issues[0].message
    assert "no JSON object" in prose.issues[0].message


def test_check_file_no_picture_sentinel(tmp_path: Path) -> None:
    for text in ("NO PICTURE ATTACHED\n", "`NO PICTURE ATTACHED.`"):
        report = check_file(_write(tmp_path, "nopic.json", text))
        assert [(i.code, i.level) for i in report.issues] == [("no-picture-attached", "error")]
        assert "attach" in report.issues[0].message.lower()
        assert not report.partial and MORE_CHECKS_NOTE not in report.format_text()


def test_check_file_normalises_llm_quirks(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    data["cefr_level"] = "a1"
    data["target_lang"] = "DE"
    data["facts"] = ["Brasilien produziert den meisten Kaffee der Welt."]
    data["tasks"][1]["kind"] = "True-or-False"
    data["tasks"][2]["kind"] = "fill_in_the_blanks"
    report = check_file(_write(tmp_path, "quirks.json", json.dumps(data, ensure_ascii=False)))
    assert report.ok and report.worksheet is not None
    notes = {(i.code, i.where) for i in report.issues}
    assert notes >= {("normalized", "/cefr_level"), ("normalized", "/target_lang"),
                     ("normalized", "/facts"), ("normalized", "/tasks/1/kind"),
                     ("normalized", "/tasks/2/kind")}
    assert all(i.level == "warning" for i in report.issues)
    assert report.worksheet.tasks[2].kind == "cloze" and report.worksheet.cefr_level == "A1"
    # a quirk plus a real problem: the note is kept next to the contract error
    data["tasks"][2]["colour"] = "red"
    report = check_file(_write(tmp_path, "quirks.json", json.dumps(data, ensure_ascii=False)))
    assert {("normalized", "warning"), ("contract", "error")} <= {
        (i.code, i.level) for i in report.issues}


def test_only_contract_errors_say_more_checks_will_follow(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    del data["title"]
    report = check_file(_write(tmp_path, "bad.json", json.dumps(data)))
    assert report.partial and report.format_text().endswith(MORE_CHECKS_NOTE)
    ok = check_file(_write(tmp_path, "ok.json", json.dumps(BASE)))
    assert not ok.partial and MORE_CHECKS_NOTE not in ok.format_text()
    legacy = check_file(_write(tmp_path, "v2.json", json.dumps({"title": "x", "content": "y"})))
    assert not legacy.partial


def test_environment_issues_are_listed_separately(tmp_path: Path) -> None:
    report = validate(worksheet_from_dict(_image_case("missing.jpg")), base_dir=tmp_path)
    assert [i.code for i in report.environment_issues] == ["image-not-found"]


def test_contract_errors_have_clean_pointers_and_suggestions(tmp_path: Path) -> None:
    data = copy.deepcopy(BASE)
    data["tasks"][1]["scene"] = 5
    data["tasks"][3]["kind"] = "labelz"
    data["tasks"][0]["pairz"] = []
    data["source_lang"] = "English"
    report = check_file(_write(tmp_path, "bad.json", json.dumps(data)))
    by_where = {i.where: i.message for i in report.issues}
    assert "/tasks/1/scene" in by_where and "scene id" in by_where["/tasks/1/scene"]
    assert not any("str" in w.rsplit("/", 1)[-1] for w in by_where)
    assert "did you mean 'label'" in by_where["/tasks/3"]
    assert "did you mean 'pairs'" in by_where["/tasks/0/pairz"]
    assert "did you mean 'en'" in by_where["/source_lang"]
