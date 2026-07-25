"""Tests for exercise generation: variety, data-driven content, media tasks."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from langwich.generate import GenerationSession, generate_exercise
from langwich.graph import build_default_graph
from langwich.text import SourceText

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = REPO_ROOT / "examples"


@pytest.fixture(scope="module")
def graph():
    return build_default_graph()


@pytest.fixture()
def coffee() -> SourceText:
    return SourceText.from_dict(
        json.loads((EXAMPLES / "coffee_en_de.json").read_text(encoding="utf-8"))
    )


@pytest.fixture()
def film() -> SourceText:
    return SourceText.from_dict(
        json.loads((EXAMPLES / "film_de_fr.json").read_text(encoding="utf-8"))
    )


# ---------------------------------------------------------------------------
# Repetition: FIB variants must not blank the same sentences
# ---------------------------------------------------------------------------

def _blanked_sentences(exercise) -> set[str]:
    return {item["sentence"] for item in exercise.items}


def test_word_bank_skips_the_opening_sentence(graph, coffee):
    # The reading text is printed right above the first exercise — its
    # opening sentence must not reappear as an exercise item.
    ex = generate_exercise(graph.nodes["fib_word_bank"], coffee, GenerationSession())
    assert not any(item["sentence"].startswith("Jeden Morgen") for item in ex.items)


def test_fib_variants_use_different_sentences(graph, coffee):
    session = GenerationSession()
    word_bank = generate_exercise(graph.nodes["fib_word_bank"], coffee, session)
    first_letter = generate_exercise(graph.nodes["fib_first_letter"], coffee, session)

    assert len(word_bank.items) == 6
    assert len(first_letter.items) == 6
    # With a shared session the second variant must draw entirely fresh sentences
    assert not _blanked_sentences(word_bank) & _blanked_sentences(first_letter)


def test_fib_third_variant_blanks_fresh_words(graph, coffee):
    session = GenerationSession()
    answers: list[set[str]] = []
    for node_id in ("fib_word_bank", "fib_first_letter", "fib_translation_hint"):
        ex = generate_exercise(graph.nodes[node_id], coffee, session)
        answers.append({sol["answer"].lower() for sol in ex.solution})
    # Even once sentences run short, the blanked words must stay distinct
    assert not answers[0] & answers[1]
    assert not (answers[0] | answers[1]) & answers[2]


def test_blanks_preserve_punctuation(graph, coffee):
    session = GenerationSession()
    ex = generate_exercise(graph.nodes["fib_word_bank"], coffee, session)
    for item in ex.items:
        sentence = item["sentence"]
        assert "______" in sentence
        # Blanking a sentence-final word must not swallow the punctuation
        assert sentence.rstrip()[-1] in ".!?"


def test_full_translation_shown_once_not_per_item(graph, coffee):
    ex = generate_exercise(graph.nodes["fib_full_translation"], coffee, GenerationSession())
    assert ex.context_text == coffee.translation
    assert all("translation" not in item for item in ex.items)


def test_multiple_choice_distractors_share_pos(graph, coffee):
    ex = generate_exercise(graph.nodes["fib_multiple_choice"], coffee, GenerationSession())
    by_stem = {}
    for v in coffee.vocabulary.items:
        term = v.term
        for article in ("der ", "die ", "das "):
            if term.startswith(article):
                term = term[len(article):]
        by_stem[term.lower()] = v.pos
    for item, sol in zip(ex.items, ex.solution):
        answer_pos = by_stem.get(sol["answer"].lower())
        if answer_pos is None:
            continue
        pos_set = {by_stem.get(c.lower()) for c in item["choices"]}
        pos_set.discard(None)
        assert pos_set == {answer_pos}, f"mixed POS in choices {item['choices']}"


# ---------------------------------------------------------------------------
# Formerly blank / hardcoded exercises
# ---------------------------------------------------------------------------

def test_wc_compound_generates_from_grammar_examples(graph, coffee):
    ex = generate_exercise(graph.nodes["wc_compound"], coffee, GenerationSession())
    assert ex is not None
    compounds = {sol["compound"] for sol in ex.solution}
    assert {"Kaffeepflanze", "Milchschaum", "Apfelstrudel", "Filterkaffee"} <= compounds
    item = ex.items[0]
    assert item["format"] == "compound"
    assert len(item["left"]) == len(item["right"]) == len(compounds)


def test_picture_color_query_derives_from_scene(graph, coffee, film):
    de = generate_exercise(graph.nodes["pic_color_query"], coffee, GenerationSession())
    questions = " ".join(item["question"] for item in de.items)
    assert "die Tasse" in questions and "das Fahrrad" in questions
    answers = " ".join(sol["answer"] for sol in de.solution)
    assert "weiß" in answers and "rot" in answers

    fr = generate_exercise(graph.nodes["pic_color_query"], film, GenerationSession())
    fr_questions = " ".join(item["question"] for item in fr.items)
    # French template with articles resolved from the vocabulary
    assert "De quelle couleur" in fr_questions
    assert "le fauteuil" in fr_questions
    fr_answers = " ".join(sol["answer"] for sol in fr.solution)
    assert "rouge" in fr_answers


def test_picture_position_answers_come_from_text(graph, coffee):
    ex = generate_exercise(graph.nodes["pic_position"], coffee, GenerationSession())
    assert ex.items, "position exercise must have items"
    assert len(ex.solution) == len(ex.items)
    for sol in ex.solution:
        assert sol["answer"] in coffee.picture_paragraph


def test_picture_fib_blanks_scene_words(graph, film):
    ex = generate_exercise(graph.nodes["pic_fib"], film, GenerationSession())
    assert ex is not None
    blanked = ex.items[0]["text"]
    answers = ex.solution[0]["answers"]
    assert blanked.count("______") == len(answers) > 0
    for answer in answers:
        assert answer in film.picture_paragraph


def test_scene_description_localized_with_lines(graph, film):
    ex = generate_exercise(graph.nodes["pic_scene_description"], film, GenerationSession())
    item = ex.items[0]
    assert item["lines"] > 0
    assert "Décris" in item["instruction"]  # target language (French)
    assert "Beschreibe" in ex.instruction  # native language (German)


def test_category_labels_localized(graph, film):
    ex = generate_exercise(graph.nodes["wc_category"], film, GenerationSession())
    assert ex is not None
    categories = ex.items[0]["categories"]
    # German learner: labels in German, not raw enum values
    assert "Farben" in categories
    assert "color" not in categories


# ---------------------------------------------------------------------------
# Media exercises
# ---------------------------------------------------------------------------

def test_media_video_search_builds_search_task(graph, coffee):
    ex = generate_exercise(graph.nodes["media_video_search"], coffee, GenerationSession())
    assert ex is not None
    assert "Kaffee Dokumentation" in ex.context_text
    tasks = " ".join(item["task"] for item in ex.items)
    assert "Title of the video" in tasks
    assert all(item["lines"] >= 1 for item in ex.items)
    # deliberately no links
    assert "http" not in tasks and "http" not in ex.instruction


def test_media_localized_for_german_learner(graph, film):
    ex = generate_exercise(graph.nodes["media_video_search"], film, GenerationSession())
    assert "Französisch" in ex.instruction  # native-language instruction
    assert "Suchideen" in ex.context_text
    # search suggestions are target-language (French)
    assert "documentaire" in ex.context_text


def test_media_fact_hunt_uses_key_vocabulary(graph, coffee):
    ex = generate_exercise(graph.nodes["media_fact_hunt"], coffee, GenerationSession())
    tasks = " ".join(item["task"] for item in ex.items)
    assert "der Kaffee" in tasks  # most frequent noun in the text


# ---------------------------------------------------------------------------
# Regressions confirmed during review
# ---------------------------------------------------------------------------

def _mini_text(content: str, vocab: list[dict], target_lang: str = "de") -> SourceText:
    return SourceText.from_dict({
        "title": "t", "content": content, "translation": "x",
        "source_lang": "en", "target_lang": target_lang,
        "cefr_level": "B1", "topic": "test",
        "vocabulary": {"items": vocab},
    })


def test_blank_is_word_bounded(graph):
    # Blanking 'Kaffee' must not eat the front of 'Kaffeepflanze'
    text = _mini_text(
        "Die Kaffeepflanze braucht guten Kaffee.",
        [{"term": "der Kaffee", "translation": "coffee", "pos": "noun"}],
    )
    ex = generate_exercise(graph.nodes["fib_word_bank"], text, GenerationSession())
    assert "Kaffeepflanze" in ex.items[0]["sentence"]
    assert "______pflanze" not in ex.items[0]["sentence"]


def test_word_bank_has_no_duplicate_answers(graph):
    text = _mini_text(
        "Der Kaffee ist stark. Ohne Kaffee geht hier gar nichts.",
        [{"term": "der Kaffee", "translation": "coffee", "pos": "noun"}],
    )
    ex = generate_exercise(graph.nodes["fib_word_bank"], text, GenerationSession())
    answers = [sol["answer"] for sol in ex.solution]
    assert len(answers) == len(set(answers))


def test_base_form_does_not_blank_nouns(graph):
    # 'Arbeit' must not be treated as a conjugated form of 'arbeiten'
    text = _mini_text(
        "Die Arbeit auf der Plantage ist hart.",
        [{"term": "arbeiten", "translation": "to work", "pos": "verb"}],
    )
    ex = generate_exercise(graph.nodes["fib_base_form"], text, GenerationSession())
    assert ex is None


def test_lowercase_token_is_not_an_inflected_german_noun(graph):
    # 'weine' (I cry) must not be linked to the noun 'der Wein'
    text = _mini_text(
        "Ich weine oft im Kino.",
        [{"term": "der Wein", "translation": "wine", "pos": "noun"}],
    )
    ex = generate_exercise(graph.nodes["fib_translation_hint"], text, GenerationSession())
    assert ex is None


def test_fib_without_material_returns_none(graph):
    text = _mini_text("Ein Satz ohne passende Wörter.", [
        {"term": "der Zug", "translation": "train", "pos": "noun"},
    ])
    assert generate_exercise(graph.nodes["fib_word_bank"], text, GenerationSession()) is None


def test_compound_examples_may_carry_articles(graph, coffee):
    coffee.grammar.phenomena[2].examples = [
        "die Kaffeepflanze (Kaffee + Pflanze)",
        "der Milchschaum (Milch + Schaum)",
        "Apfelstrudel (Apfel + Strudel)",
    ]
    ex = generate_exercise(graph.nodes["wc_compound"], coffee, GenerationSession())
    compounds = {sol["compound"] for sol in ex.solution}
    assert compounds == {"Kaffeepflanze", "Milchschaum", "Apfelstrudel"}


def test_passe_compose_is_not_a_compound_phenomenon(graph, film):
    # The 'passé composé' phenomenon must not feed the compound exercise;
    # for the film example the fallback finds nothing either.
    ex = generate_exercise(graph.nodes["wc_compound"], film, GenerationSession())
    assert ex is None


def test_french_color_answers_have_no_bad_agreement(graph, film):
    ex = generate_exercise(graph.nodes["pic_color_query"], film, GenerationSession())
    for sol in ex.solution:
        # Answer key names the color only — never a sentence like
        # 'l'affiche est bleu.' with broken gender agreement
        assert " est " not in sol["answer"]


# ---------------------------------------------------------------------------
# Graph invariants
# ---------------------------------------------------------------------------

def test_every_exercise_node_generates_for_coffee(graph, coffee):
    session = GenerationSession()
    for node in graph.exercises():
        ex = generate_exercise(node, coffee, session)
        assert ex is not None, f"{node.id} generated nothing for the coffee example"
        assert ex.items, f"{node.id} produced an empty exercise"


def test_combinable_with_references_exist(graph):
    for node in graph.exercises():
        for other in node.combinable_with:
            assert other in graph.nodes, f"{node.id} references unknown node {other}"


def test_edges_reference_known_nodes(graph):
    for edge in graph.edges:
        assert edge.source in graph.nodes
        assert edge.target in graph.nodes


# ---------------------------------------------------------------------------
# Word bank casing: sentence-initial capitals must not leak into options
# ---------------------------------------------------------------------------

def test_word_bank_drops_sentence_initial_capitalization(graph, coffee):
    # "Vor ihr steht eine weiße Tasse..." blanks sentence-initial "Vor",
    # whose vocabulary entry is lowercase ("vor") — the bank must show
    # "vor". Nouns ("Frau", "Milchschaum") keep their capital.
    found_lower_vor = False
    for seed in range(10):
        import random
        random.seed(seed)
        ex = generate_exercise(
            graph.nodes["fib_word_bank"], coffee, GenerationSession()
        )
        assert ex is not None
        assert "Vor" not in ex.word_bank
        if "vor" in ex.word_bank:
            found_lower_vor = True
        stems = {v.term.split()[-1].lower(): v.term.split()[-1]
                 for v in coffee.vocabulary.items}
        for word in ex.word_bank:
            stem = stems.get(word.lower())
            if stem and stem[:1].isupper():
                assert word[:1].isupper(), f"noun '{word}' lost its capital"
    assert found_lower_vor
