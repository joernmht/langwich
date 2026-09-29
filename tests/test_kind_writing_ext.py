"""The writing extension: a text to answer ('input'), the points the answer
must cover, register and audience, one block of lines per point
('paragraphs'), and writing in the source language ('output_lang')."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.model import ContractError, WritingTask, worksheet_from_dict
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.html import Builder
from langwich.validate import Issue, validate
from tests.test_render import need_pdf

ROOT = Path(__file__).resolve().parent.parent
LENA = ROOT / "examples" / "lena_01_en_de.json"

#: The validator codes this file exercises (collected by tests/test_validate.py).
COVERED_CODES = {"writing-no-model-answer", "point-not-covered"}

MARCO = (
    "Liebe Lena,\n\nwie war deine erste Woche im Café Lindner? Deine Mama sagt, du röstest "
    "jetzt selbst Kaffee! Was war am schwierigsten? Und hat Herr Novak endlich einmal "
    "gelächelt?\n\nIch komme im Mai nach Wien. Hast du dann Zeit?\n\nViele Grüße aus Triest\n"
    "Marco"
)

#: 88 words in four paragraphs; covers every point of REPLY.
REPLY_ANSWER = (
    "Lieber Onkel Marco, danke für deine E-Mail! Die erste Woche war anstrengend, aber sehr "
    "schön.\n\nAm schwierigsten war das Rösten. Am Mittwoch hatte ich keine Geduld, und meine "
    "Röstung war viel zu dunkel und bitter. Ich musste den Kaffee mit viel Zucker trinken!\n\n"
    "Am Freitag habe ich Herrn Novak, unserem strengsten Stammgast, seine Melange gemacht. Der "
    "Milchschaum war perfekt, und er hat keinen Zucker genommen! Gelächelt hat er nicht, aber er "
    "kommt morgen wieder.\n\nKomm im Mai unbedingt ins Café Lindner! Dann röste ich Bohnen nur "
    "für dich.\n\nLiebe Grüße\nLena"
)

#: Lena answers her uncle's email (replaces task t12 of the Lena example).
REPLY: dict[str, Any] = {
    "id": "t12", "kind": "writing", "stage": "production",
    "title": "Friday night: an answer to Trieste",
    "prompt": "Uncle Marco has written to Lena. Write her answer in German, one paragraph for "
              "each point.",
    "input": MARCO,
    "register": "informal",
    "audience": "your uncle Marco in Trieste",
    "points": [
        {"point": "Say what was hardest this week and why.",
         "covered_by": "Am schwierigsten war das Rösten"},
        {"point": "Tell him what happened with Herr Novak on Friday.",
         "covered_by": "er hat keinen Zucker genommen"},
        {"point": "Invite him to Café Lindner in May.",
         "covered_by": "Komm im Mai unbedingt ins Café Lindner"},
    ],
    "paragraphs": True,
    "starter": "Lieber Onkel Marco,",
    "must_use": ["die Röstung", "bitter", "der Milchschaum", "der Stammgast"],
    "min_words": 70, "max_words": 100,
    "model_answer": REPLY_ANSWER,
}

#: Mediation: Lena tells her English flatmate about a German notice, in English
#: (replaces task t13 of the Lena example).
NOTE: dict[str, Any] = {
    "id": "t13", "kind": "writing", "stage": "production",
    "title": "For Tom: the coffee course",
    "prompt": "Lena's English flatmate Tom would like to join this course, but he does not read "
              "German. Write him a short message in English.",
    "input": "Kaffeekurs im Café Lindner\n\nWoher kommt unser Kaffee? Wie wird er geröstet? Im "
             "Kurs lernen Sie alles über die Reise der Bohne und rösten Ihre eigene Mischung.\n\n"
             "Samstag, 14. Juni, 10–13 Uhr, in der Rösterei hinter dem Café\nPreis: 35 Euro, mit "
             "Frühstück",
    "output_lang": "source",
    "register": "informal",
    "audience": "Tom, Lena's flatmate",
    "points": [
        {"point": "What do you learn in the course?",
         "covered_by": "you learn where the coffee comes from and how it is roasted"},
        {"point": "When is it, and what does it cost?", "covered_by": "It costs 35 euros"},
    ],
    "starter": "Hi Tom,",
    "min_words": 40, "max_words": 60,
    "model_answer": "Hi Tom, there's a coffee course at Café Lindner! In three hours you learn "
                    "where the coffee comes from and how it is roasted, and you roast your own "
                    "blend. It's on Saturday, 14 June, from 10 to 1, in the roastery behind the "
                    "café. It costs 35 euros, breakfast included. Just sign up at the counter "
                    "with Frau Berger. Lena",
}


def _lena(task: dict[str, Any] = REPLY, **changes: Any) -> dict[str, Any]:
    """The Lena example with ``task`` (plus ``changes``) in place of the task
    with the same id: t12 (tasks[11]) the email, t13 (tasks[12]) the note."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    new = {**copy.deepcopy(task), **changes}
    data["tasks"] = [new if t["id"] == new["id"] else t for t in data["tasks"]]
    if new["id"] != "t12":
        data["tasks"][11] = copy.deepcopy(REPLY)
    return data


def _issues(data: dict[str, Any], code: str | None = None) -> list[Issue]:
    issues = validate(worksheet_from_dict(data)).issues
    return [i for i in issues if code is None or i.code == code]


def _covered(covered_by: str) -> dict[str, Any]:
    points = copy.deepcopy(REPLY["points"])
    points[0]["covered_by"] = covered_by
    return _lena(points=points)


def _section(html: str, title: str = REPLY["title"]) -> str:
    """The worksheet section of the writing task called ``title``."""
    sections = re.findall(r'<section class="task unit k-writing[^"]*".*?</section>', html,
                          flags=re.S)
    return next(s for s in sections if f"<h3>{title}</h3>" in s)


def _solution(html: str, title: str) -> str:
    solutions = html.split('class="solutions', 1)[1]
    return re.search(rf'<div class="sb">(?:(?!<div class="sb">).)*?{re.escape(title)}.*?</div>',
                     solutions, flags=re.S).group(0)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_the_new_fields_are_read() -> None:
    ws = worksheet_from_dict(_lena())
    task = next(t for t in ws.tasks if isinstance(t, WritingTask))
    assert task.register_ == "informal"  # "register" in the JSON
    assert task.input == MARCO and task.input_lang == "target" and task.output_lang == "target"
    assert task.audience == "your uncle Marco in Trieste" and task.paragraphs is True
    assert [p.covered_by for p in task.points][0] == "Am schwierigsten war das Rösten"


def test_the_new_fields_default_to_a_plain_writing_task() -> None:
    plain = {k: v for k, v in REPLY.items()
             if k not in ("input", "register", "audience", "points", "paragraphs")}
    task = next(t for t in worksheet_from_dict(_lena(plain)).tasks if isinstance(t, WritingTask))
    assert task.input is None and task.register_ is None and task.audience is None
    assert task.points == [] and task.paragraphs is False
    assert (task.input_lang, task.output_lang) == ("target", "target")


@pytest.mark.parametrize(("changes", "where"), [
    ({"register": "casual"}, "/tasks/11/register"),
    ({"register_": "formal"}, "/tasks/11/register_"),
    ({"output_lang": "de"}, "/tasks/11/output_lang"),
    ({"points": [{"point": f"Point {n}"} for n in range(7)]}, "/tasks/11/points"),
    ({"points": [{"point": ""}]}, "/tasks/11/points/0/point"),
])
def test_the_contract_rejects(changes: dict[str, Any], where: str) -> None:
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(_lena(**changes))
    assert where in [loc for loc, _ in exc.value.problems]


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


def test_a_reply_and_a_mediation_are_clean() -> None:
    assert _issues(_lena()) == []
    assert _issues(_lena(NOTE)) == []


@pytest.mark.parametrize("drop", [(), ("points",), ("input",)])
def test_input_or_points_without_a_model_answer(drop: tuple[str, ...]) -> None:
    task = {k: v for k, v in REPLY.items() if k not in ("model_answer", *drop)}
    hits = _issues(_lena(task), "writing-no-model-answer")
    assert [(i.level, i.where) for i in hits] == [("warning", "/tasks/11")]
    assert '"model_answer"' in hits[0].message and "target language" in hits[0].message
    assert ("covered_by" in hits[0].message) == ("points" not in drop)
    # without a model answer, 'covered_by' cannot be checked
    assert _issues(_lena(task), "point-not-covered") == []


def test_a_mediation_without_a_model_answer_asks_for_the_source_language() -> None:
    task = {k: v for k, v in NOTE.items() if k != "model_answer"}
    (hit,) = _issues(_lena(task), "writing-no-model-answer")
    assert "source language" in hit.message


def test_a_plain_writing_task_may_leave_out_the_model_answer() -> None:
    task = {k: v for k, v in REPLY.items() if k not in ("input", "points", "model_answer")}
    assert _issues(_lena(task), "writing-no-model-answer") == []


def test_a_point_without_covered_by() -> None:
    points = copy.deepcopy(REPLY["points"])
    del points[1]["covered_by"]
    (hit,) = _issues(_lena(points=points), "point-not-covered")
    assert (hit.level, hit.where) == ("warning", "/tasks/11/points/1")
    assert "Herr Novak on Friday" in hit.message and '"covered_by"' in hit.message


def test_covered_by_that_the_model_answer_does_not_contain() -> None:
    (hit,) = _issues(_covered("Am schwierigsten war die Röstung"), "point-not-covered")
    assert (hit.level, hit.where) == ("warning", "/tasks/11/points/0/covered_by")
    # the words of the model answer closest to it, so the quote can be fixed
    assert "did you mean 'Am schwierigsten war das Rösten'?" in hit.message
    assert "hardest this week" in hit.message


def test_covered_by_with_nothing_close_gets_no_suggestion() -> None:
    (hit,) = _issues(_covered("Wir fahren nach Salzburg"), "point-not-covered")
    assert "did you mean" not in hit.message


@pytest.mark.parametrize("covered_by", [
    "am  schwierigsten WAR das Rösten",          # case and spacing
    "Am schwierigsten war das Rösten.",         # punctuation around the quote
    "„Komm im Mai unbedingt ins Café Lindner!“",  # quote marks around it
    "Am Freitag habe ich … seine Melange gemacht",  # words left out
    "Am Mittwoch ... bitter",
])
def test_covered_by_is_compared_leniently(covered_by: str) -> None:
    assert _issues(_covered(covered_by), "point-not-covered") == []


def test_covered_by_parts_must_keep_their_order() -> None:
    (hit,) = _issues(_covered("keinen Zucker genommen … Milchschaum"), "point-not-covered")
    assert hit.where == "/tasks/11/points/0/covered_by"


def test_typographic_apostrophes_match_straight_ones() -> None:
    task = copy.deepcopy(NOTE)
    task["points"][0]["covered_by"] = "there’s a coffee course"
    assert _issues(_lena(task)) == []


def test_must_use_is_not_checked_in_a_source_language_text() -> None:
    task = {**NOTE, "must_use": ["die Röstung"]}
    assert _issues(_lena(task), "model-answer-missing-must-use") == []
    # (the same word in a target-language model answer that lacks it is reported)
    assert _issues(_lena(task, output_lang="target"), "model-answer-missing-must-use")


def test_words_are_counted_in_the_language_of_the_model_answer() -> None:
    data = _lena(NOTE, model_answer="トムへ、カフェでコーヒーの講座があります。土曜日です。")
    data["source_lang"] = "ja"  # written without spaces: a word count means nothing
    assert _issues(data, "model-answer-length") == []
    data["tasks"][12]["output_lang"] = "target"
    assert _issues(data, "model-answer-length")


# ---------------------------------------------------------------------------
# The worksheet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_reply_shows_input_points_and_one_block_per_point(page: str) -> None:
    html = build_html(worksheet_from_dict(_lena()), RenderOptions(page=page))
    section = _section(html)
    order = ['class="prompt"', 'class="wmeta"', 'class="box input', 'class="points"',
             'class="usewords"', 'class="lines']
    positions = [section.index(mark) for mark in order]
    assert positions == sorted(positions)
    # who it is for, and the register as a tag
    assert ('<p class="wmeta"><span class="cap">For:</span>your uncle Marco in Trieste'
            '<span class="reg">informal</span></p>') in section
    # the email in a box, in German, with its paragraphs and line breaks
    assert '<div class="box input tl" lang="de"><p>Liebe Lena,</p>' in section
    assert "<p>Viele Grüße aus Triest<br>Marco</p></div>" in section
    # the points as a numbered tick list
    assert '<span class="cap">Include:</span>' in section
    assert section.count('<li><span class="tick"></span><span class="pn">') == 3
    # 100 words ≈ 10 lines, split into 3 blocks of 4, plus the starter line
    blocks = re.findall(r'<div class="lines numbered">(.*?)</div></div>', section)
    assert [b.count("<div") for b in blocks] == [5, 4, 4]
    assert blocks[0].startswith('<div class="starter tl" lang="de"><span class="pn">1</span>'
                                "Lieber Onkel Marco,")
    assert '<div><span class="pn">3</span>' in blocks[2]


@pytest.mark.parametrize(("lines", "starter", "blocks"), [
    (6, "Lieber Onkel Marco,", [4, 3, 3]),  # at least three lines per block
    (13, None, [5, 5, 5]),                  # split evenly (rounded up)
])
def test_paragraph_blocks(lines: int, starter: str | None, blocks: list[int]) -> None:
    html = build_html(worksheet_from_dict(_lena(lines=lines, starter=starter)))
    found = re.findall(r'<div class="lines numbered">(.*?)</div></div>', _section(html))
    assert [b.count("<div") for b in found] == blocks


def test_without_paragraphs_the_lines_are_one_block() -> None:
    section = _section(build_html(worksheet_from_dict(_lena(paragraphs=False))))
    assert 'class="lines numbered"' not in section and 'class="pn"' not in section
    assert section.count('<div class="lines">') == 1
    assert section.count('<li><span class="tick"></span>Say what') == 1


def test_a_mediation_is_written_in_the_source_language() -> None:
    html = build_html(worksheet_from_dict(_lena(NOTE, input_lang="source")))
    section = _section(html, NOTE["title"])
    assert '<div class="box input src" lang="en">' in section
    assert '<div class="starter src" lang="en">Hi Tom,</div>' in section
    assert '<div class="lines">' in section


def test_register_without_audience() -> None:
    data = _lena()
    del data["tasks"][11]["audience"]
    data["tasks"][11]["register"] = "formal"
    section = _section(build_html(worksheet_from_dict(data)))
    assert '<p class="wmeta"><span class="reg">formal</span></p>' in section


def test_user_text_is_escaped() -> None:
    points = [{"point": "Say <why> & how", "covered_by": "Am schwierigsten war das Rösten"}]
    data = _lena(input="Lies das: <b>Tom & Jerry</b>", audience="Tom <3", points=points)
    html = build_html(worksheet_from_dict(data))
    section = _section(html)
    assert "<p>Lies das: &lt;b&gt;Tom &amp; Jerry&lt;/b&gt;</p>" in section
    assert "Tom &lt;3" in section and "Say &lt;why&gt; &amp; how" in section
    assert "<b>Tom" not in html and "<why>" not in html


# ---------------------------------------------------------------------------
# The answer key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_key_lists_the_points_after_the_model_answer(page: str) -> None:
    html = build_html(worksheet_from_dict(_lena()), RenderOptions(page=page))
    block = _solution(html, "Friday night: an answer to Trieste")
    assert '<span class="model" lang="de">Lieber Onkel Marco,' in block
    # paragraphs start new lines
    assert "aber sehr schön.<br>Am schwierigsten" in block and "Liebe Grüße<br>Lena" in block
    points = block.split('<ul class="pts">', 1)[1]
    assert points.count("<li>") == 3
    assert ('<li>Say what was hardest this week and why. — <span class="tl" lang="de">'
            "„Am schwierigsten war das Rösten“</span></li>") in points


def test_the_key_of_a_mediation_is_in_the_source_language() -> None:
    points = copy.deepcopy(NOTE["points"])
    del points[1]["covered_by"]
    html = build_html(worksheet_from_dict(_lena(NOTE, points=points)))
    block = _solution(html, "For Tom: the coffee course")
    assert '<span class="model src" lang="en">Hi Tom,' in block
    assert ("<li>What do you learn in the course? — “you learn where the coffee comes from "
            "and how it is roasted”</li>") in block
    assert "<li>When is it, and what does it cost?</li>" in block


def test_the_key_estimate_makes_room_for_the_points() -> None:
    with_points, without = (Builder(worksheet_from_dict(data)) for data in
                            (_lena(), _lena(points=[], paragraphs=False)))
    heights = [b.solution_h(next(pt for pt in b.plan.tasks if pt.task.id == "t12"), 55.0)
               for b in (with_points, without)]
    assert heights[0] > heights[1] + 3 * 4.76


# ---------------------------------------------------------------------------
# The PDF
# ---------------------------------------------------------------------------


def test_block_numbers_stand_in_the_gutter(tmp_path: Path) -> None:
    fitz = need_pdf(pymupdf=True)
    out = tmp_path / "reply.pdf"
    render_worksheet(worksheet_from_dict(_lena()), out, RenderOptions(page="epaper"))
    doc = fitz.open(out)
    page = next(p for p in doc if "Lieber Onkel Marco," in p.get_text())
    words = page.get_text("words")
    starter = next(w for w in words if w[4] == "Lieber")
    number = next(w for w in words if w[4] == "1" and abs(w[3] - starter[3]) < 2.5)
    assert number[2] < starter[0]  # left of the first line, on its baseline
