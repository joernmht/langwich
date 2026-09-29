"""The classify kind: checks, row order, word box, answer key and rendering."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key
from langwich.model import ClassifyTask, ContractError, parse_worksheet, worksheet_from_dict
from langwich.plan import plan
from langwich.plan import tested_terms as collect_tested_terms
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.css import A4_CONTENT_W, EPAPER_CONTENT_W, GUTTER_W, MAIN_W
from langwich.render.tasks import CLASSIFY_COL_MIN, CLASSIFY_KEEP_ROWS
from langwich.validate import CHECKS, Issue, validate
from tests.test_render import need_pdf

#: The validator codes this file triggers (see tests/test_validate.py).
COVERED_CODES = {"category-unused", "duplicate-entry"}

ROOT = Path(__file__).resolve().parent.parent
MM = 72 / 25.4
NBSP = " "
LENA = ROOT / "examples" / "lena_01_en_de.json"
SHOWCASE = ROOT / "tests" / "fixtures" / "kinds_showcase.json"

CAST = ["Lena", "Frau Berger", "Herr Novak"]

#: Who does what in Lena's week (a grid across the whole story).
WHO: list[dict[str, str]] = [
    {"text": "trinkt seit vierzig Jahren jeden Morgen eine Melange", "answer": "Herr Novak"},
    {"text": "gibt Lena eine Schürze", "answer": "Frau Berger"},
    {"text": "riecht an den grünen Bohnen", "answer": "Lena"},
    {"text": "öffnet einen großen Sack aus Jute", "answer": "Frau Berger"},
    {"text": "dreht die Hitze höher", "answer": "Lena"},
    {"text": "schiebt die Zuckerdose zur Seite", "answer": "Herr Novak"},
    {"text": "röstet neue Bohnen, langsam und nicht so dunkel", "answer": "Lena"},
]

GENDERS = ["der", "die", "das"]

#: Nouns of scene 2 without their articles (a columns task).
NOUNS: list[dict[str, str]] = [
    {"text": "Sack", "answer": "der"},
    {"text": "Bohne", "answer": "die"},
    {"text": "Land", "answer": "das"},
    {"text": "Äquator", "answer": "der"},
    {"text": "Kaffeekirsche", "answer": "die"},
    {"text": "Schiff", "answer": "das"},
    {"text": "Bauer", "answer": "der"},
    {"text": "Sonne", "answer": "die"},
]

#: The index of the classify task in the worksheets below (t7's place).
AT = 6


def _data(items: list[dict[str, str]] | None = None, categories: list[str] | None = None,
          **fields: Any) -> dict[str, Any]:
    """Lena with a classify task in place of t7 (the task count stays the
    same): who does what, unless other items are given."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = {"id": "sort", "kind": "classify", "stage": "gist", "scene": ["s1", "s2", "s3", "s4"],
            "categories": list(categories or CAST), "items": copy.deepcopy(items or WHO),
            **fields}
    data["tasks"] = [task if t["id"] == "t7" else t for t in data["tasks"]]
    assert data["tasks"][AT] is task
    return data


def _nouns(categories: list[str] | None = None, **fields: Any) -> dict[str, Any]:
    """Lena with a der/die/das columns task after scene 2."""
    return _data(NOUNS, categories or GENDERS,
                 **{"stage": "form", "scene": "s2", "layout": "columns", **fields})


def _ws(items: list[dict[str, str]] | None = None, categories: list[str] | None = None,
        **fields: Any):
    return worksheet_from_dict(_data(items, categories, **fields))


def _hits(data: dict[str, Any], code: str) -> list[Issue]:
    return [i for i in validate(worksheet_from_dict(data)).issues if i.code == code]


def _planned(ws, seed: int | None = None):
    return next(pt for pt in plan(ws, seed).tasks if isinstance(pt.task, ClassifyTask))


def _section(html: str) -> str:
    m = re.search(r'<section class="task unit k-classify[^"]*"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, "classify task not found"
    return m.group(0)


def _mm(style: str, prop: str = "width") -> float:
    m = re.search(rf"{prop}:([\d.]+)mm", style)
    assert m, style
    return float(m.group(1))


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_defaults_to_the_grid():
    task = _ws().tasks[AT]
    assert isinstance(task, ClassifyTask)
    assert task.layout == "grid"
    assert task.categories == CAST
    assert [(i.text, i.answer) for i in task.items] == [(i["text"], i["answer"]) for i in WHO]


@pytest.mark.parametrize("change", [
    lambda t: t.__setitem__("categories", ["Lena"]),
    lambda t: t.__setitem__("categories", ["a", "b", "c", "d", "e", "f", "g"]),
    lambda t: t.__setitem__("items", t["items"][:1]),
    lambda t: t["items"][0].__setitem__("text", ""),
    lambda t: t["items"][0].pop("answer"),
    lambda t: t.__setitem__("layout", "table"),
    lambda t: t["items"][0].__setitem__("hint", "Novak"),  # unknown field
])
def test_contract_rejects_bad_tasks(change):
    data = _data()
    change(data["tasks"][AT])
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


def test_categories_must_be_distinct():
    with pytest.raises(ContractError, match="categories must be distinct"):
        _ws(categories=["Lena", "Frau Berger", "lena"])


@pytest.mark.parametrize("answer, guess", [
    ("lena", "did you mean 'Lena'?"),              # the case of a letter
    ("Frau Bergers", "did you mean 'Frau Berger'?"),
    ("the owner", "copy the category exactly."),   # nothing close
])
def test_an_answer_must_be_copied_from_the_categories(answer, guess):
    items = copy.deepcopy(WHO)
    items[3]["answer"] = answer
    with pytest.raises(ContractError) as err:
        _ws(items)
    message = str(err.value)
    assert (f"items[3].answer '{answer}' is not one of the categories ('Lena', 'Frau Berger', "
            "'Herr Novak'); copy the category exactly") in message
    assert guess in message


@pytest.mark.parametrize("kind", ["categorize", "sorting", "who said what", "Multiple-Matching"])
def test_lenient_loading_reads_the_aliases_as_classify(kind):
    data = _data()
    data["tasks"][AT]["kind"] = kind
    ws, notes = parse_worksheet(json.dumps(data, ensure_ascii=False))
    assert isinstance(ws.tasks[AT], ClassifyTask)
    assert any(n.code == "normalized" for n in notes)


# ---------------------------------------------------------------------------
# Validator: duplicate-entry, category-unused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("data", [_data(), _nouns()], ids=["grid", "columns"])
def test_a_good_task_passes(data):
    report = validate(worksheet_from_dict(data))
    assert report.ok
    assert not [i for i in report.issues if i.code in COVERED_CODES]


def test_a_repeated_item_is_an_error():
    items = [*WHO, {"text": "Gibt  Lena eine\nSchürze", "answer": "Frau Berger"}]
    hits = _hits(_data(items), "duplicate-entry")
    assert [(i.level, i.where) for i in hits] == [("error", f"/tasks/{AT}/items/7/text")]
    message = hits[0].message
    assert "the item 'Gibt Lena eine Schürze' is already listed (items/1)" in message
    assert "learners would sort it twice" in message
    assert "Replace it with another word or sentence from the story" in message


def test_an_item_in_two_categories_says_neither_answer_is_right():
    items = [*WHO, {"text": "dreht die Hitze höher", "answer": "Frau Berger"}]
    hits = _hits(_data(items), "duplicate-entry")
    assert [i.where for i in hits] == [f"/tasks/{AT}/items/7/text"]
    assert ("it belongs to both 'Lena' and 'Frau Berger', so neither answer is right"
            in hits[0].message)


def test_similar_items_are_not_repeats():
    items = [*WHO, {"text": "riecht an den roten Bohnen", "answer": "Frau Berger"}]
    assert not _hits(_data(items), "duplicate-entry")


def test_an_empty_category_is_a_warning():
    data = _data(categories=["Lena", "Frau Berger", "Marco", "Herr Novak"])
    hits = _hits(data, "category-unused")
    assert [(i.level, i.where) for i in hits] == [("warning", f"/tasks/{AT}/categories/2")]
    message = hits[0].message
    assert "no item has the answer 'Marco', so its column stays empty" in message
    assert "Add 1–2 items that belong to it, or remove the category from 'categories'." in message


def test_one_of_two_categories_empty_cannot_just_be_removed():
    items = [i for i in WHO if i["answer"] == "Lena"]
    hits = _hits(_data(items, ["Lena", "Herr Novak"]), "category-unused")
    assert [i.where for i in hits] == [f"/tasks/{AT}/categories/1"]
    assert "replace it with a category that some of the items belong to" in hits[0].message
    assert "remove the category" not in hits[0].message


def test_every_empty_category_is_named():
    data = _nouns(categories=["der", "die", "das", "den", "dem"])
    assert [i.where for i in _hits(data, "category-unused")] == [
        f"/tasks/{AT}/categories/3", f"/tasks/{AT}/categories/4"]


#: A grammar box on the genders of scene 2, printed beside the classify task.
GENDER_BOX: dict[str, Any] = {
    "id": "g3", "name": "der, die, das", "explanation": "Every noun has a gender.",
    "rule": "der (masculine), die (feminine), das (neuter)",
}


@pytest.mark.parametrize(("box", "shown"), [
    # the table sorts the items into the columns of their categories
    ({"table": {"head": ["der", "die", "das"], "rows": [["Sack", "Bohne", "Schiff"]]}},
     "der Sack"),
    ({"table": {"head": ["", "der", "die"], "rows": [["Nomen", "der Tisch", "die Sonne"]]}},
     "die Sonne"),
    # an example gives an item with its category
    ({"examples": ["Der Bauer bringt die Kirschen."]}, "der Bauer"),
])
def test_a_grammar_box_beside_the_task_must_not_sort_its_items(
    box: dict[str, Any], shown: str,
) -> None:
    data = _nouns(grammar="g3")
    data["grammar"].append({**GENDER_BOX, "examples": ["Der Tisch ist groß."]})
    assert not _hits(data, "grammar-gives-away")
    data["grammar"][-1].update(box)
    hits = _hits(data, "grammar-gives-away")
    assert [i.where for i in hits] == ["/grammar/2"]
    assert f"shows its answer '{shown}'" in hits[0].message


def test_a_grammar_box_may_show_the_items_in_another_column():
    # the categories of other nouns, or the items without their category
    data = _nouns(grammar="g3")
    data["grammar"].append({**GENDER_BOX, "examples": ["Wo ist ein Sack?"],
                            "table": {"head": ["der", "die", "das"],
                                      "rows": [["Tisch", "Lampe", "Buch"]]}})
    assert not _hits(data, "grammar-gives-away")


def test_covered_codes_are_checks():
    assert COVERED_CODES <= set(CHECKS)
    assert CHECKS["duplicate-entry"][0] == "error"
    assert CHECKS["category-unused"][0] == "warning"


# ---------------------------------------------------------------------------
# Planner: the grid's rows, the columns' word box
# ---------------------------------------------------------------------------


def test_the_grid_rows_are_shuffled_the_same_way_for_the_same_seed():
    ws = _ws()
    pt = _planned(ws, 7)
    assert sorted(pt.row_order) == list(range(len(WHO)))
    assert pt.row_order == _planned(ws, 7).row_order
    assert pt.bank is None
    orders = {tuple(_planned(ws, seed).row_order) for seed in range(20)}
    assert len(orders) > 10


@pytest.mark.parametrize("n", [2, 3, 7])
def test_the_grid_never_keeps_the_written_order(n):
    ws = _ws(WHO[:n])
    for seed in range(60):
        assert _planned(ws, seed).row_order != list(range(n))


def test_the_columns_word_box_holds_every_item_once_shuffled():
    ws = worksheet_from_dict(_nouns())
    texts = [i["text"] for i in NOUNS]
    for seed in range(40):
        pt = _planned(ws, seed)
        assert pt.row_order is None
        assert sorted(pt.bank) == sorted(texts)
        assert pt.bank != texts
    assert _planned(ws, 3).bank == _planned(ws, 3).bank


def test_only_the_columns_items_are_tested_words():
    # the learner writes the words of a columns task: no gloss may give them away
    assert {"sack", "bohne", "kaffeekirsche"} <= collect_tested_terms(worksheet_from_dict(_nouns()))
    assert "gibt lena eine schürze" not in collect_tested_terms(_ws())


# ---------------------------------------------------------------------------
# Answer key
# ---------------------------------------------------------------------------


def test_the_grid_key_gives_the_category_of_each_printed_row():
    ws = _ws()
    pt = _planned(ws)
    assert answer_key(pt, ws) == [WHO[j]["answer"] for j in pt.row_order]


def test_the_columns_key_lists_each_categorys_words():
    ws = worksheet_from_dict(_nouns())
    assert answer_key(_planned(ws), ws) == [
        f"der:{NBSP}Sack, Äquator, Bauer",
        f"die:{NBSP}Bohne, Kaffeekirsche, Sonne",
        f"das:{NBSP}Land, Schiff",
    ]
    ws = worksheet_from_dict(_nouns(categories=["der", "die", "das", "den"]))
    assert answer_key(_planned(ws), ws)[-1] == f"den:{NBSP}–"


def _solution(html: str, title: str) -> str:
    solutions = html.split('class="solutions', 1)[1]
    return solutions.split(title, 1)[1].split('<div class="sb">', 1)[0]


def test_the_key_is_numbered_like_the_grid_rows():
    ws = _ws()
    block = _solution(build_html(ws), "Sort them")
    assert re.findall(r'<span class="kn">(\d+)</span>', block) == [
        str(n) for n in range(1, len(WHO) + 1)]
    pt = _planned(ws)
    first = WHO[pt.row_order[0]]["answer"]
    assert f'<span class="kn">1</span>{NBSP}<span class="k" lang="de">{first}' in block


def test_the_columns_key_has_no_numbers():
    block = _solution(build_html(worksheet_from_dict(_nouns())), "Sort them")
    assert 'class="kn"' not in block
    assert f"der:{NBSP}Sack, Äquator, Bauer" in block


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_grid_is_a_table_with_a_tick_box_per_category(page):
    ws = _ws()
    pt = _planned(ws)
    section = _section(build_html(ws, RenderOptions(page=page)))
    assert "Tick the right column for each line." in section
    assert " keep" in section and "data-soft" not in section  # seen whole
    heads = re.findall(r'<th class="cat tl" lang="de">([^<]+)</th>', section)
    assert heads == CAST  # names head the columns in the serif face
    rows = re.findall(r'<tr><td class="n">(\d+)</td><td class="t tl" lang="de">([^<]+)</td>',
                      section)
    assert rows == [(str(n), WHO[j]["text"]) for n, j in enumerate(pt.row_order, 1)]
    assert section.count('<td class="bx"><span></span></td>') == len(WHO) * len(CAST)
    for item in WHO:  # the answers are not printed beside the items
        assert f">{item['answer']}</td>" not in section


def test_source_language_categories_are_set_in_sans():
    categories = ["nervous", "impatient", "disappointed"]
    items = [{"text": "„Das dauert ja ewig“, denkt Lena.", "answer": "impatient"},
             {"text": "Lenas Hände zittern.", "answer": "nervous"},
             {"text": "Der Kaffee ist viel zu bitter.", "answer": "disappointed"}]
    section = _section(build_html(_ws(items, categories, stage="detail", scene=["s3", "s4"])))
    assert re.findall(r'<th class="cat">([^<]+)</th>', section) == categories


def test_a_long_grid_may_break_between_rows():
    items = [{"text": f"{i['text']} ({n})", "answer": i["answer"]}
             for n in (1, 2) for i in WHO][:CLASSIFY_KEEP_ROWS + 1]
    section = _section(build_html(_ws(items)))
    assert 'data-soft="1"' in section  # kept whole unless the page before stays empty
    section = _section(build_html(_ws(items[:CLASSIFY_KEEP_ROWS])))
    assert "data-soft" not in section


def _grid_widths(section: str) -> tuple[float, list[float]]:
    table = re.search(r'<table class="cls grid" style="([^"]+)">', section)
    assert table
    cols = [float(w) for w in re.findall(r'<col style="width:([\d.]+)mm">', section)]
    return _mm(table.group(1)), cols


@pytest.mark.parametrize("page, grammar, width", [
    ("a4", None, A4_CONTENT_W), ("a4", "g2", MAIN_W), ("epaper", "g2", EPAPER_CONTENT_W)])
def test_the_grid_fits_its_column(page, grammar, width):
    fields = {"grammar": grammar} if grammar else {}
    section = _section(build_html(_ws(**fields), RenderOptions(page=page)))
    assert ('<aside class="aside-stack">' in section) == (width == MAIN_W)
    total, cols = _grid_widths(section)
    assert cols[0] == GUTTER_W and len(cols) == 2 + len(CAST)
    assert total == pytest.approx(sum(cols), abs=.2)
    assert total <= width + .1
    assert all(w >= CLASSIFY_COL_MIN for w in cols[2:])


def test_short_items_keep_the_boxes_near_the_words():
    items = [{"text": i["text"], "answer": i["answer"]} for i in NOUNS]
    total, cols = _grid_widths(_section(build_html(_ws(items, GENDERS, stage="form",
                                                       scene="s2"))))
    assert total < A4_CONTENT_W / 2
    assert cols[2:] == [CLASSIFY_COL_MIN] * 3  # der, die, das: the narrowest columns


def test_six_long_categories_still_fit_beside_a_side_column():
    categories = ["Montagmorgen", "Dienstagmittag", "Mittwochabend", "Donnerstagnacht",
                  "Freitagfrüh", "Samstagabend"]
    items = [{"text": f"Lena arbeitet am {c}.", "answer": c} for c in categories]
    section = _section(build_html(_ws(items, categories, grammar="g2")))
    assert '<aside class="aside-stack">' in section
    total, cols = _grid_widths(section)
    assert total <= MAIN_W + .1
    assert cols[1] > 30  # the items keep a readable column


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_columns_print_the_word_box_and_a_column_per_category(page):
    ws = worksheet_from_dict(_nouns())
    pt = _planned(ws)
    section = _section(build_html(ws, RenderOptions(page=page)))
    assert "Write each word from the box in the right column." in section
    assert " keep" in section and "data-soft" not in section
    box = re.search(r'<ul class="words tl" lang="de">(.*?)</ul>', section)
    assert box and re.findall(r"<li>([^<]+)</li>", box.group(1)) == pt.bank
    assert re.findall(r'<th class="cat tl" lang="de">([^<]+)</th>', section) == GENDERS
    # 3 words at most in a category, and one line more
    assert section.count("<tr><td><span></span>") == 4
    assert section.count("<td><span></span></td>") == 4 * len(GENDERS)
    width = EPAPER_CONTENT_W if page == "epaper" else A4_CONTENT_W
    table = re.search(r'<table class="cls cols" style="([^"]+)">', section)
    assert table and _mm(table.group(1)) == pytest.approx(width - GUTTER_W, abs=.1)


def test_own_instruction_wins():
    data = _nouns(instruction="Sortiere die Wörter nach ihrem Artikel.")
    section = _section(build_html(worksheet_from_dict(data)))
    assert '<p class="ins">Sortiere die Wörter nach ihrem Artikel.</p>' in section


def test_text_is_escaped():
    items = copy.deepcopy(WHO)
    items[2]["text"] = "riecht <b>an</b> den Bohnen & lacht"
    categories = ["Lena", "Frau <Berger>", "Herr Novak"]
    for item in items:
        if item["answer"] == "Frau Berger":
            item["answer"] = "Frau <Berger>"
    section = _section(build_html(_ws(items, categories)))
    assert "riecht &lt;b&gt;an&lt;/b&gt; den Bohnen &amp; lacht" in section
    assert ">Frau &lt;Berger&gt;</th>" in section
    assert "<b>an" not in section and "<Berger>" not in section


def test_german_learners_sort_a_french_story():
    """The showcase's classify task (who does what in a French story), with
    the built-in German title and instructions."""
    data = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["kind"] == "classify")
    assert task["categories"] == ["Mila", "Karim", "Madame Roux"]
    del task["title"], task["instruction"]
    ws = worksheet_from_dict(data)
    assert not [i for i in validate(ws).issues if i.code in COVERED_CODES]
    options = RenderOptions(base_dir=SHOWCASE.parent)
    section = _section(build_html(ws, options))
    assert ">Sortiere</h3>" in section
    assert "Kreuze für jede Zeile die richtige Spalte an." in section
    assert '<th class="cat tl" lang="fr">Madame Roux</th>' in section
    task["layout"] = "columns"
    section = _section(build_html(worksheet_from_dict(data), options))
    assert "Schreibe jedes Wort aus dem Kasten in die richtige Spalte." in section
    assert '<span class="cap">Wortkasten</span>' in section


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_pdf_boxes_line_up_under_their_headings(tmp_path, page):
    """One tick box per row and category: the boxes of a column share one x,
    centred under the category's heading; those of a row share one y; the
    grid stays inside the page."""
    pymupdf = need_pdf(pymupdf=True)
    out = tmp_path / "classify.pdf"
    data = _data()
    data["tasks"] = data["tasks"][AT:AT + 1]  # the story and the task: a quick render
    result = render_worksheet(worksheet_from_dict(data), out,
                              RenderOptions(page=page, base_dir=LENA.parent))
    assert result.weasyprint_error is None
    found_on = []  # (page, its tick boxes)
    for pdf_page in pymupdf.open(out):
        # (a frame: a filled square with a square hole)
        boxes = [d["rect"] for d in pdf_page.get_drawings()
                 if d["type"] == "f" and len(d["items"]) == 2
                 and abs(d["rect"].width - 4.4 * MM) < .1 * MM
                 and abs(d["rect"].height - 4.4 * MM) < .1 * MM]
        if boxes:
            found_on.append((pdf_page, boxes))
    assert len(found_on) == 1  # the whole grid on one page
    pdf_page, boxes = found_on[0]
    assert len(boxes) == len(WHO) * len(CAST)
    xs = sorted({round((r.x0 + r.x1) / 2, 1) for r in boxes})
    ys = sorted({round((r.y0 + r.y1) / 2, 1) for r in boxes})
    assert len(xs) == len(CAST) and len(ys) == len(WHO)
    for name, x in zip(CAST, xs):
        words = name.split()
        found = [w for w in pdf_page.get_text("words")
                 if w[4] in words and min(ys) - 15 * MM < w[3] < min(ys)]
        assert found, name
        heading = (min(w[0] for w in found) + max(w[2] for w in found)) / 2
        assert abs(heading - x) < 1 * MM, name
    assert all(pdf_page.rect.contains(r) for r in boxes)
    assert max(r.x1 for r in boxes) < pdf_page.rect.x1 - 8 * MM
