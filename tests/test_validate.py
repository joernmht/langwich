"""Tests for langwich.validate: one clean fixture plus one mutation per check."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from langwich.model import worksheet_from_dict
from langwich.validate import CHECKS, STORY_WORDS, Issue, Report, check_file, validate

REPO_ROOT = Path(__file__).resolve().parent.parent
LENA = REPO_ROOT / "examples" / "lena_01_en_de.json"

SVG = '<svg viewBox="0 0 100 60" xmlns="http://www.w3.org/2000/svg"><rect width="100" height="60"/></svg>'

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
    ("empty-gap", _set("tasks/2/items/0", "Mein Bruder trinkt {{ }} mit Milch."),
     "/tasks/2/items/0"),
    ("unbalanced-braces", _set("tasks/2/items/0", "Mein Bruder trinkt {{Kaffee}} mit {{Milch."),
     "/tasks/2/items/0"),
    ("markup-in-story", _set("story/scenes/0/text", BASE["story"]["scenes"][0]["text"]
                             + " Sie {{lächelt}}."), "/story/scenes/0/text"),
    ("label-without-labels", _add_task({"id": "t9", "kind": "label", "stage": "picture",
                                        "scene": "s1"}), "/tasks/5/scene"),
    ("duplicate-label-number", _set("story/scenes/1/picture/labels/1/n", 1),
     "/story/scenes/1/picture/labels/1/n"),
    ("label-without-position", _set("story/scenes/1/picture/labels/0/x", None),
     "/story/scenes/1/picture/labels/0"),
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
    ("distractor-is-answer", _set("tasks/2/distractors", ["Kuchen"]), "/tasks/2/distractors/0"),
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
    ("image-not-found",
     _chain(lambda d: d["story"]["scenes"][1]["picture"].pop("svg"),
            _set("story/scenes/1/picture/image", "pictures/missing.jpg")),
     "/story/scenes/1/picture/image"),
    ("label-draws-instead", lambda d: d["story"]["scenes"][1]["picture"].pop("svg"), "/tasks/3"),
    ("grammar-gives-away",
     _set("grammar/0/examples", ["Zum Geburtstag gibt es einen großen Kuchen."]), "/grammar/0"),
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


def test_every_check_is_exercised() -> None:
    covered = {c[0] for c in CASES} | {"contract", "legacy-format", "code-fence"}
    assert covered == set(CHECKS)


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


def test_existing_image_and_urls_are_fine(tmp_path: Path) -> None:
    (tmp_path / "pic.png").write_bytes(b"\x89PNG")
    for image in ("pic.png", "https://example.org/cafe.jpg", str(tmp_path / "pic.png")):
        data = _mutated(_set("story/scenes/1/picture/image", image))
        assert "image-not-found" not in {i.code for i in _issues(data, base_dir=tmp_path)}


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


def test_practice_stage_only_for_copies() -> None:
    copied = "Dann trinkt er noch eine {{Tasse}} Kaffee."
    data = _mutated(_chain(_set("tasks/2/items/0", copied), _set("tasks/2/stage", "form")))
    assert "copies-story" not in {i.code for i in _issues(data)}


def test_transform_answer_copying_the_story_is_flagged() -> None:
    task = {"id": "t9", "kind": "transform", "stage": "practice", "scene": "s2",
            "items": [{"prompt": "Er trinkt noch eine Tasse Kaffee. (dann)",
                       "answer": "Dann trinkt er noch eine Tasse Kaffee."}]}
    issues = _issues(_mutated(_add_task(task)))
    assert ("copies-story", "/tasks/5/items/0") in {(i.code, i.where) for i in issues}


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
    data = _mutated(_set("story/scenes/1/picture/image", "pic.png"))
    path = _write(tmp_path, "ws.json", json.dumps(data, ensure_ascii=False))
    assert "image-not-found" in {i.code for i in check_file(path).issues}
    (tmp_path / "pic.png").write_bytes(b"\x89PNG")
    assert "image-not-found" not in {i.code for i in check_file(path).issues}


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
    assert report.ok and [i.code for i in report.issues] == ["code-fence"]
