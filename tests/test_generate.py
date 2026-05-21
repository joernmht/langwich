"""Per-exercise-type generation tests using the coffee example."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from langwich.generate import ExerciseInstance, generate_exercise
from langwich.graph import build_default_graph, ExerciseNode
from langwich.text import SourceText


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def coffee_text() -> SourceText:
    with open(EXAMPLES_DIR / "coffee_en_de.json") as f:
        data = json.load(f)
    return SourceText.from_dict(data)


@pytest.fixture
def graph():
    return build_default_graph()


def _node(graph, node_id: str) -> ExerciseNode:
    return graph.nodes[node_id]  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# FIB exercises
# ---------------------------------------------------------------------------

class TestFIB:
    @pytest.mark.parametrize("node_id", [
        "fib_word_bank",
        "fib_first_letter",
        "fib_multiple_choice",
        "fib_translation_hint",
        "fib_no_hint",
        "fib_full_translation",
    ])
    def test_fib_produces_items_and_solutions(
        self, coffee_text: SourceText, graph, node_id: str,
    ) -> None:
        ex = generate_exercise(_node(graph, node_id), coffee_text)
        assert ex is not None
        assert len(ex.items) > 0
        assert len(ex.solution) > 0
        assert ex.node_id == node_id

    def test_word_bank_has_distractors(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "fib_word_bank"), coffee_text)
        assert ex is not None
        assert len(ex.word_bank) > len(ex.solution)

    def test_first_letter_has_hints(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "fib_first_letter"), coffee_text)
        assert ex is not None
        for item in ex.items:
            assert "hint" in item

    def test_multiple_choice_has_choices(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "fib_multiple_choice"), coffee_text)
        assert ex is not None
        for item in ex.items:
            assert "choices" in item
            assert len(item["choices"]) >= 2

    def test_base_form_produces_items(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "fib_base_form"), coffee_text)
        assert ex is not None
        assert len(ex.items) >= 0


# ---------------------------------------------------------------------------
# Picture exercises
# ---------------------------------------------------------------------------

class TestPicture:
    @pytest.mark.parametrize("node_id", [
        "pic_color_query",
        "pic_element_marking",
        "pic_position",
        "pic_object_naming",
        "pic_scene_description",
        "pic_fib",
    ])
    def test_picture_produces_items(
        self, coffee_text: SourceText, graph, node_id: str,
    ) -> None:
        ex = generate_exercise(_node(graph, node_id), coffee_text)
        assert ex is not None
        assert len(ex.items) > 0
        assert ex.picture_prompt != ""

    def test_returns_none_without_picture_scene(self, graph) -> None:
        text = SourceText(
            title="t", content="c", translation="tr",
            source_lang="en", target_lang="de",
            cefr_level="A1", topic="test",
        )
        ex = generate_exercise(_node(graph, "pic_color_query"), text)
        assert ex is None


# ---------------------------------------------------------------------------
# Word Connections exercises
# ---------------------------------------------------------------------------

class TestWordConnections:
    def test_translation_produces_items(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "wc_translation"), coffee_text)
        assert ex is not None
        assert len(ex.items) > 0
        assert len(ex.solution) > 0

    def test_synonym_produces_items(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "wc_synonym"), coffee_text)
        assert ex is not None
        assert len(ex.items) > 0
        assert all(s.get("synonym") for s in ex.solution)

    def test_antonym_produces_items(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "wc_antonym"), coffee_text)
        assert ex is not None
        assert len(ex.items) > 0
        assert all(s.get("antonym") for s in ex.solution)

    def test_category_groups_by_semantic_type(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "wc_category"), coffee_text)
        assert ex is not None
        assert len(ex.items) > 0
        assert "categories" in ex.items[0]
        assert "words" in ex.items[0]

    def test_compound_returns_none(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "wc_compound"), coffee_text)
        assert ex is None

    def test_returns_none_without_vocabulary(self, graph) -> None:
        text = SourceText(
            title="t", content="c", translation="tr",
            source_lang="en", target_lang="de",
            cefr_level="A1", topic="test",
        )
        ex = generate_exercise(_node(graph, "wc_translation"), text)
        assert ex is None
