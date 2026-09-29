"""The crossword kind: grid layout, checks, answer key and rendering."""

from __future__ import annotations

import copy
import json
import random
import re
import time
from pathlib import Path
from typing import Any

import pytest
from fontTools.ttLib import TTFont

from langwich import crossword
from langwich.answers import answer_key
from langwich.crossword import MAX_SIDE, Layout, enclosed, layout, letters, printed
from langwich.model import ContractError, CrosswordTask, parse_worksheet, worksheet_from_dict
from langwich.plan import plan
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.css import BASE_CSS, FONT_FILES, FONTS_DIR, GUTTER_W, MAIN_W
from langwich.validate import CHECKS, Issue, validate
from tests.test_render import need_pdf

#: The validator codes this file triggers (see tests/test_validate.py).
COVERED_CODES = {"crossword-word", "crossword-layout", "clue-is-answer", "duplicate-entry"}

ROOT = Path(__file__).resolve().parent.parent
MM = 72 / 25.4
LENA = ROOT / "examples" / "lena_01_en_de.json"
SHOWCASE = ROOT / "tests" / "fixtures" / "kinds_showcase.json"

#: Key words of the Lena story with B1 clues in the target language.
ENTRIES: list[dict[str, str]] = [
    {"answer": "Bohne", "clue": "Aus ihr macht man Kaffee; vor dem Rösten ist sie grün."},
    {"answer": "ernten", "clue": "Im Herbst pflücken die Bauern die roten Kirschen: Sie ___ sie."},
    {"answer": "trocknen",
     "clue": "Die Kaffeekirschen liegen in der Sonne, bis sie nicht mehr nass sind. Sie ___."},
    {"answer": "rösten", "clue": "Grüne Bohnen in einer heißen Trommel braun machen."},
    {"answer": "Geschmack",
     "clue": "Fruchtig oder kräftig: So schmeckt ein Kaffee. Das ist sein ___."},
    {"answer": "bitter", "clue": "Das Gegenteil von süß."},
    {"answer": "Milchschaum", "clue": "Die weiße, lockere Haube auf einem Cappuccino."},
    {"answer": "Stammgast", "clue": "Jemand, der seit Jahren jeden Morgen in dasselbe Café kommt."},
    {"answer": "Zucker", "clue": "Herr Novak nimmt drei Löffel davon, denn er mag es süß."},
    {"answer": "Melange", "clue": "Ein typischer Wiener Kaffee mit heißer Milch und Schaum."},
]

#: Six more, for a 16-word grid (the contract's maximum).
MORE_ENTRIES: list[dict[str, str]] = [
    {"answer": "Theke", "clue": "Hinter ihr steht Lena und macht den Kaffee."},
    {"answer": "Schürze",
     "clue": "Frau Berger gibt sie Lena am ersten Tag, damit ihre Kleidung sauber bleibt."},
    {"answer": "Fenster", "clue": "Dort sitzt Herr Novak jeden Morgen und schaut hinaus."},
    {"answer": "Kaffeekirsche", "clue": "Die rote Frucht, in der die Bohnen wachsen."},
    {"answer": "Rösterei", "clue": "Der kleine Raum hinter dem Café, in dem die Bohnen braun werden."},
    {"answer": "Geduld", "clue": "Frau Berger sagt: Rösten braucht ___."},
]

#: 'Kuh' shares no letter with the other words: it cannot join the grid.
NIGHT: list[dict[str, str]] = [
    {"answer": "Sonne", "clue": "Sie scheint am Tag."},
    {"answer": "Mond", "clue": "Er scheint in der Nacht."},
    {"answer": "Stern", "clue": "Ein kleines Licht am Himmel."},
    {"answer": "Nest", "clue": "Das Haus eines Vogels."},
    {"answer": "Kuh", "clue": "Sie gibt Milch."},
]


def _data(entries: list[dict[str, str]] | None = None, **fields: Any) -> dict[str, Any]:
    """Lena with a crossword after scene 4 in place of task t13 (the task
    count stays the same)."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = {"id": "cw", "kind": "crossword", "stage": "practice", "scene": "s4",
            "clue_lang": "target", "entries": copy.deepcopy(entries or ENTRIES), **fields}
    data["tasks"] = [t for t in data["tasks"] if t["id"] != "t13"] + [task]
    return data


def _ws(entries: list[dict[str, str]] | None = None, **fields: Any):
    return worksheet_from_dict(_data(entries, **fields))


def _answers(entries: list[dict[str, str]]) -> list[str]:
    return [e["answer"] for e in entries]


def _hits(data: dict[str, Any], code: str) -> list[Issue]:
    issues = validate(worksheet_from_dict(data)).issues
    return [i for i in issues if i.code == code]


def _planned(ws, seed: int | None = None):
    return next(pt for pt in plan(ws, seed).tasks if isinstance(pt.task, CrosswordTask))


def _section(html: str) -> str:
    m = re.search(r'<section class="task unit k-crossword[^"]*"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, "crossword task not found"
    return m.group(0)


def _check_grid(answers: list[str], grid: Layout) -> None:
    """Everything a printed crossword needs: each placed word reads correctly
    in its cells, every run of two or more letters is exactly one placed word
    (so words only touch at crossings), the grid is one piece, within
    MAX_SIDE, turned landscape, numbered row by row, in clue order."""
    shapes = [letters(a) for a in answers]
    assert sorted([p.index for p in grid.placed] + list(grid.unplaced)) == list(range(len(answers)))
    covered: dict[tuple[int, int], set[str]] = {}
    for p in grid.placed:
        dr, dc = (0, 1) if p.across else (1, 0)
        for k, ch in enumerate(shapes[p.index]):
            cell = (p.row + dr * k, p.col + dc * k)
            assert grid.cells[cell] == printed(ch) or grid.cells[cell].lower() == ch.lower()
            covered.setdefault(cell, set()).add(ch.lower())
    assert set(covered) == set(grid.cells)
    assert all(len(found) == 1 for found in covered.values()), "a crossing of two letters"
    if not grid.placed:
        return
    assert grid.rows <= grid.cols <= MAX_SIDE
    assert {r for r, _ in grid.cells} == set(range(grid.rows))
    assert {c for _, c in grid.cells} == set(range(grid.cols))
    runs = set()
    for across in (True, False):
        for line in range(grid.rows if across else grid.cols):
            length = grid.cols if across else grid.rows
            k = 0
            while k < length:
                start = k
                while k < length and ((line, k) if across else (k, line)) in grid.cells:
                    k += 1
                if k - start >= 2:
                    runs.add(((line, start) if across else (start, line), across, k - start))
                k += 1
    placed = {((p.row, p.col), p.across, len(shapes[p.index])) for p in grid.placed}
    assert runs == placed
    seen, todo = set(), [next(iter(grid.cells))]
    while todo:
        r, c = todo.pop()
        if (r, c) in seen or (r, c) not in grid.cells:
            continue
        seen.add((r, c))
        todo += [(r + 1, c), (r - 1, c), (r, c + 1), (r, c - 1)]
    assert seen == set(grid.cells), "the grid falls apart"
    starts = sorted({(p.row, p.col) for p in grid.placed})
    assert all(p.number == starts.index((p.row, p.col)) + 1 for p in grid.placed)
    order = [(not p.across, p.number) for p in grid.placed]
    assert order == sorted(order)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_accepts_a_crossword_and_defaults_to_source_clues():
    data = _data()
    del data["tasks"][-1]["clue_lang"]
    task = worksheet_from_dict(data).tasks[-1]
    assert isinstance(task, CrosswordTask)
    assert task.clue_lang == "source"
    assert [e.answer for e in task.entries] == _answers(ENTRIES)


@pytest.mark.parametrize("change", [
    lambda t: t.__setitem__("entries", t["entries"][:3]),              # fewer than 4
    lambda t: t.__setitem__("entries", t["entries"] * 2),              # more than 16
    lambda t: t["entries"][0].__setitem__("answer", "B"),              # one letter
    lambda t: t["entries"][0].__setitem__("clue", ""),                 # no clue
    lambda t: t.__setitem__("clue_lang", "german"),
    lambda t: t["entries"][0].__setitem__("hint", "b"),                # unknown field
])
def test_contract_rejects_bad_crosswords(change):
    data = _data()
    change(data["tasks"][-1])
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


def test_lenient_loading_reads_crossword_puzzle_as_crossword():
    data = _data()
    data["tasks"][-1]["kind"] = "crossword-puzzle"
    ws, notes = parse_worksheet(json.dumps(data, ensure_ascii=False))
    assert isinstance(ws.tasks[-1], CrosswordTask)
    assert any(n.code == "normalized" for n in notes)


# ---------------------------------------------------------------------------
# Layout
# ---------------------------------------------------------------------------


def test_layout_joins_every_key_word_of_the_story():
    answers = _answers(ENTRIES)
    grid = layout(answers)
    assert grid.unplaced == ()
    _check_grid(answers, grid)
    assert len(grid.placed) == len(answers)
    assert any(p.across for p in grid.placed) and not all(p.across for p in grid.placed)


def test_layout_holds_sixteen_words_within_the_largest_grid():
    answers = _answers(ENTRIES + MORE_ENTRIES)
    grid = layout(answers)
    assert grid.unplaced == ()
    _check_grid(answers, grid)
    assert grid.rows <= MAX_SIDE and grid.cols <= MAX_SIDE


@pytest.mark.parametrize("seed", range(6))
def test_layout_rules_hold_for_many_word_sets(seed):
    rng = random.Random(seed)
    for _ in range(25):
        answers = ["".join(rng.choice("aeinrstlodhuk") for _ in range(rng.randint(2, 14)))
                   for _ in range(rng.randint(4, 16))]
        grid = layout(answers)
        _check_grid(answers, grid)


def test_crossings_compare_letters_whatever_their_case():
    grid = layout(["Bohne", "bitter"])  # B/b and e/e are the shared letters
    assert grid.unplaced == ()
    _check_grid(["Bohne", "bitter"], grid)
    bohne, bitter = sorted(grid.placed, key=lambda p: p.index)
    assert bohne.across != bitter.across
    assert set(grid.cells.values()) <= set("BOHNEITR")


def test_a_cell_starting_two_words_has_one_number():
    grid = layout(["Hund", "Hose"])  # they share only the H
    assert [(p.number, p.across) for p in grid.placed] == [(1, True), (1, False)]
    assert (grid.placed[0].row, grid.placed[0].col) == (grid.placed[1].row, grid.placed[1].col)


def test_words_that_share_no_letter_are_unplaced():
    answers = _answers(NIGHT)
    grid = layout(answers)
    assert grid.unplaced == (answers.index("Kuh"),)
    _check_grid(answers, grid)


def test_a_word_longer_than_the_grid_is_unplaced():
    long = "Kaffeekirschenernte" + "n"  # 20 letters
    assert len(long) > MAX_SIDE
    answers = [*_answers(ENTRIES[:5]), long]
    grid = layout(answers)
    assert grid.unplaced == (5,)
    _check_grid(answers, grid)


def test_duplicates_never_share_their_cells():
    answers = ["Bohne", "Bohne", "Zucker", "Melange", "bitter"]
    grid = layout(answers)
    _check_grid(answers, grid)


def test_layout_is_deterministic_and_does_not_depend_on_the_render_seed():
    answers = _answers(ENTRIES + MORE_ENTRIES)
    first = layout(answers)
    crossword._layout.cache_clear()
    assert layout(list(answers)) == first
    ws = _ws(ENTRIES + MORE_ENTRIES)
    assert _planned(ws, seed=1).crossword == _planned(ws, seed=2).crossword == first


def test_layout_is_fast():
    answers = _answers(ENTRIES + MORE_ENTRIES)
    crossword._layout.cache_clear()
    start = time.perf_counter()
    layout(answers)
    assert time.perf_counter() - start < 0.25  # about 20 ms on a laptop


def test_empty_and_single_answers():
    assert layout([]) == Layout(rows=0, cols=0, placed=(), unplaced=(), cells={})
    grid = layout(["Kaffee"])
    assert (grid.rows, grid.cols, grid.unplaced) == (1, 6, ())
    assert "".join(grid.cells[(0, c)] for c in range(6)) == "KAFFEE"


def test_letters_print_in_capitals_one_per_cell():
    assert printed("Straße") == "STRAßE"  # ß has no one-letter capital
    assert letters("Café") == ["C", "a", "f", "é"]  # a combining accent stays on its letter
    grid = layout(["Straße", "Soße", "Salz", "Suppe"])
    _check_grid(["Straße", "Soße", "Salz", "Suppe"], grid)
    assert "ß" in grid.cells.values()
    assert all(v == v.upper() or v == "ß" for v in grid.cells.values())


def test_is_word():
    assert crossword.is_word("Bohne") and crossword.is_word("rösten")
    assert crossword.is_word("Café")
    for bad in ("die Bohne", "Kaffee-Bohne", "aujourd'hui", "B2", "Zug_Nummer", ""):
        assert not crossword.is_word(bad), bad


def test_enclosed_cells_are_the_ones_letters_cut_off():
    ring = {(r, c): "A" for r in range(3) for c in range(3) if (r, c) != (1, 1)}
    grid = Layout(rows=3, cols=3, placed=(), unplaced=(), cells=ring)
    assert enclosed(grid) == {(1, 1)}
    notch = {cell: "A" for cell in ring if cell != (0, 1)}
    assert enclosed(Layout(rows=3, cols=3, placed=(), unplaced=(), cells=notch)) == set()


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------


def test_a_good_crossword_passes_the_crossword_checks():
    report = validate(_ws())
    assert report.ok
    assert not [i for i in report.issues if i.code in COVERED_CODES]
    assert not [i for i in validate(_ws(ENTRIES + MORE_ENTRIES)).issues if i.code in COVERED_CODES]


@pytest.mark.parametrize(("answer", "fix"), [
    ("die Bohne", "'Bohne'"),
    ("Kaffee-Bohne", "single word"),
    ("Espresso2", "numbers as words"),
])
def test_crossword_word(answer, fix):
    data = _data()
    data["tasks"][-1]["entries"][0]["answer"] = answer
    hits = _hits(data, "crossword-word")
    assert [(i.level, i.where) for i in hits] == [("error", "/tasks/13/entries/0/answer")]
    assert fix in hits[0].message
    # the layout error does not name it again
    assert not any(answer in i.message for i in _hits(data, "crossword-layout"))


def test_duplicate_entry():
    entries = copy.deepcopy(ENTRIES)
    entries[4]["answer"] = "bohne"
    hits = _hits(_data(entries), "duplicate-entry")
    assert [(i.level, i.where) for i in hits] == [("error", "/tasks/13/entries/4/answer")]
    assert "entries/0" in hits[0].message


def test_a_grammar_box_beside_the_crossword_must_not_show_its_words():
    data = _data(grammar="g3")
    data["grammar"].append({"id": "g3", "name": "Compound nouns",
                            "explanation": "German glues nouns together.",
                            "rule": "Nomen + Nomen", "examples": ["der Stadtplan"]})
    assert not _hits(data, "grammar-gives-away")
    data["grammar"][-1]["examples"] = ["die Milch + der Schaum = der Milchschaum"]
    hits = _hits(data, "grammar-gives-away")
    assert [i.where for i in hits] == ["/grammar/2"]
    assert "shows its answer 'Milchschaum'" in hits[0].message


def test_crossword_layout_names_the_words_the_grid_cannot_take():
    data = _data(NIGHT)
    hits = _hits(data, "crossword-layout")
    assert [(i.level, i.where) for i in hits] == [("error", "/tasks/13/entries")]
    assert "'Kuh' (entries/4)" in hits[0].message
    assert "share" in hits[0].message
    # the same layout as every render
    unplaced = _planned(worksheet_from_dict(data)).crossword.unplaced
    assert [NIGHT[i]["answer"] for i in unplaced] == ["Kuh"]


def test_crossword_layout_names_a_word_too_long_for_the_grid():
    entries = copy.deepcopy(ENTRIES)
    entries[3]["answer"] = "Kaffeekirschenernten"
    hits = _hits(_data(entries), "crossword-layout")
    assert [(i.level, i.where) for i in hits] == [("error", "/tasks/13/entries/3/answer")]
    assert "20 letters" in hits[0].message and str(MAX_SIDE) in hits[0].message


def test_clue_is_answer():
    entries = copy.deepcopy(ENTRIES)
    entries[0]["clue"] = "Die grüne bohne: aus ihr macht man Kaffee."
    entries[8]["clue"] = "Sie steht in der Zuckerdose."  # a longer word: no give-away
    hits = _hits(_data(entries), "clue-is-answer")
    assert [(i.level, i.where) for i in hits] == [("warning", "/tasks/13/entries/0/clue")]


def test_covered_codes_are_checks():
    assert COVERED_CODES <= set(CHECKS)


# ---------------------------------------------------------------------------
# Answer key
# ---------------------------------------------------------------------------


def test_answer_key_lists_the_words_in_clue_order_in_capitals():
    ws = _ws()
    pt = _planned(ws)
    grid = pt.crossword
    assert grid is not None
    key = answer_key(pt, ws)
    assert key == [printed(ENTRIES[p.index]["answer"]) for p in grid.placed]
    assert "RÖSTEN" in key and "BOHNE" in key
    across = [p.number for p in grid.placed if p.across]
    down = [p.number for p in grid.placed if not p.across]
    assert [p.number for p in grid.placed] == sorted(across) + sorted(down)


def test_answer_key_numbers_say_across_or_down():
    ws = _ws()
    html = build_html(ws)
    grid = _planned(ws).crossword
    assert grid is not None
    solutions = html.split('class="solutions', 1)[1]
    for p in grid.placed:
        arrow = "→" if p.across else "↓"
        word = printed(ENTRIES[p.index]["answer"])
        assert f'<span class="kn">{p.number} {arrow}</span>' in solutions
        assert word in solutions


def test_the_arrows_of_the_key_are_in_the_bundled_fonts():
    # Atkinson (sans) has no arrows; Literata, second in the sans stack, has both
    assert '--sans: "Atkinson Hyperlegible Next", "Literata"' in BASE_CSS
    for family, _, _, name in FONT_FILES:
        if family == "Literata":
            cmap = TTFont(FONTS_DIR / name).getBestCmap()
            assert 0x2192 in cmap and 0x2193 in cmap, name


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_grid_and_clues_are_rendered(page):
    ws = _ws()
    grid = _planned(ws).crossword
    assert grid is not None
    section = _section(build_html(ws, RenderOptions(page=page)))
    assert " keep" in section and "data-soft" not in section  # must be seen whole
    assert f'lang="de" style="--cell:7.0mm;width:{7.0 * grid.cols:.1f}mm"' in section
    assert section.count("<tr>") == grid.rows
    assert section.count('<td class="x">') == len(grid.cells)
    assert section.count('class="bk"') == len(enclosed(grid))
    starts = {(p.row, p.col) for p in grid.placed}
    assert len(re.findall(r'<span class="cn">\d+</span>', section)) == len(starts)
    assert ">Across</span>" in section and ">Down</span>" in section
    # the learner writes the letters: none is printed in the grid
    table = section.split('<table class="cwg"', 1)[1].split(">", 1)[1].split("</table>", 1)[0]
    assert not re.search(r"[A-Za-zÄÖÜß]", re.sub(r"<[^>]+>", "", table))
    for entry in ENTRIES:  # target-language clues: serif, lang="de"
        assert f'<div class="c tl" lang="de">{entry["clue"]}</div>' in section


def test_source_language_clues_are_set_in_sans():
    ws = _ws(clue_lang="source",
             entries=[{**e, "clue": f"clue {i} in English"} for i, e in enumerate(ENTRIES)])
    section = _section(build_html(ws))
    assert '<div class="c src">clue 0 in English</div>' in section
    assert 'class="c tl"' not in section


def test_clues_are_escaped():
    entries = copy.deepcopy(ENTRIES)
    entries[0]["clue"] = "<b>Aus ihr</b> macht man Kaffee & Espresso."
    section = _section(build_html(_ws(entries)))
    assert "&lt;b&gt;Aus ihr&lt;/b&gt; macht man Kaffee &amp; Espresso." in section
    assert "<b>Aus ihr" not in section


def test_a_side_column_shrinks_the_cells_to_fit():
    data = _data(ENTRIES + MORE_ENTRIES, grammar="g9")
    data["grammar"].append({
        "id": "g9", "name": "Verbs as nouns",
        "explanation": "Any German infinitive can become a neuter noun.",
        "rule": "das + Infinitiv (groß)", "examples": ["Das Lesen macht Spaß."],
    })
    ws = worksheet_from_dict(data)
    grid = _planned(ws).crossword
    assert grid is not None and 7.0 * grid.cols > MAIN_W - GUTTER_W  # too wide at 7 mm
    section = _section(build_html(ws))
    assert '<aside class="aside-stack">' in section
    cell = float(re.search(r"--cell:([\d.]+)mm", section).group(1))
    assert 5.0 < cell < 7.0 and cell * grid.cols <= MAIN_W - GUTTER_W


def test_a_tall_grid_gets_smaller_cells_on_epaper():
    ws = _ws(ENTRIES + MORE_ENTRIES)
    grid = _planned(ws).crossword
    assert grid is not None and grid.rows > 12
    assert "--cell:7.0mm" in _section(build_html(ws))
    assert "--cell:6.0mm" in _section(build_html(ws, RenderOptions(page="epaper")))


def test_german_learners_read_waagerecht_and_senkrecht():
    """The showcase's crossword (French key words, German clues), with the
    built-in German title and instruction."""
    data = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["kind"] == "crossword")
    del task["title"], task["instruction"]
    ws = worksheet_from_dict(data)
    assert not [i for i in validate(ws).issues if i.code in COVERED_CODES]
    section = _section(build_html(ws, RenderOptions(base_dir=SHOWCASE.parent)))
    assert ">Waagerecht</span>" in section and ">Senkrecht</span>" in section
    assert ">Kreuzworträtsel</h3>" in section and "Löse das Kreuzworträtsel." in section
    assert '<div class="c src">der Markt</div>' in section


def test_unplaced_words_are_left_out_with_a_warning():
    from langwich.render.html import Builder

    builder = Builder(_ws(NIGHT))
    section = _section(builder.build())
    assert "Sie gibt Milch." not in section  # the clue of 'Kuh'
    assert section.count('<div class="c tl"') == 4
    assert any("Kuh" in w for w in builder.warnings)


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_crossword_pdf_draws_the_grid_at_its_cell_size(tmp_path):
    """E-paper, the narrower page: the grid is drawn at 7 mm per cell (the
    size set per task through the --cell property), inside the page, with
    the enclosed cells black; the key says across and down."""
    pymupdf = need_pdf(pymupdf=True)
    out = tmp_path / "crossword.pdf"
    data = _data()
    data["tasks"] = data["tasks"][-1:]  # the story and the crossword: a quick render
    ws = worksheet_from_dict(data)
    grid = _planned(ws).crossword
    assert grid is not None
    result = render_worksheet(ws, out, RenderOptions(page="epaper", base_dir=LENA.parent))
    assert result.weasyprint_error is None
    doc = pymupdf.open(out)
    page = next(p for p in doc if ENTRIES[5]["clue"] in p.get_text())
    drawings = page.get_drawings()
    borders = [d["rect"] for d in drawings if d["type"] == "s" and d["width"] == pytest.approx(.75)]
    box = pymupdf.Rect(min(r.x0 for r in borders), min(r.y0 for r in borders),
                       max(r.x1 for r in borders), max(r.y1 for r in borders))
    assert page.rect.contains(box)
    border = .75 / MM
    assert box.width / MM == pytest.approx(7.0 * grid.cols + border, abs=.3)
    assert box.height / MM == pytest.approx(7.0 * grid.rows + border, abs=.3)
    black = [d["rect"] for d in drawings if d["type"] == "f" and d["fill"] == (0.0, 0.0, 0.0)
             and d["rect"].width / MM == pytest.approx(7.0, abs=.2)]
    assert len(black) == len(enclosed(grid)) and all(box.contains(r) for r in black)
    key = "".join(p.get_text() for p in doc).split("Solutions", 1)[1]
    assert "↓" in key and "MILCHSCHAUM" in key
