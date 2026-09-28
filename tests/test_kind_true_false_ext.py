"""The true_false extension: a third box 'not in the text' ('not_given'),
the words of the story that prove each answer ('justify', item 'quote'),
and the checks, answer key and layout that go with them."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key
from langwich.locale import BUILTIN_LANGUAGES
from langwich.model import ContractError, TrueFalseTask, worksheet_from_dict
from langwich.plan import plan
from langwich.render import RenderOptions, build_html, metrics, render_worksheet
from langwich.render.html import Builder, esc
from langwich.render.tasks import TF_HEAD_PT, tf_column_width
from langwich.validate import Issue, validate
from tests.test_render import need_pdf

ROOT = Path(__file__).resolve().parent.parent
LENA = ROOT / "examples" / "lena_01_en_de.json"

#: The validator codes this file exercises (collected by tests/test_validate.py).
COVERED_CODES = {
    "tf-no-not-given", "tf-quote-missing", "tf-quote-not-in-story", "tf-not-given-correction",
}

#: Lena's first morning with a third box and quotes (replaces task t3, scene s1).
MORNING: dict[str, Any] = {
    "id": "t3", "kind": "true_false", "stage": "gist", "scene": "s1",
    "title": "Lena's first morning",
    "not_given": True, "justify": True,
    "items": [
        {"statement": "Lena arbeitet schon seit einem Jahr im Café Lindner.", "answer": False,
         "correction": "Es ist ihr erster Tag im Café.",
         "quote": "Lena steht zum ersten Mal hinter der Theke"},
        {"statement": "Herr Novak kommt seit Jahrzehnten jeden Morgen ins Café Lindner.",
         "answer": True,
         "quote": "Seit vierzig Jahren trinkt er hier jeden Morgen eine Melange"},
        {"statement": "Lena hat in der Nacht vor ihrem ersten Tag schlecht geschlafen.",
         "answer": "not_given"},
        {"statement": "Herr Novak trinkt seine Melange ohne Zucker.", "answer": False,
         "correction": "Er nimmt immer drei Löffel Zucker.",
         "quote": "immer mit drei Löffeln Zucker"},
        {"statement": "Frau Berger ist Lenas Tante.", "answer": "not_given"},
        {"statement": "Lena soll schon am Montag Herrn Novaks Melange machen.", "answer": False,
         "correction": "Sie soll sie erst am Freitag machen.",
         "quote": "„Am Freitag machst du Herrn Novaks Melange“"},
    ],
}

#: Two boxes, quotes only: Wednesday in the roastery (a new detail task on s3).
ROASTERY: dict[str, Any] = {
    "id": "t3b", "kind": "true_false", "stage": "detail", "scene": "s3",
    "title": "Wednesday in the roastery",
    "justify": True,
    "items": [
        {"statement": "Erst beim Rösten riecht der Kaffee so, wie wir ihn kennen.", "answer": True,
         "quote": "Erst beim Rösten entsteht der typische Kaffeeduft."},
        {"statement": "Eine helle Röstung schmeckt kräftig und bitter.", "answer": False,
         "correction": "Sie schmeckt fruchtig und ein bisschen säuerlich.",
         "quote": "Eine helle Röstung schmeckt fruchtig und ein bisschen säuerlich"},
        {"statement": "Lena wartet geduldig, bis Frau Berger zurückkommt.", "answer": False,
         "correction": "Sie dreht die Hitze höher.",
         "quote": "Das dauert ja ewig, denkt Lena und dreht die Hitze höher."},
    ],
}


def _lena(task: dict[str, Any] = MORNING, **changes: Any) -> dict[str, Any]:
    """The Lena example with ``task`` (plus ``changes``) in place of t3
    (tasks[2]), or inserted before t5 when it is ROASTERY."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    new = {**copy.deepcopy(task), **changes}
    if new["id"] == "t3":
        data["tasks"][2] = new
    else:
        at = next(i for i, t in enumerate(data["tasks"]) if t["id"] == "t5")
        data["tasks"].insert(at, new)
    return data


def _items(changes: dict[int, dict[str, Any]]) -> dict[str, Any]:
    """MORNING with the fields of some items changed, ``{2: {"quote": "…"}}``
    (``None`` removes a field)."""
    items = copy.deepcopy(MORNING["items"])
    for j, fields in changes.items():
        for name, value in fields.items():
            if value is None:
                items[j].pop(name, None)
            else:
                items[j][name] = value
    return _lena(items=items)


def _issues(data: dict[str, Any], code: str | None = None) -> list[Issue]:
    issues = validate(worksheet_from_dict(data)).issues
    return [i for i in issues if code is None or i.code == code]


def _key(data: dict[str, Any], task_id: str = "t3") -> list[str]:
    ws = worksheet_from_dict(data)
    pt = next(pt for pt in plan(ws).tasks if pt.task.id == task_id)
    return answer_key(pt, ws)


def _section(html: str, title: str = MORNING["title"]) -> str:
    """The worksheet section of the true_false task called ``title``."""
    sections = re.findall(r'<section class="task unit k-true_false[^"]*".*?</section>', html,
                          flags=re.S)
    return next(s for s in sections if f"<h3>{esc(title)}</h3>" in s)


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_answers_stay_bools_or_not_given() -> None:
    ws = worksheet_from_dict(_lena())
    task = next(t for t in ws.tasks if isinstance(t, TrueFalseTask))
    assert [item.answer for item in task.items] == [False, True, "not_given", False,
                                                    "not_given", False]
    assert [type(item.answer) for item in task.items][:2] == [bool, bool]
    assert task.not_given is True and task.justify is True
    assert task.items[0].quote == "Lena steht zum ersten Mal hinter der Theke"


def test_the_new_fields_default_to_a_plain_true_false_task() -> None:
    plain = json.loads(LENA.read_text(encoding="utf-8"))["tasks"][2]
    task = next(t for t in worksheet_from_dict(_lena(plain)).tasks
                if isinstance(t, TrueFalseTask))
    assert task.not_given is False and task.justify is False
    assert all(item.quote is None for item in task.items)


def test_not_given_needs_the_third_box() -> None:
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(_lena(not_given=False))
    ((where, message),) = exc.value.problems
    assert where == "/tasks/2"
    assert message.startswith("items[2] and items[4] have answer 'not_given'")
    assert 'set "not_given": true on the task' in message


@pytest.mark.parametrize(("changes", "where"), [
    ({"not_given": "yes please"}, "/tasks/2/not_given"),
    ({"justify": [True]}, "/tasks/2/justify"),
])
def test_the_contract_rejects(changes: dict[str, Any], where: str) -> None:
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(_lena(**changes))
    assert where in [loc for loc, _ in exc.value.problems]


def test_an_answer_other_than_true_false_or_not_given_is_rejected() -> None:
    with pytest.raises(ContractError) as exc:
        worksheet_from_dict(_items({1: {"answer": "maybe"}}))
    assert "/tasks/2/items/1/answer" in [loc for loc, _ in exc.value.problems]


# ---------------------------------------------------------------------------
# The validator
# ---------------------------------------------------------------------------


def test_the_morning_and_the_roastery_are_clean() -> None:
    assert _issues(_lena()) == []
    assert _issues(_lena(ROASTERY)) == []


def test_a_third_box_that_no_statement_needs() -> None:
    items = [item for item in MORNING["items"] if item["answer"] != "not_given"]
    (hit,) = _issues(_lena(items=items), "tf-no-not-given")
    assert (hit.level, hit.where) == ("warning", "/tasks/2/not_given")
    assert '"answer": "not_given"' in hit.message and 'remove "not_given": true' in hit.message
    # without the third box, nothing is missing
    assert _issues(_lena(items=items, not_given=False)) == []


def test_justify_needs_a_quote_for_every_true_and_false_statement() -> None:
    data = _items({0: {"quote": None}, 1: {"quote": "  "}})
    hits = _issues(data, "tf-quote-missing")
    assert [(i.level, i.where) for i in hits] == [("warning", "/tasks/2/items/0"),
                                                  ("warning", "/tasks/2/items/1")]
    assert "show it is false" in hits[0].message and "show it is true" in hits[1].message
    assert '"quote"' in hits[0].message and "Café Lindner" in hits[0].message
    # 'not in the text' statements have nothing to quote (items 2 and 4 have none)
    assert _issues(_lena(), "tf-quote-missing") == []


def test_quotes_are_optional_without_justify() -> None:
    data = _items({0: {"quote": None}, 1: {"quote": None}})
    data["tasks"][2]["justify"] = False
    assert _issues(data) == []


def test_a_quote_the_scene_does_not_contain() -> None:
    data = _items({1: {"quote": "Seit vierzig Jahren trinkt er hier jeden Tag eine Melange"}})
    (hit,) = _issues(data, "tf-quote-not-in-story")
    assert (hit.level, hit.where) == ("warning", "/tasks/2/items/1/quote")
    assert "is not in scene 's1'" in hit.message
    # the words of the scene closest to it, so the quote can be fixed
    assert "did you mean 'Seit vierzig Jahren trinkt er hier jeden Morgen eine Melange'?" in (
        hit.message)


def test_a_quote_from_another_scene() -> None:
    # (true, but from Tuesday: the learner reads scene 1 for this task)
    data = _items({1: {"quote": "Diese Bohnen kommen aus Äthiopien"}})
    (hit,) = _issues(data, "tf-quote-not-in-story")
    assert "is not in scene 's1'" in hit.message and "did you mean" not in hit.message
    # a task about the whole story may quote any scene
    data["tasks"][2]["scene"] = ["s1", "s2"]
    assert _issues(data, "tf-quote-not-in-story") == []
    del data["tasks"][2]["scene"]
    assert _issues(data, "tf-quote-not-in-story") == []


def test_a_task_about_several_scenes_names_them() -> None:
    data = _items({1: {"quote": "Lena trinkt gern Tee"}})
    data["tasks"][2]["scene"] = ["s1", "s2", "s3"]
    (hit,) = _issues(data, "tf-quote-not-in-story")
    assert "is not in scenes 's1', 's2' and 's3'" in hit.message
    del data["tasks"][2]["scene"]
    (hit,) = _issues(data, "tf-quote-not-in-story")
    assert "is not in the story" in hit.message


def test_a_quote_is_checked_without_justify_too() -> None:
    data = _items({0: {"quote": "Lena arbeitet seit einem Jahr hier"}})
    data["tasks"][2]["justify"] = False
    assert [i.code for i in _issues(data)] == ["tf-quote-not-in-story"]


@pytest.mark.parametrize("quote", [
    "lena steht zum  ersten Mal HINTER der Theke",            # case and spacing
    "Lena steht zum ersten Mal hinter der Theke.",            # punctuation around it
    "„Lena steht zum ersten Mal hinter der Theke“",           # quote marks around it
    "Am Freitag machst du Herrn Novaks Melange, sagt sie",    # the story's „…“ left out
    "\"Am Freitag machst du Herrn Novaks Melange\", sagt sie",  # straight quote marks
    "Es ist Montag … Lena steht zum ersten Mal hinter der Theke",  # words left out
    "Seit vierzig Jahren ... jeden Morgen eine Melange",
])
def test_quotes_are_compared_leniently(quote: str) -> None:
    assert _issues(_items({0: {"quote": quote}}), "tf-quote-not-in-story") == []


def test_quote_parts_must_keep_their_order() -> None:
    data = _items({0: {"quote": "hinter der Theke … Es ist Montag"}})
    (hit,) = _issues(data, "tf-quote-not-in-story")
    assert hit.where == "/tasks/2/items/0/quote"


@pytest.mark.parametrize(("fields", "named", "remove"), [
    ({"correction": "Sie hat gut geschlafen."}, "'correction'", "Remove it;"),
    ({"quote": "Lena schläft gut"}, "'quote'", "Remove it;"),
    ({"correction": "Sie hat gut geschlafen.", "quote": "Lena schläft gut"},
     "'correction' and 'quote'", "Remove them;"),
])
def test_a_not_given_statement_has_nothing_to_correct_or_quote(
        fields: dict[str, str], named: str, remove: str) -> None:
    # (one warning: its quote, which is not in the story, is not also reported)
    hits = _issues(_items({2: fields}))
    assert [(i.code, i.level, i.where) for i in hits] == [
        ("tf-not-given-correction", "warning", "/tasks/2/items/2")]
    assert f"it has {named}" in hits[0].message and remove in hits[0].message


def test_only_false_statements_need_a_correction() -> None:
    assert _issues(_items({2: {"correction": None}}), "tf-missing-correction") == []
    (hit,) = _issues(_items({3: {"correction": None}}), "tf-missing-correction")
    assert hit.where == "/tasks/2/items/3"


# ---------------------------------------------------------------------------
# The answer key
# ---------------------------------------------------------------------------


def test_the_key_shows_corrections_and_quotes() -> None:
    assert _key(_lena()) == [
        "false – Es ist ihr erster Tag im Café. «Lena steht zum ersten Mal hinter der Theke»",
        "true – «Seit vierzig Jahren trinkt er hier jeden Morgen eine Melange»",
        "not in the text",
        "false – Er nimmt immer drei Löffel Zucker. «immer mit drei Löffeln Zucker»",
        "not in the text",
        # the story's own „…“ around a whole quotation give way to «…»
        "false – Sie soll sie erst am Freitag machen. «Am Freitag machst du Herrn Novaks "
        "Melange»",
    ]


@pytest.mark.parametrize(("quote", "shown"), [
    ("„Morgen wieder“, sagt er. „Um sieben.“",
     "«„Morgen wieder“, sagt er. „Um sieben.“»"),
    ("  »Um sieben.«  ", "«Um sieben.»"),
    ("'Um sieben.'", "«Um sieben.»"),
    ("Um sieben.", "«Um sieben.»"),
    ("„“", ""),
])
def test_quote_marks_in_the_key(quote: str, shown: str) -> None:
    (entry,) = _key(_lena(items=[{"statement": "Herr Novak kommt morgen um sieben wieder.",
                                  "answer": True, "quote": quote}]))
    assert entry == (f"true – {shown}" if shown else "true")


def test_the_key_without_quotes_is_unchanged() -> None:
    assert _key(_lena(json.loads(LENA.read_text(encoding="utf-8"))["tasks"][2])) == [
        "false – Es ist ihr erster Tag im Café.", "true",
        "false – Er nimmt immer drei Löffel Zucker.",
        "false – Sie soll sie erst am Freitag machen.",
    ]
    # a false statement quoted without a correction
    assert _key(_items({0: {"correction": None}}))[0] == (
        "false – «Lena steht zum ersten Mal hinter der Theke»")


def test_the_key_speaks_the_learners_language() -> None:
    data = _lena()
    data["source_lang"] = "de"
    data["target_lang"] = "fr"  # (the key words follow the source language)
    key = _key(data)
    assert key[1].startswith("richtig – «") and key[2] == "steht nicht im Text"
    assert key[0].startswith("falsch – ")


# ---------------------------------------------------------------------------
# The worksheet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_three_boxes_under_one_row_of_heads(page: str) -> None:
    html = build_html(worksheet_from_dict(_lena()), RenderOptions(page=page))
    section = _section(html)
    assert 'class="task unit k-true_false keep' in section  # (the heads stay in view)
    heads = re.findall(r'<th class="h" style="width:([\d.]+)mm">(.*?)</th>', section)
    assert [text for _, text in heads] == ["true", "false", "not in the text"]
    assert len({width for width, _ in heads}) == 1
    bodies = re.findall(r"<tbody>(.*?)</tbody>", section, flags=re.S)
    assert len(bodies) == 6
    assert all(body.count('<td class="b"><span class="bxs"></span></td>') == 3
               for body in bodies)
    assert ('<td class="c"><span class="tl" lang="de">Frau Berger ist Lenas Tante.</span></td>'
            in bodies[4])
    # below each statement: the correction line, then the line for the quote
    assert all(body.index('class="corr"') < body.index('<div class="wl evd">')
               for body in bodies)
    assert section.count('<span class="cue">In the text:</span>') == 6
    assert '<table class="tf3 just">' in section and "not in the text</th>" in section
    assert 'class="items tf' not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_two_boxes_with_a_line_for_the_quote(page: str) -> None:
    html = build_html(worksheet_from_dict(_lena(ROASTERY)), RenderOptions(page=page))
    section = _section(html, ROASTERY["title"])
    assert '<div class="items tf just">' in section and "<table" not in section
    items = re.findall(r'<div class="it">.*?</div></div>', section, flags=re.S)
    assert len(items) == 3
    for item in items:
        assert item.count('<span class="bxs"></span>') == 2
        assert item.index('<span class="corr"></span>') < item.index(
            '<div class="wl evd"><span class="cue">In the text:</span>'
            '<span class="line"></span></div>')
    # (a two-box task still breaks between statements)
    assert 'k-true_false keep' not in section


def test_a_plain_task_looks_as_before() -> None:
    html = build_html(worksheet_from_dict(_lena(not_given=False, justify=False,
                                                items=MORNING["items"][:2])))
    section = _section(html)
    assert '<div class="items tf">' in section
    assert "evd" not in section and "tf3" not in section and "not in the text" not in section
    assert "Tick true or false. Correct the false statements.</p>" in section


@pytest.mark.parametrize(("not_given", "justify", "instruction"), [
    (True, False, "Tick true, false or not in the text. Correct the false statements."),
    (False, True, "Tick true or false. Correct the false statements. Copy the words from the "
                  "story that show it."),
    (True, True, "Tick true, false or not in the text. Correct the false statements. Copy the "
                 "words from the story that show it."),
])
def test_the_default_instruction_names_the_third_box_and_the_quotes(
        not_given: bool, justify: bool, instruction: str) -> None:
    items = MORNING["items"] if not_given else ROASTERY["items"]
    html = build_html(worksheet_from_dict(_lena(not_given=not_given, justify=justify,
                                                items=items)))
    assert f'<p class="ins">{instruction}</p>' in _section(html)


def test_an_own_instruction_wins() -> None:
    html = build_html(worksheet_from_dict(_lena(instruction="Richtig, falsch oder offen?")))
    assert '<p class="ins">Richtig, falsch oder offen?</p>' in _section(html)


def test_the_instruction_and_heads_speak_the_learners_language() -> None:
    data = _lena()
    data["source_lang"] = "de"
    data["target_lang"] = "fr"
    section = _section(build_html(worksheet_from_dict(data)))
    assert ("Kreuze richtig, falsch oder steht nicht im Text an. Verbessere die falschen "
            "Aussagen. Schreibe die Wörter aus der Geschichte ab, die es zeigen.") in section
    heads = re.findall(r'<th class="h"[^>]*>(.*?)</th>', section)
    assert heads == ["richtig", "falsch", "steht nicht im Text"]
    assert section.count('<span class="cue">Im Text:</span>') == 6


def test_user_text_is_escaped() -> None:
    data = _items({4: {"statement": "Frau <b>Berger</b> & Lena"}})
    data["ui"] = {"not_given": "n/a <i>", "evidence": "Beleg & Zitat:"}
    section = _section(build_html(worksheet_from_dict(data)))
    assert "Frau &lt;b&gt;Berger&lt;/b&gt; &amp; Lena" in section
    assert ">n/a &lt;i&gt;</th>" in section and ">Beleg &amp; Zitat:</span>" in section
    assert "<b>Berger" not in section and "<i></th>" not in section


@pytest.mark.parametrize("lang", BUILTIN_LANGUAGES)
@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_every_head_fits_its_column(lang: str, page: str) -> None:
    data = _lena()
    data["source_lang"] = lang
    data["target_lang"] = "de" if lang != "de" else "fr"
    b = Builder(worksheet_from_dict(data), RenderOptions(page=page))
    width, size = tf_column_width(b), TF_HEAD_PT[page]
    for key in ("true", "false", "not_given"):
        head = b.t(key)
        # no word broken, 1 mm clear on either side, at most two lines
        assert all(metrics.width_mm(w, "sans-bold", size) <= width - 2.0 for w in head.split())
        assert metrics.line_count(head, width - 2.0, "sans-bold", size) <= 2
    assert 12.0 <= width <= 18.0


def test_the_height_estimate_makes_room_for_heads_and_quote_lines() -> None:
    def height(**changes: Any) -> float:
        b = Builder(worksheet_from_dict(_lena(**changes)))
        return b.estimate_task_h(next(pt for pt in b.plan.tasks if pt.task.id == "t3"))

    plain = height(not_given=False, justify=False, items=MORNING["items"][:2] * 3)
    assert height(justify=False) > plain + 8.0
    assert height() > height(justify=False) + 6 * 9.0


# ---------------------------------------------------------------------------
# The PDF
# ---------------------------------------------------------------------------


def test_the_heads_are_repeated_on_every_page_of_the_task(tmp_path: Path) -> None:
    fitz = need_pdf(pymupdf=True)
    out = tmp_path / "morning.pdf"
    # six statements with quote lines are taller than an e-paper page
    render_worksheet(worksheet_from_dict(_lena()), out, RenderOptions(page="epaper"))
    starts = [" ".join(item["statement"].split()[:4]) for item in MORNING["items"]]
    pages = []
    for page in fitz.open(out):
        tops = [r.y0 for start in starts for r in page.search_for(start)]
        if tops:
            pages.append((page, tops))
    assert len(pages) >= 2
    assert sum(len(tops) for _, tops in pages) == len(starts)
    for page, tops in pages:
        # the heads over the box columns (small type: the instruction names them too)
        heads = [span for block in page.get_text("dict")["blocks"]
                 for line in block.get("lines", ()) for span in line["spans"]
                 if span["text"].strip() in ("true", "false") and span["size"] < 9]
        assert sorted(span["text"].strip() for span in heads) == ["false", "true"]
        assert all(span["bbox"][3] < min(tops) for span in heads)
