"""Round-trip tests for SourceText serialisation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from langwich.graph import SemanticType
from langwich.text import PictureScene, SourceText


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


@pytest.fixture
def coffee_data() -> dict:
    with open(EXAMPLES_DIR / "coffee_en_de.json") as f:
        return json.load(f)


@pytest.fixture
def coffee_text(coffee_data: dict) -> SourceText:
    return SourceText.from_dict(coffee_data)


class TestFromDict:
    def test_scalar_fields(self, coffee_text: SourceText) -> None:
        assert coffee_text.title == "Kaffee: Vom Feld bis ins Café"
        assert coffee_text.source_lang == "en"
        assert coffee_text.target_lang == "de"
        assert coffee_text.cefr_level == "B1"
        assert coffee_text.topic == "coffee"

    def test_picture_scene_loaded(self, coffee_text: SourceText) -> None:
        assert coffee_text.picture_scene is not None
        assert isinstance(coffee_text.picture_scene, PictureScene)
        assert coffee_text.picture_scene.paragraph_index == 4
        assert len(coffee_text.picture_scene.elements) > 0

    def test_vocabulary_loaded(self, coffee_text: SourceText) -> None:
        assert coffee_text.vocabulary is not None
        assert len(coffee_text.vocabulary.items) == 38

    def test_grammar_loaded(self, coffee_text: SourceText) -> None:
        assert coffee_text.grammar is not None
        assert len(coffee_text.grammar.phenomena) == 3
        assert coffee_text.grammar.has_phenomenon("passive voice")

    def test_semantic_type_preserved(self, coffee_text: SourceText) -> None:
        vocab = coffee_text.vocabulary
        assert vocab is not None
        kaffee = next(v for v in vocab.items if v.term == "der Kaffee")
        assert kaffee.semantic_type == SemanticType.DRINK
        weiss = next(v for v in vocab.items if v.term == "weiß")
        assert weiss.semantic_type == SemanticType.COLOR
        theke = next(v for v in vocab.items if v.term == "die Theke")
        assert theke.semantic_type == SemanticType.FURNITURE

    def test_semantic_type_defaults_to_other(self) -> None:
        data = {
            "title": "t", "content": "c", "translation": "tr",
            "source_lang": "en", "target_lang": "de",
            "cefr_level": "A1", "topic": "test",
            "vocabulary": {
                "items": [{"term": "x", "translation": "y", "pos": "noun"}]
            },
        }
        text = SourceText.from_dict(data)
        assert text.vocabulary is not None
        assert text.vocabulary.items[0].semantic_type == SemanticType.OTHER

    def test_synonym_antonym_loaded(self, coffee_text: SourceText) -> None:
        vocab = coffee_text.vocabulary
        assert vocab is not None
        kraeftig = next(v for v in vocab.items if v.term == "kräftig")
        assert kraeftig.synonym == "stark"
        assert kraeftig.antonym == "mild"

    def test_flat_vocabulary_list(self) -> None:
        data = {
            "title": "t", "content": "c", "translation": "tr",
            "source_lang": "en", "target_lang": "de",
            "cefr_level": "A1", "topic": "test",
            "vocabulary": [
                {"term": "a", "translation": "b", "pos": "noun"},
            ],
        }
        text = SourceText.from_dict(data)
        assert text.vocabulary is not None
        assert len(text.vocabulary.items) == 1

    def test_paragraphs(self, coffee_text: SourceText) -> None:
        paras = coffee_text.paragraphs
        assert len(paras) == 6
        assert paras[0].startswith("Nur wenige")

    def test_picture_paragraph(self, coffee_text: SourceText) -> None:
        pp = coffee_text.picture_paragraph
        assert pp is not None
        assert "Café" in pp


class TestRoundTrip:
    def test_to_dict_from_dict(self, coffee_text: SourceText) -> None:
        d = coffee_text.to_dict()
        rebuilt = SourceText.from_dict(d)

        assert rebuilt.title == coffee_text.title
        assert rebuilt.content == coffee_text.content
        assert rebuilt.source_lang == coffee_text.source_lang
        assert rebuilt.cefr_level == coffee_text.cefr_level

    def test_vocabulary_round_trip(self, coffee_text: SourceText) -> None:
        d = coffee_text.to_dict()
        rebuilt = SourceText.from_dict(d)

        assert rebuilt.vocabulary is not None
        assert coffee_text.vocabulary is not None
        assert len(rebuilt.vocabulary.items) == len(coffee_text.vocabulary.items)

    def test_semantic_type_round_trip(self, coffee_text: SourceText) -> None:
        d = coffee_text.to_dict()
        rebuilt = SourceText.from_dict(d)

        assert rebuilt.vocabulary is not None
        assert coffee_text.vocabulary is not None
        for orig, rt in zip(coffee_text.vocabulary.items, rebuilt.vocabulary.items):
            assert rt.semantic_type == orig.semantic_type, (
                f"{rt.term}: {rt.semantic_type} != {orig.semantic_type}"
            )

    def test_grammar_round_trip(self, coffee_text: SourceText) -> None:
        d = coffee_text.to_dict()
        rebuilt = SourceText.from_dict(d)

        assert rebuilt.grammar is not None
        assert coffee_text.grammar is not None
        assert len(rebuilt.grammar.phenomena) == len(coffee_text.grammar.phenomena)

    def test_picture_scene_round_trip(self, coffee_text: SourceText) -> None:
        d = coffee_text.to_dict()
        rebuilt = SourceText.from_dict(d)

        assert rebuilt.picture_scene is not None
        assert coffee_text.picture_scene is not None
        assert rebuilt.picture_scene.description == coffee_text.picture_scene.description
        assert rebuilt.picture_scene.elements == coffee_text.picture_scene.elements
        assert rebuilt.picture_scene.paragraph_index == coffee_text.picture_scene.paragraph_index
