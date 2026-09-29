"""The cloze hint "choice": every gap offers its options, {{right::wrong1|wrong2}}."""

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
from langwich.answers import answer_key
from langwich.model import ClozeTask, ContractError, Worksheet, worksheet_from_dict
from langwich.plan import plan
from langwich.render import RenderOptions, build_html, render_worksheet
from langwich.render.css import GUTTER_W, MAIN_W
from langwich.validate import CHECKS, Issue, validate

#: The validator codes this file exercises (see tests/test_validate.py).
COVERED_CODES = {"choice-options", "unused-field"}

LENA = Path(__file__).resolve().parent.parent / "examples" / "lena_01_en_de.json"
MM = 72 / 25.4
NBSP = "\u00a0"
#: Between the letter and the word in the key: no line break (see answers._key_choice).
KEY_DASH = "\u00a0–\u2060\u00a0"

#: A passage in two paragraphs, the options in brackets (inline).
DIARY: dict[str, Any] = {
    "id": "ch1", "kind": "cloze", "stage": "form", "scene": "s2", "hint": "choice",
    "title": "Lena's diary: Tuesday",
    "text": "Heute {{hat::ist|habe}} mir Frau Berger einen Sack aus Jute gezeigt. Die grünen "
            "Bohnen {{kommen::kommt|kamen}} aus Äthiopien, aber Kaffee {{wächst::wachsen|wachst}} "
            "auch in Brasilien und Vietnam.\n\nDanach liegen die Kirschen {{in::auf|an}} der "
            "Sonne, bis sie ganz trocken sind. Ich war überrascht, {{weil::denn|deshalb}} die "
            "Bohnen wie Heu gerochen haben.",
}

#: A note with numbered gaps and the options below it.
NOTE: dict[str, Any] = {
    "id": "ch2", "kind": "cloze", "stage": "practice", "scene": "s3", "hint": "choice",
    "choice_layout": "below", "title": "A note for Frau Berger",
    "text": "Liebe Frau Berger, es tut mir leid {{wegen::trotz|statt}} der Bohnen von gestern. "
            "Ich {{hatte::war|wurde}} keine Geduld und habe die Hitze zu hoch gedreht. Eine "
            "dunkle Röstung schmeckt {{bitterer::bitter|bitterste}} als eine helle. Morgen röste "
            "ich die Bohnen langsam, {{damit::obwohl|denn}} der Kaffee nicht zu bitter wird. "
            "{{Vielleicht::Obwohl|Weil}} braucht Herr Novak dann keinen Zucker mehr.",
}

#: Sentences with inline options; the last one has two gaps.
FRIDAY: dict[str, Any] = {
    "id": "ch3", "kind": "cloze", "stage": "form", "scene": "s4", "hint": "choice",
    "title": "Friday morning in the café",
    "items": [
        "Um sieben {{sitzt::setzt|sitzen}} Herr Novak schon am Fenster.",
        "Lena stellt die Tasse vorsichtig {{auf den::auf dem|in den}} Tisch.",
        "Herr Novak {{probiert::probieren|probierst}} die Melange und "
        "{{lächelt::lächeln|lächelst}}.",
    ],
}

#: Sentences with the options below each; the second one has two gaps.
AFTER: dict[str, Any] = {
    "id": "ch4", "kind": "cloze", "stage": "form", "scene": "s4", "hint": "choice",
    "choice_layout": "below", "title": "After the test",
    "items": [
        "Frau Berger ist stolz, {{weil::denn|deshalb}} Lena so viel gelernt hat.",
        "Lena {{wird::werden|wirst}} morgen wieder um sieben {{erwartet::erwarten|erwartete}}.",
        "Nach der Schicht fährt Lena mit {{ihrem::ihren|ihrer}} Fahrrad nach Hause.",
    ],
}

#: A grammar point about the very words a choice gap offers.
WEIL_DENN: dict[str, Any] = {
    "id": "g9", "name": "weil or denn?",
    "explanation": "Both give a reason, but they put the verb in different places.",
    "rule": "weil: verb at the end · denn: verb in second place",
    "examples": ["Ich bleibe zu Hause, weil ich müde bin.",
                 "Ich bleibe zu Hause, denn ich bin müde."],
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


def _index(ws: Worksheet, task_id: str) -> int:
    return next(i for i, t in enumerate(ws.tasks) if t.id == task_id)


def _at(issues: list[Issue], where: str) -> list[Issue]:
    """The issues at ``where`` or below it."""
    return [i for i in issues if i.where == where or i.where.startswith(where + "/")]


def _choice_issues(task: dict[str, Any]) -> list[Issue]:
    """The choice-options issues of ``task`` (added to the Lena example)."""
    ws = _ws(task)
    return [i for i in _at(validate(ws).issues, f"/tasks/{_index(ws, task['id'])}")
            if i.code == "choice-options"]


def _planned(ws: Worksheet, task_id: str, seed: int | None = None):
    return next(pt for pt in plan(ws, seed).tasks if pt.task.id == task_id)


def _section(html: str, ws: Worksheet, task_id: str) -> str:
    number = _planned(ws, task_id).number
    m = re.search(rf'<section class="task unit [^"]*" id="task-{number}"[^>]*>.*?</section>', html,
                  flags=re.S)
    assert m, f"task {task_id} not found"
    return m.group(0)


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", fragment)).replace(NBSP, " ").strip()


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------


def test_contract_reads_choice_and_its_layout() -> None:
    ws = _ws(DIARY, NOTE)
    diary, note = (t for t in ws.tasks if t.id in ("ch1", "ch2"))
    assert isinstance(diary, ClozeTask) and isinstance(note, ClozeTask)
    assert diary.hint == "choice" and diary.choice_layout == "inline"
    assert note.choice_layout == "below"
    gap = markup.gaps(diary.text or "")[0]
    assert gap.answer == "hat" and markup.wrong_options(gap) == ["ist", "habe"]


def test_contract_rejects_an_unknown_layout() -> None:
    with pytest.raises(ContractError) as err:
        _ws({**NOTE, "choice_layout": "above"})
    assert any("choice_layout" in loc for loc, _ in err.value.problems), err.value.problems


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def test_every_covered_code_is_a_check() -> None:
    assert COVERED_CODES <= set(CHECKS)


def test_choice_tasks_pass_every_check() -> None:
    ws = _ws(DIARY, NOTE, FRIDAY, AFTER)
    issues = validate(ws).issues
    assert not [i for i in issues if i.level == "error"]
    for task_id in ("ch1", "ch2", "ch3", "ch4"):
        assert _at(issues, f"/tasks/{_index(ws, task_id)}") == [], task_id
    assert not [i for i in issues if i.code in ("choice-options", "grammar-gives-away")]


def test_a_gap_without_wrong_options_is_an_error() -> None:
    ws = _ws({**FRIDAY, "items": ["Um sieben {{sitzt}} Herr Novak schon am Fenster."]})
    i = _index(ws, "ch3")
    hits = [x for x in validate(ws).issues if x.code == "missing-gap-hint"]
    assert [(x.where, x.level) for x in hits] == [(f"/tasks/{i}/items/0", "error")]
    assert "{{sitzt::<wrong>|<wrong>}}" in hits[0].message


def test_at_most_three_wrong_options() -> None:
    task = {**FRIDAY, "items": ["Um sieben {{sitzt::setzt|sitzen|sitzte|saß}} Herr Novak da."]}
    hits = _choice_issues(task)
    assert len(hits) == 1 and hits[0].level == "warning"
    assert hits[0].where.endswith("/items/0")
    assert "4 wrong options" in hits[0].message and "1–3" in hits[0].message
    assert _choice_issues({**task, "items": ["Um sieben {{sitzt::setzt|sitzen|saß}} er da."]}) == []


def test_a_wrong_option_listed_twice() -> None:
    hits = _choice_issues({**FRIDAY, "items": ["Um sieben {{sitzt::setzt| setzt }} er da."]})
    assert len(hits) == 1 and "'setzt' twice" in hits[0].message


@pytest.mark.parametrize("gap", ["{{sitzt::setzt|sitzt}}", "{{sitzt|sitzt da::sitzt da}}"])
def test_a_wrong_option_that_is_an_answer(gap: str) -> None:
    hits = _choice_issues({**FRIDAY, "items": [f"Um sieben {gap} Herr Novak."]})
    assert len(hits) == 1
    assert "also an accepted answer" in hits[0].message and "two right options" in hits[0].message


def test_options_that_differ_only_in_case_are_two_options() -> None:
    # 'Sie' or 'sie' is what the gap asks, not a repeat
    task = {**FRIDAY, "items": ["Frau Berger fragt: „Möchten {{Sie::sie}} eine Melange?“"]}
    assert _choice_issues(task) == []


def test_a_capital_at_the_start_of_a_sentence_gives_the_answer_away() -> None:
    text = "Lena ist müde. {{Am::im|um}} Abend schläft sie gut. Sie {{schläft::schlaft}} lange."
    hits = _choice_issues({**DIARY, "text": text})
    assert len(hits) == 1 and hits[0].where.endswith("/text")
    message = hits[0].message
    assert "starts a sentence" in message and "'im', 'um' do not" in message
    assert "{{Am::Im|Um}}" in message
    # every option with a capital: nothing to see
    assert _choice_issues({**DIARY, "text": text.replace("im|um", "Im|Um")}) == []
    # when the capital is the whole difference, the gap has to move
    hits = _choice_issues({**DIARY, "text": "{{Sie::sie}} kommen morgen, sagt Lena."})
    assert len(hits) == 1 and "inside the sentence" in hits[0].message


@pytest.mark.parametrize(("text", "shown", "fix"), [
    # the answer key would print '… Bohnen. der Duft …'
    ("Lena röstet neue Bohnen. {{der::die|das}} Duft ist wunderbar.", "", "{{Der::Die|Das}}"),
    # ... and the small letter marks the answer
    ("{{der::Die|Das}} Duft ist wunderbar.",
     ", and the capital letter of 'Die', 'Das' shows that they are wrong", "{{Der::Die|Das}}"),
    ("Ist das Lena? {{ja::nein}}, das ist sie.", "", "{{Ja::Nein}}"),
])
def test_a_small_letter_at_the_start_of_a_sentence(text: str, shown: str, fix: str) -> None:
    hits = _choice_issues({**DIARY, "text": text})
    assert len(hits) == 1 and hits[0].where.endswith("/text")
    answer = markup.gaps(text)[0].answer
    assert (f"starts a sentence, but its answer '{answer}' has no capital letter, so the answer "
            f"key would print the sentence with a small letter{shown}.") in hits[0].message
    assert f"Write every option with a capital letter here: {fix}." in hits[0].message


@pytest.mark.parametrize("text", [
    "Lena kauft z. B. {{die::der|das}} Bohnen aus Äthiopien.",  # after an abbreviation
    "Am 3. {{und::oder}} am 4. Mai ist das Café zu.",            # after an ordinal
    "Lena weiß es: {{die::der|das}} Bohnen sind zu dunkel.",     # after a colon
    "Lena wartet … {{und::oder}} wartet.",                       # after '…'
    "{{der::die|das}} Kaffee",                                   # a phrase, not a sentence
])
def test_a_small_letter_may_follow_a_full_stop_inside_a_sentence(text: str) -> None:
    assert _choice_issues({**DIARY, "text": text}) == []


@pytest.mark.parametrize(("text", "fix"), [
    ("Lena trinkt {{den::Die|Das}} Kaffee.", "{{den::die|das}}"),
    ("Lena trinkt {{Den::die|das}} Kaffee.", "{{den::die|das}}"),
    ("Lena trinkt {{den::Die|das}} Kaffee.", "{{den::die|das}}"),
])
def test_options_inside_a_sentence_start_alike(text: str, fix: str) -> None:
    hits = _choice_issues({**DIARY, "text": text})
    assert len(hits) == 1 and hits[0].where.endswith("/text")
    message = hits[0].message
    assert "do not start alike" in message and "the capital shows which option is right" in message
    assert f"If these words are written in lower case inside a sentence, write them so: {fix}." \
        in message
    # never just 'write it in lower case': a noun or the formal Sie keeps its capital
    assert "If a capital belongs to the word (a name, a noun or the formal Sie), keep it" in message


@pytest.mark.parametrize("text", [
    "Lena bringt die {{Tasse::schnell|gut}} an den Tisch.",   # a noun (vocabulary.items)
    "Lena fragt: „Trinken {{Sie::du|ihr}} die Melange?“",    # the formal Sie
    "Er gibt {{Lena::ihm|uns}} eine Schürze.",                # a name
    "Lena lernt heute etwas {{Neues::neues}}.",               # the case is what the gap asks
])
def test_a_capital_that_belongs_to_the_word_is_no_give_away(text: str) -> None:
    assert _choice_issues({**DIARY, "text": text}) == []


@pytest.mark.parametrize(("gap", "joined", "fix"), [
    ("{{sitzt::setzt, sitzen}}", "'setzt, sitzen'", "{{sitzt::setzt|sitzen}}"),
    ("{{sitzt::setzt / sitzen|saß}}", "'setzt / sitzen'", "{{sitzt::setzt|sitzen|saß}}"),
    ("{{sitzt::setzt;sitzen}}", "'setzt;sitzen'", "{{sitzt::setzt|sitzen}}"),
    ("{{sitzt::setzt,}}", "'setzt,'", "{{sitzt::setzt}}"),
])
def test_wrong_options_joined_by_a_sign_print_as_one(gap: str, joined: str, fix: str) -> None:
    hits = _choice_issues({**FRIDAY, "items": [f"Um sieben {gap} Herr Novak da."]})
    assert len(hits) == 1
    assert f"has the wrong option {joined}, which the choice would print as one option" \
        in hits[0].message
    assert f"Separate the wrong options with '|', not with ',', ';' or '/': {fix}." \
        in hits[0].message


@pytest.mark.parametrize("gap", [
    "{{sitzt::setzt oder sitzen}}",          # a word, not a sign: 'or' is also a French word
    "{{1/2::1/3|3/4}}",                      # the answer has the sign too
    "{{sitzt, sagt Lena,::setzt, sagt Lena,}}",
])
def test_signs_that_the_answer_has_too_are_fine(gap: str) -> None:
    hits = _choice_issues({**FRIDAY, "items": [f"Um sieben {gap} Herr Novak da."]})
    assert not [h for h in hits if "print as one option" in h.message]


def test_distractors_and_a_layout_need_the_hint_that_prints_them() -> None:
    ws = _ws({**NOTE, "distractors": ["weil"]},
             {**FRIDAY, "id": "wb", "hint": "word_bank", "choice_layout": "below",
              "items": ["Um sieben {{sitzt}} Herr Novak schon am Fenster."]})
    note, bank = _index(ws, "ch2"), _index(ws, "wb")
    hits = [x for x in validate(ws).issues if x.code == "unused-field"]
    assert [(x.where, x.level) for x in hits] == [
        (f"/tasks/{note}/distractors", "warning"), (f"/tasks/{bank}/choice_layout", "warning")]
    assert "its hint is 'choice', which prints no word box" in hits[0].message
    assert "after the '::': {{right::wrong|wrong}}" in hits[0].message
    assert "'choice_layout' \"below\" arranges the options of choice gaps" in hits[1].message
    assert "the hint 'word_bank', so it has no effect" in hits[1].message


def test_empty_and_broken_gaps_are_left_to_their_own_checks() -> None:
    ws = _ws({**FRIDAY, "items": ["Um sieben {{ }} Herr Novak.", "Er {{sitzt::setzt da."]})
    codes = {x.code for x in _at(validate(ws).issues, f"/tasks/{_index(ws, 'ch3')}")}
    assert {"empty-gap", "unbalanced-braces"} <= codes and "choice-options" not in codes


def test_a_grammar_point_about_the_options_is_no_give_away() -> None:
    # the rule names weil and denn: it is what the choice is about
    data = _data({**AFTER, "grammar": "g9"})
    data["grammar"].append(copy.deepcopy(WEIL_DENN))
    assert "grammar-gives-away" not in {i.code for i in validate(worksheet_from_dict(data)).issues}
    # … but an example that is the item itself still is one
    data["grammar"][-1]["examples"].append(
        "Frau Berger ist stolz, weil Lena so viel gelernt hat.")
    issues = validate(worksheet_from_dict(data)).issues
    assert any(i.code == "grammar-gives-away" for i in issues)


def test_options_are_printed_anyway_so_only_a_near_copy_leaks() -> None:
    subordinate = {
        "id": "g9", "name": "Clauses with the verb at the end",
        "explanation": "In a subordinate clause the conjugated verb goes to the end.",
        "rule": "Konjunktion … Verb (am Ende)",
        "examples": ["Sie lacht, obwohl sie müde ist."],
    }
    item = "Lena bleibt ruhig, {{obwohl::weil|denn}} ihre Hände zittern."
    data = _data({**FRIDAY, "grammar": "g9", "items": [item]})
    data["grammar"].append(subordinate)
    assert "grammar-gives-away" not in {i.code for i in validate(worksheet_from_dict(data)).issues}
    # the same gap without options: the example shows the answer
    data["tasks"][-1] = {**FRIDAY, "grammar": "g9", "hint": "none",
                         "items": ["Lena bleibt ruhig, {{obwohl}} ihre Hände zittern."]}
    assert "grammar-gives-away" in {i.code for i in validate(worksheet_from_dict(data)).issues}


# ---------------------------------------------------------------------------
# Planner and answer key
# ---------------------------------------------------------------------------


def test_every_gap_gets_its_options_shuffled() -> None:
    ws = _ws(DIARY)
    pt = _planned(ws, "ch1")
    assert pt.gap_options is not None and len(pt.gap_options) == 5
    gaps = markup.gaps(DIARY["text"])
    for gap, shown in zip(gaps, pt.gap_options):
        assert sorted(shown) == sorted([gap.answer, *markup.wrong_options(gap)])
        assert shown != [gap.answer, *markup.wrong_options(gap)]  # never the written order
    assert pt.gap_options == _planned(ws, "ch1").gap_options  # the same JSON, the same order
    orders = {json.dumps(_planned(ws, "ch1", seed).gap_options) for seed in range(8)}
    assert len(orders) > 1  # … and the seed shuffles them


def test_the_answer_never_sits_in_one_place_three_times_in_a_row() -> None:
    items = [f"Satz {n}: Lena {{{{ist::sind|bist}}}} da." for n in range(8)]
    ws = _ws({**FRIDAY, "items": items})
    for seed in range(30):
        shown = _planned(ws, "ch3", seed).gap_options or []
        places = [opts.index("ist") for opts in shown]
        assert all(len(set(places[k:k + 3])) > 1 for k in range(len(places) - 2)), places


def test_two_options_are_shuffled_freely() -> None:
    ws = _ws({**FRIDAY, "items": ["Frau Berger fragt: „Möchten {{Sie::sie}} eine Melange?“"]})
    firsts = {(_planned(ws, "ch3", seed).gap_options or [[]])[0][0] for seed in range(20)}
    assert firsts == {"Sie", "sie"}  # the answer is not always second


def test_the_key_names_the_right_options() -> None:
    ws = _ws(DIARY, FRIDAY)
    assert answer_key(_planned(ws, "ch1"), ws) == ["hat", "kommen", "wächst", "in", "weil"]
    assert answer_key(_planned(ws, "ch3"), ws) == ["sitzt", "auf den", "probiert … lächelt"]
    # an alternative is accepted, but only the option that is printed is named
    ws = _ws({**FRIDAY, "items": ["Um sieben {{sitzt|hockt::setzt|sitzen}} er da."]})
    assert answer_key(_planned(ws, "ch3"), ws) == ["sitzt"]


def test_below_the_key_gives_the_letter_too() -> None:
    ws = _ws(NOTE, AFTER)

    def entry(options: list[str], answer: str) -> str:
        return f"{'abcd'[options.index(answer)]}{KEY_DASH}{answer}"

    pt = _planned(ws, "ch2")
    answers = ["wegen", "hatte", "bitterer", "damit", "Vielleicht"]
    assert answer_key(pt, ws) == [entry(o, a) for o, a in zip(pt.gap_options or [], answers)]
    pt = _planned(ws, "ch4")
    shown = pt.gap_options or []
    assert answer_key(pt, ws) == [
        entry(shown[0], "weil"),
        f"{entry(shown[1], 'wird')} … {entry(shown[2], 'erwartet')}",
        entry(shown[3], "ihrem"),
    ]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_inline_options_stand_in_brackets(page: str) -> None:
    ws = _ws(DIARY)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "ch1")
    assert 'class="task unit k-cloze' in section and " keep" not in section
    assert "Circle the right word in the brackets." in section
    assert '<div class="passage tl" lang="de">' in section
    assert section.count("<p>") == 2  # the two paragraphs
    assert 'class="blank"' not in section
    assert re.findall(r'<span class="gn">(\d+)</span>', section) == ["1", "2", "3", "4", "5"]
    pt = _planned(ws, "ch1")
    groups = section.split('<span class="choice">')[1:]
    assert len(groups) == 5
    for group, shown in zip(groups, pt.gap_options or []):
        assert re.findall(r'<span class="o">([^<]*)</span>', group)[:len(shown)] == shown
    # the first gap reads '1(ist / hat / habe)' in the order of the planner
    first = " / ".join((pt.gap_options or [[]])[0])
    assert f"Heute 1({first}) mir Frau Berger" in _text(section)


def test_inline_options_break_only_after_a_slash() -> None:
    ws = _ws({**FRIDAY, "items": ["Er trinkt {{Kaffee::Tee|Kakao}}, dann geht er."]})
    html = _section(build_html(ws), ws, "ch3")
    pieces = html.split('<span class="co">')[1:]
    assert len(pieces) == 3
    # (each piece stays whole; the spaces between them are the only breaks)
    assert pieces[0].startswith('<span class="bo">(</span><span class="o">')
    assert pieces[0].endswith(f'<span class="sl">{NBSP}/</span></span> ')
    assert pieces[1].endswith(f'<span class="sl">{NBSP}/</span></span> ')
    assert pieces[2].startswith('<span class="o">')
    assert '<span class="bc">)</span>,</span></span> dann geht er.' in pieces[2]  # the comma too


def test_inline_items_have_no_gap_numbers() -> None:
    ws = _ws(FRIDAY)
    section = _section(build_html(ws), ws, "ch3")
    assert '<div class="items gapped">' in section
    assert section.count('<div class="it">') == 3
    assert 'class="gn"' not in section
    assert section.count('<span class="choice">') == 4


@pytest.mark.parametrize("page", ["a4", "epaper"])
def test_options_below_a_text_line_up(page: str) -> None:
    ws = _ws(NOTE)
    section = _section(build_html(ws, RenderOptions(page=page)), ws, "ch2")
    assert " keep" in section
    assert "Tick the right word for each numbered gap." in section
    blanks = re.findall(r'<span class="blank" style="width:([\d.]+)mm">', section)
    assert len(blanks) == 5 and len(set(blanks)) == 1 and float(blanks[0]) <= 24.0
    rows = re.findall(r'<div class="chr" style="grid-template-columns:([^"]+)">(.*?)</div></div>'
                      r'(?=<div class="chr"|</div>)', section)
    assert len(rows) == 5
    assert len({style for style, _ in rows}) == 1  # one set of columns: a, b, c line up
    pt = _planned(ws, "ch2")
    for n, ((_, row), shown) in enumerate(zip(rows, pt.gap_options or []), 1):
        assert f'<span class="nn">{n}</span>' in row
        assert re.findall(r'<span class="lt">([a-d])</span>', row) == ["a", "b", "c"]
        assert re.findall(r'<span class="tl" lang="de">([^<]*)</span>', row) == shown


def test_options_below_each_item() -> None:
    ws = _ws(AFTER)
    section = _section(build_html(ws), ws, "ch4")
    items = re.findall(r'<div class="it">.*?(?=<div class="it">|</div></div></section>)', section)
    assert [it.count('<div class="chr"') for it in items] == [1, 2, 1]
    # only the item with two gaps numbers them (in the text and in the rows)
    assert 'class="gn"' not in items[0] and 'class="gn"' not in items[2]
    assert re.findall(r'<span class="gn">(\d)</span>', items[1]) == ["1", "2", "1", "2"]
    styles = set(re.findall(r'class="chr" style="grid-template-columns:([^"]+)"', section))
    assert len(styles) == 1 and styles.pop().startswith("6.0mm ")


def test_options_fit_beside_a_grammar_box() -> None:
    data = _data({**NOTE, "grammar": "g9"}, {**AFTER, "grammar": "g9b"})
    data["grammar"] += [copy.deepcopy(WEIL_DENN), {**copy.deepcopy(WEIL_DENN), "id": "g9b"}]
    ws = worksheet_from_dict(data)
    html = build_html(ws)
    for task_id, number_w in (("ch2", GUTTER_W), ("ch4", 0.0)):
        section = _section(html, ws, task_id)
        assert '<aside class="aside-stack">' in section and "weil or denn?" in section
        # (the passage's gap numbers stand in the gutter, the items' in the column)
        for style in re.findall(r'class="chr" style="grid-template-columns:([^"]+)"', section):
            widths = [float(w) for w in re.findall(r"([\d.]+)mm", style)]
            assert sum(widths) - number_w <= MAIN_W - GUTTER_W + 0.1, style


def test_options_too_long_for_a_row_stand_one_below_the_other() -> None:
    long_gap = ("{{werden jeden Mittwoch geröstet::haben jeden Mittwoch geröstet|sind jeden "
                "Mittwoch röstend|werden jeden Mittwoch rösten}}")
    ws = _ws({**NOTE, "text": f"Die Bohnen {long_gap}. Der Kaffee {{{{wird::werden}}}} gemahlen."})
    section = _section(build_html(ws, RenderOptions(page="epaper")), ws, "ch2")
    rows = re.findall(r'<div class="chr" style="grid-template-columns:([^"]+)">', section)
    assert rows[0] == "9.0mm 1fr" and '<div class="chw">' in section
    assert rows[1] != rows[0]  # the short row keeps its own columns


def test_a_task_instruction_wins() -> None:
    ws = _ws({**NOTE, "instruction": "Lena leaves a note on the roaster."})
    section = _section(build_html(ws), ws, "ch2")
    assert "Lena leaves a note on the roaster." in section
    assert "Tick the right word" not in section


def test_options_are_escaped() -> None:
    task = {**FRIDAY, "items": ["Er sagt {{<b>&amp;::<i>|\"x\"}} laut."]}
    for layout in ("inline", "below"):
        ws = _ws({**task, "choice_layout": layout})
        section = _section(build_html(ws), ws, "ch3")
        assert "&lt;b&gt;&amp;amp;" in section and "&lt;i&gt;" in section
        assert "<b>" not in section and "<i>" not in section


def test_the_solutions_print_the_key() -> None:
    ws = _ws(NOTE)
    solutions = build_html(ws).split('class="solutions', 1)[1]
    for entry in answer_key(_planned(ws, "ch2"), ws):
        assert f'<span class="k" lang="de">{entry}</span>' in solutions


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


def test_choices_wrap_cleanly_on_an_epaper_page(tmp_path: Path) -> None:
    pymupdf = _pymupdf()
    data = _data(DIARY, NOTE, FRIDAY, AFTER)
    data["tasks"] = [t for t in data["tasks"] if t["id"].startswith("ch")]
    ws = worksheet_from_dict(data)
    result = render_worksheet(ws, tmp_path / "choice.pdf", RenderOptions(page="epaper"))
    assert result.pdf is not None and result.warnings == []
    doc = pymupdf.open(result.pdf)
    lines: list[str] = []
    for page in doc:
        # (the word joiner in the key needs no font of its own)
        assert all("Literata" in f[3] or "Atkinson" in f[3] for f in page.get_fonts()), \
            page.get_fonts()
        width = page.rect.width
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                text = "".join(span["text"] for span in line["spans"]).strip()
                if text:
                    lines.append(text)
                for span in line["spans"]:
                    if span["text"].strip():
                        x0, _, x1, _ = span["bbox"]
                        assert x0 >= 8 * MM - 2 and x1 <= width - 8 * MM + 2, span["text"]
    # a line never starts with a slash or a closing bracket, never ends in an opening one,
    # and a key entry ('c – Vielleicht') never ends a line at its dash
    assert not [t for t in lines if t.startswith(("/", ")")) or t.endswith(("(", "–"))]
    words = " ".join(lines)
    for word in ("lächelst", "Vielleicht", "bitterste", "erwartete"):
        assert word in words, f"{word!r} was broken or lost"
