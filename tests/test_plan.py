"""The lesson arc: ordering, glosses, sidebars and seeded shuffles."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from langwich import markup
from langwich.model import VocabItem, Worksheet, load_worksheet, worksheet_from_dict
from langwich.plan import _is_tested, plan, strip_article, term_pattern
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
    # comes before that scene's detail/picture/form tasks
    assert by_scene["s4"] == ["t11", "t7", "t9", "t10", "t8"]
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


# ---------------------------------------------------------------------------
# Finding vocabulary in the story (glosses, validator word checks)
# ---------------------------------------------------------------------------


def _item(term: str, pos: str, forms: str | None = None, plural: str | None = None) -> VocabItem:
    return VocabItem(term=term, translation="x", pos=pos, forms=forms, plural=plural)


def _found(lang: str, item: VocabItem, text: str) -> str | None:
    m = term_pattern(item, lang).search(text)
    return m.group(0) if m else None


def _story_ws(lang: str, scenes: list[str], items: list[dict]) -> Worksheet:
    """A small worksheet: the given scene texts and vocabulary, one writing task."""
    data = _lena_dict()
    data["target_lang"] = lang
    data["story"]["scenes"] = [
        {"id": f"s{i + 1}", "heading": f"Scene {i + 1}", "beat": "setup", "text": text}
        for i, text in enumerate(scenes)
    ]
    data["vocabulary"] = {"target": [], "items": items}
    data["tasks"] = [{"id": "t1", "kind": "writing", "stage": "production", "title": "Write",
                      "instruction": "Write.", "prompt": "Write about it."}]
    data["grammar"], data["facts"] = [], []
    return worksheet_from_dict(data)


@pytest.mark.parametrize(("lang", "term", "pos", "text"), [
    # short stems never reach into unrelated words
    ("de", "sehen", "verb", "Das ist sehr schön."),
    ("de", "fahren", "verb", "Das Fahrrad steht vor der Tür."),
    ("de", "gehen", "verb", "Das hat sie nicht gehört."),
    ("de", "essen", "verb", "Essig und Öl."),
    ("de", "stehen", "verb", "Am Stand gibt es Obst."),  # 'stand' only with a prefix
    ("de", "der Gips", "noun", "Der Gipsarm juckt."),
    # a short bare verb stem is mostly another word
    ("de", "malen", "verb", "Sag das noch mal."),
    ("de", "reisen", "verb", "Es gibt Reis mit Gemüse."),
    ("de", "weinen", "verb", "Ein Glas Wein, bitte."),
    ("de", "landen", "verb", "Das Land ist schön."),
    ("fr", "finir", "verb", "À la fin du film."),
    ("es", "comer", "verb", "Hace la compra."),
    ("es", "tomar", "verb", "Compra tomates."),
    ("es", "pasar", "verb", "Come pasta."),
    ("es", "cenar", "verb", "Cuesta diez centavos."),
    ("es", "la sal", "noun", "Luego salió."),
    ("es", "el mar", "noun", "El martes."),
    ("es", "caro", "adjective", "La carne es buena."),
    ("fr", "venir", "verb", "Le vendeur rit."),
    ("fr", "partir", "verb", "Il y a des gens partout."),
    ("fr", "sortir", "verb", "Une sorte de film."),
    ("fr", "la mer", "noun", "Merci beaucoup."),
    ("fr", "le sel", "noun", "Selon lui, c'est vrai."),
    ("fr", "le vin", "noun", "Il a vingt ans."),
    ("fr", "la rue", "noun", "Dans la ruelle."),
])
def test_short_stems_do_not_match_unrelated_words(lang, term, pos, text):
    assert _found(lang, _item(term, pos), text) is None


@pytest.mark.parametrize(("lang", "term", "pos", "text", "match"), [
    ("de", "sehen", "verb", "Sie sieht das Meer.", "sieht"),
    ("de", "sehen", "verb", "Wir sehen uns.", "sehen"),
    ("de", "fahren", "verb", "Sie fährt nach Hause.", "fährt"),
    ("de", "die Tasse", "noun", "Zwei Tassen Kaffee.", "Tassen"),
    ("de", "müde", "adjective", "Die müden Kinder.", "müden"),
    ("es", "tomar", "verb", "Toma un café.", "Toma"),
    ("es", "comer", "verb", "Comemos juntos.", "Comemos"),
    ("es", "pensar", "verb", "Piensa en su abuela.", "Piensa"),
    ("es", "el mar", "noun", "Los mares del sur.", "mares"),
    ("es", "caro", "adjective", "Las gambas son caras.", "caras"),
    ("fr", "la mer", "noun", "Il regarde la mer.", "mer"),
    ("fr", "manger", "verb", "Nous mangeons.", "mangeons"),
    ("fr", "complet", "adjective", "La salle est complète.", "complète"),
    ("it", "la mela", "noun", "Due mele rosse.", "mele"),
    ("it", "venire", "verb", "Viene domani.", "Viene"),
    ("de", "malen", "verb", "Sie malt ein Bild.", "malt"),
    ("de", "geben", "verb", "Gib mir das Buch!", "Gib"),
    ("fr", "finir", "verb", "Le film finit.", "finit"),
    ("fr", "partir", "verb", "Il part demain.", "part"),
    ("es", "la luz", "noun", "Las luces de la calle.", "luces"),
    ("fr", "le journal", "noun", "Les journaux du matin.", "journaux"),
    ("fr", "s'éteindre", "verb", "La lumière s'est éteinte.", "éteinte"),
    ("fr", "rejoindre", "verb", "Elle rejoint ses amis.", "rejoint"),
])
def test_inflected_forms_are_still_found(lang, term, pos, text, match):
    assert _found(lang, _item(term, pos), text) == match


def test_a_gloss_anchors_on_the_real_word_not_a_look_alike():
    ws = _story_ws("de", ["Lena ist sehr müde. Sie will den Hafen sehen."],
                   [{"term": "sehen", "translation": "to see", "pos": "verb"}])
    [gloss] = plan(ws).scenes[0].glosses
    assert gloss.match == "sehen"


def test_an_exact_match_is_preferred_over_an_earlier_stem_match():
    item = _item("arbeiten", "verb")
    m = term_pattern(item, "de").search("Die Arbeiter warten. Lena will heute arbeiten.")
    assert m.group(0) == "arbeiten" and m.group("exact") is not None
    # with no exact occurrence the inflected one is used
    assert _found("de", item, "Die Arbeiter warten.") == "Arbeiter"


def test_two_items_on_one_word_the_exact_one_is_glossed():
    ws = _story_ws("de", ["Die Arbeit im Café ist schwer."], [
        {"term": "arbeiten", "translation": "to work", "pos": "verb"},
        {"term": "die Arbeit", "translation": "work", "pos": "noun"},
    ])
    assert [g.item.term for g in plan(ws).scenes[0].glosses] == ["die Arbeit"]


def test_a_label_no_longer_hides_an_unrelated_verb():
    # 'das Fahrrad' is a label answer (tested); 'fahren' is not the same word
    data = _lena_dict()
    data["vocabulary"]["items"].append(
        {"term": "fahren", "translation": "to ride", "pos": "verb", "scene": "s4"})
    ws = worksheet_from_dict(data)
    assert "fahrrad" in collect_tested_terms(ws)
    glossed = {g.item.term for b in plan(ws).scenes for g in b.glosses}
    assert "fahren" in glossed


@pytest.mark.parametrize(("term", "forms", "text", "match"), [
    ("zugeben", "gibt zu, gab zu, hat zugegeben", "„Ich habe es verwechselt“, gibt sie zu.", "gibt"),
    ("zugeben", None, "„Ich habe es verwechselt“, gibt sie zu.", "gibt"),
    ("zugeben", None, "Sie hat es zugegeben.", "zugegeben"),
    ("zugeben", None, "Es fällt ihr schwer, das zuzugeben.", "zuzugeben"),
    ("zugeben", None, "Ich weiß, dass sie es zugibt.", "zugibt"),
    ("anziehen", "zieht an, zog an, hat angezogen", "Mia zieht ihre Stiefel an.", "zieht"),
    ("anziehen", None, "Mia zieht ihre Stiefel an und geht hinaus.", "zieht"),
    ("anziehen", "zieht an, zog an, hat angezogen", "Sie zog die Jacke an.", "zog"),
    ("anziehen", "zieht an, zog an, hat angezogen", "Sie hat sich schnell angezogen.",
     "angezogen"),
    ("anrufen", None, "Sie ruft ihren Onkel an.", "ruft"),
    ("anrufen", None, "Am Abend rief sie ihren Onkel an.", "rief"),
    ("anrufen", None, "Hat er schon angerufen?", "angerufen"),
    ("aufmachen", None, "Lena macht die Tür auf.", "macht"),
    ("einkaufen", None, "Frau Berger kauft Milch ein.", "kauft"),
    ("vorbereiten", "bereitet vor, hat vorbereitet", "Sie bereitet alles vor.", "bereitet"),
    ("aufstehen", None, "Er stand um sechs Uhr auf.", "stand"),
    ("aushelfen", None, "Lena hilft im Café aus.", "hilft"),
    ("ansehen", "sieht an, sah an, hat angesehen",
     "Signor Bruno sieht die Tasse lange an, schiebt sie zurück und geht.", "sieht"),
    ("zurückschieben", None,
     "Signor Bruno sieht die Tasse lange an, schiebt sie zurück und geht.", "schiebt"),
])
def test_german_separable_verbs_are_found_split_and_joined(term, forms, text, match):
    assert _found("de", _item(term, "verb", forms), text) == match


@pytest.mark.parametrize("text", [
    "Er gibt ihm etwas zu essen.",          # 'zu' is the infinitive marker
    "Er gibt ihr das Buch, die Tür ist zu.",  # the particle is in another clause
    "Sie ruft an der Tür nach ihm.",          # 'an' is a preposition
])
def test_a_separable_particle_must_close_the_clause(text):
    for term in ("zugeben", "anrufen"):
        assert _found("de", _item(term, "verb"), text) is None


@pytest.mark.parametrize(("lang", "term", "forms", "text", "match"), [
    ("de", "sich freuen", None, "Lena freut sich sehr.", "freut"),
    ("de", "sich beeilen", None, "Lena beeilt sich.", "beeilt"),
    ("de", "sich freinehmen", None, "Lena nimmt sich frei.", "nimmt"),
    ("de", "sich freinehmen", "nimmt sich frei, nahm sich frei, hat sich freigenommen",
     "Sie fragt, ob sie sich ein paar Tage freinehmen darf.", "freinehmen"),
    ("de", "sich freinehmen", "nimmt sich frei, nahm sich frei, hat sich freigenommen",
     "Nimmt sie sich morgen frei?", "Nimmt"),
    ("fr", "se lever", None, "Elle se lève tôt.", "lève"),
    ("fr", "se dépêcher", None, "Paula se dépêche.", "dépêche"),
    ("fr", "s'arrêter", None, "Elle s'arrête devant la porte.", "arrête"),
    ("fr", "se promener", None, "Nous nous promenons.", "promenons"),
    ("it", "alzarsi", None, "Emma si alza presto.", "alza"),
    ("it", "divertirsi", None, "Ci divertiamo molto.", "divertiamo"),
    ("it", "sedersi", None, "Emma si siede.", "siede"),
    ("es", "levantarse", None, "Se levanta temprano.", "levanta"),
    ("es", "lavarse", None, "Me lavo las manos.", "lavo"),
    ("es", "sentarse", None, "Ana se sienta.", "sienta"),
    ("pt", "levantar-se", None, "Ela levanta-se cedo.", "levanta"),
])
def test_reflexive_verbs_match_without_their_pronoun(lang, term, forms, text, match):
    assert _found(lang, _item(term, "verb", forms), text) == match


def test_reflexive_forms_do_not_turn_short_words_loose():
    # 'me río' must not make 'río' (river) a form of 'reírse'
    item = _item("reírse", "verb", "me río, te ríes, se ríe")
    assert _found("es", item, "El río es largo.") is None
    assert _found("es", item, "Carmen se ríe.") == "se ríe"


def test_phrases_match_when_all_their_words_share_a_sentence():
    item = _item("sich Sorgen machen", "phrase")
    assert _found("de", item, "Onkel Marco macht sich Sorgen.") == "macht"
    assert _found("de", item, "Macht euch keine Sorgen!") == "Macht"
    assert _found("de", item, "Er macht Kaffee. Sie hat keine Sorgen.") is None
    assert _found("es", _item("medio kilo", "phrase"), "Un kilo y medio, por favor.") == "kilo"
    # a form keeps its verb: 'a lieu' is not just 'lieu'
    avoir_lieu = _item("avoir lieu", "phrase", "a lieu, a eu lieu")
    assert _found("fr", avoir_lieu, "Au lieu de rire, il part.") is None
    assert _found("fr", avoir_lieu, "Le festival a lieu en octobre.") == "a lieu"


@pytest.mark.parametrize(("lang", "term", "text"), [
    ("zh", "朋友", "晚上他在咖啡馆工作。他的朋友也来喝茶。"),
    ("zh", "喝", "他的朋友也来喝茶。"),
    ("ja", "友達", "私の友達は学生です。"),
    ("th", "กาแฟ", "ฉันชอบดื่มกาแฟทุกเช้า"),
])
def test_languages_without_spaces_match_substrings(lang, term, text):
    assert _found(lang, _item(term, "noun"), text) == term


def test_chinese_scenes_get_glosses():
    ws = _story_ws("zh", ["晚上他在咖啡馆工作。他的朋友也来喝茶。", "但是很舒服。"], [
        {"term": "朋友", "translation": "friend", "pos": "noun"},
        {"term": "舒服", "translation": "comfortable", "pos": "adjective"},
    ])
    p = plan(ws)
    assert [[g.match for g in b.glosses] for b in p.scenes] == [["朋友"], ["舒服"]]


def test_split_and_reflexive_items_are_glossed_in_the_lena_02_story():
    ws = load_worksheet(LENA.parent / "lena_02_en_de.json")
    matches = {g.item.term: g.match for b in plan(ws).scenes for g in b.glosses}
    assert matches["ansehen"] == "sieht"
    assert matches["zurückschieben"] == "schiebt"
    assert matches["sich Sorgen machen"] == "macht"
    assert matches["sich freinehmen"] == "freinehmen"


def test_a_tested_finite_form_hides_the_gloss_of_its_separable_verb():
    ws = _story_ws("de", ["„Ich habe es verwechselt“, gibt sie zu."],
                   [{"term": "zugeben", "translation": "to admit", "pos": "verb"}])
    assert [g.item.term for g in plan(ws).scenes[0].glosses] == ["zugeben"]
    assert _is_tested(ws.vocab_item("zugeben"), {"gibt"}, "de")


# ---------------------------------------------------------------------------
# Word boxes and shuffles
# ---------------------------------------------------------------------------


def test_label_word_box_leaves_out_the_articles():
    ws = load_worksheet(LENA)
    label = next(t for t in plan(ws).tasks if t.task.kind == "label")
    terms = [lb.term for lb in ws.scene(label.task.scene).picture.labels]
    assert sorted(label.bank) == sorted(strip_article(t, "de") for t in terms)
    assert not any(w.split()[0].lower() in ("der", "die", "das") for w in label.bank)


def test_two_pair_match_never_keeps_the_given_order():
    data = _lena_dict()
    match = data["tasks"][0]
    match["pairs"], match["extra"] = match["pairs"][:2], []
    ws = worksheet_from_dict(data)
    for seed in range(40):
        assert plan(ws, seed=seed).before[0].right_order == [1, 0]


def test_two_option_multiple_choice_is_still_shuffled_both_ways():
    data = _lena_dict()
    mc = next(t for t in data["tasks"] if t["kind"] == "multiple_choice")
    for item in mc["items"]:
        item["options"] = [item["answer"], next(o for o in item["options"] if o != item["answer"])]
    ws = worksheet_from_dict(data)
    positions = set()
    for seed in range(20):
        planned = next(t for t in plan(ws, seed=seed).tasks if t.task.id == mc["id"])
        positions.update(order.index(item.answer)
                         for order, item in zip(planned.option_orders, planned.task.items))
    assert positions == {0, 1}  # the answer is not always swapped into second place


def test_match_letters_continue_after_z():
    ws = load_worksheet(LENA)
    pt = plan(ws).before[0]
    pt.right_order = list(range(30))
    assert pt.letter_for_pair(0) == "A"
    assert pt.letter_for_pair(25) == "Z"
    assert pt.letter_for_pair(26) == "AA"
    assert pt.letter_for_pair(29) == "AD"


#: One task of every kind whose options or words the planner shuffles with
#: a seed: option balancing (multiple_choice, cloze choice, including a gap
#: with a single option) and the word boxes (cloze, table, dialogue, label).
_SHUFFLED: dict = {
    "schema": "langwich/3", "title": "Im Café", "source_lang": "en", "target_lang": "de",
    "cefr_level": "B1", "topic": "coffee",
    "story": {"logline": "Lena learns to roast coffee.", "scenes": [{
        "id": "s1", "heading": "Die Rösterei", "text": "Lena röstet Kaffee.",
        "picture": {"svg": "<svg></svg>", "labels": [
            {"n": 1, "term": "die Tasse"}, {"n": 2, "term": "der Sack"},
            {"n": 3, "term": "das Sieb"}, {"n": 4, "term": "die Waage"},
        ]},
    }]},
    "vocabulary": {"items": [{"term": "die Tasse", "translation": "cup"}]},
    "tasks": [
        {"id": "mc", "kind": "multiple_choice", "stage": "detail", "scene": "s1", "items": [
            {"question": f"Q{i}", "options": options, "answer": options[i % len(options)]}
            for i, options in enumerate(
                [["a", "b", "c"], ["d", "e", "f", "g"], ["h", "i"], ["j", "k", "l"],
                 ["m", "n", "o", "p"], ["q", "r", "s"], ["t", "u"], ["v", "w", "x", "y"]]
            )
        ]},
        {"id": "ch", "kind": "cloze", "stage": "form", "scene": "s1", "hint": "choice",
         "text": "{{hat::ist|habe}} {{kommen::kommt}} {{in::auf|an|um}} {{weil::denn|da}} "
                 "{{Sie::sie}} {{nur}} {{am::im|um}} {{wird::werden|wurde}} {{aus::von}}"},
        {"id": "wb", "kind": "cloze", "stage": "practice", "scene": "s1",
         "items": ["Sie {{röstet}} Kaffee.", "Der {{Sack}} ist {{schwer}}.", "Ein {{sack}}."],
         "distractors": ["leicht", "Röstet", "die Bohne"]},
        {"id": "tb", "kind": "table", "stage": "practice", "scene": "s1", "hint": "word_bank",
         "head": ["Land", "Bohne"], "rows": [["{{Brasilien}}", "{{Arabica}}"],
                                             ["{{Vietnam}}", "{{Robusta}}"]],
         "distractors": ["Peru"]},
        {"id": "dl", "kind": "dialogue", "stage": "practice", "scene": "s1", "bank": True,
         "lines": [{"speaker": "Lena", "text": "Ich {{möchte}} einen {{Kaffee}}."},
                   {"speaker": "Anna", "text": "Mit {{Milch}}?"}],
         "distractors": ["Tee", "Zucker"]},
        {"id": "lb", "kind": "label", "stage": "picture", "scene": "s1"},
    ],
}


def test_seeded_orders_never_change():
    """The same JSON and seed always give the same sheet: tidying the planner
    must not move one option or word for any seed. (When a change of the
    shuffles is intended, update the digest and rebuild the showcase.)"""
    ws = worksheet_from_dict(_SHUFFLED)
    orders = []
    for seed in range(300):
        for pt in plan(ws, seed=seed).tasks:
            orders.append([pt.task.id, pt.option_orders, pt.gap_options, pt.bank])
    digest = hashlib.sha256(json.dumps(orders, ensure_ascii=False).encode()).hexdigest()
    assert digest == "87ddb45c56bcd9954cb5676f76150e00ef3c9f954bee847b2f80e053d3efe02c"
