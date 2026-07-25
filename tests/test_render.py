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
    count = data.count(b"/Type /Page") - data.count(b"/Type /Pages")
    if count > 0:
        return count
    # WeasyPrint stores page objects inside compressed object streams —
    # decompress them and read /Count off the page tree.
    import re
    import zlib
    counts = []
    for m in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        try:
            blob = zlib.decompress(m.group(1).rstrip(b"\r\n"))
        except zlib.error:
            continue
        counts += [int(c) for c in
                   re.findall(rb"/Type /Pages[^>]*/Count (\d+)", blob)]
    return max(counts, default=0)


@pytest.mark.parametrize("example", [
    "coffee_en_de.json", "coffee_de_fr.json", "film_de_fr.json",
])
def test_examples_render_end_to_end(tmp_path, example):
    out = tmp_path / "worksheet.pdf"
    main([
        "--from-json", str(EXAMPLES / example),
        "--exercises", ALL_EXERCISES,
        "--allow-color",
        "-o", str(out),
    ])
    assert out.exists()
    assert out.stat().st_size > 10_000
    assert _page_count(out) >= 5


def test_default_selection_renders(tmp_path):
    out = tmp_path / "default.pdf"
    main(["--from-json", str(EXAMPLES / "coffee_en_de.json"), "-o", str(out)])
    assert out.exists()


def test_one_task_per_page(tmp_path):
    # 5 exercises → at least reading page + one page per task.
    exercises = "fib_word_bank,fib_first_letter,wc_translation,wc_synonym,wc_compound"
    out = tmp_path / "one_per_page.pdf"
    main([
        "--from-json", str(EXAMPLES / "coffee_en_de.json"),
        "--exercises", exercises,
        "-o", str(out),
    ])
    assert _page_count(out) >= 1 + len(exercises.split(","))


def test_color_exercise_skipped_without_allow_color(tmp_path, capsys):
    out = tmp_path / "no_color.pdf"
    main([
        "--from-json", str(EXAMPLES / "coffee_en_de.json"),
        "--exercises", "pic_color_query,fib_word_bank",
        "-o", str(out),
    ])
    assert out.exists()
    assert "colour exercise 'pic_color_query'" in capsys.readouterr().err


def test_html_engine_writes_html_and_pdf(tmp_path):
    pytest.importorskip("weasyprint")
    out = tmp_path / "html_engine.pdf"
    main(["--from-json", str(EXAMPLES / "coffee_en_de.json"), "-o", str(out)])
    html_out = out.with_suffix(".html")
    assert out.exists() and html_out.exists()
    content = html_out.read_text(encoding="utf-8")
    # one section per task + cover + references
    assert content.count('class="page task"') >= 4
    assert 'class="vocab"' in content  # per-page vocabulary bands


def test_reportlab_engine_still_works(tmp_path):
    out = tmp_path / "reportlab.pdf"
    main([
        "--from-json", str(EXAMPLES / "coffee_en_de.json"),
        "--engine", "reportlab",
        "-o", str(out),
    ])
    assert out.exists()
    assert not out.with_suffix(".html").exists()


def test_local_image_is_embedded(tmp_path):
    from PIL import Image as PILImage

    img_path = tmp_path / "scene.png"
    PILImage.new("RGB", (640, 480), (200, 30, 30)).save(img_path)

    out = tmp_path / "with_image.pdf"
    main([
        "--from-json", str(EXAMPLES / "coffee_en_de.json"),
        "--exercises", "pic_object_naming",
        "--image", str(img_path),
        "--image-credit", "Test image, public domain",
        "-o", str(out),
    ])
    assert out.exists()
    assert out.stat().st_size > 5_000


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
