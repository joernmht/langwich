"""The langwich/3 contract: loading, friendly errors, JSON Schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from langwich.model import (
    NO_PICTURE_SENTINEL,
    TASK_KINDS,
    ContractError,
    Worksheet,
    canonical_kind,
    is_no_picture_reply,
    json_schema,
    load_worksheet,
    normalize_quirks,
    parse_json_text,
    parse_worksheet,
    worksheet_from_dict,
)

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
LENA = EXAMPLES / "lena_01_en_de.json"


def _lena() -> dict:
    return json.loads(LENA.read_text(encoding="utf-8"))


def test_reference_example_loads():
    ws = load_worksheet(LENA)
    assert isinstance(ws, Worksheet)
    assert ws.schema_id == "langwich/3"
    assert [s.id for s in ws.story.scenes] == ["s1", "s2", "s3", "s4"]
    assert ws.scene("s4").picture.has_visual


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.name)
def test_every_bundled_example_loads(path):
    load_worksheet(path)


def test_unknown_field_is_reported_with_pointer():
    data = _lena()
    data["tasks"][0]["pairz"] = []
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(data)
    locations = [loc for loc, _ in exc.value.problems]
    assert "/tasks/0/pairz" in locations


def test_discriminator_tag_is_dropped_from_pointer():
    data = _lena()
    data["tasks"][2]["items"][0].pop("answer")  # true_false item without answer
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(data)
    assert any(loc == "/tasks/2/items/0/answer" for loc, _ in exc.value.problems)


def test_multiple_choice_answer_must_be_an_option():
    data = _lena()
    mc = next(t for t in data["tasks"] if t["kind"] == "multiple_choice")
    mc["items"][0]["answer"] = "something else"
    with pytest.raises(ContractError, match="not one of the options"):
        worksheet_from_dict(data)


def test_cloze_needs_text_or_items():
    data = _lena()
    cloze = next(t for t in data["tasks"] if t["kind"] == "cloze")
    cloze["text"] = "Ein {{Test}}."
    cloze["items"] = ["Noch ein {{Test}}."]
    with pytest.raises(ContractError, match="exactly one"):
        worksheet_from_dict(data)


def test_pos_is_normalised_and_checked():
    data = _lena()
    data["vocabulary"]["items"][0]["pos"] = "NOUN"
    assert worksheet_from_dict(data).vocabulary.items[0].pos == "noun"
    data["vocabulary"]["items"][0]["pos"] = "thing"
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


def test_legacy_v2_file_gets_upgrade_hint(tmp_path):
    legacy = {"title": "Kaffee", "content": "Text.", "translation": "Text.",
              "source_lang": "en", "target_lang": "de", "cefr_level": "B1",
              "topic": "coffee", "vocabulary": {"items": []}}
    path = tmp_path / "old.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    with pytest.raises(ContractError) as exc:
        load_worksheet(path)
    assert "langwich prompt --from-json" in str(exc.value)


def test_wrong_schema_id():
    data = _lena()
    data["schema"] = "langwich/2"
    with pytest.raises(ContractError, match="langwich/3"):
        worksheet_from_dict(data)


def test_invalid_json_and_missing_file(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{\n  'single quotes': 1\n}", encoding="utf-8")
    with pytest.raises(ContractError, match="line 2"):
        load_worksheet(bad)
    with pytest.raises(ContractError, match="not found"):
        load_worksheet(tmp_path / "missing.json")


def test_utf8_bom_is_accepted(tmp_path):
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + LENA.read_bytes())
    assert load_worksheet(path).title == "Fünf Tage im Café Lindner"


def test_svg_must_be_svg():
    data = _lena()
    data["story"]["scenes"][3]["picture"]["svg"] = "<div>not a drawing</div>"
    with pytest.raises(ContractError, match="svg"):
        worksheet_from_dict(data)


def test_json_schema_covers_every_task_kind():
    schema = json_schema()
    text = json.dumps(schema)
    for kind in TASK_KINDS:
        assert f'"{kind}"' in text
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert "schema" in schema["properties"]


def test_round_trip_by_alias():
    ws = load_worksheet(LENA)
    again = worksheet_from_dict(json.loads(ws.model_dump_json(by_alias=True, exclude_none=True)))
    assert again == ws


def test_task_scene_ids_accepts_str_list_and_none():
    data = copy.deepcopy(_lena())
    data["tasks"][2]["scene"] = ["s1", "s2"]
    ws = worksheet_from_dict(data)
    assert ws.tasks[2].scene_ids == ["s1", "s2"]
    assert ws.tasks[0].scene_ids == []


# ---------------------------------------------------------------------------
# Lenient loading
# ---------------------------------------------------------------------------


def _text() -> str:
    return LENA.read_text(encoding="utf-8")


@pytest.mark.parametrize("wrap", [
    "Here is your worksheet:\n\n```json\n{}\n```\n",
    "```\n{}\n```\nLet me know if you want changes!",
    "{}\nI hope this helps.",
    "Sure — the JSON: {}  Enjoy!",
])
def test_wrapped_json_is_extracted_with_a_note(wrap):
    ws, notes = parse_worksheet(wrap.replace("{}", _text().strip()))
    assert ws.title == "Fünf Tage im Café Lindner"
    assert [n.code for n in notes] == ["wrapped-json"]
    assert "start with {" in notes[0].message


def test_plain_json_has_no_notes():
    ws, notes = parse_worksheet(_text())
    assert notes == [] and ws.schema_id == "langwich/3"


def test_a_nested_object_is_never_mistaken_for_the_worksheet():
    text = 'Here: {"broken": \n{"id": "t1", "kind": "match"}\n'
    with pytest.raises(ContractError) as exc:
        parse_json_text(text)
    assert exc.value.code == "contract"


def test_broken_json_inside_a_fence_reports_the_file_line():
    body = _text().replace('"cefr_level": "B1",', '"cefr_level": "B1" "x",', 1)
    text = "Here you go:\n```json\n" + body + "```\n"
    with pytest.raises(ContractError) as exc:
        parse_json_text(text)
    line = next(i for i, ln in enumerate(text.splitlines(), 1) if '"cefr_level": "B1" "x"' in ln)
    message = exc.value.problems[0][1]
    assert f"line {line}," in message and "inside the code fence" in message


def test_no_trailing_comma_repair():
    text = _text().replace('"cefr_level": "B1",', '"cefr_level": "B1",,', 1)
    with pytest.raises(ContractError, match="trailing comma"):
        parse_json_text(text)


def test_no_picture_sentinel_is_its_own_error():
    for text in ("NO PICTURE ATTACHED", "  no picture attached.\n", '"NO PICTURE ATTACHED"'):
        assert is_no_picture_reply(text)
        with pytest.raises(ContractError) as exc:
            parse_worksheet(text)
        assert exc.value.code == "no-picture-attached"
        assert NO_PICTURE_SENTINEL in exc.value.problems[0][1]
    assert not is_no_picture_reply("NO PICTURE ATTACHED, but here is a worksheet: {}")


def test_empty_file_message(tmp_path):
    path = tmp_path / "empty.json"
    path.write_text("\n", encoding="utf-8")
    with pytest.raises(ContractError, match="empty"):
        load_worksheet(path)


def test_quirks_are_normalised_with_notes():
    data = _lena()
    data["cefr_level"] = "b1"
    data["source_lang"] = "EN"
    data["facts"] = [f["text"] for f in data["facts"]]
    aliases = {0: "matching", 1: "multiple-choice", 2: "True or False", 3: "fill_in_the_blank"}
    for index, alias in aliases.items():
        data["tasks"][index]["kind"] = alias
    original = [t["kind"] for t in _lena()["tasks"]]
    notes = normalize_quirks(data)
    assert data["cefr_level"] == "B1" and data["source_lang"] == "en"
    assert all(isinstance(f, dict) and f["text"] for f in data["facts"])
    for index, alias in aliases.items():
        assert data["tasks"][index]["kind"] == canonical_kind(alias)
    assert all(n.code == "normalized" for n in notes)
    assert {n.where for n in notes} >= {"/cefr_level", "/source_lang", "/facts"}
    assert [t["kind"] for t in data["tasks"]][4:] == original[4:]


@pytest.mark.parametrize(("alias", "kind"), [
    ("multiple-choice", "multiple_choice"), ("mcq", "multiple_choice"),
    ("fill_in_the_blanks", "cloze"), ("gap_fill", "cloze"), ("true_or_false", "true_false"),
    ("matching", "match"), ("ordering", "order_events"), ("short_answer", "questions"),
    ("essay", "writing"), ("drawing", "draw"), ("Cloze", "cloze"), ("quiz", None),
])
def test_canonical_kind(alias, kind):
    assert canonical_kind(alias) == kind


def test_load_worksheet_collects_notes(tmp_path):
    path = tmp_path / "fenced.json"
    path.write_text("```json\n" + _text() + "```", encoding="utf-8")
    notes: list = []
    assert load_worksheet(path, notes).title == "Fünf Tage im Café Lindner"
    assert [n.code for n in notes] == ["wrapped-json"]


def test_contract_error_keeps_the_notes():
    data = _lena()
    data["tasks"][0]["kind"] = "matching"
    data["tasks"][0]["colour"] = "red"
    with pytest.raises(ContractError) as exc:
        parse_worksheet(json.dumps(data))
    assert [n.where for n in exc.value.notes] == ["/tasks/0/kind"]
    assert [loc for loc, _ in exc.value.problems] == ["/tasks/0/colour"]


# ---------------------------------------------------------------------------
# Friendly contract messages
# ---------------------------------------------------------------------------


def _problems(data) -> dict[str, str]:
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(data)
    return dict(exc.value.problems)


def test_union_tags_never_appear_in_pointers():
    data = _lena()
    data["tasks"][2]["scene"] = 7
    data["tasks"][3]["scene"] = [7]
    problems = _problems(data)
    assert set(problems) == {"/tasks/2/scene", "/tasks/3/scene/0"}
    assert "scene id" in problems["/tasks/2/scene"]


def test_unknown_kind_and_field_get_did_you_mean():
    data = _lena()
    data["tasks"][0]["kind"] = "multiple_choise"
    data["tasks"][1]["pairz"] = []
    data["tasks"][1]["kind"] = "match"
    problems = _problems(data)
    assert "did you mean 'multiple_choice'" in problems["/tasks/0"]
    assert "did you mean 'pairs'" in problems["/tasks/1/pairz"]


def test_object_expected_message_gives_an_example():
    data = _lena()
    data["tasks"].append("write a story")
    problems = _problems(data)
    assert "JSON object" in problems[f"/tasks/{len(data['tasks']) - 1}"]
    data = _lena()
    data["vocabulary"]["items"][0] = "der Kaffee"
    message = _problems(data)["/vocabulary/items/0"]
    assert '"term"' in message and '"translation"' in message and "plain string" in message


def test_literal_and_pattern_messages():
    data = _lena()
    data["tasks"][0]["stage"] = "warmup"
    data["target_lang"] = "German"
    data["story"]["characters"][0]["id"] = "lena mayer"
    problems = _problems(data)
    assert "did you mean 'warm_up'" in problems["/tasks/0/stage"]
    assert "did you mean 'de'" in problems["/target_lang"]
    assert "letters, digits" in problems["/story/characters/0/id"]


def test_multiple_choice_message_lists_options_and_near_match():
    data = _lena()
    mc = next(t for t in data["tasks"] if t["kind"] == "multiple_choice")
    right = mc["items"][0]["answer"]
    mc["items"][0]["answer"] = right.upper()
    index = data["tasks"].index(mc)
    message = _problems(data)[f"/tasks/{index}/items/0"]
    assert f"did you mean {right!r}" in message
    assert all(repr(o) in message for o in mc["items"][0]["options"])
    assert not message.startswith("Value error")


def test_missing_field_mentions_its_purpose():
    data = _lena()
    del data["story"]["logline"]
    assert "who wants what" in _problems(data)["/story/logline"]
