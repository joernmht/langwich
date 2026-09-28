"""questions with "starter" and "question_lang", media_search with its
"media" on the page: the contract, the answer-ignores-starter check, the HTML
and the answer key."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key
from langwich.model import ContractError, worksheet_from_dict
from langwich.plan import plan
from langwich.render import RenderOptions, build_html
from langwich.validate import Issue, validate

#: The validator codes these tests trigger (see tests/test_validate.py).
COVERED_CODES = {"answer-ignores-starter"}

REPO = Path(__file__).resolve().parent.parent
LENA = REPO / "examples" / "lena_01_en_de.json"
SHOWCASE = REPO / "tests" / "fixtures" / "kinds_showcase.json"

#: An A1-style gist task on scene 1 (it replaces the true_false task t3):
#: English questions, German starters on the answer lines, model answers
#: that begin with them — and one frame with a gap inside.
FIRST_MORNING: dict[str, Any] = {
    "id": "t3", "kind": "questions", "stage": "gist", "scene": "s1",
    "title": "Lena's first morning",
    "instruction": "Answer in German. Finish the sentence on each line.",
    "question_lang": "source",
    "items": [
        {"question": "Why is Lena nervous on her first morning?",
         "starter": "Lena ist nervös, weil …",
         "answer": "Lena ist nervös, weil Herr Novak schon am Fenster sitzt.", "lines": 2},
        {"question": "How does Herr Novak take his Melange?",
         "starter": "Er trinkt sie immer mit …",
         "answer": "Er trinkt sie immer mit drei Löffeln Zucker.", "lines": 1},
        {"question": "When does Lena have to make Herr Novak's Melange?",
         "starter": "Am … macht Lena seine Melange.",
         "answer": "Am Freitag macht Lena seine Melange.", "lines": 0},
    ],
}


def _lena(**items: Any) -> dict[str, Any]:
    """The Lena example with FIRST_MORNING as t3; ``items`` update its first item."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = copy.deepcopy(FIRST_MORNING)
    task["items"][0].update(items)
    index = next(i for i, t in enumerate(data["tasks"]) if t["id"] == "t3")
    data["tasks"][index] = task
    return data


def _issues(data: dict[str, Any]) -> list[Issue]:
    return validate(worksheet_from_dict(data)).issues


def _starter_issues(data: dict[str, Any]) -> list[Issue]:
    return [i for i in _issues(data) if i.code == "answer-ignores-starter"]


def _section(html: str, ws: Any, task_id: str) -> str:
    number = next(pt.number for pt in plan(ws).tasks if pt.task.id == task_id)
    match = re.search(rf'<section class="task unit[^"]*" id="task-{number}".*?</section>', html,
                      flags=re.S)
    assert match, task_id
    return match.group(0)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_question_lang_defaults_to_target_and_starter_to_none() -> None:
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = next(t for t in worksheet_from_dict(data).tasks if t.id == "t4")
    assert task.kind == "questions"
    assert task.question_lang == "target"
    assert all(item.starter is None for item in task.items)


def test_source_questions_with_starters_are_valid() -> None:
    task = next(t for t in worksheet_from_dict(_lena()).tasks if t.id == "t3")
    assert task.kind == "questions"
    assert task.question_lang == "source"
    assert task.items[0].starter == "Lena ist nervös, weil …"


@pytest.mark.parametrize("value", ["english", "src", "", None])
def test_question_lang_is_target_or_source(value: Any) -> None:
    data = _lena()
    next(t for t in data["tasks"] if t["id"] == "t3")["question_lang"] = value
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


def test_media_is_one_of_four() -> None:
    data = json.loads(LENA.read_text(encoding="utf-8"))
    next(t for t in data["tasks"] if t["id"] == "t14")["media"] = "radio"
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


# ---------------------------------------------------------------------------
# answer-ignores-starter
# ---------------------------------------------------------------------------


def test_answers_that_follow_their_starters_are_clean() -> None:
    assert _issues(_lena()) == []


@pytest.mark.parametrize("starter, answer", [
    # case, the trailing '...' and the whitespace of the starter do not count
    ("lena ist nervös, weil...", "Lena ist nervös, weil Herr Novak schon da ist."),
    ("Lena ist nervös,   weil  ", "Lena ist nervös, weil Herr Novak schon da ist."),
    # typographic and straight apostrophes and quote marks are the same
    ("Lena’s Hände zittern, weil …", "Lena's Hände zittern, weil Herr Novak schon da ist."),
    ("„Morgen wieder“, sagt …", '"Morgen wieder", sagt Herr Novak.'),
    # a gap inside the frame: the words around it, in order
    ("Seit … Jahren trinkt er dort Melange.", "Seit vierzig Jahren trinkt er dort Melange."),
    ("Lena ist ___, weil …", "Lena ist nervös, weil Herr Novak schon da ist."),
])
def test_starters_match_leniently(starter: str, answer: str) -> None:
    assert _starter_issues(_lena(starter=starter, answer=answer)) == []


@pytest.mark.parametrize("items", [
    {"answer": None},  # no model answer: the key says "Answers will vary."
    {"starter": None, "answer": "Weil Herr Novak schon da ist."},
])
def test_nothing_to_compare_is_clean(items: dict[str, Any]) -> None:
    assert _starter_issues(_lena(**items)) == []


def test_answer_that_ignores_its_starter_is_flagged() -> None:
    issues = _starter_issues(_lena(answer="Weil Herr Novak schon am Fenster sitzt."))
    assert len(issues) == 1
    issue = issues[0]
    assert issue.level == "warning"
    assert issue.where == "/tasks/2/items/0/answer"
    assert "'Weil Herr Novak schon am Fenster sitzt.'" in issue.message
    assert "does not begin with the starter 'Lena ist nervös, weil …'" in issue.message
    assert "word for word, and complete the sentence" in issue.message


def test_frame_with_a_gap_inside_asks_to_fill_it() -> None:
    data = _lena()
    next(t for t in data["tasks"] if t["id"] == "t3")["items"][2]["answer"] = (
        "Lena macht seine Melange am Freitag.")
    issues = _starter_issues(data)
    assert [i.where for i in issues] == ["/tasks/2/items/2/answer"]
    assert "does not follow the starter 'Am … macht Lena seine Melange.'" in issues[0].message
    assert "fill in each '…'" in issues[0].message


def test_a_changed_word_in_the_starter_is_flagged() -> None:
    issues = _starter_issues(_lena(answer="Lena war nervös, weil Herr Novak schon da ist."))
    assert [i.where for i in issues] == ["/tasks/2/items/0/answer"]


def test_target_language_questions_are_checked_too() -> None:
    data = _lena()
    task = next(t for t in data["tasks"] if t["id"] == "t4")
    task["items"][1]["starter"] = "Die Bauern ernten die Kaffeekirschen und …"
    assert [i.where for i in _starter_issues(data)] == ["/tasks/3/items/1/answer"]
    task["items"][1]["answer"] = "Die Bauern ernten die Kaffeekirschen und trocknen sie."
    assert _starter_issues(data) == []


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_source_questions_are_sans_with_the_source_language(page: str) -> None:
    ws = worksheet_from_dict(_lena())
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "t3")
    assert ('<p class="q src" lang="en">Why is Lena nervous on her first morning?</p>'
            in section)
    assert 'class="tl q"' not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_target_questions_stay_serif_with_the_target_language(page: str) -> None:
    ws = worksheet_from_dict(_lena())
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "t4")
    assert '<p class="tl q" lang="de">Wo wächst Kaffee?</p>' in section
    assert 'class="q src"' not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_starter_is_printed_on_the_first_answer_line(page: str) -> None:
    ws = worksheet_from_dict(_lena())
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "t3")
    blocks = re.findall(r'<div class="lines">(.*?</div>)</div>', section)
    assert blocks == [
        # two lines: the starter's line and one more
        '<div class="starter tl" lang="de">Lena ist nervös, weil …</div><div></div>',
        '<div class="starter tl" lang="de">Er trinkt sie immer mit …</div>',
        # "lines": 0 — the starter still gets its line
        '<div class="starter tl" lang="de">Am … macht Lena seine Melange.</div>',
    ]


def test_question_without_starter_or_lines_prints_no_lines() -> None:
    data = _lena(starter=None, lines=0)
    ws = worksheet_from_dict(data)
    section = _section(build_html(ws), ws, "t3")
    assert section.count('<div class="lines">') == 2


def test_questions_and_starters_are_escaped() -> None:
    ws = worksheet_from_dict(_lena(question="Why <b>nervous</b> & shy?", starter="Weil <i> …",
                                   answer="Weil <i> alles neu ist."))
    section = _section(build_html(ws), ws, "t3")
    assert "Why &lt;b&gt;nervous&lt;/b&gt; &amp; shy?" in section
    assert "Weil &lt;i&gt; …" in section
    assert "<b>" not in section and "<i>" not in section


def test_answer_key_prints_the_model_answers() -> None:
    ws = worksheet_from_dict(_lena())
    pt = next(pt for pt in plan(ws).tasks if pt.task.id == "t3")
    assert answer_key(pt, ws) == [item["answer"] for item in FIRST_MORNING["items"]]


@pytest.mark.parametrize("media", ["video", "article", "podcast", "image"])
def test_media_search_caption_names_the_media(media: str) -> None:
    data = json.loads(LENA.read_text(encoding="utf-8"))
    next(t for t in data["tasks"] if t["id"] == "t14")["media"] = media
    ws = worksheet_from_dict(data)
    for page in ("a4", "epaper"):
        section = _section(build_html(ws, RenderOptions(page=page)), ws, "t14")
        assert f'<span class="cap">Search for · {media}</span>' in section


def test_media_search_caption_in_the_learners_language() -> None:
    data = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    ws = worksheet_from_dict(data)
    task_id = next(t["id"] for t in data["tasks"] if t["kind"] == "media_search")
    section = _section(build_html(ws), ws, task_id)
    assert '<span class="cap">Suche nach · Video</span>' in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_media_search_queries_break_only_after_a_separator(page: str) -> None:
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["id"] == "t14")
    task["queries"] = ["Kaffee rösten", "Wiener Kaffeehäuser und ihre lange Geschichte als "
                       "immaterielles Kulturerbe der UNESCO", "Melange"]
    ws = worksheet_from_dict(data)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "t14")
    queries = re.search(r'<span class="q tl" lang="de">(.*?)</span></div>', section).group(1)
    parts = queries.split('<span class="sep">·</span><wbr>')
    assert len(parts) == 3
    # short queries never break; one too long for the line wraps like text
    assert parts[0] == '<span class="nw">Kaffee rösten</span>'
    assert parts[2] == '<span class="nw">Melange</span>'
    assert parts[1].startswith("Wiener Kaffeehäuser") and "nw" not in parts[1]
