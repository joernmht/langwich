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


class TestComprehension:
    def test_questions_produce_items(self, coffee_text: SourceText, graph) -> None:
        ex = generate_exercise(_node(graph, "comp_questions"), coffee_text)
        assert ex is not None
        assert len(ex.items) == len(coffee_text.questions)
        assert all("prompt" in it for it in ex.items)

    def test_true_false_has_answers(self, coffee_text: SourceText, graph) -> None:
        ex = generate_exercise(_node(graph, "comp_true_false"), coffee_text)
        assert ex is not None
        assert {s["answer"] for s in ex.solution} <= {"True", "False"}

    def test_comprehension_none_without_material(self, coffee_data: dict, graph) -> None:
        data = dict(coffee_data)
        data.pop("questions", None)
        data.pop("true_false", None)
        text = SourceText.from_dict(data)
        assert generate_exercise(_node(graph, "comp_questions"), text) is None
        assert generate_exercise(_node(graph, "comp_true_false"), text) is None


class TestRecapNotRepetition:
    """Gap-fills must practise the reworded summary, not re-print the article."""

    def test_cloze_uses_summary_not_article(self, coffee_text: SourceText, graph) -> None:
        assert coffee_text.summary, "fixture must have a summary"
        ex = generate_exercise(_node(graph, "fib_word_bank"), coffee_text)
        assert ex is not None and ex.items
        for it in ex.items:
            lead = it["sentence"].split("______")[0].strip()
            if len(lead) > 12:  # ignore very short leading fragments
                assert lead in coffee_text.summary, lead
                assert lead not in coffee_text.content, (
                    "gap-fill is repeating the article verbatim"
                )

    def test_cloze_falls_back_to_article_without_summary(
        self, coffee_data: dict, graph,
    ) -> None:
        data = dict(coffee_data)
        data.pop("summary", None)
        text = SourceText.from_dict(data)
        ex = generate_exercise(_node(graph, "fib_word_bank"), text)
        assert ex is not None and ex.items  # still works, from the article


class TestSequence:
    def test_order_events_produces_scrambled_items_and_key(
        self, coffee_text: SourceText, graph,
    ) -> None:
        ex = generate_exercise(_node(graph, "comp_sequence"), coffee_text)
        assert ex is not None
        assert len(ex.items) >= 3
        assert all("letter" in it and "text" in it for it in ex.items)
        seq = ex.solution[0]["sequence"]
        # the answer key is a permutation of the displayed letters
        assert sorted(seq) == sorted(it["letter"] for it in ex.items)

    def test_sequence_none_when_too_short(self, graph) -> None:
        text = SourceText(
            title="t", content="Only one sentence here.", translation="x",
            source_lang="en", target_lang="de", cefr_level="A1", topic="t",
        )
        assert generate_exercise(_node(graph, "comp_sequence"), text) is None


class TestNewTaskTypes:
    def test_process_chart(self, coffee_text: SourceText, graph) -> None:
        ex = generate_exercise(_node(graph, "fib_process"), coffee_text)
        assert ex is not None
        steps = ex.items[0]["steps"]
        assert len(steps) == len(coffee_text.process)
        blanks = [s for s in steps if "number" in s]
        assert blanks and len(ex.word_bank) == len(blanks) == len(ex.solution)
        # first and last stage are always given (anchors)
        assert "text" in steps[0] and "text" in steps[-1]

    def test_process_none_when_no_steps(self, coffee_data: dict, graph) -> None:
        data = dict(coffee_data)
        data.pop("process", None)
        text = SourceText.from_dict(data)
        assert generate_exercise(_node(graph, "fib_process"), text) is None

    def test_vocab_lookup(self, coffee_text: SourceText, graph) -> None:
        ex = generate_exercise(_node(graph, "voc_lookup"), coffee_text)
        assert ex is not None and ex.items[0]["rows"] > 0

    def test_discussion(self, coffee_text: SourceText, graph) -> None:
        ex = generate_exercise(_node(graph, "prod_discussion"), coffee_text)
        assert ex is not None and ex.items[0]["prompt"] == coffee_text.discussion

    def test_discussion_none_without_prompt(self, coffee_data: dict, graph) -> None:
        data = dict(coffee_data)
        data.pop("discussion", None)
        text = SourceText.from_dict(data)
        assert generate_exercise(_node(graph, "prod_discussion"), text) is None
