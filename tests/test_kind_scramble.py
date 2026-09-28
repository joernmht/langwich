"""scramble: word tiles to put in order. The contract, the scramble checks,
the planner's shuffle (never a correct order), the answer key and the HTML."""

from __future__ import annotations

import copy
import itertools
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key, scramble_sentence
from langwich.model import ContractError, canonical_kind, worksheet_from_dict
from langwich.plan import PlannedTask, plan
from langwich.render import RenderOptions, build_html
from langwich.validate import Issue, validate

#: The validator codes these tests trigger (see tests/test_validate.py).
COVERED_CODES = {"scramble-alternative", "scramble-punctuation", "scramble-capital"}

REPO = Path(__file__).resolve().parent.parent
LENA = REPO / "examples" / "lena_01_en_de.json"

#: A form task on scene 4 (it replaces the word_building task t8): verb
#: second after a time, a question word and an imperative — two of them
#: with another correct order.
WORD_ORDER: dict[str, Any] = {
    "id": "t8", "kind": "scramble", "stage": "form", "scene": "s4",
    "title": "Friday, word by word",
    "items": [
        {"chunks": ["am Freitag", "darf", "Lena", "die Melange", "machen"],
         "alternatives": [["Lena", "darf", "am Freitag", "die Melange", "machen"]],
         "cue": "On Friday Lena is allowed to make the Melange."},
        {"chunks": ["warum", "nimmt", "Herr Novak", "so viel", "Zucker"], "end": "?"},
        {"chunks": ["röste", "die Bohnen", "bitte", "nicht", "so dunkel"], "end": "!",
         "alternatives": [["röste", "bitte", "die Bohnen", "nicht", "so dunkel"]]},
    ],
}

#: WORD_ORDER's position in the task list (for JSON pointers).
INDEX = 7


def _lena(*items: dict[str, Any]) -> dict[str, Any]:
    """The Lena example with WORD_ORDER as t8; ``items`` replace its items."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = copy.deepcopy(WORD_ORDER)
    if items:
        task["items"] = list(items)
    assert data["tasks"][INDEX]["id"] == "t8"
    data["tasks"][INDEX] = task
    return data


def _issues(data: dict[str, Any], code: str | None = None) -> list[Issue]:
    issues = validate(worksheet_from_dict(data)).issues
    return [i for i in issues if code is None or i.code == code]


def _planned(data: dict[str, Any], seed: int | None = None) -> tuple[Any, PlannedTask]:
    ws = worksheet_from_dict(data)
    return ws, next(pt for pt in plan(ws, seed).tasks if pt.task.id == "t8")


def _section(html: str, pt: PlannedTask) -> str:
    match = re.search(rf'<section class="task unit[^"]*" id="task-{pt.number}".*?</section>',
                      html, flags=re.S)
    assert match
    return match.group(0)


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_end_defaults_to_a_full_stop_and_the_rest_to_nothing() -> None:
    task = worksheet_from_dict(_lena({"chunks": ["heute", "regnet", "es"]})).tasks[INDEX]
    assert task.kind == "scramble"
    item = task.items[0]
    assert (item.end, item.alternatives, item.cue) == (".", [], None)


@pytest.mark.parametrize("item", [
    {"chunks": ["heute", "regnet"]},                              # fewer than 3 tiles
    {"chunks": [f"w{k}" for k in range(13)]},                     # more than 12
    {"chunks": ["heute", "", "es"]},                              # an empty tile
    {"chunks": ["heute", "regnet", "es"], "end": "?!"},           # not one of . ? ! … ""
    {"chunks": ["heute", "regnet", "es"], "answer": "Heute regnet es."},  # unknown field
])
def test_invalid_items_are_contract_errors(item: dict[str, Any]) -> None:
    with pytest.raises(ContractError):
        worksheet_from_dict(_lena(item))


def test_no_items_is_a_contract_error() -> None:
    data = _lena()
    data["tasks"][INDEX]["items"] = []
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


@pytest.mark.parametrize("alias", ["word_order", "Unscramble", "jumbled-sentences",
                                   "sentence scramble", "scrambled_sentences"])
def test_llm_names_for_the_kind_mean_scramble(alias: str) -> None:
    assert canonical_kind(alias) == "scramble"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_the_task_is_clean() -> None:
    assert _issues(_lena()) == []


@pytest.mark.parametrize(("alternative", "wrong"), [
    (["Lena", "darf", "am Freitag", "machen"], "lacks 'die Melange'"),
    (["Lena", "darf", "am Freitag", "die Melange", "machen", "heute"], "adds 'heute'"),
    # a capital is another tile: only the answer key capitalises
    (["Am Freitag", "darf", "Lena", "die Melange", "machen"],
     "lacks 'am Freitag' and adds 'Am Freitag'"),
    ([], "lacks 'am Freitag', 'darf', 'Lena', 'die Melange', 'machen'"),
])
def test_an_alternative_must_use_the_same_tiles(alternative: list[str], wrong: str) -> None:
    item = copy.deepcopy(WORD_ORDER["items"][0])
    item["alternatives"].append(alternative)
    issues = _issues(_lena(item), "scramble-alternative")
    assert [(i.level, i.where) for i in issues] == [
        ("error", f"/tasks/{INDEX}/items/0/alternatives/1")]
    assert f"this alternative {wrong}, so it is not an order" in issues[0].message
    assert "change only the order" in issues[0].message


def test_a_repeated_tile_must_be_repeated_in_the_alternative() -> None:
    item = {"chunks": ["die", "Katze", "sieht", "die", "Maus"],
            "alternatives": [["die", "Maus", "sieht", "die", "Katze"], ["die", "Maus", "sieht",
                                                                         "Katze"]]}
    issues = _issues(_lena(item), "scramble-alternative")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/items/0/alternatives/1"]
    assert "lacks 'die'" in issues[0].message


@pytest.mark.parametrize(("chunks", "k", "shown", "end"), [
    # the sentence end on the last tile
    (["am Freitag", "darf", "Lena", "die Melange", "machen."], 4, "ends with '.'", "."),
    (["warum", "nimmt", "Herr Novak", "so viel", "Zucker?"], 4, "ends with '?'", "?"),
    (["dann", "wartet", "Lena", "..."], 3, "is only punctuation", "…"),
    (["dann", "wartet", "Lena", "!"], 3, "is only punctuation", "!"),
    # ? ! … inside the sentence too
    (["Lena", "wartet …", "und", "wartet"], 1, "ends with '…'", "…"),
    # Spanish opening marks show the first tile (the key adds them)
    (["¿dónde", "está", "el café"], 0, "starts with '¿'", "?"),
])
def test_sentence_punctuation_on_a_tile_is_flagged(
    chunks: list[str], k: int, shown: str, end: str,
) -> None:
    issues = _issues(_lena({"chunks": chunks}), "scramble-punctuation")
    assert [(i.level, i.where) for i in issues] == [
        ("warning", f"/tasks/{INDEX}/items/0/chunks/{k}")]
    assert shown in issues[0].message
    assert f'set "end": "{end}" on the item' in issues[0].message


def test_the_fix_names_the_tile_without_its_mark() -> None:
    issues = _issues(_lena({"chunks": ["am Freitag", "darf", "Lena", "machen."]}),
                     "scramble-punctuation")
    assert "Write it as 'machen' here and in every alternative" in issues[0].message


@pytest.mark.parametrize("chunks", [
    ["Frau Berger", "röstet", "z. B.", "Bohnen aus Äthiopien"],   # an abbreviation
    ["am 3.", "Oktober", "fliegt", "Lena", "nach Wien"],           # a German ordinal
    ["Lena", "sagt", "„Danke“"],                                   # quote marks are fine
    ["heute", "regnet", "es,", "sagt", "Lena"],                    # so are commas
])
def test_full_stops_inside_the_sentence_and_other_marks_are_fine(chunks: list[str]) -> None:
    assert _issues(_lena({"chunks": chunks}), "scramble-punctuation") == []


def test_a_capitalised_first_tile_is_flagged() -> None:
    item = copy.deepcopy(WORD_ORDER["items"][0])
    item["chunks"][0] = "Am Freitag"
    item["alternatives"] = []
    issues = _issues(_lena(item), "scramble-capital")
    assert [(i.level, i.where) for i in issues] == [
        ("warning", f"/tasks/{INDEX}/items/0/chunks/0")]
    assert "the tile 'Am Freitag' starts the sentence" in issues[0].message
    assert "Write it in lower case ('am Freitag')" in issues[0].message
    assert "Keep a capital only for a name or a noun" in issues[0].message


def test_the_first_tile_of_an_alternative_counts_too() -> None:
    # 'Warum' starts the alternative; the worksheet writes 'warum' elsewhere
    item = {"chunks": ["Herr Novak", "fragt", "Warum"],
            "alternatives": [["Warum", "fragt", "Herr Novak"]], "end": "?"}
    issues = _issues(_lena(item), "scramble-capital")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/items/0/chunks/2"]


@pytest.mark.parametrize("first", [
    "Lena",                  # a character's name
    "Herr Novak",            # a name with a title
    "Kaffee",                # a noun the story writes mid-sentence
    "Kaffeebohnen",          # a noun the worksheet never writes in lower case
    "UNESCO",                # an acronym
    "„warum",                # (lower case after a quote mark)
])
def test_words_that_are_capitalised_anyway_are_fine(first: str) -> None:
    item = {"chunks": [first, "kommt", "nicht", "aus Wien"]}
    assert _issues(_lena(item), "scramble-capital") == []


def test_the_capital_after_an_opening_quote_mark_counts() -> None:
    issues = _issues(_lena({"chunks": ["„Warum", "fragst", "du“"]}), "scramble-capital")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/items/0/chunks/0"]
    assert "('„warum')" in issues[0].message


def test_a_scramble_that_copies_the_story_is_flagged() -> None:
    item = {"chunks": ["seit vierzig Jahren", "trinkt", "er", "hier", "jeden Morgen",
                       "eine Melange,", "immer mit drei Löffeln Zucker"]}
    issues = _issues(_lena(item), "copies-story")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/items/0"]


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


def test_tiles_are_deterministic() -> None:
    _, first = _planned(_lena(), seed=11)
    _, again = _planned(_lena(), seed=11)
    assert first.tiles == again.tiles
    assert first.tiles is not None and len(first.tiles) == len(WORD_ORDER["items"])


@pytest.mark.parametrize("seed", range(60))
def test_tiles_are_never_shown_in_a_correct_order(seed: int) -> None:
    _, pt = _planned(_lena(), seed=seed)
    assert pt.tiles is not None
    for item, shown in zip(WORD_ORDER["items"], pt.tiles):
        assert sorted(shown) == sorted(item["chunks"])
        assert shown not in [item["chunks"], *item.get("alternatives", [])]


@pytest.mark.parametrize("seed", range(40))
def test_the_one_wrong_order_is_found_when_almost_every_order_is_right(seed: int) -> None:
    orders = [list(p) for p in itertools.permutations(["a", "b", "c"])]
    wrong = orders.pop(seed % len(orders))
    item = {"chunks": orders[0], "alternatives": orders[1:]}
    _, pt = _planned(_lena(item), seed=seed)
    assert pt.tiles == [wrong]


def test_any_order_will_do_when_every_order_is_right() -> None:
    orders = [list(p) for p in itertools.permutations(["a", "b", "c"])]
    _, pt = _planned(_lena({"chunks": orders[0], "alternatives": orders[1:]}), seed=3)
    assert pt.tiles is not None and pt.tiles[0] in orders


@pytest.mark.parametrize("seed", range(20))
def test_repeated_tiles_are_shuffled_by_their_words(seed: int) -> None:
    chunks = ["die", "Katze", "sieht", "die", "Maus"]
    _, pt = _planned(_lena({"chunks": chunks}), seed=seed)
    assert pt.tiles is not None
    assert sorted(pt.tiles[0]) == sorted(chunks) and pt.tiles[0] != chunks


# ---------------------------------------------------------------------------
# Answer key
# ---------------------------------------------------------------------------


def test_the_key_gives_each_sentence_and_its_other_orders() -> None:
    ws, pt = _planned(_lena())
    assert answer_key(pt, ws) == [
        "Am Freitag darf Lena die Melange machen. / Lena darf am Freitag die Melange machen.",
        "Warum nimmt Herr Novak so viel Zucker?",
        "Röste die Bohnen bitte nicht so dunkel! / Röste bitte die Bohnen nicht so dunkel!",
    ]


def test_an_alternative_that_repeats_the_sentence_is_printed_once() -> None:
    item = {"chunks": ["heute", "regnet", "es"], "alternatives": [["heute", "regnet", "es"]]}
    ws, pt = _planned(_lena(item))
    assert answer_key(pt, ws) == ["Heute regnet es."]


@pytest.mark.parametrize(("chunks", "end", "lang", "sentence"), [
    (["heute", "regnet", "es"], ".", "de", "Heute regnet es."),
    (["und dann", "kam", "niemand"], "…", "de", "Und dann kam niemand…"),
    (["heute", "regnet", "es"], "", "de", "Heute regnet es"),
    # no space after an elision; the letter after it is the first one
    (["l'", "homme", "arrive"], ".", "fr", "L'homme arrive."),
    (["dall’", "Italia", "arriva", "il caffè"], ".", "it", "Dall’Italia arriva il caffè."),
    (["it's", "late"], ".", "en", "It's late."),
    # French spaces before ? and !
    (["tu", "viens", "demain"], "?", "fr", "Tu viens demain ?"),
    (["quelle", "surprise"], "!", "fr-CA", "Quelle surprise !"),
    # Spanish opens questions and exclamations
    (["dónde", "está", "el mercado"], "?", "es", "¿Dónde está el mercado?"),
    (["qué", "calor", "hace"], "!", "es-MX", "¡Qué calor hace!"),
    (["¿dónde", "está", "el mercado"], "?", "es", "¿Dónde está el mercado?"),
    # after an opening quote mark; a number stays as it is
    (["„komm", "doch", "mit“"], "", "de", "„Komm doch mit“"),
    (["1989", "fiel", "die Mauer"], ".", "de", "1989 fiel die Mauer."),
    ([" am Abend ", "kommt", "Marco"], ".", "de", "Am Abend kommt Marco."),
])
def test_scramble_sentence(chunks: list[str], end: str, lang: str, sentence: str) -> None:
    assert scramble_sentence(chunks, end, lang) == sentence


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_tiles_are_printed_in_the_planned_order(page: str) -> None:
    ws, pt = _planned(_lena())
    section = _section(build_html(ws, RenderOptions(page=page)), pt)
    assert 'class="task unit k-scramble' in section
    rows = re.findall(r'<div class="tiles tl" lang="de">(.*?)</div>', section)
    assert pt.tiles is not None
    assert [re.findall(r'<span class="tile">(.*?)</span>', row) for row in rows] == pt.tiles
    assert "todo" not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_cue_and_the_end_marks_are_printed(page: str) -> None:
    ws, pt = _planned(_lena())
    section = _section(build_html(ws, RenderOptions(page=page)), pt)
    assert ('<p class="cue" lang="en">On Friday Lena is allowed to make the Melange.</p>'
            in section)
    assert section.count('<p class="cue"') == 1
    ends = re.findall(r'<span class="end">(.*?)</span>', section)
    assert ends == [".", "?", "!"]
    assert section.count('<div class="sls tl" lang="de">') == 3


def test_the_sentences_themselves_are_not_on_the_page() -> None:
    ws, pt = _planned(_lena())
    section = _section(build_html(ws), pt)
    assert "am Freitag darf" not in section and "Am Freitag darf" not in section
    assert "Warum nimmt" not in section


def test_no_end_mark_without_end() -> None:
    ws, pt = _planned(_lena({"chunks": ["heute", "regnet", "es"], "end": ""}))
    section = _section(build_html(ws), pt)
    assert 'class="end"' not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_a_long_sentence_gets_a_second_line(page: str) -> None:
    long = {"chunks": ["seit Mittwoch", "weiß", "Lena", "genau,", "warum", "Herrn Novak",
                       "eine dunkle Röstung", "viel", "zu bitter", "ist"]}
    short = {"chunks": ["heute", "regnet", "es"]}
    ws, pt = _planned(_lena(long, short))
    section = _section(build_html(ws, RenderOptions(page=page)), pt)
    blocks = re.findall(r'<div class="sls tl" lang="de">(.*?)</div></div>', section)
    assert [block.count('<div class="sl">') for block in blocks] == [2, 1]


def test_a_very_long_sentence_gets_at_most_four_lines() -> None:
    chunks = ["am allerersten Arbeitstag", "erklärt", "die strenge Chefin Frau Berger",
              "der neuen Kellnerin", "hinter der Theke", "ganz geduldig und ausführlich",
              "die komplizierte Geschichte", "der alten Wiener Kaffeehäuser", "und",
              "ihrer berühmten Stammgäste", "mit allen Einzelheiten", "noch einmal"]
    ws, pt = _planned(_lena({"chunks": chunks}))
    section = _section(build_html(ws), pt)
    assert section.count('<div class="sl">') == 4


def test_tiles_and_cues_are_escaped() -> None:
    item = {"chunks": ["<b>heute</b>", "regnet", "es & schneit"], "cue": "It <i>rains</i>."}
    ws, pt = _planned(_lena(item))
    section = _section(build_html(ws), pt)
    assert "&lt;b&gt;heute&lt;/b&gt;" in section and "es &amp; schneit" in section
    assert "It &lt;i&gt;rains&lt;/i&gt;." in section
    assert "<b>" not in section and "<i>" not in section
