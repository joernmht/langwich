"""Smoke tests: build a whole worksheet end to end and assert it renders."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from langwich.cli import select_exercises
from langwich.graph import build_default_graph
from langwich.plan import build_worksheet
from langwich.render import render_worksheet
from langwich.text import SourceText


EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


def _examples() -> list[Path]:
    out = []
    for p in sorted(EXAMPLES_DIR.glob("*.json")):
        with open(p) as f:
            data = json.load(f)
        if all(k in data for k in ("title", "content", "translation",
                                   "source_lang", "target_lang",
                                   "cefr_level", "topic")):
            out.append(p)
    return out


@pytest.mark.parametrize("json_path", _examples(), ids=lambda p: p.name)
def test_default_selection_renders(json_path: Path) -> None:
    with open(json_path) as f:
        data = json.load(f)
    text = SourceText.from_dict(data)
    graph = build_default_graph()

    node_ids = select_exercises(graph, text, focus=[])
    assert node_ids, "auto-selection must choose at least one exercise"

    exercises, _ = build_worksheet(text, node_ids, graph)
    assert exercises, "at least one exercise must be generated"

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "worksheet.pdf"
        result = render_worksheet(text, exercises, out)
        assert result.exists() and result.stat().st_size > 1000


def test_all_exercise_types_render() -> None:
    with open(EXAMPLES_DIR / "coffee_en_de.json") as f:
        data = json.load(f)
    text = SourceText.from_dict(data)
    graph = build_default_graph()

    all_ids = [n.id for n in graph.exercises()]
    exercises, skipped = build_worksheet(text, all_ids, graph)
    assert len(exercises) >= 12

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "worksheet.pdf"
        result = render_worksheet(text, exercises, out)
        assert result.exists() and result.stat().st_size > 2000
