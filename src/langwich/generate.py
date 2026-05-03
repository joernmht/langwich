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

from langwich.graph import ExerciseNode, ExerciseType, VocabularyItem
from langwich.text import SourceText


# ---------------------------------------------------------------------------
# Instruction localization
# ---------------------------------------------------------------------------

_INSTRUCTION_TRANSLATIONS: dict[str, dict[str, str]] = {
    "de": {
        "Fill in the blanks using the words from the word bank.": "Fülle die Lücken mit den Wörtern aus der Wortbank aus.",
        "Fill in the blanks. The first letter is given.": "Fülle die Lücken aus. Der erste Buchstabe ist angegeben.",
        "Choose the correct word for each blank.": "Wähle das richtige Wort für jede Lücke.",
        "Fill in the blanks. The translation is given as a hint.": "Fülle die Lücken aus. Die Übersetzung ist als Hinweis angegeben.",
        "Fill in the correct form of the word in parentheses.": "Setze die richtige Form des Wortes in Klammern ein.",
        "Fill in the blanks from memory.": "Fülle die Lücken aus dem Gedächtnis aus.",
        "Fill in the blanks using the translation as reference.": "Fülle die Lücken mithilfe der Übersetzung aus.",
        "Look at the picture and answer the color questions.": "Sieh dir das Bild an und beantworte die Farbfragen.",
        "Find and circle the following elements in the picture.": "Finde und kreise die folgenden Elemente im Bild ein.",
        "Describe the position of the objects using prepositions.": "Beschreibe die Position der Gegenstände mit Präpositionen.",
        "Describe the picture in your own words.": "Beschreibe das Bild in eigenen Worten.",
        "Fill in the blanks using what you see in the picture.": "Fülle die Lücken anhand des Bildes aus.",
        "Complete the picture task.": "Bearbeite die Bildaufgabe.",
        "Find the synonym for each word.": "Finde das Synonym für jedes Wort.",
        "Find the antonym (opposite) for each word.": "Finde das Antonym (Gegenteil) für jedes Wort.",
        "Sort the words into the correct categories.": "Ordne die Wörter den richtigen Kategorien zu.",
        "Connect the word parts to form compound words.": "Verbinde die Wortteile zu zusammengesetzten Wörtern.",
        "Complete the word connections.": "Vervollständige die Wortverbindungen.",
        "Fill in the blanks.": "Fülle die Lücken aus.",
    },
    "fr": {
        "Fill in the blanks using the words from the word bank.": "Remplis les blancs avec les mots de la banque de mots.",
        "Fill in the blanks. The first letter is given.": "Remplis les blancs. La première lettre est donnée.",
        "Choose the correct word for each blank.": "Choisis le mot correct pour chaque blanc.",
        "Fill in the blanks. The translation is given as a hint.": "Remplis les blancs. La traduction est donnée comme indice.",
        "Fill in the correct form of the word in parentheses.": "Écris la forme correcte du mot entre parenthèses.",
        "Fill in the blanks from memory.": "Remplis les blancs de mémoire.",
        "Fill in the blanks using the translation as reference.": "Remplis les blancs en utilisant la traduction comme référence.",
        "Look at the picture and answer the color questions.": "Regarde l'image et réponds aux questions sur les couleurs.",
        "Find and circle the following elements in the picture.": "Trouve et entoure les éléments suivants dans l'image.",
        "Describe the position of the objects using prepositions.": "Décris la position des objets en utilisant des prépositions.",
        "Describe the picture in your own words.": "Décris l'image avec tes propres mots.",
        "Fill in the blanks using what you see in the picture.": "Remplis les blancs en utilisant ce que tu vois dans l'image.",
        "Complete the picture task.": "Complète l'exercice sur l'image.",
        "Find the synonym for each word.": "Trouve le synonyme de chaque mot.",
        "Find the antonym (opposite) for each word.": "Trouve l'antonyme (le contraire) de chaque mot.",
        "Sort the words into the correct categories.": "Classe les mots dans les bonnes catégories.",
        "Connect the word parts to form compound words.": "Relie les parties de mots pour former des mots composés.",
        "Complete the word connections.": "Complète les associations de mots.",
        "Fill in the blanks.": "Remplis les blancs.",
    },
    "es": {
        "Fill in the blanks using the words from the word bank.": "Rellena los huecos con las palabras del banco de palabras.",
        "Fill in the blanks. The first letter is given.": "Rellena los huecos. Se da la primera letra.",
        "Choose the correct word for each blank.": "Elige la palabra correcta para cada hueco.",
        "Fill in the blanks. The translation is given as a hint.": "Rellena los huecos. La traducción se da como pista.",
        "Fill in the correct form of the word in parentheses.": "Escribe la forma correcta de la palabra entre paréntesis.",
        "Fill in the blanks from memory.": "Rellena los huecos de memoria.",
        "Fill in the blanks using the translation as reference.": "Rellena los huecos usando la traducción como referencia.",
        "Look at the picture and answer the color questions.": "Mira la imagen y responde las preguntas sobre colores.",
        "Find and circle the following elements in the picture.": "Encuentra y rodea los siguientes elementos en la imagen.",
        "Describe the position of the objects using prepositions.": "Describe la posición de los objetos usando preposiciones.",
        "Describe the picture in your own words.": "Describe la imagen con tus propias palabras.",
        "Fill in the blanks using what you see in the picture.": "Rellena los huecos usando lo que ves en la imagen.",
        "Complete the picture task.": "Completa la tarea de imagen.",
        "Find the synonym for each word.": "Encuentra el sinónimo de cada palabra.",
        "Find the antonym (opposite) for each word.": "Encuentra el antónimo (opuesto) de cada palabra.",
        "Sort the words into the correct categories.": "Clasifica las palabras en las categorías correctas.",
        "Connect the word parts to form compound words.": "Conecta las partes de palabras para formar palabras compuestas.",
        "Complete the word connections.": "Completa las conexiones de palabras.",
        "Fill in the blanks.": "Rellena los huecos.",
    },
}

_LANG_NAMES: dict[str, dict[str, str]] = {
    "en": {"de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "en": "English"},
    "de": {"de": "deutsche", "fr": "französische", "es": "spanische", "it": "italienische", "pt": "portugiesische", "en": "englische"},
    "fr": {"de": "allemand", "fr": "français", "es": "espagnol", "it": "italien", "pt": "portugais", "en": "anglais"},
    "es": {"de": "alemán", "fr": "francés", "es": "español", "it": "italiano", "pt": "portugués", "en": "inglés"},
}


def _localize(en_text: str, source_lang: str) -> str:
    if source_lang == "en":
        return en_text
    lang_table = _INSTRUCTION_TRANSLATIONS.get(source_lang)
    if lang_table:
        return lang_table.get(en_text, en_text)
    return en_text


def _lang_name(lang_code: str, in_language: str) -> str:
    names = _LANG_NAMES.get(in_language, _LANG_NAMES["en"])
    return names.get(lang_code, lang_code)


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


def generate_exercise(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    """Generate a concrete exercise instance from a node + text."""
    etype = node.exercise_type
    if etype == ExerciseType.FILL_IN_BLANKS:
        return _generate_fib(node, text)
    elif etype == ExerciseType.PICTURE_INTERACTION:
        return _generate_picture(node, text)
    elif etype == ExerciseType.WORD_CONNECTIONS:
        return _generate_word_connections(node, text)
    return None


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
        color_vocab = []
        if text.vocabulary:
            color_vocab = [v for v in text.vocabulary.items
                          if v.semantic_type and v.semantic_type.value == "color"]
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
        random.shuffle(all_words)
        items = [{"words": all_words, "categories": list(categories.keys())}]
        solutions = [{"category": k, "words": [_strip_article(v.term) for v in vs]}
                     for k, vs in categories.items()]

    elif node.id == "wc_compound":
        pass

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
