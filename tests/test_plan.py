"""The lesson arc: ordering, glosses, sidebars and seeded shuffles."""

from __future__ import annotations

import json
from pathlib import Path

from langwich import markup
from langwich.model import load_worksheet, worksheet_from_dict
from langwich.plan import plan, strip_article, term_pattern
from langwich.plan import tested_terms as collect_tested_terms

LENA = Path(__file__).resolve().parent.parent / "examples" / "lena_01_en_de.json"


def _lena_dict() -> dict:
    return json.loads(LENA.read_text(encoding="utf-8"))


def test_arc_order_follows_stages_not_json_order():
    p = plan(load_worksheet(LENA))
    assert [t.task.id for t in p.before] == ["t1", "t2"]
    by_scene = {b.scene.id: [t.task.id for t in b.tasks] for b in p.scenes}
    assert by_scene["s1"] == ["t3"]
    assert by_scene["s3"] == ["t5", "t6"]  # form before practice
    # the whole-story order task (gist, no scene) follows the last scene and
    # comes before that scene's detail/form/picture tasks
    assert by_scene["s4"] == ["t11", "t7", "t8", "t9", "t10"]
    assert [t.task.id for t in p.your_turn] == ["t12", "t13"]
    assert [t.task.id for t in p.further] == ["t14"]
    assert [t.number for t in p.tasks] == list(range(1, 15))


def test_production_is_always_after_the_story_even_with_a_scene():
    data = _lena_dict()
    writing = next(t for t in data["tasks"] if t["kind"] == "writing")
    writing["scene"] = "s1"
    p = plan(worksheet_from_dict(data))
    assert writing["id"] in [t.task.id for t in p.your_turn]


def test_task_follows_the_last_scene_it_references():
    data = _lena_dict()
    data["tasks"][2]["scene"] = ["s1", "s3"]  # true/false spanning scenes
    p = plan(worksheet_from_dict(data))
    s3 = next(b for b in p.scenes if b.scene.id == "s3")
    assert "t3" in [t.task.id for t in s3.tasks]


def test_glosses_never_contain_tested_words():
    ws = load_worksheet(LENA)
    p = plan(ws)
    tested = collect_tested_terms(ws)
    glossed = {g.item.term for b in p.scenes for g in b.glosses}
    assert glossed, "scenes should carry glosses"
    for term in ws.vocabulary.target:
        assert term not in glossed
    for term in glossed:
        assert strip_article(term).casefold() not in tested
    # label answers and word-building answers are tested, so never glossed
    assert "die Tasse" not in glossed
    assert "der Apfelstrudel" not in glossed


def test_glosses_point_at_surface_forms_in_the_scene():
    p = plan(load_worksheet(LENA))
    for block in p.scenes:
        for g in block.glosses:
            if g.match:
                assert g.match in block.scene.text


def test_each_word_is_glossed_once_per_worksheet():
    p = plan(load_worksheet(LENA))
    terms = [g.item.term for b in p.scenes for g in b.glosses]
    assert len(terms) == len(set(terms))


def test_grammar_sidebar_sits_beside_the_task_that_references_it():
    p = plan(load_worksheet(LENA))
    by_id = {t.task.id: t for t in p.tasks}
    assert [s.grammar.id for s in by_id["t5"].sidebars if s.grammar] == ["g1"]
    assert [s.grammar.id for s in by_id["t8"].sidebars if s.grammar] == ["g2"]
    assert p.reference_grammar == []


def test_facts_attach_to_their_scene():
    p = plan(load_worksheet(LENA))
    facts = {b.scene.id: [s.fact.id for s in b.sidebars if s.fact] for b in p.scenes}
    assert facts["s2"] == ["f1"] and facts["s3"] == ["f2"]


def test_shuffles_are_deterministic_and_consistent():
    ws = load_worksheet(LENA)
    a, b = plan(ws), plan(ws)
    assert [t.right_order for t in a.tasks] == [t.right_order for t in b.tasks]
    assert [t.bank for t in a.tasks] == [t.bank for t in b.tasks]
    other = plan(ws, seed=12345)
    assert [t.right_order for t in other.tasks] != [t.right_order for t in a.tasks] or \
        [t.bank for t in other.tasks] != [t.bank for t in a.tasks]


def test_match_letters_point_at_the_right_partner():
    p = plan(load_worksheet(LENA))
    match = p.before[0]
    column = match.right_column
    for i, pair in enumerate(match.task.pairs):
        letter = match.letter_for_pair(i)
        assert column["ABCDEFGHIJ".index(letter)] == pair.right
    assert column != [pair.right for pair in match.task.pairs] + list(match.task.extra)


def test_word_bank_holds_every_answer_and_the_distractors_once():
    ws = load_worksheet(LENA)
    p = plan(ws)
    cloze = next(t for t in p.tasks if t.task.id == "t6")
    answers = [g.answer for g in markup.gaps(cloze.task.text)]
    assert sorted(cloze.bank) == sorted(answers + cloze.task.distractors)
    base_form = next(t for t in p.tasks if t.task.id == "t5")
    assert base_form.bank is None  # hint=base_form has no bank


def test_order_events_display_is_shuffled_and_numbers_recover_the_story():
    p = plan(load_worksheet(LENA))
    order = next(t for t in p.tasks if t.task.kind == "order_events")
    assert order.events != order.task.events
    recovered = sorted(order.events, key=order.event_number)
    assert recovered == order.task.events


def test_term_pattern_finds_inflected_and_irregular_forms():
    ws = load_worksheet(LENA)
    item = ws.vocab_item("wachsen")
    assert term_pattern(item).search("Kaffee wächst vor allem in den Tropen")
    assert term_pattern(ws.vocab_item("tropisch")).search("in tropischen Ländern")
    assert term_pattern(ws.vocab_item("die Tasse")).search("eine weiße Tasse")
    assert not term_pattern(ws.vocab_item("die Tasse")).search("Tassenhalter aus Holz")
