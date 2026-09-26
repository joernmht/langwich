"""The langwich/3 contract: loading, friendly errors, JSON Schema."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from langwich.model import (
    TASK_KINDS,
    ContractError,
    Worksheet,
    json_schema,
    load_worksheet,
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
