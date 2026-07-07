"""End-to-end rendering test: all exercise types into one PDF."""

import json
from pathlib import Path

import pytest

from langwich.generate import generate_exercise
from langwich.graph import build_default_graph
from langwich.render import render_worksheet
from langwich.text import SourceText

EXAMPLE = Path(__file__).parent.parent / "examples" / "coffee_en_de.json"


@pytest.fixture()
def text() -> SourceText:
    with open(EXAMPLE, encoding="utf-8") as f:
        return SourceText.from_dict(json.load(f))


def test_render_full_task_library(tmp_path, text):
    graph = build_default_graph()
    exercises = []
    for node in sorted(graph.exercises(), key=lambda n: n.id):
        ex = generate_exercise(node, text)
        if ex:
            exercises.append(ex)
    assert len(exercises) >= 58

    out = render_worksheet(text, exercises, tmp_path / "full.pdf")
    assert out.exists()
    assert out.stat().st_size > 20_000
    data = out.read_bytes()
    assert data.startswith(b"%PDF")


def test_render_showcase_selection(tmp_path, text):
    graph = build_default_graph()
    node_ids = ["fib_word_bank", "pz_word_search", "media_podcast",
                "soc_chat", "st_reflection"]
    exercises = [generate_exercise(graph.nodes[nid], text) for nid in node_ids]
    out = render_worksheet(text, [e for e in exercises if e],
                           tmp_path / "showcase.pdf")
    assert out.exists() and out.stat().st_size > 10_000
