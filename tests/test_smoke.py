"""Smoke tests: load example JSON, render PDF, assert it is non-empty."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from langwich.generate import generate_exercise
from langwich.graph import build_default_graph
from langwich.render import render_worksheet
from langwich.text import SourceText


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
COFFEE_JSON = EXAMPLES_DIR / "coffee_en_de.json"


def _loadable_examples() -> list[Path]:
    """Return example JSONs that conform to the SourceText schema."""
    results = []
    for p in sorted(EXAMPLES_DIR.glob("*.json")):
        with open(p) as f:
            data = json.load(f)
        if all(k in data for k in ("title", "content", "translation",
                                    "source_lang", "target_lang",
                                    "cefr_level", "topic")):
            results.append(p)
    return results


@pytest.mark.parametrize("json_path", _loadable_examples(), ids=lambda p: p.name)
def test_smoke_render(json_path: Path) -> None:
    with open(json_path) as f:
        data = json.load(f)
    text = SourceText.from_dict(data)
    graph = build_default_graph()

    default_ids = ["fib_word_bank", "pic_color_query", "wc_translation"]
    exercises = []
    for nid in default_ids:
        node = graph.nodes[nid]
        ex = generate_exercise(node, text)  # type: ignore[arg-type]
        if ex:
            exercises.append(ex)

    assert len(exercises) > 0, "at least one exercise must be generated"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "worksheet.pdf"
        result = render_worksheet(text, exercises, out)
        assert result.exists()
        assert result.stat().st_size > 0


def test_smoke_all_exercise_types() -> None:
    with open(COFFEE_JSON) as f:
        data = json.load(f)
    text = SourceText.from_dict(data)
    graph = build_default_graph()

    exercises = []
    for node in graph.exercises():
        ex = generate_exercise(node, text)
        if ex:
            exercises.append(ex)

    assert len(exercises) >= 10

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "worksheet.pdf"
        result = render_worksheet(text, exercises, out)
        assert result.exists()
        assert result.stat().st_size > 1000
