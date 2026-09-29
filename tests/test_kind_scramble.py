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
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.validate import Issue, validate
from tests.test_render import need_pdf

#: The validator codes these tests trigger (see tests/test_validate.py).
COVERED_CODES = {"scramble-alternative", "scramble-punctuation", "scramble-capital"}

REPO = Path(__file__).resolve().parent.parent
LENA = REPO / "examples" / "lena_01_en_de.json"
SHOWCASE = REPO / "tests" / "fixtures" / "kinds_showcase.json"

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


def _showcase(*items: dict[str, Any]) -> dict[str, Any]:
    """The French showcase fixture with ``items`` in its scramble task t18."""
    data = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["id"] == "t18")
    task["items"] = list(items)
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


@pytest.mark.parametrize("field", ["words", "tiles"])
def test_other_names_for_the_chunks_point_at_chunks(field: str) -> None:
    with pytest.raises(ContractError) as err:
        worksheet_from_dict(_lena({field: ["heute", "regnet", "es"]}))
    problems = dict(err.value.problems)
    assert problems[f"/tasks/{INDEX}/items/0/{field}"].startswith(
        f"'{field}' is not a field here (did you mean 'chunks'?)")
    assert problems[f"/tasks/{INDEX}/items/0/chunks"].startswith(
        "the required field 'chunks' is missing")


def test_items_nested_under_the_kind_are_located_in_the_task() -> None:
    data = _lena()
    data["tasks"][INDEX]["scramble"] = {"items": data["tasks"][INDEX].pop("items")}
    with pytest.raises(ContractError) as err:
        worksheet_from_dict(data)
    assert sorted(loc for loc, _ in err.value.problems) == [
        f"/tasks/{INDEX}/items", f"/tasks/{INDEX}/scramble",
    ]


@pytest.mark.parametrize("end", ["。", "？", "！"])
def test_the_full_width_end_marks_are_allowed(end: str) -> None:
    item = worksheet_from_dict(_lena({"chunks": ["heute", "regnet", "es"], "end": end}))
    assert item.tasks[INDEX].items[0].end == end


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
    # the end marks of other scripts: 'end' cannot print them
    (["私は", "コーヒーを", "飲みます。"], 2, "ends with '。'", ""),
    (["你", "喝", "咖啡吗？"], 2, "ends with '？'", ""),
    (["هل", "تشرب", "القهوة؟"], 2, "ends with '؟'", ""),
    (["मैं", "कॉफ़ी", "पीता हूँ।"], 2, "ends with '।'", ""),
])
def test_sentence_punctuation_on_a_tile_is_flagged(
    chunks: list[str], k: int, shown: str, end: str,
) -> None:
    issues = _issues(_lena({"chunks": chunks}), "scramble-punctuation")
    assert [(i.level, i.where) for i in issues] == [
        ("warning", f"/tasks/{INDEX}/items/0/chunks/{k}")]
    assert shown in issues[0].message
    assert f'set "end": "{end}" on the item' in issues[0].message


def test_an_end_mark_that_end_cannot_print_is_left_off() -> None:
    # with the default "end" '.', the key would print '飲みます。.'
    issues = _issues(_lena({"chunks": ["私は", "コーヒーを", "飲みます。"]}),
                     "scramble-punctuation")
    assert "Write it as '飲みます' here and in every alternative" in issues[0].message
    assert "'end' can only be '.', '?', '!' or '…'" in issues[0].message


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
    assert ("If the word is written in lower case inside a sentence, write the tile so "
            "('am Freitag') here and in every alternative") in issues[0].message
    # never simply 'write it in lower case': that would turn a formal 'Sie' into 'sie'
    assert ("If the word keeps its capital wherever it stands (a name, a noun or the formal "
            "Sie), keep the capital") in issues[0].message


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


@pytest.mark.parametrize("item", [
    # the formal Sie keeps its capital, though the story writes 'sie' (she)
    {"chunks": ["Sie", "trinken", "die Melange", "mit Zucker"]},
    {"chunks": ["Ihr Kaffee", "ist", "zu bitter"]},
    {"chunks": ["Ihnen", "schmeckt", "die Melange"]},
])
def test_the_formal_sie_is_capitalised_anyway(item: dict[str, Any]) -> None:
    assert _issues(_lena(item), "scramble-capital") == []


def test_an_alternative_with_the_tile_inside_shows_that_the_capital_is_the_words() -> None:
    # 'Essen' (a noun that vocabulary.items does not list) and the verb 'essen'
    meal = {"chunks": ["Essen", "gibt es", "um zwölf"]}
    verb = {"chunks": ["Lena", "will", "nichts", "essen"]}
    issues = _issues(_lena(meal, verb), "scramble-capital")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/items/0/chunks/0"]
    assert "('essen')" in issues[0].message  # (only if it is written so inside a sentence)
    meal["alternatives"] = [["um zwölf", "gibt es", "Essen"]]
    assert _issues(_lena(meal, verb), "scramble-capital") == []


def test_without_noun_capitals_any_capitalised_first_tile_is_flagged() -> None:
    # French: 'normalement' is written nowhere in lower case, but only names
    # keep their capital inside a French sentence
    assert "normalement" not in SHOWCASE.read_text(encoding="utf-8").casefold()
    item = {"chunks": ["Normalement", "Mila", "achète", "des fraises"]}
    issues = _issues(_showcase(item), "scramble-capital")
    assert len(issues) == 1
    assert "write the tile so ('normalement')" in issues[0].message
    assert "wherever it stands (a name), keep the capital" in issues[0].message


@pytest.mark.parametrize("item", [
    {"chunks": ["Mila", "achète", "des fraises"]},                 # a character's name
    {"chunks": ["Madame Roux", "vend", "des fraises"]},            # ... with a title
    {"chunks": ["Lyon", "est", "une grande ville"]},               # a place the story names
    {"chunks": ["Pauline", "arrive", "demain"],                   # a name inside a sentence
     "alternatives": [["demain", "arrive", "Pauline"]]},
])
def test_without_noun_capitals_names_are_fine(item: dict[str, Any]) -> None:
    assert _issues(_showcase(item), "scramble-capital") == []


def test_the_capital_after_an_opening_quote_mark_counts() -> None:
    issues = _issues(_lena({"chunks": ["„Warum", "fragst", "du“"]}), "scramble-capital")
    assert [i.where for i in issues] == [f"/tasks/{INDEX}/items/0/chunks/0"]
    assert "('„warum')" in issues[0].message


@pytest.mark.parametrize("example", [
    "Am Freitag darf Lena die Melange machen.",   # the sentence of the tiles
    "Lena darf am Freitag die Melange machen.",   # ... in another correct order
])
def test_a_grammar_box_beside_the_scramble_must_not_show_its_sentence(example: str) -> None:
    data = _lena()
    data["tasks"][INDEX]["grammar"] = "g2"  # the box is printed beside the scramble
    assert _issues(data, "grammar-gives-away") == []
    data["grammar"][1]["examples"] = [example]
    issues = _issues(data, "grammar-gives-away")
    assert [i.where for i in issues] == ["/grammar/1"]
    assert "beside task 't8'" in issues[0].message


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
    (["je", "l'", "aime"], ".", "fr", "Je l'aime."),
    (["va-t’", "en", "vite"], ".", "fr", "Va-t’en vite."),
    (["jusqu'", "à", "demain"], ".", "fr", "Jusqu'à demain."),
    (["dall’", "Italia", "arriva", "il caffè"], ".", "it", "Dall’Italia arriva il caffè."),
    (["c'", "è", "un'", "amica"], ".", "it", "C'è un'amica."),
    (["l'", "àvia", "arriba"], ".", "ca", "L'àvia arriba."),
    (["um", "copo", "d'", "água"], ".", "pt", "Um copo d'água."),
    (["it's", "late"], ".", "en", "It's late."),
    # a possessive or a shortened word is followed by a space
    (["das ist", "Jonas'", "Schürze"], ".", "de", "Das ist Jonas' Schürze."),
    (["my", "parents'", "house", "is", "big"], ".", "en", "My parents' house is big."),
    (["vorrei", "un po'", "di", "zucchero"], ".", "it", "Vorrei un po' di zucchero."),
    (["Lorenzo", "de'", "Medici", "arriva"], ".", "it", "Lorenzo de' Medici arriva."),
    (["rock", "'n'", "roll", "forever"], "!", "en", "Rock 'n' roll forever!"),
    # no spaces in Chinese and Japanese (or Thai), whose marks are full width
    (["我", "喜欢", "喝", "咖啡"], ".", "zh", "我喜欢喝咖啡。"),
    (["你", "喝", "咖啡", "吗"], "?", "zh-TW", "你喝咖啡吗？"),
    (["私は", "コーヒーを", "飲みます"], "。", "ja", "私はコーヒーを飲みます。"),
    (["すごい", "です", "ね"], "！", "ja", "すごいですね！"),
    (["ฉัน", "ชอบ", "กาแฟ"], "", "th", "ฉันชอบกาแฟ"),
    # the capitals of the language: Turkish İ, Dutch IJ
    (["iyi", "günler", "dilerim"], "!", "tr", "İyi günler dilerim!"),
    (["ırmak", "çok", "derin"], ".", "tr", "Irmak çok derin."),
    (["ijs", "is", "koud"], ".", "nl", "IJs is koud."),
    (["iyi", "günler"], ".", "de", "Iyi günler."),
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


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_chinese_and_japanese_end_marks_are_full_width(page: str) -> None:
    data = _lena({"chunks": ["私は", "コーヒーを", "飲みます"]},
                 {"chunks": ["コーヒーを", "飲みます", "か"], "end": "?"})
    data["target_lang"] = "ja"
    ws, pt = _planned(data)
    section = _section(build_html(ws, RenderOptions(page=page)), pt)
    assert re.findall(r'<span class="end">(.*?)</span>', section) == ["。", "？"]
    assert answer_key(pt, ws) == ["私はコーヒーを飲みます。", "コーヒーを飲みますか？"]


def test_a_right_to_left_line_has_its_end_mark_at_the_left() -> None:
    data = _lena()
    data["target_lang"] = "he"  # (the tiles stay German: only the direction changes)
    ws, pt = _planned(data)
    section = _section(build_html(ws), pt)
    assert section.count('<div class="sls tl rtl" lang="he" dir="rtl">') == 3
    ws, pt = _planned(_lena())
    assert " rtl" not in _section(build_html(ws), pt)


@pytest.mark.parametrize(("target", "at_left"), [("de", False), ("he", True)])
def test_the_end_mark_stands_where_the_sentence_ends(target: str, at_left: bool,
                                                    tmp_path: Path) -> None:
    pymupdf = need_pdf(pymupdf=True)
    data = _lena()
    data["tasks"] = [data["tasks"][INDEX]]
    data["target_lang"] = target  # (the tiles stay German: only the direction changes)
    out = tmp_path / "scramble.pdf"
    render_worksheet(worksheet_from_dict(data), out, RenderOptions(page="epaper",
                                                                    solutions="none"))
    doc = pymupdf.open(out)
    ends = [w for page in doc for w in page.get_text("words") if w[4] in ("?", "!")]
    assert len(ends) == 2
    middle = doc[0].rect.width / 2
    assert all((w[2] < middle) == at_left for w in ends)


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
