"""End-to-end render smoke tests for both bundled examples."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from langwich.cli import main
from langwich.text import SourceText

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"

ALL_EXERCISES = ",".join([
    "fib_word_bank", "fib_first_letter", "fib_multiple_choice",
    "fib_translation_hint", "fib_base_form", "fib_no_hint",
    "fib_full_translation",
    "pic_color_query", "pic_element_marking", "pic_position",
    "pic_object_naming", "pic_scene_description", "pic_fib",
    "wc_translation", "wc_synonym", "wc_antonym", "wc_category", "wc_compound",
    "media_video_search", "media_article_search", "media_fact_hunt",
])


def _page_count(pdf_path: Path) -> int:
    data = pdf_path.read_bytes()
    return data.count(b"/Type /Page") - data.count(b"/Type /Pages")


@pytest.mark.parametrize("example", [
    "coffee_en_de.json", "coffee_de_fr.json", "film_de_fr.json",
])
def test_examples_render_end_to_end(tmp_path, example):
    out = tmp_path / "worksheet.pdf"
    main([
        "--from-json", str(EXAMPLES / example),
        "--exercises", ALL_EXERCISES,
        "-o", str(out),
    ])
    assert out.exists()
    assert out.stat().st_size > 10_000
    assert _page_count(out) >= 5


def test_default_selection_renders(tmp_path):
    out = tmp_path / "default.pdf"
    main(["--from-json", str(EXAMPLES / "coffee_en_de.json"), "-o", str(out)])
    assert out.exists()


def test_bundled_examples_parse():
    for path in sorted(EXAMPLES.glob("*.json")):
        text = SourceText.from_dict(json.loads(path.read_text(encoding="utf-8")))
        assert text.vocabulary and len(text.vocabulary.items) >= 20
        assert text.picture_scene and text.picture_scene.elements
        assert text.grammar and text.grammar.phenomena


def test_from_dict_accepts_bare_lists():
    # vocabulary/grammar may be given as bare lists instead of {"items": []}
    text = SourceText.from_dict({
        "title": "t", "content": "Ein Satz.", "translation": "One sentence.",
        "source_lang": "en", "target_lang": "de", "cefr_level": "A1",
        "topic": "test",
        "vocabulary": [{"term": "der Satz", "translation": "sentence", "pos": "noun"}],
        "grammar": [{"name": "x", "description": "y"}],
    })
    assert text.vocabulary.items[0].term == "der Satz"
    assert text.grammar.phenomena[0].name == "x"
