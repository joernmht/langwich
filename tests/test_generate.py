"""Per-exercise-type generation tests using the coffee example."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from langwich.generate import generate_exercise
from langwich.graph import build_default_graph, ExerciseNode
from langwich.text import SourceText


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def coffee_data() -> dict:
    with open(EXAMPLES_DIR / "coffee_en_de.json") as f:
        return json.load(f)


@pytest.fixture
def coffee_text(coffee_data: dict) -> SourceText:
    return SourceText.from_dict(coffee_data)


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

    def test_compound_uses_compound_data(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "wc_compound"), coffee_text)
        assert ex is not None
        assert ex.items[0]["left"] and ex.items[0]["right"]
        assert all("compound" in s for s in ex.solution)

    def test_compound_returns_none_without_data(self, coffee_data: dict, graph) -> None:
        data = dict(coffee_data)
        data.pop("compounds", None)
        text = SourceText.from_dict(data)
        ex = generate_exercise(_node(graph, "wc_compound"), text)
        assert ex is None

    def test_returns_none_without_vocabulary(self, graph) -> None:
        text = SourceText(
            title="t", content="c", translation="tr",
            source_lang="en", target_lang="de",
            cefr_level="A1", topic="test",
        )
        ex = generate_exercise(_node(graph, "wc_translation"), text)
        assert ex is None


# ---------------------------------------------------------------------------
# No-overlap planner + topic-agnostic generation
# ---------------------------------------------------------------------------

from langwich.plan import build_worksheet  # noqa: E402
from langwich.text import PictureScene, SceneElement  # noqa: E402


class TestNoOverlap:
    def test_no_sentence_reused_across_exercises(
        self, coffee_text: SourceText, graph,
    ) -> None:
        node_ids = ["fib_word_bank", "fib_translation_hint", "fib_no_hint"]
        exercises, _ = build_worksheet(coffee_text, node_ids, graph, seed=0)
        seen: set[str] = set()
        for ex in exercises:
            for item in ex.items:
                sentence = item.get("sentence")
                if sentence:
                    assert sentence not in seen, f"sentence reused: {sentence}"
                    seen.add(sentence)

    def test_exercises_follow_difficulty_order(
        self, coffee_text: SourceText, graph,
    ) -> None:
        node_ids = ["pic_object_naming", "fib_word_bank", "wc_translation"]
        exercises, _ = build_worksheet(coffee_text, node_ids, graph, seed=0)
        types = [ex.exercise_type for ex in exercises]
        # Word connections warm-up comes before the picture task.
        assert types.index("word_connections") < types.index("picture")


class TestTopicAgnostic:
    """Picture generation must read scene facts, never hard-coded content."""

    def _farm_text(self) -> SourceText:
        return SourceText(
            title="Auf dem Bauernhof",
            content="Auf dem Hof steht ein grüner Traktor neben der roten Scheune. "
                    "Ein gelbes Huhn sitzt auf dem Zaun.",
            translation="On the farm a green tractor stands next to the red barn. "
                        "A yellow hen sits on the fence.",
            source_lang="en", target_lang="de", cefr_level="A1", topic="farm",
            picture_scene=PictureScene(
                description="A farmyard with a tractor, a barn and a hen.",
                elements=[
                    SceneElement(name="der Traktor", color="grün",
                                 position="Der Traktor steht neben der Scheune."),
                    SceneElement(name="die Scheune", color="rot"),
                    SceneElement(name="das Huhn", color="gelb"),
                ],
            ),
        )

    def test_color_query_uses_scene_colors(self, graph) -> None:
        text = self._farm_text()
        ex = generate_exercise(_node(graph, "pic_color_query"), text)
        assert ex is not None
        answers = {s["answer"] for s in ex.solution}
        assert answers == {"grün", "rot", "gelb"}
        # No coffee leakage.
        assert "weiß" not in answers

    def test_object_naming_uses_scene_elements(self, graph) -> None:
        text = self._farm_text()
        ex = generate_exercise(_node(graph, "pic_object_naming"), text)
        assert ex is not None
        names = {s["answer"] for s in ex.solution}
        assert names == {"der Traktor", "die Scheune", "das Huhn"}
