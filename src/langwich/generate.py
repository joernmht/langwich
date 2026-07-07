"""Exercise generation from a SourceText using the exercise graph.

The text is the gold mine. This module extracts exercise content from it:
- FIB: blank out words, produce hints
- Picture: reference picture_scene elements
- WordConnections: pair vocabulary items
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from langwich import puzzles
from langwich.culture import fallback_resource, pick_resource
from langwich.graph import ExerciseNode, ExerciseType, VocabularyItem
from langwich.i18n import (
    connector_words,
    day_names,
    lang_name as _lang_name,
    localize as _localize,
    localize_fmt,
    question_words,
)
from langwich.text import SourceText


@dataclass
class ExerciseInstance:
    """A concrete exercise generated from a text."""
    node_id: str  # which ExerciseNode this came from
    title: str
    instruction: str
    items: list[dict] = field(default_factory=list)
    solution: list[dict] = field(default_factory=list)
    word_bank: list[str] = field(default_factory=list)
    picture_prompt: str = ""
    # Culture-library resource backing this exercise (title, url, description,
    # category ...). A non-empty "url" makes the renderer print a QR code.
    resource: dict = field(default_factory=dict)


def generate_exercise(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    """Generate a concrete exercise instance from a node + text."""
    generators = {
        ExerciseType.FILL_IN_BLANKS: _generate_fib,
        ExerciseType.PICTURE_INTERACTION: _generate_picture,
        ExerciseType.WORD_CONNECTIONS: _generate_word_connections,
        ExerciseType.PUZZLE: _generate_puzzle,
        ExerciseType.TEXT_ANALYSIS: _generate_text_analysis,
        ExerciseType.WRITING: _generate_writing,
        ExerciseType.DIALOGUE: _generate_dialogue,
        ExerciseType.MEDIA: _generate_media,
        ExerciseType.SOCIAL_MEDIA: _generate_social,
        ExerciseType.REAL_WORLD: _generate_real_world,
        ExerciseType.NUMBERS: _generate_numbers,
        ExerciseType.STUDY: _generate_study,
    }
    generator = generators.get(node.exercise_type)
    return generator(node, text) if generator else None


# ---------------------------------------------------------------------------
# FIB generators
# ---------------------------------------------------------------------------

def _pick_blank_targets(text: SourceText, count: int = 6) -> list[tuple[str, str]]:
    """Pick sentences from the text and a word to blank from each.

    Returns list of (sentence, blanked_word).
    """
    if not text.vocabulary or not text.vocabulary.items:
        return []

    vocab_terms = {_strip_article(v.term).lower() for v in text.vocabulary.items}
    results: list[tuple[str, str]] = []

    for para in text.paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            words = sentence.split()
            for word in words:
                clean = re.sub(r"[.,;:!?]", "", word).lower()
                if clean in vocab_terms and len(clean) > 2:
                    results.append((sentence, word))
                    break
            if len(results) >= count:
                break
        if len(results) >= count:
            break

    return results[:count]


def _strip_article(term: str) -> str:
    for article in ("der ", "die ", "das ", "ein ", "eine "):
        if term.lower().startswith(article):
            return term[len(article):]
    return term


def _pick_verb_targets(text: SourceText, count: int = 6) -> list[tuple[str, str, str]]:
    """Pick sentences containing inflected verbs from vocabulary.

    Returns list of (sentence, inflected_form, base_form).
    Only matches words that look like conjugated verb forms (ending in -t, -e,
    -st, -en, -et) and share a meaningful stem with a vocabulary verb.
    """
    if not text.vocabulary or not text.vocabulary.items:
        return []

    verbs = {_strip_article(v.term).lower(): v.term
             for v in text.vocabulary.items if v.pos == "verb"}
    # Collect non-verb vocabulary to exclude nouns that look like verb forms
    non_verb_words = {_strip_article(v.term).lower()
                      for v in text.vocabulary.items if v.pos != "verb"}
    results: list[tuple[str, str, str]] = []
    seen_verbs: set[str] = set()

    # Common German verb conjugation endings
    verb_endings = ("t", "e", "st", "en", "et", "te", "tet", "ten")

    for para in text.paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            words = sentence.split()
            for word in words:
                clean = re.sub(r"[.,;:!?]", "", word).lower()
                if len(clean) < 3:
                    continue
                # Skip if this word is a known non-verb in vocabulary
                if clean in non_verb_words:
                    continue
                # Must end with a verb conjugation suffix
                if not any(clean.endswith(e) for e in verb_endings):
                    continue
                for stem, base in verbs.items():
                    if stem in seen_verbs:
                        continue
                    # The stem without -en/-n ending
                    verb_root = stem[:-2] if stem.endswith("en") else stem[:-1]
                    if len(verb_root) < 3:
                        continue
                    # The word must start with the verb root (allowing umlaut)
                    # and the word itself must not be the infinitive
                    if (clean.startswith(verb_root) and clean != stem
                            and len(clean) <= len(stem) + 2):
                        results.append((sentence, word, base))
                        seen_verbs.add(stem)
                        break
                else:
                    continue
                break
            if len(results) >= count:
                break
        if len(results) >= count:
            break

    return results[:count]


def _generate_fib(node: ExerciseNode, text: SourceText) -> ExerciseInstance:
    # Base form variant: only blank verbs and always provide the infinitive
    if node.hint_type == "base_form":
        return _generate_fib_base_form(node, text)

    targets = _pick_blank_targets(text)
    items: list[dict] = []
    solutions: list[dict] = []
    bank_words: list[str] = []

    for i, (sentence, word) in enumerate(targets, 1):
        blanked = sentence.replace(word, "______", 1)

        item: dict = {"number": i, "sentence": blanked}

        if node.hint_type == "first_letter":
            clean = re.sub(r"[.,;:!?]", "", word)
            item["hint"] = clean[0] + "______"
        elif node.hint_type == "multiple_choice":
            clean = re.sub(r"[.,;:!?]", "", word)
            distractors = _get_distractors(clean, text)
            options = [clean] + distractors[:2]
            random.shuffle(options)
            item["choices"] = options
        elif node.hint_type == "translation":
            clean = re.sub(r"[.,;:!?]", "", word)
            translation = _find_translation(clean, text)
            if translation:
                item["hint"] = f"({translation})"
        elif node.hint_type == "full_translation":
            para_idx = _find_paragraph_index(sentence, text)
            if para_idx is not None and text.translation:
                trans_paras = [p.strip() for p in text.translation.split("\n\n") if p.strip()]
                if para_idx < len(trans_paras):
                    item["translation"] = trans_paras[para_idx]

        clean_word = re.sub(r"[.,;:!?]", "", word)
        bank_words.append(clean_word)
        items.append(item)
        solutions.append({"number": i, "answer": clean_word})

    # Add distractors to word bank
    if node.hint_type == "word_bank" and text.vocabulary:
        extra = [_strip_article(v.term) for v in text.vocabulary.items
                 if _strip_article(v.term) not in bank_words]
        random.shuffle(extra)
        bank_words.extend(extra[:3])
        random.shuffle(bank_words)

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_fib_instruction(node, text.source_lang),
        items=items,
        solution=solutions,
        word_bank=bank_words if node.hint_type == "word_bank" else [],
    )


def _generate_fib_base_form(node: ExerciseNode, text: SourceText) -> ExerciseInstance:
    """FIB variant that blanks inflected verbs and gives the infinitive as hint."""
    targets = _pick_verb_targets(text)
    items: list[dict] = []
    solutions: list[dict] = []

    for i, (sentence, inflected, base) in enumerate(targets, 1):
        blanked = sentence.replace(inflected, "______", 1)
        clean = re.sub(r"[.,;:!?]", "", inflected)
        items.append({
            "number": i,
            "sentence": f"{blanked}  ({base})",
        })
        solutions.append({"number": i, "answer": clean})

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_fib_instruction(node, text.source_lang),
        items=items,
        solution=solutions,
    )


def _fib_instruction(node: ExerciseNode, source_lang: str = "en") -> str:
    instructions = {
        "word_bank": "Fill in the blanks using the words from the word bank.",
        "first_letter": "Fill in the blanks. The first letter is given.",
        "multiple_choice": "Choose the correct word for each blank.",
        "translation": "Fill in the blanks. The translation is given as a hint.",
        "base_form": "Fill in the correct form of the word in parentheses.",
        "none": "Fill in the blanks from memory.",
        "full_translation": "Fill in the blanks using the translation as reference.",
    }
    en_text = instructions.get(node.hint_type or "none", "Fill in the blanks.")
    return _localize(en_text, source_lang)


def _get_distractors(word: str, text: SourceText) -> list[str]:
    if not text.vocabulary:
        return []
    candidates = [_strip_article(v.term) for v in text.vocabulary.items
                  if _strip_article(v.term).lower() != word.lower()]
    random.shuffle(candidates)
    return candidates[:3]


def _find_translation(word: str, text: SourceText) -> str | None:
    if not text.vocabulary:
        return None
    for v in text.vocabulary.items:
        if _strip_article(v.term).lower() == word.lower():
            return v.translation
    return None


def _find_base_form(word: str, text: SourceText) -> str | None:
    if not text.vocabulary:
        return None
    for v in text.vocabulary.items:
        if v.pos == "verb":
            stem = _strip_article(v.term).lower()
            if word.lower().startswith(stem[:3]):
                return v.term
    return None


def _find_paragraph_index(sentence: str, text: SourceText) -> int | None:
    for i, para in enumerate(text.paragraphs):
        if sentence in para:
            return i
    return None


# ---------------------------------------------------------------------------
# Picture generators
# ---------------------------------------------------------------------------

def _generate_picture(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    if not text.picture_scene:
        return None

    scene = text.picture_scene
    elements = scene.elements
    items: list[dict] = []
    solutions: list[dict] = []

    if node.id == "pic_color_query":
        # Generate color questions from the picture paragraph
        color_pairs = [
            ("die Tasse", "weiß"),
            ("der Teller", "blau"),
            ("das Fahrrad", "rot"),
        ]
        for i, (obj, color) in enumerate(color_pairs, 1):
            items.append({"number": i, "question": f"Welche Farbe hat {obj}?"})
            solutions.append({"number": i, "answer": color})

    elif node.id == "pic_element_marking":
        for i, elem in enumerate(elements[:5], 1):
            items.append({"number": i, "instruction": f'Kreise \u201e{elem}\u201c im Bild ein!'})

    elif node.id == "pic_position":
        position_pairs = [
            ("die Tasse", "dem Teller", "Die Tasse steht neben dem Teller."),
            ("der Apfelstrudel", "der Tasse", "Der Apfelstrudel liegt neben der Tasse."),
            ("das Fahrrad", "der Laterne", "Das Fahrrad lehnt an der Laterne."),
            ("die Frau", "dem Fenster", "Die Frau sitzt am Fenster."),
        ]
        for i, (a, b_dative, answer) in enumerate(position_pairs, 1):
            items.append({
                "number": i,
                "question": f"Wo befindet sich {a} im Bild?",
            })
            solutions.append({"number": i, "answer": answer})

    elif node.id == "pic_object_naming":
        for i, elem in enumerate(elements[:6], 1):
            items.append({"number": i, "instruction": f"Gegenstand {i}: ___________"})
            solutions.append({"number": i, "answer": elem})

    elif node.id == "pic_scene_description":
        items.append({
            "instruction": "Beschreibe das Bild in 4-6 Sätzen. "
            "Verwende dabei mindestens 3 Präpositionen (neben, vor, durch, an, ...)."
        })

    elif node.id == "pic_fib":
        pic_para = text.picture_paragraph
        if pic_para:
            blanks = ["weiße", "Cappuccino", "blauen", "rotes", "Laterne"]
            blanked_text = pic_para
            for w in blanks:
                blanked_text = blanked_text.replace(w, "______", 1)
            items.append({"text": blanked_text})
            solutions = [{"answers": blanks}]

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_picture_instruction(node, text.source_lang, text.target_lang),
        items=items,
        solution=solutions,
        picture_prompt=scene.description,
    )


def _picture_instruction(node: ExerciseNode, source_lang: str = "en", target_lang: str = "") -> str:
    if node.id == "pic_object_naming":
        return _pic_object_naming_instruction(source_lang, target_lang)
    instructions = {
        "pic_color_query": "Look at the picture and answer the color questions.",
        "pic_element_marking": "Find and circle the following elements in the picture.",
        "pic_position": "Describe the position of the objects using prepositions.",
        "pic_scene_description": "Describe the picture in your own words.",
        "pic_fib": "Fill in the blanks using what you see in the picture.",
    }
    en_text = instructions.get(node.id, "Complete the picture task.")
    return _localize(en_text, source_lang)


def _pic_object_naming_instruction(source_lang: str, target_lang: str) -> str:
    target_name = _lang_name(target_lang, source_lang)
    templates = {
        "en": f"Write the {target_name} word for each numbered object in the picture.",
        "de": f"Schreibe das {target_name} Wort für jeden nummerierten Gegenstand im Bild.",
        "fr": f"Écris le mot {target_name} pour chaque objet numéroté dans l'image.",
        "es": f"Escribe la palabra en {target_name} para cada objeto numerado en la imagen.",
    }
    return templates.get(source_lang, templates["en"])


# ---------------------------------------------------------------------------
# Word Connections generators
# ---------------------------------------------------------------------------

def _generate_word_connections(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    if not text.vocabulary or not text.vocabulary.items:
        return None

    vocab = text.vocabulary.items
    items: list[dict] = []
    solutions: list[dict] = []

    if node.id == "wc_translation":
        selected = random.sample(vocab, min(8, len(vocab)))
        left = [{"number": i, "term": v.term} for i, v in enumerate(selected, 1)]
        right_items = list(enumerate(selected, 1))
        random.shuffle(right_items)
        right = [{"letter": chr(64 + j), "term": r.translation}
                 for j, (_, r) in enumerate(right_items, 1)]
        items = [{"left": left, "right": right}]
        solutions = [{"number": i, "letter": chr(64 + next(
            j for j, (orig_i, _) in enumerate(right_items, 1) if orig_i == i
        ))} for i in range(1, len(selected) + 1)]

    elif node.id == "wc_synonym":
        with_syn = [v for v in vocab if v.synonym]
        selected = with_syn[:6] if len(with_syn) >= 3 else with_syn
        for i, v in enumerate(selected, 1):
            items.append({"number": i, "term": v.term, "connect_to": "?"})
            solutions.append({"number": i, "term": v.term, "synonym": v.synonym})

    elif node.id == "wc_antonym":
        with_ant = [v for v in vocab if v.antonym]
        selected = with_ant[:6] if len(with_ant) >= 3 else with_ant
        for i, v in enumerate(selected, 1):
            items.append({"number": i, "term": v.term, "connect_to": "?"})
            solutions.append({"number": i, "term": v.term, "antonym": v.antonym})

    elif node.id == "wc_category":
        by_type: dict[str, list[VocabularyItem]] = {}
        for v in vocab:
            st = v.semantic_type.value if v.semantic_type else "other"
            by_type.setdefault(st, []).append(v)
        # Pick categories with 2+ items
        categories = {k: vs for k, vs in by_type.items() if len(vs) >= 2 and k != "other"}
        all_words = [_strip_article(v.term) for vs in categories.values() for v in vs]
        if not all_words:
            return None
        random.shuffle(all_words)
        items = [{"words": all_words, "categories": list(categories.keys())}]
        solutions = [{"category": k, "words": [_strip_article(v.term) for v in vs]}
                     for k, vs in categories.items()]

    elif node.id == "wc_compound":
        compounds = _find_compounds(text)
        if len(compounds) >= 3:
            rights = [c["right"] for c in compounds]
            random.shuffle(rights)
            items = [{
                "left_column": [c["left"] for c in compounds],
                "right_column": rights,
            }]
            solutions = [{"parts": f"{c['left']} + {c['right']}",
                          "compound": c["compound"]} for c in compounds]

    if not items:
        return None

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_wc_instruction(node, text.source_lang, text.target_lang),
        items=items,
        solution=solutions,
    )


def _wc_instruction(node: ExerciseNode, source_lang: str = "en", target_lang: str = "") -> str:
    if node.id == "wc_translation":
        return _wc_translation_instruction(source_lang, target_lang)
    instructions = {
        "wc_synonym": "Find the synonym for each word.",
        "wc_antonym": "Find the antonym (opposite) for each word.",
        "wc_category": "Sort the words into the correct categories.",
        "wc_compound": "Connect the word parts to form compound words.",
    }
    en_text = instructions.get(node.id, "Complete the word connections.")
    return _localize(en_text, source_lang)


def _wc_translation_instruction(source_lang: str, target_lang: str) -> str:
    target_name = _lang_name(target_lang, source_lang)
    source_name = _lang_name(source_lang, source_lang)
    templates = {
        "en": f"Connect each {target_name} word to its {source_name} translation.",
        "de": f"Verbinde jedes {target_name} Wort mit seiner {source_name}n Übersetzung.",
        "fr": f"Relie chaque mot {target_name} à sa traduction {source_name}.",
        "es": f"Conecta cada palabra en {target_name} con su traducción en {source_name}.",
    }
    return templates.get(source_lang, templates["en"])


# ---------------------------------------------------------------------------
# Shared helpers for the extended task library
# ---------------------------------------------------------------------------

def _pick_vocab(text: SourceText, count: int, pos: str | None = None) -> list[VocabularyItem]:
    """A stable selection of vocabulary items, optionally filtered by POS."""
    if not text.vocabulary:
        return []
    items = text.vocabulary.items
    if pos:
        items = [v for v in items if v.pos == pos]
    return items[:count]


def _topic_label(text: SourceText) -> str:
    return text.topic.replace("-", " ").replace("_", " ")


def _hashtag(term: str) -> str:
    word = puzzles.clean_word(term)
    return "#" + word[:1].upper() + word[1:] if word else ""


def _sentences(text: SourceText) -> list[str]:
    result = []
    for para in text.paragraphs:
        result.extend(s for s in re.split(r"(?<=[.!?])\s+", para) if s.strip())
    return result


def _find_compounds(text: SourceText) -> list[dict]:
    """Find compound words in the text that start with a vocabulary term.

    E.g. text token "Kaffeepflanze" + vocab "der Kaffee" →
    left "Kaffee", right "pflanze".
    """
    if not text.vocabulary:
        return []
    stems = {}
    for v in text.vocabulary.items:
        stem = puzzles.clean_word(v.term)
        if len(stem) >= 4:
            stems[stem.lower()] = stem

    found: dict[str, dict] = {}
    for sentence in _sentences(text):
        for token in re.findall(r"[^\W\d_]+", sentence, re.UNICODE):
            low = token.lower()
            if token in found:
                continue
            for stem_low, stem in stems.items():
                if len(low) < len(stem_low) + 3:
                    continue
                if low.startswith(stem_low):
                    remainder = token[len(stem_low):]
                    if remainder.isalpha():
                        found[token] = {"left": stem,
                                        "right": remainder.lower(),
                                        "compound": token}
                        break
                if low.endswith(stem_low):
                    remainder = token[:len(low) - len(stem_low)]
                    if remainder.isalpha():
                        found[token] = {"left": remainder,
                                        "right": stem_low,
                                        "compound": token}
                        break
    return list(found.values())[:6]


def _resource_for(node: ExerciseNode, text: SourceText) -> dict:
    """Pick a culture-library resource (or a search fallback) for a node."""
    category = node.media_category or "video"
    res = pick_resource(text.target_lang, category, topic=text.topic,
                        cefr_level=text.cefr_level)
    if res is None:
        res = fallback_resource(text.target_lang, category, text.topic)
    d = res.to_dict()
    d["scan_label"] = _localize("Scan to open:", text.source_lang)
    return d


# ---------------------------------------------------------------------------
# Puzzle generators
# ---------------------------------------------------------------------------

def _generate_puzzle(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    vocab = _pick_vocab(text, 10)
    if not vocab:
        return None
    items: list[dict] = []
    solutions: list[dict] = []
    instruction_key = ""

    if node.id == "pz_word_search":
        instruction_key = ("Find the hidden words in the letter grid. "
                           "Words run horizontally, vertically, or diagonally.")
        ws = puzzles.build_word_search([v.term for v in vocab[:8]])
        if ws is None:
            return None
        items.append({"grid": ws.grid})
        items.append({"bank": [p["word"] for p in ws.placements]})
        for p in ws.placements:
            (r0, c0), (r1, c1) = p["start"], p["end"]
            solutions.append({"note": f"{p['word']}: ({r0 + 1},{c0 + 1}) → ({r1 + 1},{c1 + 1})"})

    elif node.id == "pz_word_scramble":
        instruction_key = ("Unscramble the letters to form words from this "
                           "worksheet. The translation is given as a hint.")
        n = 1
        for v in vocab:
            scrambled = puzzles.scramble_word(v.term)
            if not scrambled:
                continue
            items.append({"number": n, "scramble": scrambled,
                          "hint": v.translation, "lines": 0})
            solutions.append({"number": n, "answer": puzzles.clean_word(v.term).upper()})
            n += 1
            if n > 6:
                break
        if not items:
            return None

    elif node.id == "pz_crossword":
        instruction_key = ("Solve the crossword. The clues are the translations "
                           "of the words.")
        cw = puzzles.build_crossword([(v.term, v.translation) for v in vocab])
        if cw is None:
            return None
        items.append({"crossword": {
            "width": cw.width,
            "height": cw.height,
            "cells": {f"{r},{c}": ch for (r, c), ch in cw.cells.items()},
            "numbers": {f"{r},{c}": n for (r, c), n in cw.numbers.items()},
        }})
        items.append({
            "clues_across": cw.across,
            "clues_down": cw.down,
            "across_label": _localize("Across", text.source_lang),
            "down_label": _localize("Down", text.source_lang),
        })
        for e in cw.across:
            solutions.append({"note": f"→ {e['number']}: {e['answer']}"})
        for e in cw.down:
            solutions.append({"note": f"↓ {e['number']}: {e['answer']}"})

    elif node.id == "pz_odd_one_out":
        instruction_key = ("Circle the word that does not fit in each row and "
                           "explain why.")
        by_type: dict[str, list[VocabularyItem]] = {}
        for v in (text.vocabulary.items if text.vocabulary else []):
            st = v.semantic_type.value if v.semantic_type else "other"
            by_type.setdefault(st, []).append(v)
        groups = {k: vs for k, vs in by_type.items() if len(vs) >= 3}
        if len(groups) < 2:
            # fall back to part-of-speech grouping
            by_pos: dict[str, list[VocabularyItem]] = {}
            for v in (text.vocabulary.items if text.vocabulary else []):
                by_pos.setdefault(v.pos, []).append(v)
            groups = {k: vs for k, vs in by_pos.items() if len(vs) >= 3}
        keys = list(groups)
        if len(keys) < 2:
            return None
        n = 1
        for i, key in enumerate(keys):
            other_key = keys[(i + 1) % len(keys)]
            base = [puzzles.clean_word(v.term) for v in groups[key][:3]]
            odd = puzzles.clean_word(groups[other_key][0].term)
            row = base + [odd]
            random.shuffle(row)
            items.append({"number": n, "words_row": row, "why": True})
            solutions.append({"number": n, "answer": odd,
                              "note": f"the others are {key}"})
            n += 1
            if n > 4:
                break

    elif node.id == "pz_secret_code":
        instruction_key = "Decode the secret words using the number key."
        code = puzzles.build_secret_code([v.term for v in vocab[:5]])
        if code is None:
            return None
        items.append({"key_table": code.key})
        for i, entry in enumerate(code.encoded, 1):
            items.append({"number": i, "code": entry["code"], "lines": 0})
            solutions.append({"number": i, "answer": entry["answer"]})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_localize(instruction_key, text.source_lang),
        items=items,
        solution=solutions,
    )


# ---------------------------------------------------------------------------
# Text-analysis generators
# ---------------------------------------------------------------------------

def _misspell(word: str, rng: random.Random) -> str | None:
    """Swap two adjacent inner letters — a plausible spelling error."""
    letters = list(word)
    positions = [i for i in range(1, len(letters) - 2)
                 if letters[i].isalpha() and letters[i + 1].isalpha()
                 and letters[i].lower() != letters[i + 1].lower()]
    if not positions:
        return None
    i = rng.choice(positions)
    letters[i], letters[i + 1] = letters[i + 1], letters[i]
    return "".join(letters)


def _generate_text_analysis(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    items: list[dict] = []
    solutions: list[dict] = []
    instruction = ""

    if node.id == "ta_error_correction":
        instruction = _localize("Each sentence contains one spelling mistake. "
                                "Underline it and write the correct word.",
                                text.source_lang)
        rng = random.Random(len(text.content))
        targets = _pick_blank_targets(text, count=6)
        n = 1
        for sentence, word in targets:
            clean = re.sub(r"[.,;:!?]", "", word)
            wrong = _misspell(clean, rng)
            if not wrong:
                continue
            items.append({"number": n,
                          "task": sentence.replace(clean, wrong, 1),
                          "lines": 1})
            solutions.append({"number": n, "answer": f"{wrong} → {clean}"})
            n += 1
        if not items:
            return None

    elif node.id == "ta_word_marking":
        if not text.vocabulary:
            return None
        by_pos: dict[str, list[VocabularyItem]] = {}
        for v in text.vocabulary.items:
            by_pos.setdefault(v.pos, []).append(v)
        pos = max(by_pos, key=lambda p: len(by_pos[p])) if by_pos else None
        if pos not in ("noun", "verb", "adjective"):
            return None
        instruction = _localize(f"Read the text and underline all {pos}s.",
                                text.source_lang)
        para = text.paragraphs[0] if text.paragraphs else ""
        if not para:
            return None
        items.append({"box": para})
        stems = [puzzles.clean_word(v.term).lower() for v in by_pos[pos]]
        matches = sorted({
            re.sub(r"[.,;:!?]", "", w)
            for w in para.split()
            if re.sub(r"[.,;:!?]", "", w).lower() in stems
        })
        if matches:
            solutions.append({"note": ", ".join(matches)})

    elif node.id == "ta_translation":
        instruction = _localize("Translate the sentences into your native language.",
                                text.source_lang)
        sentences = _sentences(text)[:5]
        if not sentences:
            return None
        for i, s in enumerate(sentences, 1):
            items.append({"number": i, "task": s, "lines": 1})

    elif node.id == "ta_transformation":
        instruction = _localize("Rewrite the first paragraph of the text in the "
                                "past tense.", text.source_lang)
        para = text.paragraphs[0] if text.paragraphs else ""
        if not para:
            return None
        items.append({"box": para})
        items.append({"lines": max(4, len(para) // 70 + 2)})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
        solution=solutions,
    )


# ---------------------------------------------------------------------------
# Writing generators
# ---------------------------------------------------------------------------

def _generate_writing(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    vocab = _pick_vocab(text, 8)
    bank = [puzzles.clean_word(v.term) or v.term for v in vocab[:6]]
    items: list[dict] = []
    resource: dict = {}
    instruction = ""

    if node.id == "wr_creative":
        instruction = _localize("Write a short text about the topic. Use at "
                                "least five words from the word bank.", lang)
        items.append({"bank": bank})
        items.append({"lines": 8})

    elif node.id == "wr_acrostic":
        instruction = _localize("Write an acrostic poem: each line begins with "
                                "the letter on the left.", lang)
        word = ""
        for v in vocab:
            candidate = puzzles.clean_word(v.term).upper()
            if 5 <= len(candidate) <= 9:
                word = candidate
                break
        if not word:
            word = puzzles.clean_word(_topic_label(text)).upper()[:8]
        if len(word) < 3:
            return None
        items.append({"acrostic": list(word)})

    elif node.id == "wr_letter":
        instruction = _localize("Write a letter about the topic. Follow the "
                                "structure.", lang)
        for section, lines in (("Greeting", 1), ("Introduction", 2),
                               ("Main part", 4), ("Closing", 1), ("Signature", 1)):
            items.append({"label": _localize(section, lang), "lines": lines})

    elif node.id == "wr_diary":
        instruction = _localize("Write a diary entry about a day connected to "
                                "the topic. Use at least four words from the "
                                "word bank.", lang)
        items.append({"bank": bank[:5]})
        items.append({"lines": 8})

    elif node.id == "wr_headline":
        instruction = _localize("Read the facts and write a newspaper headline "
                                "and a short lead paragraph.", lang)
        facts = " ".join(_sentences(text)[:2])
        items.append({"label": _localize("Facts", lang)})
        items.append({"box": facts})
        items.append({"label": _localize("Headline:", lang), "lines": 1})
        items.append({"label": _localize("Lead paragraph:", lang), "lines": 3})

    elif node.id == "wr_review":
        instruction = _localize("Write a review. Colour in the stars and "
                                "explain your opinion.", lang)
        resource = _resource_for(node, text)
        items.append({"label": _localize("Title:", lang), "lines": 1})
        items.append({"label": _localize("Rating:", lang), "stars": 5})
        items.append({"label": _localize("Summary:", lang), "lines": 3})
        items.append({"label": _localize("My opinion:", lang), "lines": 3})
        items.append({"label": _localize("Recommendation:", lang), "lines": 2})

    elif node.id == "wr_postcard":
        instruction = _localize("Write a postcard to a friend about the topic.", lang)
        items.append({"postcard": {"message_lines": 6, "address_lines": 3}})

    elif node.id == "wr_opinion":
        instruction = _localize("Collect arguments for and against, then write "
                                "your own opinion.", lang)
        statement = localize_fmt(
            "“{topic} plays a bigger role in our lives today than ever before.”",
            lang, topic=_topic_label(text).capitalize())
        items.append({"label": _localize("Statement:", lang)})
        items.append({"box": statement})
        items.append({"table": {
            "headers": [_localize("Arguments for", lang),
                        _localize("Arguments against", lang)],
            "rows": [["", ""], ["", ""], ["", ""]],
            "row_height": 10,
        }})
        items.append({"label": _localize("My opinion:", lang), "lines": 4})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
        resource=resource,
    )


# ---------------------------------------------------------------------------
# Dialogue generators
# ---------------------------------------------------------------------------

def _generate_dialogue(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    topic = _topic_label(text)
    items: list[dict] = []
    instruction = ""

    if node.id == "dlg_roleplay":
        instruction = _localize("Read the role cards and write the dialogue.", lang)
        items.append({"role_card": {
            "title": _localize("Person A", lang),
            "text": localize_fmt("You are curious about {topic} and ask lots of "
                                 "questions.", lang, topic=topic),
        }})
        items.append({"role_card": {
            "title": _localize("Person B", lang),
            "text": localize_fmt("You are an expert on {topic} and answer "
                                 "patiently.", lang, topic=topic),
        }})
        items.append({"dialogue_lines": {"speakers": ["A", "B"], "turns": 8}})

    elif node.id == "dlg_interview":
        instruction = _localize("You are interviewing an expert on the topic. "
                                "Write six questions. The question words help "
                                "you.", lang)
        items.append({"label": _localize("Question words:", lang)})
        items.append({"bank": question_words(text.target_lang)})
        for i in range(1, 7):
            items.append({"number": i, "task": "", "lines": 1})

    elif node.id == "dlg_comic":
        instruction = _localize("Draw a four-panel comic about the topic and "
                                "fill in the speech bubbles.", lang)
        items.append({"frames": {"count": 4, "per_row": 2, "caption_lines": 1}})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
    )


# ---------------------------------------------------------------------------
# Media generators (QR codes from the culture library)
# ---------------------------------------------------------------------------

def _generate_media(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    resource = _resource_for(node, text)
    vocab = _pick_vocab(text, 8)
    bank = [puzzles.clean_word(v.term) or v.term for v in vocab]
    items: list[dict] = []
    instruction = ""

    if node.id == "media_podcast":
        instruction = _localize("Scan the QR code and listen to one episode. "
                                "Then complete the tasks.", lang)
        items.append({"task": _localize("Before listening: which five words do "
                                        "you expect to hear? Write them down.",
                                        lang), "lines": 2})
        items.append({"task": _localize("While listening: note three new words.",
                                        lang), "lines": 2})
        items.append({"task": _localize("After listening: summarize the episode "
                                        "in three sentences.", lang), "lines": 3})

    elif node.id == "media_video":
        instruction = _localize("Scan the QR code and watch one video. Then "
                                "complete the tasks.", lang)
        items.append({"task": _localize("Tick the words from the word bank that "
                                        "you hear.", lang)})
        items.append({"checkboxes": bank[:8]})
        items.append({"task": _localize("What is the video about? Write two "
                                        "sentences.", lang), "lines": 2})
        items.append({"task": _localize("Would you recommend it? Why (not)?",
                                        lang), "lines": 2})

    elif node.id == "media_music":
        instruction = _localize("Scan the QR code and listen to a song by this "
                                "artist. Then complete the tasks.", lang)
        items.append({"task": _localize("Which song did you choose? Write down "
                                        "the title.", lang), "lines": 1})
        items.append({"task": _localize("What is the song about?", lang),
                      "lines": 2})
        items.append({"task": _localize("Write down one line you like and "
                                        "translate it.", lang), "lines": 2})

    elif node.id == "media_film":
        instruction = _localize("Scan the QR code and watch a trailer or an "
                                "episode. Then complete the tasks.", lang)
        items.append({"task": _localize("Who are the main characters?", lang),
                      "lines": 2})
        items.append({"task": _localize("Where does the story take place?", lang),
                      "lines": 1})
        items.append({"task": _localize("Would you like to watch more? Why (not)?",
                                        lang), "lines": 2})

    elif node.id == "media_news":
        instruction = _localize("Scan the QR code, choose one article and read "
                                "it. Then complete the tasks.", lang)
        items.append({"task": _localize("Which article did you choose? Write "
                                        "the headline in your own words.", lang),
                      "lines": 1})
        items.append({"task": _localize("Note three new words and their "
                                        "translations.", lang)})
        items.append({"table": {
            "headers": [_localize("Word", lang), "→", ""],
            "rows": [["", "→", ""], ["", "→", ""], ["", "→", ""]],
            "row_height": 8,
        }})
        items.append({"task": _localize("Summarize the article in two sentences.",
                                        lang), "lines": 2})

    elif node.id == "media_radio":
        instruction = _localize("Scan the QR code and listen to the radio for "
                                "five minutes. Then complete the tasks.", lang)
        items.append({"task": _localize("Which station or programme are you "
                                        "listening to?", lang), "lines": 1})
        items.append({"task": _localize("Make a tally mark every time you "
                                        "recognize one of these words:", lang)})
        items.append({"checkboxes": bank[:6]})
        items.append({"task": _localize("What kind of programme is it (news, "
                                        "music, talk)?", lang), "lines": 1})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
        resource=resource,
    )


# ---------------------------------------------------------------------------
# Social-media generators
# ---------------------------------------------------------------------------

def _generate_social(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    vocab = _pick_vocab(text, 8)
    items: list[dict] = []
    instruction = ""

    if node.id == "soc_chat":
        instruction = _localize("Write a chat conversation about the topic. "
                                "Fill in both sides.", lang)
        items.append({"box": localize_fmt(
            "Situation: Two friends are making plans connected to {topic}.",
            lang, topic=_topic_label(text))})
        items.append({"bank": [puzzles.clean_word(v.term) or v.term
                               for v in vocab[:4]]})
        items.append({"chat": 8})

    elif node.id == "soc_comments":
        instruction = _localize("Read the post and write three replies.", lang)
        post_text = " ".join(_sentences(text)[:2])
        items.append({"post": {"author": "@lang_daily", "text": post_text}})
        items.append({"reply": {"label": _localize("Reply 1 — agree:", lang),
                                "lines": 2}})
        items.append({"reply": {"label": _localize("Reply 2 — ask a question:",
                                                   lang), "lines": 2}})
        items.append({"reply": {"label": _localize("Reply 3 — share your own "
                                                   "experience:", lang),
                                "lines": 2}})

    elif node.id == "soc_micro_post":
        instruction = _localize("Summarize the text in one social media post "
                                "(max. 280 characters) and add three hashtags.",
                                lang)
        items.append({"label": _localize("Your post:", lang), "lines": 4})
        hashtags = [h for h in (_hashtag(v.term) for v in vocab) if h][:5]
        if hashtags:
            items.append({"bank": hashtags})
        items.append({"label": _localize("Your hashtags:", lang), "lines": 1})

    elif node.id == "soc_caption":
        instruction = _localize("Write a caption and hashtags for each photo.",
                                lang)
        photos: list[str] = []
        if text.picture_scene and text.picture_scene.elements:
            elems = text.picture_scene.elements
            photos = [", ".join(elems[i:i + 2]) for i in range(0, min(6, len(elems)), 2)]
        if not photos:
            photos = [v.term for v in vocab[:3]]
        for i, photo in enumerate(photos[:3], 1):
            items.append({"number": i,
                          "task": f"{_localize('Photo:', lang)} [{photo}]"})
            items.append({"label": _localize("Caption:", lang), "lines": 2})

    elif node.id == "soc_storyboard":
        instruction = _localize("Plan a five-frame story about the topic: "
                                "sketch each frame and write a caption.", lang)
        items.append({"frames": {"count": 5, "per_row": 5, "caption_lines": 1,
                                 "frame_label": _localize("Frame", lang)}})

    elif node.id == "soc_video_script":
        instruction = _localize("Write the script for a 30-second video about "
                                "the topic.", lang)
        items.append({"bank": [puzzles.clean_word(v.term) or v.term
                               for v in vocab[:3]]})
        items.append({"label": _localize("Hook (0–5 seconds):", lang), "lines": 2})
        items.append({"label": _localize("Main part (5–25 seconds):", lang),
                      "lines": 4})
        items.append({"label": _localize("Call to action (25–30 seconds):", lang),
                      "lines": 2})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
    )


# ---------------------------------------------------------------------------
# Real-world generators
# ---------------------------------------------------------------------------

def _generate_real_world(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    items: list[dict] = []
    instruction = ""

    if node.id == "rw_how_to":
        instruction = _localize("Explain step by step how to do something "
                                "connected to the topic. The connector words "
                                "help you.", lang)
        items.append({"label": _localize("Connector words:", lang)})
        items.append({"bank": connector_words(text.target_lang)})
        for i in range(1, 7):
            items.append({"number": i, "task": "", "lines": 1})

    elif node.id == "rw_shopping_list":
        instruction = _localize("Complete the shopping list with quantities and "
                                "prices, then add two items of your own.", lang)
        vocab = _pick_vocab(text, 20, pos="noun")
        preferred = [v for v in vocab if v.semantic_type
                     and v.semantic_type.value in ("food", "drink", "clothing",
                                                   "furniture")]
        chosen = (preferred + [v for v in vocab if v not in preferred])[:5]
        if not chosen:
            return None
        rows = [[v.term, "", ""] for v in chosen] + [["", "", ""], ["", "", ""]]
        items.append({"table": {
            "headers": [_localize("Item", lang), _localize("Quantity", lang),
                        _localize("Price", lang)],
            "rows": rows,
            "row_height": 8,
        }})

    elif node.id == "rw_week_planner":
        instruction = _localize("Fill in the weekly planner: write one activity "
                                "for each day.", lang)
        rows = [[day, ""] for day in day_names(text.target_lang)]
        items.append({"table": {
            "headers": [_localize("Day", lang), _localize("Activity", lang)],
            "rows": rows,
            "row_height": 9,
        }})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
    )


# ---------------------------------------------------------------------------
# Numbers generators
# ---------------------------------------------------------------------------

_DEFAULT_NUMBERS = [3, 12, 25, 48, 100, 250, 1000]
_CLOCK_TIMES = ["07:15", "09:30", "12:00", "16:45", "20:05", "21:50"]


def _generate_numbers(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    items: list[dict] = []
    solutions: list[dict] = []
    instruction = ""

    if node.id == "num_write_words":
        instruction = _localize("Write the numbers as words.", lang)
        found = [int(m) for m in re.findall(r"\b\d{1,4}\b", text.content)]
        numbers: list[int] = []
        for n in found + _DEFAULT_NUMBERS:
            if n not in numbers:
                numbers.append(n)
            if len(numbers) >= 6:
                break
        for i, n in enumerate(numbers, 1):
            items.append({"number": i, "task": str(n), "lines": 1})

    elif node.id == "num_clock":
        instruction = _localize("Write the time shown on each clock in words.",
                                lang)
        for i, t in enumerate(_CLOCK_TIMES[:4], 1):
            items.append({"number": i, "clock": t, "lines": 1})
            solutions.append({"number": i, "answer": t})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
        solution=solutions,
    )


# ---------------------------------------------------------------------------
# Study-tool generators
# ---------------------------------------------------------------------------

def _generate_study(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    lang = text.source_lang
    items: list[dict] = []
    instruction = ""

    if node.id == "st_flashcards":
        vocab = _pick_vocab(text, 12)
        if not vocab:
            return None
        instruction = _localize("Cut out the flashcards along the dashed lines "
                                "and practise regularly.", lang)
        items.append({"cards": [{"front": v.term, "back": v.translation}
                                for v in vocab]})

    elif node.id == "st_dictation":
        vocab = sorted(_pick_vocab(text, 20),
                       key=lambda v: -len(puzzles.clean_word(v.term)))[:6]
        if not vocab:
            return None
        instruction = _localize("Copy each word twice, then cover the word and "
                                "write it from memory.", lang)
        items.append({"table": {
            "headers": [_localize("Word", lang), _localize("Practice 1", lang),
                        _localize("Practice 2", lang),
                        _localize("From memory", lang)],
            "rows": [[v.term, "", "", ""] for v in vocab],
            "row_height": 8,
        }})

    elif node.id == "st_reflection":
        instruction = _localize("Think about this worksheet and complete the "
                                "sentences.", lang)
        items.append({"task": _localize("Three new words I learned:", lang),
                      "lines": 3})
        items.append({"task": _localize("Two things I found difficult:", lang),
                      "lines": 2})
        items.append({"task": _localize("One thing I want to review:", lang),
                      "lines": 1})
        items.append({"tip": _localize("Done? Take a photo of your worksheet "
                                       "and upload it to an AI assistant for "
                                       "feedback!", lang)})

    if not items:
        return None
    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
    )
