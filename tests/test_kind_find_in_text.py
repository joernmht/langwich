"""The find_in_text kind: the answer check, glosses, answer key and rendering."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

import pytest

from langwich.answers import answer_key
from langwich.model import ContractError, FindInTextTask, parse_worksheet, worksheet_from_dict
from langwich.plan import plan
from langwich.plan import tested_terms as collect_tested_terms
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.css import A4_CONTENT_W, GUTTER_W, MAIN_W
from langwich.render.tasks import FIND_ARROW_W, FIND_CLUE_MIN, FIND_LINE_MIN
from langwich.validate import CHECKS, Issue, validate
from tests.test_render import need_pdf

#: The validator codes this file triggers (see tests/test_validate.py).
COVERED_CODES = {"find-not-in-text"}

ROOT = Path(__file__).resolve().parent.parent
MM = 72 / 25.4
LENA = ROOT / "examples" / "lena_01_en_de.json"
SHOWCASE = ROOT / "tests" / "fixtures" / "kinds_showcase.json"

#: Words and phrases of scene 4 with English clues (A2); the first stands
#: apart in its sentence ('beobachtet Lena Herrn Novak genau').
ITEMS: list[dict[str, str]] = [
    {"clue": "watches closely", "answer": "beobachtet … genau"},
    {"clue": "stirs", "answer": "rührt"},
    {"clue": "the door is unlocked", "answer": "wird die Tür aufgesperrt"},
    {"clue": "(her hands) are shaking", "answer": "zittern"},
    {"clue": "turns out well", "answer": "gelingt"},
]

#: Scene 3 with German paraphrases and explanations (C1).
EXPLAINED: list[dict[str, str]] = [
    {"clue": "ein Gefühl, wenn etwas schiefgeht", "answer": "enttäuscht",
     "explanation": "Sie ist traurig, weil der Kaffee nicht so gut ist, wie sie gehofft hat."},
    {"clue": "Lena findet das Warten zu lang", "answer": "Das dauert ja ewig",
     "explanation": "„ja“ zeigt, dass sie ungeduldig ist; es dauert nur ein paar Minuten."},
    {"clue": "ein Geschmack mit ein wenig Säure", "answer": "säuerlich"},
]

#: The index of the find_in_text task in the worksheets below (t7's place).
AT = 6


def _data(items: list[dict[str, str]] | None = None, **fields: Any) -> dict[str, Any]:
    """Lena with a find_in_text task after scene 4 in place of t7 (the task
    count stays the same)."""
    data = json.loads(LENA.read_text(encoding="utf-8"))
    task = {"id": "fit", "kind": "find_in_text", "stage": "detail", "scene": "s4",
            "clue_lang": "source", "items": copy.deepcopy(items or ITEMS), **fields}
    data["tasks"] = [task if t["id"] == "t7" else t for t in data["tasks"]]
    assert data["tasks"][AT] is task
    return data


def _ws(items: list[dict[str, str]] | None = None, **fields: Any):
    return worksheet_from_dict(_data(items, **fields))


def _hits(data: dict[str, Any], code: str = "find-not-in-text") -> list[Issue]:
    return [i for i in validate(worksheet_from_dict(data)).issues if i.code == code]


def _answers(data: dict[str, Any], *answers: str) -> dict[str, Any]:
    """``data`` with the first answers of its find_in_text task replaced."""
    for item, answer in zip(data["tasks"][AT]["items"], answers):
        item["answer"] = answer
    return data


def _planned(ws):
    return next(pt for pt in plan(ws).tasks if isinstance(pt.task, FindInTextTask))


def _section(html: str) -> str:
    m = re.search(r'<section class="task unit k-find_in_text[^"]*"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, "find_in_text task not found"
    return m.group(0)


def _glossed(ws) -> dict[str, list[str]]:
    return {b.scene.id: [g.item.term for g in b.glosses] for b in plan(ws).scenes}


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_defaults_to_target_clues_without_explanations():
    data = _data()
    del data["tasks"][AT]["clue_lang"]
    task = worksheet_from_dict(data).tasks[AT]
    assert isinstance(task, FindInTextTask)
    assert (task.clue_lang, task.explain) == ("target", False)
    assert [i.answer for i in task.items] == [i["answer"] for i in ITEMS]
    assert all(i.explanation is None for i in task.items)


@pytest.mark.parametrize("change", [
    lambda t: t.__setitem__("items", []),
    lambda t: t["items"][0].__setitem__("clue", ""),
    lambda t: t["items"][0].__setitem__("answer", ""),
    lambda t: t["items"][0].pop("answer"),
    lambda t: t.__setitem__("clue_lang", "english"),
    lambda t: t["items"][0].__setitem__("hint", "genau"),  # unknown field
])
def test_contract_rejects_bad_tasks(change):
    data = _data()
    change(data["tasks"][AT])
    with pytest.raises(ContractError):
        worksheet_from_dict(data)


@pytest.mark.parametrize("kind", ["find-the-word", "word hunt", "scanning", "Find in the text"])
def test_lenient_loading_reads_the_aliases_as_find_in_text(kind):
    data = _data()
    data["tasks"][AT]["kind"] = kind
    ws, notes = parse_worksheet(json.dumps(data, ensure_ascii=False))
    assert isinstance(ws.tasks[AT], FindInTextTask)
    assert any(n.code == "normalized" for n in notes)


# ---------------------------------------------------------------------------
# Validator: find-not-in-text
# ---------------------------------------------------------------------------


def test_answers_copied_from_their_scene_pass():
    report = validate(_ws())
    assert report.ok
    assert not [i for i in report.issues if i.code in COVERED_CODES]
    explained = _data(EXPLAINED, scene="s3", clue_lang="target", explain=True)
    assert not _hits(explained)  # (a missing explanation is no problem: the key says so)


@pytest.mark.parametrize("answer", [
    "Beobachtet",                          # the case of a letter
    "Herrn  Novak\ngenau",                 # spaces and line breaks
    "„Morgen wieder“",                     # quotation marks around it
    "Morgen wieder.",                      # the full stop after it
    '"Morgen wieder", sagt er',            # other quotation marks inside
    "schiebt … zur Seite",                 # '…' for the words in between
    "schiebt ... zur Seite",
    "sieben wird die Tür",
])
def test_the_search_forgives_what_copying_changes(answer):
    assert not _hits(_answers(_data(), answer))


def test_typographic_and_straight_apostrophes_are_the_same():
    """The showcase's find_in_text task searches scene 1, which writes
    straight apostrophes ('s'arrête' is one of its answers)."""
    data = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    task = next(t for t in data["tasks"] if t["kind"] == "find_in_text")
    assert task["scene"] == "s1" and "s'arrête" in [item["answer"] for item in task["items"]]
    task["items"] += [{"clue": "heute", "answer": "aujourd’hui"},
                      {"clue": "bitte", "answer": "s’il vous plaît"}]
    assert not _hits(data)
    data["story"]["scenes"][0]["text"] = data["story"]["scenes"][0]["text"].replace("'", "’")
    task["items"][-2]["answer"] = "aujourd'hui"
    assert not _hits(data)


def test_a_scene_heading_is_searched_too():
    data = _data(scene="s3")
    data["tasks"][AT]["items"] = [{"clue": "much too dark", "answer": "Viel zu dunkel"}]
    assert not _hits(data)


def test_a_task_without_scene_searches_the_whole_story():
    data = _answers(_data(), "Äthiopien")  # scene 2
    del data["tasks"][AT]["scene"]
    assert not _hits(data)
    data["tasks"][AT]["scene"] = ["s2", "s4"]
    assert not _hits(data)


def test_an_unknown_scene_is_reported_once():
    data = _answers(_data(scene="s9"), "Äthiopien")
    issues = validate(worksheet_from_dict(data)).issues
    assert [i.code for i in issues] == ["unknown-scene"]


def test_the_dictionary_form_is_not_in_the_scene():
    hits = _hits(_answers(_data(), "beobachtet … genau", "rühren"))
    assert [(i.level, i.where) for i in hits] == [("warning", f"/tasks/{AT}/items/1/answer")]
    message = hits[0].message
    assert "'rühren' does not occur in scene 's4', which this task is about" in message
    assert "(did you mean 'rührt'?)" in message
    assert "exactly as the scene writes it" in message and "not the dictionary form" in message


def test_part_of_a_word_is_not_the_word():
    # 'Dose' occurs only inside 'Zuckerdose'
    hits = _hits(_answers(_data(), "Dose"))
    assert [i.where for i in hits] == [f"/tasks/{AT}/items/0/answer"]
    assert "(did you mean 'Zuckerdose'?)" in hits[0].message


def test_an_answer_from_another_scene_names_that_scene():
    hits = _hits(_answers(_data(), "Äthiopien"))
    assert len(hits) == 1
    assert "is not in scene 's4', which this task is about, but in scene 's2'" in hits[0].message
    assert "add 's2' to the task's 'scene'" in hits[0].message


def test_a_changed_phrase_gets_the_closest_words_of_its_sentence():
    hits = _hits(_answers(_data(), "der Milchschaum gelingt nicht"))
    assert len(hits) == 1
    assert "(did you mean 'der Milchschaum gelingt'?)" in hits[0].message
    assert "with '…' between words that stand apart" in hits[0].message


def test_the_parts_around_an_ellipsis_must_share_a_sentence():
    # 'beobachtet' and 'Zucker' are in two sentences of scene 4
    hits = _hits(_answers(_data(), "beobachtet … Zucker"))
    assert len(hits) == 1
    assert "'…' stands only for words between two parts of one sentence" in hits[0].message


def test_a_task_about_the_whole_story_says_so():
    data = _answers(_data(), "Zucker brauchte sie keinen")
    del data["tasks"][AT]["scene"]
    hits = _hits(data)
    assert len(hits) == 1
    assert "does not occur in the story (did you mean 'Zucker braucht sie keinen'?)" in (
        hits[0].message)
    assert "which this task is about" not in hits[0].message


def test_covered_codes_are_warnings():
    assert COVERED_CODES <= set(CHECKS)
    assert CHECKS["find-not-in-text"][0] == "warning"


# ---------------------------------------------------------------------------
# Glosses: the answers are tested words
# ---------------------------------------------------------------------------


def test_the_answers_are_tested_terms():
    tested = collect_tested_terms(_ws())
    assert {"rührt", "zittern", "gelingt", "wird die tür aufgesperrt"} <= tested


def test_no_gloss_beside_the_story_gives_an_answer_away():
    data = _data()
    before = _glossed(worksheet_from_dict({**data, "tasks": [
        t for t in data["tasks"] if t["id"] != "fit"]}))["s4"]
    assert {"rühren", "zittern", "aufsperren", "gelingen", "lehnen"} <= set(before)
    phrase = {"clue": "her bike stands against a street lamp",
              "answer": "lehnt ihr Fahrrad an einer Laterne"}
    after = _glossed(_ws([*ITEMS, phrase]))["s4"]
    # inflected answers and the words inside a phrase answer are not glossed
    for term in ("rühren", "zittern", "aufsperren", "gelingen", "beobachten", "lehnen"):
        assert term not in after, term
    assert "probieren" in after  # an unrelated word keeps its gloss


# ---------------------------------------------------------------------------
# Answer key
# ---------------------------------------------------------------------------


def test_answer_key_lists_the_answers():
    ws = _ws()
    assert answer_key(_planned(ws), ws) == [i["answer"] for i in ITEMS]


def test_answer_key_adds_the_explanations():
    data = _data(EXPLAINED, scene="s3", clue_lang="target", explain=True)
    ws = worksheet_from_dict(data)
    assert answer_key(_planned(ws), ws) == [
        f"enttäuscht – {EXPLAINED[0]['explanation']}",
        f"Das dauert ja ewig – {EXPLAINED[1]['explanation']}",
        "säuerlich – Answers will vary.",
    ]
    data["ui"] = {"open_answer": "Own words."}
    ws = worksheet_from_dict(data)
    assert answer_key(_planned(ws), ws)[-1] == "säuerlich – Own words."
    # an explanation without 'explain' is still printed; none without is left out
    data["tasks"][AT]["explain"] = False
    ws = worksheet_from_dict(data)
    assert answer_key(_planned(ws), ws)[1:] == [
        f"Das dauert ja ewig – {EXPLAINED[1]['explanation']}", "säuerlich"]


def test_the_key_tags_each_part_with_its_language():
    data = _data(EXPLAINED, scene="s3", clue_lang="target", explain=True)
    solutions = build_html(worksheet_from_dict(data)).split('class="solutions', 1)[1]
    assert (f'<span class="k" lang="de">enttäuscht – {EXPLAINED[0]["explanation"]}</span>'
            in solutions)
    # 'answers will vary' is in the learner's language, as are the
    # explanations of source-language clues
    assert ('<span class="k"><span lang="de">säuerlich</span><span lang="en"> – Answers will '
            "vary.</span></span>") in solutions
    source = _data([{"clue": "stirs", "answer": "rührt", "explanation": "stirs the coffee"}],
                   explain=True)
    solutions = build_html(worksheet_from_dict(source)).split('class="solutions', 1)[1]
    assert ('<span class="k"><span lang="de">rührt</span><span lang="en"> – stirs the '
            "coffee</span></span>") in solutions


def test_the_key_is_numbered_like_the_items():
    solutions = build_html(_ws()).split('class="solutions', 1)[1]
    block = solutions.split("Find it in the story", 1)[1].split('<div class="sb">', 1)[0]
    assert re.findall(r'<span class="kn">(\d+)</span>', block) == ["1", "2", "3", "4", "5"]
    assert "beobachtet … genau" in block


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_source_clues_in_sans_beside_their_lines(page):
    section = _section(build_html(_ws(), RenderOptions(page=page)))
    assert " keep" not in section  # it breaks between items
    assert "Find the word or phrase in the story that matches each clue." in section
    for item in ITEMS:
        assert f'<p class="q src">{item["clue"]}</p>' in section
    assert 'class="tl q"' not in section
    assert section.count('<span class="line"></span>') == len(ITEMS)
    rows = re.findall(r'<div class="fr" style="([^"]+)">', section)
    assert len(rows) == len(ITEMS) and len(set(rows)) == 1  # the lines align
    for item in ITEMS:  # the answers are not printed
        assert item["answer"] not in section


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_target_clues_with_explain(page):
    ws = _ws(EXPLAINED, scene="s3", clue_lang="target", explain=True)
    section = _section(build_html(ws, RenderOptions(page=page)))
    assert "Find the word or phrase in the story and explain what it means." in section
    for item in EXPLAINED:
        assert f'<p class="tl q" lang="de">{item["clue"]}</p>' in section
        assert item.get("explanation", "@") not in section
    assert section.count('<span class="cue">Meaning:</span>') == len(EXPLAINED)
    assert section.count('<span class="line"></span>') == 2 * len(EXPLAINED)


def test_own_instruction_and_german_labels():
    """The showcase with its find_in_text task (scene 1, no explanations)
    replaced by one on scene 2 that asks for explanations."""
    data = json.loads(SHOWCASE.read_text(encoding="utf-8"))
    at = next(i for i, t in enumerate(data["tasks"]) if t["kind"] == "find_in_text")
    data["tasks"][at] = {
        "id": data["tasks"][at]["id"], "kind": "find_in_text", "stage": "detail", "scene": "s2",
        "clue_lang": "source", "explain": True,
        "items": [
            {"clue": "eine Abkürzung", "answer": "un raccourci"},
            {"clue": "ein geheimer Durchgang zwischen zwei Straßen", "answer": "une traboule"},
            {"clue": "sie wissen nicht mehr, wo sie sind", "answer": "On est perdus",
             "explanation": "Sie haben sich in den Gängen verlaufen."},
        ],
    }
    ws = worksheet_from_dict(data)
    assert not [i for i in validate(ws).issues if i.code in COVERED_CODES]
    options = RenderOptions(base_dir=SHOWCASE.parent)
    section = _section(build_html(ws, options))
    assert ">Finde es in der Geschichte</h3>" in section
    assert "Finde das Wort oder die Wendung in der Geschichte und erkläre" in section
    assert section.count('<span class="cue">Bedeutung:</span>') == 3
    assert '<p class="q src">eine Abkürzung</p>' in section
    data["tasks"][at]["instruction"] = "Suche die Wörter in Szene 2."
    section = _section(build_html(worksheet_from_dict(data), options))
    assert '<p class="ins">Suche die Wörter in Szene 2.</p>' in section


def test_clues_are_escaped():
    items = copy.deepcopy(ITEMS)
    items[1]["clue"] = "<b>stirs</b> sugar & milk"
    section = _section(build_html(_ws(items)))
    assert "&lt;b&gt;stirs&lt;/b&gt; sugar &amp; milk" in section
    assert "<b>stirs" not in section


def test_a_long_answer_moves_the_lines_below_the_clues_on_the_narrow_page():
    items = [*ITEMS, {"clue": "pushes the sugar bowl aside",
                      "answer": "schiebt er die Zuckerdose zur Seite"}]
    wide = _section(build_html(_ws(items)))
    narrow = _section(build_html(_ws(items), RenderOptions(page="epaper")))
    assert wide.count('<div class="fr"') == len(items)
    assert '<div class="fr"' not in narrow
    assert narrow.count('<div class="fl"><span class="cue">→</span>') == len(items)
    # on A4 the clue column leaves the line room for the answer
    clue_w = float(re.search(r"grid-template-columns:([\d.]+)mm", wide).group(1))
    assert clue_w + FIND_ARROW_W + FIND_LINE_MIN <= A4_CONTENT_W - GUTTER_W


def test_long_clues_wrap_beside_their_lines_next_to_a_side_column():
    data = _data(EXPLAINED, scene="s3", clue_lang="target", grammar="g2")
    section = _section(build_html(worksheet_from_dict(data)))
    assert '<aside class="aside-stack">' in section
    assert section.count('<div class="fr"') == len(EXPLAINED)
    clue_w = float(re.search(r"grid-template-columns:([\d.]+)mm", section).group(1))
    assert FIND_CLUE_MIN <= clue_w <= MAIN_W - GUTTER_W - FIND_ARROW_W - FIND_LINE_MIN


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_lines_sit_on_their_clues(tmp_path):
    """E-paper: one writing line per clue, all starting and ending at the
    same x inside the page, each on the last line of its clue (a clue on
    two lines here)."""
    pymupdf = need_pdf(pymupdf=True)
    out = tmp_path / "find.pdf"
    sour = {"clue": "ein bisschen sauer, aber nicht so sauer wie eine Zitrone",
            "answer": "säuerlich"}
    data = _data([*EXPLAINED[:2], sour], scene="s3", clue_lang="target")
    data["tasks"] = data["tasks"][AT:AT + 1]  # the story and the task: a quick render
    result = render_worksheet(worksheet_from_dict(data), out,
                              RenderOptions(page="epaper", base_dir=LENA.parent))
    assert result.weasyprint_error is None
    ink3 = (0x44 / 255,) * 3  # the writing lines' colour on e-paper
    lines = []  # (page, the line's box) in reading order
    for page in pymupdf.open(out):
        lines += sorted(((page, d["rect"]) for d in page.get_drawings()
                         if d["type"] == "f" and d["fill"] == pytest.approx(ink3, abs=.01)
                         and d["rect"].width > 30 * MM),
                        key=lambda pr: pr[1].y0)
    assert len(lines) == 3
    assert len({round(r.x0, 1) for _, r in lines}) == len({round(r.x1, 1) for _, r in lines}) == 1
    for item, (page, line) in zip(data["tasks"][0]["items"], lines):
        assert page.rect.contains(line)
        last_word = item["clue"].split()[-1]
        found = [w for w in page.search_for(last_word) if w.y1 < line.y1 + 1]
        assert found, last_word
        last = max(found, key=lambda w: w.y1)
        assert abs(line.y1 - last.y1) < 1 * MM  # the line is on the clue's last line
        assert last.x1 < line.x0  # the clue ends before the line starts
    page, line = lines[2]  # the long clue: its first line is above the writing line
    assert page.search_for("ein bisschen sauer")[0].y1 < line.y0 + 1
