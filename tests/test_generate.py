"""Tests for exercise generation across the full task library."""

import json
from pathlib import Path

import pytest

from langwich.generate import generate_exercise
from langwich.graph import ExerciseType, build_default_graph
from langwich.text import SourceText

EXAMPLE = Path(__file__).parent.parent / "examples" / "coffee_en_de.json"


@pytest.fixture(scope="module")
def text() -> SourceText:
    with open(EXAMPLE, encoding="utf-8") as f:
        return SourceText.from_dict(json.load(f))


@pytest.fixture(scope="module")
def graph():
    return build_default_graph()


def test_every_exercise_type_generates_from_example(text, graph):
    failed = []
    for node in graph.exercises():
        ex = generate_exercise(node, text)
        if ex is None:
            failed.append(node.id)
    assert not failed, f"could not generate: {failed}"


def test_instances_carry_instruction_and_items(text, graph):
    for node in graph.exercises():
        ex = generate_exercise(node, text)
        assert ex is not None, node.id
        assert ex.node_id == node.id
        assert ex.items, node.id
        assert ex.instruction, node.id


def test_media_exercises_have_qr_resource(text, graph):
    for node in graph.get_by_type(ExerciseType.MEDIA):
        ex = generate_exercise(node, text)
        assert ex is not None, node.id
        assert ex.resource.get("url", "").startswith("https://"), node.id
        assert ex.resource.get("title"), node.id


def test_media_resource_matches_target_language(text, graph):
    node = graph.nodes["media_podcast"]
    ex = generate_exercise(node, text)
    assert ex.resource["language"] == "de"


def test_semantic_types_parsed_from_json(text):
    color_items = [v for v in text.vocabulary.items
                   if v.semantic_type.value == "color"]
    assert len(color_items) == 3


def test_wc_compound_finds_text_compounds(text, graph):
    ex = generate_exercise(graph.nodes["wc_compound"], text)
    assert ex is not None
    compounds = [s["compound"] for s in ex.solution]
    assert "Kaffeepflanze" in compounds


def test_error_correction_solutions_map_back(text, graph):
    ex = generate_exercise(graph.nodes["ta_error_correction"], text)
    assert ex is not None
    for item, sol in zip(ex.items, ex.solution):
        wrong, correct = (p.strip() for p in sol["answer"].split("→"))
        assert wrong in item["task"]
        assert wrong != correct


def test_micro_post_offers_hashtags(text, graph):
    ex = generate_exercise(graph.nodes["soc_micro_post"], text)
    banks = [i["bank"] for i in ex.items if "bank" in i]
    assert banks and all(h.startswith("#") for h in banks[0])


def test_localized_instructions_for_german_learner(graph):
    with open(EXAMPLE, encoding="utf-8") as f:
        data = json.load(f)
    data["source_lang"] = "de"
    text_de = SourceText.from_dict(data)
    ex = generate_exercise(graph.nodes["media_podcast"], text_de)
    assert "QR-Code" in ex.instruction


def test_unknown_target_language_still_generates_media(graph):
    with open(EXAMPLE, encoding="utf-8") as f:
        data = json.load(f)
    data["target_lang"] = "nl"
    text_nl = SourceText.from_dict(data)
    ex = generate_exercise(graph.nodes["media_video"], text_nl)
    assert ex is not None
    assert ex.resource["url"].startswith("https://")
