"""The table kind: a table or form with {{gaps}} and open (null) cells."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key
from langwich.model import ContractError, TableTask, Worksheet, worksheet_from_dict
from langwich.plan import plan
from langwich.plan import tested_terms as collect_tested_terms
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.css import A4_CONTENT_W, EPAPER_CONTENT_W, GUTTER_W, MAIN_W
from langwich.validate import CHECKS, Issue, validate

#: The validator codes this file exercises (see tests/test_validate.py).
COVERED_CODES = {"table-shape", "table-nothing-to-do", "table-too-wide"}

LENA = Path(__file__).resolve().parent.parent / "examples" / "lena_01_en_de.json"
MM = 72 / 25.4

#: A form (no head: field | value) about scene 2, with an open cell.
FORM: dict[str, Any] = {
    "id": "tab1", "kind": "table", "stage": "detail", "scene": "s2",
    "title": "The label on the sack",
    "caption": "Lieferschein – Rohkaffee, Sack Nr. 17",
    "rows": [
        ["Herkunftsland", "{{Äthiopien}}"],
        ["Farbe der Bohnen", "{{grün}}"],
        ["Geruch", "wie {{Heu}}"],
        ["Transport nach Europa", "mit dem {{Schiff}}"],
        ["Kontrolliert von", None],
    ],
}

#: A headed table with a word box, distractors and open cells.
CHART: dict[str, Any] = {
    "id": "tab2", "kind": "table", "stage": "practice", "scene": "s3",
    "title": "Frau Berger's roasting chart",
    "caption": "Röstprotokoll – Café Lindner",
    "head": ["Röstung", "Farbe", "Geschmack", "Mein Tipp"],
    "hint": "word_bank",
    "rows": [
        ["hell", "{{hellbraun}}", "fruchtig, etwas {{säuerlich}}", None],
        ["mittel", "braun", "{{rund}} und süßlich", None],
        ["dunkel", "{{dunkelbraun}}", "{{kräftig}} und bitter", None],
    ],
    "distractors": ["grün", "salzig"],
}

#: Five columns of German verb forms: the widest table the checks allow.
VERBS: dict[str, Any] = {
    "id": "tab3", "kind": "table", "stage": "form", "scene": "s3",
    "head": ["Infinitiv", "er / sie / es", "Präteritum", "Perfekt", "Nomen"],
    "rows": [
        ["rösten", "{{röstet}}", "{{röstete}}", "hat {{geröstet}}", "die {{Röstung}}"],
        ["ernten", "{{erntet}}", "erntete", "hat {{geerntet}}", "die {{Ernte}}"],
        ["trocknen", "trocknet", "{{trocknete}}", "hat {{getrocknet}}", "die {{Trocknung}}"],
        ["wachsen", "{{wächst}}", "{{wuchs}}", "ist {{gewachsen}}", "das {{Wachstum}}"],
    ],
}


def _lena() -> dict[str, Any]:
    return json.loads(LENA.read_text(encoding="utf-8"))


def _data(*tasks: dict[str, Any]) -> dict[str, Any]:
    """The Lena example with ``tasks`` added (as copies)."""
    data = _lena()
    data["tasks"] += [copy.deepcopy(t) for t in tasks]
    return data


def _ws(*tasks: dict[str, Any]) -> Worksheet:
    return worksheet_from_dict(_data(*tasks))


def _issues(*tasks: dict[str, Any]) -> list[Issue]:
    # (the example has the most tasks a B1 sheet should have; the budget is
    # tested in test_levels.py)
    return [i for i in validate(_ws(*tasks)).issues if i.code != "task-count"]


def _index(ws: Worksheet, task_id: str) -> int:
    return next(i for i, t in enumerate(ws.tasks) if t.id == task_id)


def _codes(issues: list[Issue], where: str) -> set[str]:
    """Codes of the issues at ``where`` or below it."""
    return {i.code for i in issues if i.where == where or i.where.startswith(where + "/")}


def _planned(ws: Worksheet, task_id: str, seed: int | None = None):
    return next(pt for pt in plan(ws, seed).tasks if pt.task.id == task_id)


def _section(html: str, ws: Worksheet, task_id: str) -> str:
    number = _planned(ws, task_id).number
    m = re.search(rf'<section class="task unit [^"]*" id="task-{number}"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, f"task {task_id} not found"
    return m.group(0)


def _column_widths(section: str) -> list[float]:
    return [float(w) for w in re.findall(r'<col style="width:([\d.]+)mm">', section)]


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_reads_forms_and_tables() -> None:
    ws = _ws(FORM, CHART)
    form, chart = (t for t in ws.tasks if isinstance(t, TableTask))
    assert form.head == [] and form.hint == "none" and form.distractors == []
    assert form.rows[-1] == ["Kontrolliert von", None]
    assert chart.head[0] == "Röstung" and chart.hint == "word_bank"
    assert chart.caption == "Röstprotokoll – Café Lindner"


@pytest.mark.parametrize(("change", "where"), [
    ({"rows": []}, "rows"),
    ({"hint": "choice"}, "hint"),
    ({"rows": [["Name", 7]]}, "rows"),
    ({"columns": 2}, "columns"),
])
def test_contract_rejects_bad_tables(change: dict[str, Any], where: str) -> None:
    with pytest.raises(ContractError) as err:
        _ws({**FORM, **change})
    assert any(where in loc for loc, _ in err.value.problems), err.value.problems


def test_a_table_nested_under_the_kind_is_located_in_the_task() -> None:
    # {"kind": "table", "table": {"head": …, "rows": …}}: 'rows' is missing
    # from the task, and the key 'table' is not a field of it
    task = {k: v for k, v in CHART.items() if k not in ("head", "rows")}
    task["table"] = {"head": CHART["head"], "rows": CHART["rows"]}
    with pytest.raises(ContractError) as err:
        _ws(task)
    at = len(_lena()["tasks"])
    problems = dict(err.value.problems)
    assert set(problems) == {f"/tasks/{at}/rows", f"/tasks/{at}/table"}
    assert problems[f"/tasks/{at}/rows"].startswith("the required field 'rows' is missing")
    assert problems[f"/tasks/{at}/table"].startswith("'table' is not a field here (write the "
                                                     "task's fields straight into the task")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_forms_and_tables_pass_every_check() -> None:
    assert _issues(FORM, CHART, VERBS) == []


def test_every_covered_code_is_a_check() -> None:
    assert COVERED_CODES <= set(CHECKS)


def test_a_row_must_match_the_head() -> None:
    chart = copy.deepcopy(CHART)
    chart["rows"][1] = ["mittel", "braun", "{{rund}} und süßlich"]
    ws = _ws(chart)
    i = _index(ws, "tab2")
    hits = [x for x in validate(ws).issues if x.code == "table-shape"]
    assert [x.where for x in hits] == [f"/tasks/{i}/rows/1"]
    assert hits[0].level == "error"
    assert "3 cells" in hits[0].message and "4 columns" in hits[0].message
    assert "null" in hits[0].message


def test_a_form_row_has_two_cells() -> None:
    form = copy.deepcopy(FORM)
    form["rows"][0] = ["Herkunftsland", "{{Äthiopien}}", "Afrika"]
    form["rows"][2] = ["wie {{Heu}}"]
    ws = _ws(form)
    i = _index(ws, "tab1")
    hits = [x for x in validate(ws).issues if x.code == "table-shape"]
    assert [x.where for x in hits] == [f"/tasks/{i}/rows/0", f"/tasks/{i}/rows/2"]
    assert all("2 cells" in x.message and "'head'" in x.message for x in hits)
    assert "1 cell," in hits[1].message


def test_a_table_needs_something_to_do() -> None:
    done = {**FORM, "rows": [["Herkunftsland", "Äthiopien"], ["Geruch", "wie Heu"]]}
    ws = _ws(done)
    i = _index(ws, "tab1")
    hits = [x for x in validate(ws).issues if x.code == "table-nothing-to-do"]
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/rows", "error")]
    assert "{{" in hits[0].message and "null" in hits[0].message
    # an open cell alone is something to do
    assert "table-nothing-to-do" not in _codes(
        _issues({**done, "rows": [["Herkunftsland", "Äthiopien"], ["Geruch", None]]}), "/tasks")
    # an empty gap is reported as such, not as a table without gaps
    codes = _codes(_issues({**done, "rows": [["Geruch", "wie {{ }}"]]}), "/tasks")
    assert "empty-gap" in codes and "table-nothing-to-do" not in codes


def test_more_than_five_columns_is_too_wide() -> None:
    wide = copy.deepcopy(VERBS)
    wide["head"].append("Partizip I")
    for row, extra in zip(wide["rows"], ("röstend", "erntend", "trocknend", "{{wachsend}}")):
        row.append(extra)
    ws = _ws(wide)
    i = _index(ws, "tab3")
    hits = [x for x in validate(ws).issues if x.code == "table-too-wide"]
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/head", "warning")]
    assert "6 columns" in hits[0].message
    assert "table-too-wide" not in _codes(_issues(VERBS), "/tasks")


def test_cells_get_the_gap_checks_of_their_hint() -> None:
    table = {**FORM, "hint": "base_form",
             "rows": [["Ernte", "die Bauern {{ernten::ernten}} von Hand"],
                      ["Transport", "die Bohnen {{reisen}} mit dem Schiff"],
                      ["Geruch", "wie {{Heu"]]}
    ws = _ws(table)
    i = _index(ws, "tab1")
    issues = validate(ws).issues
    assert any(x.code == "missing-gap-hint" and x.where == f"/tasks/{i}/rows/1/1" for x in issues)
    assert any(x.code == "unbalanced-braces" and x.where == f"/tasks/{i}/rows/2/1" for x in issues)
    assert "this table cell" in next(x.message for x in issues if x.code == "unbalanced-braces")


def test_a_distractor_must_not_be_an_answer() -> None:
    chart = {**CHART, "distractors": ["grün", "Rund"]}
    ws = _ws(chart)
    i = _index(ws, "tab2")
    hits = [x for x in validate(ws).issues if x.code == "distractor-is-answer"]
    assert [x.where for x in hits] == [f"/tasks/{i}/distractors/1"]


def test_gap_markup_belongs_in_the_cells_only() -> None:
    chart = {**CHART, "head": ["Röstung", "{{Farbe}}", "Geschmack", "Mein Tipp"]}
    ws = _ws(chart)
    i = _index(ws, "tab2")
    hits = [x.where for x in validate(ws).issues if x.code == "markup-outside-gaps"]
    assert hits == [f"/tasks/{i}/head/1"]


def test_a_practice_table_must_not_copy_the_story() -> None:
    copied = {**CHART, "rows": [["hell", "Erst beim Rösten entsteht der typische {{Kaffeeduft}}.",
                                 None, None]]}
    ws = _ws(copied)
    i = _index(ws, "tab2")
    assert any(x.code == "copies-story" and x.where == f"/tasks/{i}/rows/0"
               for x in validate(ws).issues)


# ---------------------------------------------------------------------------
# Planner and answer key
# ---------------------------------------------------------------------------


def test_the_word_box_holds_the_answers_and_distractors() -> None:
    chart = {**CHART, "distractors": ["grün", "salzig", "SALZIG"]}
    ws = _ws(chart)
    bank = _planned(ws, "tab2").bank
    assert bank is not None
    assert sorted(bank) == sorted(["hellbraun", "säuerlich", "rund", "dunkelbraun", "kräftig",
                                   "grün", "salzig"])
    assert bank == _planned(ws, "tab2").bank  # the same JSON gives the same box
    orders = {tuple(_planned(ws, "tab2", seed).bank or []) for seed in range(6)}
    assert len(orders) > 1  # … and the seed shuffles it
    assert _planned(_ws(FORM), "tab1").bank is None  # hint none: no box


def test_gap_answers_are_never_glossed() -> None:
    tested = collect_tested_terms(_ws(FORM))
    assert {"äthiopien", "heu", "schiff"} <= tested


def test_the_key_lists_the_gaps_row_by_row() -> None:
    form = copy.deepcopy(FORM)
    form["rows"][1] = ["Farbe der Bohnen", "{{grün|hellgrün}}"]
    ws = _ws(form)
    assert answer_key(_planned(ws, "tab1"), ws) == [
        "Äthiopien", "grün / hellgrün", "Heu", "Schiff"]
    ws = _ws(VERBS)
    assert answer_key(_planned(ws, "tab3"), ws)[:5] == [
        "röstet", "röstete", "geröstet", "Röstung", "erntet"]


def test_a_table_of_open_cells_has_open_answers() -> None:
    open_form = {**FORM, "rows": [["Dein Name", None], ["Dein Lieblingskaffee", None]]}
    ws = _ws(open_form)
    assert answer_key(_planned(ws, "tab1"), ws) == []
    html = build_html(ws, RenderOptions(page="a4"))
    assert "Answers will vary." in html


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_a_form_is_a_two_column_table(page: str) -> None:
    ws = _ws(FORM)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "tab1")
    assert 'class="task unit k-table keep"' in section and "data-soft" in section
    assert '<table class="gtab tl" lang="de"' in section
    assert "<thead>" not in section
    assert '<div class="tl gcap" lang="de">Lieferschein – Rohkaffee, Sack Nr. 17</div>' in section
    assert section.count('<td class="lab">') == 5
    assert section.count('<td class="open"><span class="wr">&nbsp;</span></td>') == 1
    numbers = re.findall(r'<span class="gn">(\d+)</span>', section)
    assert numbers == ["1", "2", "3", "4"]
    assert "wie <span class=\"gap\">" in section


def test_a_table_has_its_head_and_its_word_box_beside_it() -> None:
    narrow = {**CHART, "head": ["Röstung", "Farbe"],
              "rows": [["hell", "{{hellbraun}}"], ["dunkel", "{{dunkelbraun}}"], ["Lena", None]]}
    ws = _ws(narrow)
    section = _section(build_html(ws), ws, "tab2")
    assert "<thead><tr><th>Röstung</th><th>Farbe</th></tr></thead>" in section
    aside = section.split('<aside class="aside-stack">', 1)[1]
    assert 'class="box wordbox"' in aside and "hellbraun" in aside and "salzig" in aside
    assert "gtab-bank" not in section
    assert sum(_column_widths(section)) <= MAIN_W - GUTTER_W + 0.1


def test_a_crowded_table_puts_its_word_box_above() -> None:
    ws = _ws(CHART)
    section = _section(build_html(ws), ws, "tab2")
    assert 'class="gtab-bank"' in section and "aside-stack" not in section
    assert section.index("gtab-bank") < section.index('<table class="gtab')
    # the box is as wide as the table, which uses the width of the page
    table_w = float(re.search(r'<table class="gtab[^>]*style="width:([\d.]+)mm"', section)[1])
    assert f'<div class="gtab-bank" style="width:{table_w:.1f}mm">' in section
    assert MAIN_W - GUTTER_W < table_w <= A4_CONTENT_W - GUTTER_W + 0.1
    # e-paper: the word box comes before the table, as for every task
    epaper = _section(build_html(ws, RenderOptions(page="epaper")), ws, "tab2")
    assert '<div class="before"' in epaper and "gtab-bank" not in epaper


@pytest.mark.parametrize("page", ["a4", "epaper"])
@pytest.mark.parametrize("task", [FORM, CHART, VERBS], ids=["form", "chart", "verbs"])
def test_columns_and_blanks_fit_the_page(page: str, task: dict[str, Any]) -> None:
    ws = _ws(task)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, task["id"])
    widths = _column_widths(section)
    content = EPAPER_CONTENT_W if page == "epaper" else A4_CONTENT_W
    assert sum(widths) <= content - GUTTER_W + 0.1
    rows = re.findall(r"<tr>(.*?)</tr>", section.split("<tbody>", 1)[1])
    for row in rows:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row)
        for width, cell in zip(widths, cells):
            for blank in re.findall(r'class="blank" style="width:([\d.]+)mm"', cell):
                assert 10.0 <= float(blank) <= width - 2.0, (cell, width)


def test_hints_and_first_letters_are_printed_in_the_cells() -> None:
    table = {**FORM, "hint": "base_form",
             "rows": [["Ernte", "die Bauern {{ernten::ernten}}"], ["Sonne", "sie {{trocknen::trocknen}}"],
                      ["Schiff", "sie {{werden::werden}} gebracht"]]}
    ws = _ws(table)
    section = _section(build_html(ws), ws, "tab1")
    assert section.count('<span class="hint">(ernten)</span>') == 1
    table = {**FORM, "hint": "first_letter"}
    ws = _ws(table)
    section = _section(build_html(ws), ws, "tab1")
    assert '<span class="fl">Ä</span>' in section and '<span class="fl">S</span>' in section


def test_table_text_is_escaped() -> None:
    table = {**FORM, "caption": "Preise <b> & Co", "head": ["Ware <i>", "Preis"],
             "rows": [["Kaffee <script>", "{{3 €}} & mehr"], ["Tee", None]]}
    ws = _ws(table)
    section = _section(build_html(ws), ws, "tab1")
    assert "Preise &lt;b&gt; &amp; Co" in section and "<th>Ware &lt;i&gt;</th>" in section
    assert "Kaffee &lt;script&gt;" in section and "&amp; mehr" in section
    assert "<script>" not in section and "<b>" not in section


def test_a_row_of_the_wrong_length_still_renders() -> None:
    ws = _ws({**CHART, "rows": [["hell", "{{hellbraun}}"], ["mittel", "braun", "rund", None, "x"]]})
    section = _section(build_html(ws), ws, "tab2")
    assert len(_column_widths(section)) == 5
    assert section.count("<td") == 10


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _pymupdf():
    """pymupdf, or a skip (a failure with LANGWICH_REQUIRE_PDF=1) without
    WeasyPrint or pymupdf — as in tests/test_render.py."""
    missing = []
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError):
        missing.append("WeasyPrint")
    if importlib.util.find_spec("pymupdf") is None:
        missing.append("pymupdf")
    if missing:
        reason = f"{' and '.join(missing)} not available"
        if os.environ.get("LANGWICH_REQUIRE_PDF", "").strip() not in ("", "0"):
            pytest.fail(f"{reason}, but LANGWICH_REQUIRE_PDF is set")
        pytest.skip(reason)
    import pymupdf

    return pymupdf


def test_the_widest_table_fits_an_epaper_page(tmp_path: Path) -> None:
    pymupdf = _pymupdf()
    data = _data(VERBS, CHART)
    data["tasks"] = [t for t in data["tasks"] if t["id"] in ("tab3", "tab2")]
    ws = worksheet_from_dict(data)
    result = render_worksheet(ws, tmp_path / "table.pdf",
                              RenderOptions(page="epaper", solutions="none"))
    assert result.pdf is not None and result.warnings == []
    doc = pymupdf.open(result.pdf)
    words: list[str] = []
    for page in doc:
        width = page.rect.width
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if span["text"].strip():
                        x0, _, x1, _ = span["bbox"]
                        assert x0 >= 8 * MM - 2 and x1 <= width - 8 * MM + 2, span["text"]
        words += [w[4] for w in page.get_text("words")]
    for word in ("trocknen", "Präteritum", "Infinitiv", "Röstprotokoll", "süßlich"):
        assert word in words, f"{word!r} was broken or lost"
