"""The gapped_text kind: whole sentences taken out of a text, put back by letter."""

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
from pathlib import Path
from typing import Any

import pytest

from langwich import markup
from langwich.answers import answer_key, letter
from langwich.model import (
    ContractError,
    GappedTextTask,
    Worksheet,
    parse_worksheet,
    worksheet_from_dict,
)
from langwich.plan import plan
from langwich.plan import tested_terms as collect_tested_terms
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.validate import CHECKS, Issue, validate

#: The validator codes this file exercises (see tests/test_validate.py).
COVERED_CODES = {"gapped-text-gaps", "gapped-text-no-extra", "duplicate-entry"}

LENA = Path(__file__).resolve().parent.parent / "examples" / "lena_01_en_de.json"
MM = 72 / 25.4

#: Lena's diary on Wednesday night: five sentences out, two extra ones.
DIARY: dict[str, Any] = {
    "id": "gt1", "kind": "gapped_text", "stage": "practice", "scene": "s4",
    "title": "Lena's diary: Wednesday night",
    "text": "Mittwoch, 22 Uhr. Heute war ein schwieriger Tag in der Rösterei. {{Am Morgen hat "
            "mir Frau Berger gezeigt, wie die Röstmaschine funktioniert.}} Dann musste sie "
            "plötzlich ans Telefon. Ich war allein und wollte schneller fertig werden. {{Deshalb "
            "habe ich die Hitze einfach höher gedreht.}} Nach wenigen Minuten waren die Bohnen "
            "fast schwarz.\n\nZu Hause habe ich eine Tasse von meinem Kaffee gekocht. {{Ohne drei "
            "Löffel Zucker konnte ich ihn kaum trinken.}} Genau so viel Zucker nimmt auch Herr "
            "Novak jeden Morgen! {{Ist unsere Melange für ihn vielleicht auch zu bitter?}} "
            "Morgen will ich ihn ganz genau beobachten. {{Vielleicht verrät er mir dann, wie er "
            "seinen Kaffee wirklich mag.}}",
    "extra": ["Zum Glück war die Röstung diesmal genau richtig.",
              "In Äthiopien werden die Kaffeekirschen oft von Hand geerntet."],
}

#: The journey of the bean, three sentences out and one extra.
JOURNEY: dict[str, Any] = {
    "id": "gt2", "kind": "gapped_text", "stage": "detail", "scene": "s2",
    "text": "Frau Berger erklärt Lena, wie der Kaffee nach Wien kommt. {{Zuerst pflücken die "
            "Bauern die roten Kirschen, oft von Hand.}} Dann liegen die Kirschen in der Sonne, "
            "bis sie trocken sind. {{Danach kommen die grünen Bohnen in große Säcke aus Jute.}} "
            "Mit dem Schiff reisen die Säcke nach Europa. {{Dort werden die Bohnen geröstet, "
            "zum Beispiel im Café Lindner.}}",
    "extra": ["Herr Novak sitzt schon seit sieben Uhr am Fenster."],
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


def _hits(ws: Worksheet, code: str) -> list[Issue]:
    return [x for x in validate(ws).issues if x.code == code]


def _planned(ws: Worksheet, task_id: str, seed: int | None = None):
    return next(pt for pt in plan(ws, seed).tasks if pt.task.id == task_id)


def _section(html: str, ws: Worksheet, task_id: str) -> str:
    number = _planned(ws, task_id).number
    m = re.search(rf'<section class="task unit [^"]*" id="task-{number}"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, f"task {task_id} not found"
    return m.group(0)


def _sentences(task: dict[str, Any]) -> list[str]:
    """The removed sentences of a task, in gap order."""
    return [g.answer for g in markup.gaps(task["text"])]


def _gapped(text: str, n: int) -> str:
    """``text`` repeated as ``n`` removed sentences, each after a sentence of its own."""
    return " ".join(f"Das ist Satz {k}. {{{{{text} Nummer {k}.}}}}" for k in range(1, n + 1))


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_reads_a_gapped_text() -> None:
    ws = _ws(DIARY, {**JOURNEY, "extra": []})
    diary, journey = (t for t in ws.tasks if isinstance(t, GappedTextTask))
    assert diary.text.startswith("Mittwoch, 22 Uhr.") and len(diary.extra) == 2
    assert journey.extra == []
    left_out = copy.deepcopy(JOURNEY)
    del left_out["extra"]  # (optional)
    left = _ws(left_out).tasks[-1]
    assert isinstance(left, GappedTextTask) and left.extra == []


@pytest.mark.parametrize(("change", "where"), [
    ({"text": ""}, "text"),
    ({"extra": "Ein Satz."}, "extra"),
    ({"sentences": ["Ein Satz."]}, "sentences"),
    ({"hint": "word_bank"}, "hint"),
])
def test_contract_rejects_bad_gapped_texts(change: dict[str, Any], where: str) -> None:
    with pytest.raises(ContractError) as err:
        _ws({**JOURNEY, **change})
    assert any(where in loc for loc, _ in err.value.problems), err.value.problems


@pytest.mark.parametrize("alias", ["missing_sentences", "Gapped-Sentences", "sentence insertion"])
def test_other_names_for_the_kind_are_read(alias: str) -> None:
    ws, notes = parse_worksheet(json.dumps(_data({**JOURNEY, "kind": alias}), ensure_ascii=False))
    assert isinstance(ws.tasks[-1], GappedTextTask)
    assert any(n.code == "normalized" and "gapped_text" in n.message for n in notes)


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_every_covered_code_is_a_check() -> None:
    assert COVERED_CODES <= set(CHECKS)


def test_gapped_texts_pass_every_check() -> None:
    assert _issues(DIARY, JOURNEY) == []


def test_a_text_without_gaps_says_how_to_mark_a_sentence() -> None:
    plain = {**JOURNEY, "text": markup.fill(JOURNEY["text"])}
    ws = _ws(plain)
    i = _index(ws, "gt2")
    issues = validate(ws).issues
    hits = [x for x in issues if x.code == "cloze-without-gaps"]
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/text", "error")]
    assert "this gapped text has no gaps" in hits[0].message
    assert "{{sentence}}" in hits[0].message and "whole sentence" in hits[0].message
    # the count and the extra sentences are not judged on a text without gaps
    codes = {x.code for x in issues if x.where.startswith(f"/tasks/{i}")}
    assert not codes & {"gapped-text-gaps", "gapped-text-no-extra"}
    # single braces are named
    single = {**JOURNEY, "text": JOURNEY["text"].replace("{{", "{").replace("}}", "}")}
    message = next(x.message for x in _issues(single) if x.code == "cloze-without-gaps")
    assert "single braces" in message


def test_broken_markup_is_reported_and_nothing_crashes() -> None:
    for text in ("Erst das. {{}} Dann das.", "Erst das. {{Ein Satz. Dann das.",
                 "Erst das. {{{Ein Satz.}}} Dann das."):
        ws = _ws({**JOURNEY, "text": text})
        codes = {x.code for x in validate(ws).issues}
        assert codes & {"empty-gap", "unbalanced-braces"}, codes
        build_html(ws)
        assert isinstance(answer_key(_planned(ws, "gt2"), ws), list)


@pytest.mark.parametrize(("gaps", "flagged"), [(1, True), (2, True), (3, False), (8, False),
                                               (9, True)])
def test_three_to_eight_gaps(gaps: int, flagged: bool) -> None:
    ws = _ws({**JOURNEY, "text": _gapped("Hier fehlt ein Satz", gaps)})
    i = _index(ws, "gt2")
    hits = _hits(ws, "gapped-text-gaps")
    if not flagged:
        assert hits == []
        return
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/text", "warning")]
    message = hits[0].message
    assert f"has {gaps} gap{'s' if gaps > 1 else ''}," in message and "3–8" in message
    assert ("{{sentence}}" in message) if gaps < 3 else ("back into the text" in message)


def test_a_gapped_text_needs_an_extra_sentence() -> None:
    ws = _ws({**JOURNEY, "extra": []})
    i = _index(ws, "gt2")
    hits = _hits(ws, "gapped-text-no-extra")
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/extra", "warning")]
    assert "elimination" in hits[0].message and '"extra"' in hits[0].message
    assert _hits(_ws(JOURNEY), "gapped-text-no-extra") == []


def test_a_sentence_taken_out_twice() -> None:
    twice = {**JOURNEY, "text": JOURNEY["text"].replace(
        "{{Dort werden die Bohnen geröstet, zum Beispiel im Café Lindner.}}",
        "{{zuerst pflücken  die Bauern die roten Kirschen, oft von Hand.}}")}
    ws = _ws(twice)
    i = _index(ws, "gt2")
    hits = _hits(ws, "duplicate-entry")
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/text", "error")]
    assert "gaps 1 and 3" in hits[0].message and "Zuerst pflücken" not in hits[0].message


def test_an_extra_sentence_listed_twice() -> None:
    extra = "Herr Novak sitzt schon seit sieben Uhr am Fenster."
    ws = _ws({**JOURNEY, "extra": [extra, "Lena mag Apfelstrudel.", " HERR NOVAK sitzt schon "
                                   "seit sieben Uhr  am Fenster."]})
    i = _index(ws, "gt2")
    hits = _hits(ws, "duplicate-entry")
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/extra/2", "error")]
    assert "extra/0" in hits[0].message


def test_an_extra_sentence_that_fills_a_gap() -> None:
    removed = _sentences(JOURNEY)[1]
    ws = _ws({**JOURNEY, "extra": ["Lena mag Apfelstrudel.", removed.upper()]})
    i = _index(ws, "gt2")
    hits = _hits(ws, "distractor-is-answer")
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/extra/1", "warning")]
    assert "extra sentence" in hits[0].message
    assert _hits(ws, "duplicate-entry") == []


def test_a_grammar_box_beside_the_task_must_not_show_a_removed_sentence() -> None:
    # g1 (the passive) is printed beside the first task that names it: gt2
    data = _data({**JOURNEY, "grammar": "g1"})
    assert [x for x in validate(worksheet_from_dict(data)).issues
            if x.code == "grammar-gives-away"] == []
    data["grammar"][0]["examples"].append(_sentences(JOURNEY)[2])
    hits = _hits(worksheet_from_dict(data), "grammar-gives-away")
    assert [x.where for x in hits] == ["/grammar/0"]
    assert "beside task 'gt2'" in hits[0].message
    assert "'Dort werden die Bohnen geröstet, zum Beispiel im Café Lindner'" in hits[0].message


def test_gap_markup_belongs_in_the_text_only() -> None:
    ws = _ws({**JOURNEY, "extra": ["{{Herr Novak sitzt am Fenster.}}"]})
    i = _index(ws, "gt2")
    assert [x.where for x in _hits(ws, "markup-outside-gaps")] == [f"/tasks/{i}/extra/0"]


def test_a_practice_gapped_text_must_not_copy_the_story() -> None:
    copied = {**DIARY, "text": DIARY["text"].replace(
        "{{Deshalb habe ich die Hitze einfach höher gedreht.}}",
        "{{Das dauert ja ewig, denkt Lena und dreht die Hitze höher.}}")}
    ws = _ws(copied)
    i = _index(ws, "gt1")
    assert [x.where for x in _hits(ws, "copies-story")] == [f"/tasks/{i}/text"]
    # at a comprehension stage it may retell the story
    assert _hits(_ws({**copied, "stage": "detail"}), "copies-story") == []


# ---------------------------------------------------------------------------
# Planner and answer key
# ---------------------------------------------------------------------------


def test_the_sentences_are_shuffled_with_the_seed() -> None:
    ws = _ws(DIARY)
    slots = _planned(ws, "gt1").slot_options
    assert slots is not None
    assert sorted(slots) == sorted(_sentences(DIARY) + DIARY["extra"])
    assert slots == _planned(ws, "gt1").slot_options  # the same JSON gives the same order
    orders = {tuple(_planned(ws, "gt1", seed).slot_options or []) for seed in range(8)}
    assert len(orders) > 1  # … and the seed shuffles it


@pytest.mark.parametrize("extra", [[], ["Lena mag Apfelstrudel."],
                                   ["Lena mag Apfelstrudel.", "Es regnet in Wien."]])
def test_gap_one_is_never_a_while_gap_two_is_b(extra: list[str]) -> None:
    task = {**JOURNEY, "extra": extra}
    ws = _ws(task)
    removed = _sentences(task)
    for seed in range(400):
        slots = _planned(ws, "gt2", seed).slot_options or []
        assert slots[:len(removed)] != removed, seed


def test_the_key_gives_the_letter_of_each_sentence() -> None:
    ws = _ws(DIARY)
    pt = _planned(ws, "gt1")
    key = answer_key(pt, ws)
    assert len(key) == 5 and len(set(key)) == 5
    slots = pt.slot_options or []
    for sentence, given in zip(_sentences(DIARY), key):
        assert slots[ord(given) - ord("A")] == sentence
    # the extra sentences are never an answer
    extras = {letter(slots.index(e)) for e in DIARY["extra"]}
    assert not extras & set(key)


def test_removed_sentences_are_not_tested_words() -> None:
    tested = collect_tested_terms(_ws(JOURNEY))
    assert not any("pflücken" in t for t in tested)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_a_box_for_a_letter_in_every_gap(page: str) -> None:
    ws = _ws(DIARY)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "gt1")
    assert 'class="task unit k-gapped_text keep"' in section and "data-soft" not in section
    assert "<h3>Lena&#x27;s diary: Wednesday night</h3>" in section
    assert "Write the letter of the missing sentence in each gap." in section
    passage = re.search(r'<div class="passage tl" lang="de">(.*?)</div>', section, flags=re.S)
    assert passage, section
    body = passage.group(1)
    assert body.count("<p>") == 2  # the blank line starts a paragraph
    assert re.findall(r'<span class="gn">(\d+)</span>', body) == ["1", "2", "3", "4", "5"]
    assert body.count('<span class="blank" style="width:7.0mm">&nbsp;</span>') == 5
    assert "{{" not in section and "Röstmaschine" not in body  # the sentences are out
    assert "Rösterei. <span class=\"gap\">" in body


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_sentences_are_listed_by_letter(page: str) -> None:
    ws = _ws(DIARY)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "gt1")
    rows = re.findall(r'<div><span class="l">([A-Z])</span>'
                      r'<span class="tl" lang="de">(.*?)</span></div>', section)
    slots = _planned(ws, "gt1").slot_options
    assert [given for given, _ in rows] == list("ABCDEFG")
    assert [text for _, text in rows] == slots


def test_the_sentences_stand_beside_a_grammar_box() -> None:
    data = _data({**DIARY, "grammar": "g2"})
    for task in data["tasks"]:
        if task["id"] == "t8":
            del task["grammar"]
    ws = worksheet_from_dict(data)
    assert [i for i in validate(ws).issues if i.code != "task-count"] == []
    section = _section(build_html(ws), ws, "gt1")
    main, aside = section.split('<aside class="aside-stack">', 1)
    assert 'class="gts"' in main and "Compound nouns" in aside
    epaper = _section(build_html(ws, RenderOptions(page="epaper")), ws, "gt1")
    assert epaper.index('<div class="before"') < epaper.index('class="passage tl"')


def test_gapped_text_is_escaped() -> None:
    task = {**JOURNEY, "text": "Preise <b> & Co. {{Kaffee <script> kostet 3 €.}} Tee & mehr. "
                               "{{Ein Satz.}} Noch einer. {{Und <i>noch</i> einer.}}",
            "extra": ["Milch <u>& Zucker</u>."]}
    ws = _ws(task)
    section = _section(build_html(ws), ws, "gt2")
    assert "Preise &lt;b&gt; &amp; Co." in section and "Tee &amp; mehr." in section
    assert "Kaffee &lt;script&gt; kostet 3 €." in section
    assert "Milch &lt;u&gt;&amp; Zucker&lt;/u&gt;." in section
    assert "<script>" not in section and "<b>" not in section and "<u>" not in section


def test_the_answer_key_prints_the_letters() -> None:
    ws = _ws(DIARY)
    pt = _planned(ws, "gt1")
    html = build_html(ws, RenderOptions(solutions="separate"))
    block = re.search(rf'<span class="tn2">{pt.number}</span>.*?</div>', html, flags=re.S)
    assert block
    for n, given in enumerate(answer_key(pt, ws), 1):
        assert f'<span class="kn">{n}</span> <span class="k" lang="de">{given}</span>' \
            in block.group(0)


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


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_the_passage_and_its_sentences_share_a_page(page: str, tmp_path: Path) -> None:
    pymupdf = _pymupdf()
    data = _data(DIARY)
    # (on e-paper the scene's picture leaves room for the passage only: the
    # whole task moves to the next page rather than part the two)
    data["tasks"] = [t for t in data["tasks"] if t["id"] in ("t3", "t4", "gt1")]
    ws = worksheet_from_dict(data)
    result = render_worksheet(ws, tmp_path / "gapped.pdf",
                              RenderOptions(page=page, solutions="none"))
    assert result.pdf is not None and result.warnings == []
    doc = pymupdf.open(result.pdf)
    texts = [" ".join(p.get_text().split()) for p in doc]
    passage = [n for n, text in enumerate(texts) if "Mittwoch, 22 Uhr." in text]
    listed = [n for n, text in enumerate(texts) if DIARY["extra"][0] in text]
    assert len(passage) == 1 and len(listed) == 1
    assert listed[0] == passage[0]
    for sentence in _sentences(DIARY) + DIARY["extra"]:
        assert sentence in texts[listed[0]], sentence
    margin = 8 * MM if page == "epaper" else 12 * MM
    for n in {passage[0], listed[0]}:
        page_ = doc[n]
        for block in page_.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                for span in line["spans"]:
                    if span["text"].strip():
                        assert span["bbox"][2] <= page_.rect.width - margin + 2, span["text"]
