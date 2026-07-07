"""Exercise generation from a SourceText using the exercise graph.

The text is the gold mine. This module extracts exercise content from it:
- FIB: blank out words, produce hints
- Picture: reference picture_scene elements
- WordConnections: pair vocabulary items
- Media: link-free search & research tasks around the topic

A GenerationSession is shared across all exercises of one worksheet so
that different variants draw *different* sentences and words from the
text instead of repeating the same material.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from langwich.graph import ExerciseNode, ExerciseType, SemanticType, VocabularyItem
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

# Language names as nouns ("auf Deutsch", "in French"), keyed by the language
# the sentence is written in, then by the language being named.
_LANG_NOUNS: dict[str, dict[str, str]] = {
    "en": {"de": "German", "fr": "French", "es": "Spanish", "it": "Italian", "pt": "Portuguese", "en": "English"},
    "de": {"de": "Deutsch", "fr": "Französisch", "es": "Spanisch", "it": "Italienisch", "pt": "Portugiesisch", "en": "Englisch"},
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


def _lang_noun(lang_code: str, in_language: str) -> str:
    names = _LANG_NOUNS.get(in_language, _LANG_NOUNS["en"])
    return names.get(lang_code, lang_code)


@dataclass
class GenerationSession:
    """Shared state across all exercises of one worksheet.

    Tracks which sentences and words have already been blanked so that
    each FIB variant pulls fresh material from the text instead of
    blanking the same six sentences again and again.
    """

    used_sentences: set[str] = field(default_factory=set)
    used_words: set[str] = field(default_factory=set)


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
    context_text: str = ""  # reference text shown in a box (translation, search ideas)


def generate_exercise(
    node: ExerciseNode,
    text: SourceText,
    session: GenerationSession | None = None,
) -> ExerciseInstance | None:
    """Generate a concrete exercise instance from a node + text.

    Pass the same ``session`` for every exercise of a worksheet so the
    variants draw different sentences and words from the text.
    """
    if session is None:
        session = GenerationSession()
    etype = node.exercise_type
    if etype == ExerciseType.FILL_IN_BLANKS:
        return _generate_fib(node, text, session)
    elif etype == ExerciseType.PICTURE_INTERACTION:
        return _generate_picture(node, text)
    elif etype == ExerciseType.WORD_CONNECTIONS:
        return _generate_word_connections(node, text)
    elif etype == ExerciseType.MEDIA:
        return _generate_media(node, text)
    return None


# ---------------------------------------------------------------------------
# Text mining helpers
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[.,;:!?()\"'„“”«»–—]")


def _clean_token(token: str) -> str:
    return _PUNCT_RE.sub("", token)


def _strip_article(term: str) -> str:
    for article in ("der ", "die ", "das ", "ein ", "eine ",
                    "le ", "la ", "les ", "l'", "un ", "une ",
                    "el ", "los ", "las ", "un ", "una ",
                    "the ", "a ", "an "):
        if term.lower().startswith(article):
            return term[len(article):]
    return term


def _sentences(text: SourceText) -> list[str]:
    result = []
    for para in text.paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+", para):
            if sentence.strip():
                result.append(sentence.strip())
    return result


def _token_matches_stem(token_lower: str, stem_lower: str) -> bool:
    """Exact match plus light inflection (plural -n/-en/-e/-s)."""
    if token_lower == stem_lower:
        return True
    return any(token_lower == stem_lower + suffix for suffix in ("n", "en", "e", "s"))


def _blank_candidates(text: SourceText) -> list[tuple[str, str, VocabularyItem]]:
    """All (sentence, token, vocab item) triples where a vocabulary word
    appears in a sentence, in text order."""
    if not text.vocabulary or not text.vocabulary.items:
        return []

    by_stem = {}
    for v in text.vocabulary.items:
        stem = _strip_article(v.term).lower()
        if len(stem) > 2:
            by_stem[stem] = v

    results: list[tuple[str, str, VocabularyItem]] = []
    for sentence in _sentences(text):
        seen_in_sentence: set[str] = set()
        for token in sentence.split():
            clean = _clean_token(token).lower()
            if len(clean) <= 2 or clean in seen_in_sentence:
                continue
            # An exact stem match beats an inflection match ('ernten' is the
            # verb 'ernten', not the plural of 'die Ernte').
            item = by_stem.get(clean) or next(
                (i for stem, i in by_stem.items()
                 if _token_matches_stem(clean, stem)), None)
            if item is not None:
                results.append((sentence, token, item))
                seen_in_sentence.add(clean)
    return results


def _pick_blank_targets(
    text: SourceText,
    session: GenerationSession,
    count: int = 6,
) -> list[tuple[str, str, VocabularyItem]]:
    """Pick (sentence, token, vocab item) targets, preferring material the
    current worksheet has not used yet.

    Preference order: fresh sentence + fresh word, then fresh sentence,
    then fresh word, then anything — so repetition only appears once the
    text is exhausted.
    """
    candidates = _blank_candidates(text)

    def tier(c: tuple[str, str, VocabularyItem]) -> int:
        sentence_used = c[0] in session.used_sentences
        word_used = _clean_token(c[1]).lower() in session.used_words
        if not sentence_used and not word_used:
            return 0
        if not sentence_used:
            return 1
        if not word_used:
            return 2
        return 3

    picked: list[tuple[str, str, VocabularyItem]] = []
    picked_sentences: set[str] = set()
    for wanted_tier in range(4):
        for c in candidates:
            if len(picked) >= count:
                break
            if c[0] in picked_sentences or tier(c) != wanted_tier:
                continue
            picked.append(c)
            picked_sentences.add(c[0])
        if len(picked) >= count:
            break

    for sentence, token, _ in picked:
        session.used_sentences.add(sentence)
        session.used_words.add(_clean_token(token).lower())
    return picked


def _blank_out(sentence: str, token: str) -> str:
    """Replace the word inside ``token`` with a blank, keeping punctuation."""
    clean = _clean_token(token)
    if clean:
        blanked, n = re.subn(re.escape(clean), "______", sentence, count=1)
        if n:
            return blanked
    return sentence.replace(token, "______", 1)


def _pick_verb_targets(
    text: SourceText,
    session: GenerationSession,
    count: int = 6,
) -> list[tuple[str, str, str]]:
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

    for sentence in _sentences(text):
        for word in sentence.split():
            clean = _clean_token(word).lower()
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

    for sentence, _, _ in results[:count]:
        session.used_sentences.add(sentence)
    return results[:count]


# ---------------------------------------------------------------------------
# FIB generators
# ---------------------------------------------------------------------------

def _generate_fib(
    node: ExerciseNode, text: SourceText, session: GenerationSession
) -> ExerciseInstance:
    # Base form variant: only blank verbs and always provide the infinitive
    if node.hint_type == "base_form":
        return _generate_fib_base_form(node, text, session)

    targets = _pick_blank_targets(text, session)
    items: list[dict] = []
    solutions: list[dict] = []
    bank_words: list[str] = []
    context_text = ""

    for i, (sentence, token, vocab_item) in enumerate(targets, 1):
        blanked = _blank_out(sentence, token)
        clean = _clean_token(token)

        item: dict = {"number": i, "sentence": blanked}

        if node.hint_type == "first_letter":
            item["hint"] = clean[0] + "______"
        elif node.hint_type == "multiple_choice":
            distractors = _get_distractors(clean, text, pos=vocab_item.pos)
            options = [clean] + distractors[:2]
            random.shuffle(options)
            item["choices"] = options
        elif node.hint_type == "translation":
            item["hint"] = f"({vocab_item.translation})"

        bank_words.append(clean)
        items.append(item)
        solutions.append({"number": i, "answer": clean})

    # Full-translation variant: show the translation once as a reference box
    # instead of repeating whole paragraphs under every item.
    if node.hint_type == "full_translation" and text.translation:
        context_text = text.translation

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
        context_text=context_text,
    )


def _generate_fib_base_form(
    node: ExerciseNode, text: SourceText, session: GenerationSession
) -> ExerciseInstance:
    """FIB variant that blanks inflected verbs and gives the infinitive as hint."""
    targets = _pick_verb_targets(text, session)
    items: list[dict] = []
    solutions: list[dict] = []

    for i, (sentence, inflected, base) in enumerate(targets, 1):
        blanked = _blank_out(sentence, inflected)
        items.append({
            "number": i,
            "sentence": f"{blanked}  ({base})",
        })
        solutions.append({"number": i, "answer": _clean_token(inflected)})

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


def _get_distractors(word: str, text: SourceText, pos: str | None = None) -> list[str]:
    if not text.vocabulary:
        return []
    candidates = [v for v in text.vocabulary.items
                  if _strip_article(v.term).lower() != word.lower()]
    # Prefer distractors of the same part of speech — mixing a verb and a
    # preposition into a noun blank gives the answer away.
    same_pos = [v for v in candidates if pos and v.pos == pos]
    pool = same_pos if len(same_pos) >= 2 else candidates
    terms = [_strip_article(v.term) for v in pool]
    random.shuffle(terms)
    return terms[:3]


# ---------------------------------------------------------------------------
# Picture generators
# ---------------------------------------------------------------------------

# Per-target-language templates: these strings appear on the worksheet in the
# language being learned (the header instruction, in the learner's native
# language, explains the task).
_PICTURE_TEMPLATES: dict[str, dict[str, str]] = {
    "de": {
        "color_q": "Welche Farbe hat {obj}?",
        "color_a": "{obj} ist {color}.",
        "position_q": "Wo befindet sich {obj} im Bild?",
        "mark": "Kreise „{elem}“ im Bild ein!",
        "object_label": "Gegenstand {num}",
        "scene": "Beschreibe das Bild in 4-6 Sätzen. "
                 "Verwende dabei mindestens 3 Präpositionen ({preps}).",
    },
    "fr": {
        "color_q": "De quelle couleur est {obj} ?",
        "color_a": "{obj} est {color}.",
        "position_q": "Où se trouve {obj} sur l'image ?",
        "mark": "Entoure « {elem} » sur l'image !",
        "object_label": "Objet {num}",
        "scene": "Décris l'image en 4 à 6 phrases. "
                 "Utilise au moins 3 prépositions ({preps}).",
    },
    "es": {
        "color_q": "¿De qué color es {obj}?",
        "color_a": "{obj} es {color}.",
        "position_q": "¿Dónde está {obj} en la imagen?",
        "mark": "¡Rodea «{elem}» en la imagen!",
        "object_label": "Objeto {num}",
        "scene": "Describe la imagen en 4-6 frases. "
                 "Usa al menos 3 preposiciones ({preps}).",
    },
    "en": {
        "color_q": "What color is {obj}?",
        "color_a": "{obj} is {color}.",
        "position_q": "Where is {obj} in the picture?",
        "mark": "Circle “{elem}” in the picture!",
        "object_label": "Object {num}",
        "scene": "Describe the picture in 4-6 sentences. "
                 "Use at least 3 prepositions ({preps}).",
    },
}

_DEFAULT_PREPOSITIONS: dict[str, str] = {
    "de": "neben, vor, durch, an",
    "fr": "à côté de, devant, sur, derrière",
    "es": "junto a, delante de, sobre, detrás de",
    "en": "next to, in front of, through, behind",
}


def _pic_templates(target_lang: str) -> dict[str, str]:
    return _PICTURE_TEMPLATES.get(target_lang, _PICTURE_TEMPLATES["en"])


def _vocab_by_semantic(text: SourceText, st: SemanticType) -> list[VocabularyItem]:
    if not text.vocabulary:
        return []
    return [v for v in text.vocabulary.items if v.semantic_type == st]


def _article_form(noun: str, text: SourceText) -> str:
    """Return the vocabulary form with article for a bare noun, if known
    (e.g. 'Tasse' -> 'die Tasse', plural 'fauteuils' -> 'le fauteuil')."""
    if text.vocabulary:
        for v in text.vocabulary.items:
            if _token_matches_stem(noun.lower(), _strip_article(v.term).lower()):
                return v.term
    return noun


def _color_stems(text: SourceText) -> list[str]:
    return [_strip_article(v.term)
            for v in _vocab_by_semantic(text, SemanticType.COLOR)
            if len(_strip_article(v.term)) >= 3]


def _element_noun(elem: str, text: SourceText) -> str:
    """The noun of a scene element, ignoring color adjectives regardless of
    adjective position ('weiße Tasse' -> 'Tasse', 'fauteuils rouges' ->
    'fauteuils')."""
    stems = [c.lower() for c in _color_stems(text)]
    tokens = [t for t in elem.split()
              if not any(t.lower().startswith(s) for s in stems)]
    if not tokens:
        tokens = elem.split()
    return tokens[-1]


def _derive_color_pairs(text: SourceText) -> list[tuple[str, str]]:
    """Derive (object, color) pairs by matching color vocabulary against the
    picture scene elements (e.g. 'weiße Tasse' -> ('die Tasse', 'weiß'))."""
    if not text.picture_scene:
        return []
    colors = _vocab_by_semantic(text, SemanticType.COLOR)
    pairs: list[tuple[str, str]] = []
    for elem in text.picture_scene.elements:
        tokens = elem.split()
        for v in colors:
            stem = _strip_article(v.term)
            if len(stem) < 3:
                continue
            match = next((t for t in tokens if t.lower().startswith(stem.lower())), None)
            if match is None:
                continue
            noun = " ".join(t for t in tokens if t is not match) or elem
            pairs.append((_article_form(noun, text), stem))
            break
    return pairs


def _position_words(text: SourceText) -> list[str]:
    return [_strip_article(v.term).lower()
            for v in _vocab_by_semantic(text, SemanticType.POSITION)]


def _derive_position_items(text: SourceText) -> list[tuple[str, str | None]]:
    """Derive (object, sample answer sentence) pairs from the picture
    paragraph: the sample answer is the sentence that places the object."""
    scene = text.picture_scene
    pic_para = text.picture_paragraph or ""
    if not scene:
        return []
    pic_sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", pic_para) if s.strip()]
    preps = _position_words(text)

    results: list[tuple[str, str | None]] = []
    used_answers: set[str] = set()
    for elem in scene.elements:
        noun = _element_noun(elem, text)
        obj = _article_form(noun, text)
        answer = None
        for sent in pic_sentences:
            if sent in used_answers or noun.lower() not in sent.lower():
                continue
            sent_low = sent.lower()
            sent_tokens = {_clean_token(t).lower() for t in sent.split()}
            has_prep = not preps or any(
                (p in sent_low) if " " in p else (p in sent_tokens) for p in preps
            )
            if has_prep:
                answer = sent
                used_answers.add(sent)
                break
        results.append((obj, answer))

    # Objects whose position the text actually describes make better items.
    results.sort(key=lambda r: r[1] is None)
    return results


def _generate_picture(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    if not text.picture_scene:
        return None

    scene = text.picture_scene
    elements = scene.elements
    t = _pic_templates(text.target_lang)
    items: list[dict] = []
    solutions: list[dict] = []

    if node.id == "pic_color_query":
        for i, (obj, color) in enumerate(_derive_color_pairs(text)[:4], 1):
            items.append({"number": i, "question": t["color_q"].format(obj=obj)})
            solutions.append({"number": i,
                              "answer": t["color_a"].format(obj=obj, color=color)})

    elif node.id == "pic_element_marking":
        for i, elem in enumerate(elements[:5], 1):
            items.append({"number": i, "instruction": t["mark"].format(elem=elem)})

    elif node.id == "pic_position":
        derived = [d for d in _derive_position_items(text) if d[1]][:4]
        for i, (obj, answer) in enumerate(derived, 1):
            items.append({"number": i, "question": t["position_q"].format(obj=obj)})
            solutions.append({"number": i, "answer": answer})

    elif node.id == "pic_object_naming":
        for i, elem in enumerate(elements[:6], 1):
            label = t["object_label"].format(num=i)
            items.append({"number": i, "instruction": f"{label}: ___________"})
            solutions.append({"number": i, "answer": elem})

    elif node.id == "pic_scene_description":
        preps = ", ".join(_position_words(text)[:4]) or _DEFAULT_PREPOSITIONS.get(
            text.target_lang, _DEFAULT_PREPOSITIONS["en"])
        items.append({"instruction": t["scene"].format(preps=preps), "lines": 6})

    elif node.id == "pic_fib":
        pic_para = text.picture_paragraph
        if pic_para:
            blanked_text, answers = _blank_picture_paragraph(pic_para, text)
            if answers:
                items.append({"text": blanked_text})
                solutions = [{"answers": answers}]

    if not items:
        return None

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_picture_instruction(node, text.source_lang, text.target_lang),
        items=items,
        solution=solutions,
        picture_prompt=scene.description,
    )


def _blank_picture_paragraph(pic_para: str, text: SourceText) -> tuple[str, list[str]]:
    """Blank out scene nouns and color adjectives in the picture paragraph."""
    color_stems = [c.lower() for c in _color_stems(text)]
    element_nouns = set()
    if text.picture_scene:
        for elem in text.picture_scene.elements:
            element_nouns.add(_element_noun(elem, text).lower())

    blanked = pic_para
    answers: list[str] = []
    for token in pic_para.split():
        if len(answers) >= 5:
            break
        clean = _clean_token(token)
        low = clean.lower()
        if not clean or clean in answers:
            continue
        is_color = any(low.startswith(c) and len(c) >= 3 for c in color_stems)
        is_element = low in element_nouns
        if is_color or is_element:
            new_blanked, n = re.subn(re.escape(clean), "______", blanked, count=1)
            if n:
                blanked = new_blanked
                answers.append(clean)
    return blanked, answers


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
        if categories:
            labels = {k: _semantic_label(k, text.source_lang) for k in categories}
            items = [{"words": all_words, "categories": list(labels.values())}]
            solutions = [{"category": labels[k],
                          "words": [_strip_article(v.term) for v in vs]}
                         for k, vs in categories.items()]

    elif node.id == "wc_compound":
        pairs = _compound_pairs(text)
        if len(pairs) >= 3:
            selected = pairs[:6]
            left = [{"number": i, "term": first}
                    for i, (_, first, _) in enumerate(selected, 1)]
            right_items = list(enumerate(selected, 1))
            random.shuffle(right_items)
            right = [{"letter": chr(64 + j), "term": r[2]}
                     for j, (_, r) in enumerate(right_items, 1)]
            items = [{"left": left, "right": right, "format": "compound"}]
            solutions = [{"parts": f"{first} + {second}", "compound": compound}
                         for compound, first, second in selected]

    if not items:
        return None

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=_wc_instruction(node, text.source_lang, text.target_lang),
        items=items,
        solution=solutions,
    )


# Learner-facing names for the semantic categories, in the native language.
_SEMANTIC_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "color": "Colors", "position": "Position", "clothing": "Clothing",
        "food": "Food", "drink": "Drinks", "furniture": "Furniture",
        "body": "Body", "animal": "Animals", "profession": "Professions",
        "emotion": "Emotions", "weather": "Weather", "time": "Time",
        "other": "Other",
    },
    "de": {
        "color": "Farben", "position": "Position", "clothing": "Kleidung",
        "food": "Essen", "drink": "Getränke", "furniture": "Möbel",
        "body": "Körper", "animal": "Tiere", "profession": "Berufe",
        "emotion": "Gefühle", "weather": "Wetter", "time": "Zeit",
        "other": "Sonstiges",
    },
    "fr": {
        "color": "Couleurs", "position": "Position", "clothing": "Vêtements",
        "food": "Nourriture", "drink": "Boissons", "furniture": "Meubles",
        "body": "Corps", "animal": "Animaux", "profession": "Métiers",
        "emotion": "Émotions", "weather": "Météo", "time": "Temps",
        "other": "Autres",
    },
    "es": {
        "color": "Colores", "position": "Posición", "clothing": "Ropa",
        "food": "Comida", "drink": "Bebidas", "furniture": "Muebles",
        "body": "Cuerpo", "animal": "Animales", "profession": "Profesiones",
        "emotion": "Emociones", "weather": "Clima", "time": "Tiempo",
        "other": "Otros",
    },
}


def _semantic_label(semantic_type: str, source_lang: str) -> str:
    labels = _SEMANTIC_LABELS.get(source_lang, _SEMANTIC_LABELS["en"])
    return labels.get(semantic_type, semantic_type)


_COMPOUND_EXAMPLE_RE = re.compile(r"^\s*(\S+)\s*\((.+)\)\s*$")

_COMPOUND_PHENOMENON_KEYWORDS = (
    "compound", "komposita", "zusammenset", "zusammenges", "composé", "compuest",
)


def _compound_pairs(text: SourceText) -> list[tuple[str, str, str]]:
    """Find (compound, first part, second part) triples.

    Primary source: a 'compound nouns' grammar phenomenon whose examples
    follow the 'Kaffeepflanze (Kaffee + Pflanze)' convention. Fallback:
    scan the text for words that start with a vocabulary stem.
    """
    pairs: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    if text.grammar:
        for p in text.grammar.phenomena:
            if not any(k in p.name.lower() for k in _COMPOUND_PHENOMENON_KEYWORDS):
                continue
            for example in p.examples:
                m = _COMPOUND_EXAMPLE_RE.match(example)
                if not m:
                    continue
                parts = [s.strip() for s in m.group(2).split("+")]
                compound = m.group(1)
                if len(parts) == 2 and all(parts) and compound.lower() not in seen:
                    pairs.append((compound, parts[0], parts[1]))
                    seen.add(compound.lower())

    if pairs:
        return pairs

    # Fallback: mine the text for words built on a vocabulary stem
    stems = sorted(
        {_strip_article(v.term) for v in (text.vocabulary.items if text.vocabulary else [])
         if v.pos == "noun" and len(_strip_article(v.term)) >= 4},
        key=len, reverse=True,
    )
    for sentence in _sentences(text):
        for token in sentence.split():
            clean = _clean_token(token)
            low = clean.lower()
            if len(clean) < 7 or low in seen:
                continue
            for stem in stems:
                sl = stem.lower()
                if low.startswith(sl) and len(clean) >= len(stem) + 3 and low != sl:
                    pairs.append((clean, stem, clean[len(stem):].lower()))
                    seen.add(low)
                    break
    return pairs


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
# Media generators
# ---------------------------------------------------------------------------

# Target-language words used to build search suggestions.
_MEDIA_SEARCH_WORDS: dict[str, dict[str, str]] = {
    "de": {"video": "Dokumentation", "article": "Artikel"},
    "fr": {"video": "documentaire", "article": "article"},
    "es": {"video": "documental", "article": "artículo"},
    "it": {"video": "documentario", "article": "articolo"},
    "pt": {"video": "documentário", "article": "artigo"},
    "en": {"video": "documentary", "article": "article"},
}

# Everything below is shown in the learner's *native* language.
_MEDIA_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "video_instruction": (
            "Find a short video or documentary in {lang} about the topic. "
            "There is deliberately no link here — searching in {lang} is part "
            "of the task. Watch it, then fill in the fields below."
        ),
        "article_instruction": (
            "Find an article or encyclopedia entry in {lang} about the topic. "
            "There is deliberately no link here — searching in {lang} is part "
            "of the task. Read it, then fill in the fields below."
        ),
        "research_instruction": (
            "Research the following. Any source in {lang} counts — an "
            "encyclopedia, a news site, a video. Write down what you find."
        ),
        "search_ideas": "Search ideas",
        "video_title": "Title of the video:",
        "video_source": "Channel or source:",
        "video_length": "Length:",
        "new_words": "Three new words you heard (with translation):",
        "new_fact": "One fact from the video that is not in the text:",
        "article_headline": "Headline and source:",
        "article_keywords": "Three key words from the article (with translation):",
        "article_facts": "Two facts that are new compared to the text:",
        "article_summary": "Summarize the article in two sentences:",
        "fact_task": "One piece of information about “{term}”:",
        "fact_source": "Which source(s) did you use?",
    },
    "de": {
        "video_instruction": (
            "Finde ein kurzes Video oder eine Dokumentation auf {lang} zum "
            "Thema. Hier steht absichtlich kein Link — das Suchen auf {lang} "
            "ist Teil der Aufgabe. Schau es an und fülle danach die Felder aus."
        ),
        "article_instruction": (
            "Finde einen Artikel oder Lexikoneintrag auf {lang} zum Thema. "
            "Hier steht absichtlich kein Link — das Suchen auf {lang} ist "
            "Teil der Aufgabe. Lies ihn und fülle danach die Felder aus."
        ),
        "research_instruction": (
            "Recherchiere Folgendes. Jede Quelle auf {lang} zählt — Lexikon, "
            "Nachrichtenseite oder Video. Notiere, was du findest."
        ),
        "search_ideas": "Suchideen",
        "video_title": "Titel des Videos:",
        "video_source": "Kanal oder Quelle:",
        "video_length": "Länge:",
        "new_words": "Drei neue Wörter, die du gehört hast (mit Übersetzung):",
        "new_fact": "Ein Fakt aus dem Video, der nicht im Text steht:",
        "article_headline": "Überschrift und Quelle:",
        "article_keywords": "Drei Schlüsselwörter aus dem Artikel (mit Übersetzung):",
        "article_facts": "Zwei Fakten, die neu gegenüber dem Text sind:",
        "article_summary": "Fasse den Artikel in zwei Sätzen zusammen:",
        "fact_task": "Eine Information über „{term}“:",
        "fact_source": "Welche Quelle(n) hast du benutzt?",
    },
    "fr": {
        "video_instruction": (
            "Trouve une courte vidéo ou un documentaire en {lang} sur le "
            "sujet. Il n'y a volontairement pas de lien ici — chercher en "
            "{lang} fait partie de l'exercice. Regarde-la, puis remplis les "
            "champs ci-dessous."
        ),
        "article_instruction": (
            "Trouve un article ou une entrée d'encyclopédie en {lang} sur le "
            "sujet. Il n'y a volontairement pas de lien ici — chercher en "
            "{lang} fait partie de l'exercice. Lis-le, puis remplis les "
            "champs ci-dessous."
        ),
        "research_instruction": (
            "Fais des recherches sur les points suivants. Toute source en "
            "{lang} compte — encyclopédie, site d'actualités ou vidéo. Note "
            "ce que tu trouves."
        ),
        "search_ideas": "Idées de recherche",
        "video_title": "Titre de la vidéo :",
        "video_source": "Chaîne ou source :",
        "video_length": "Durée :",
        "new_words": "Trois mots nouveaux que tu as entendus (avec traduction) :",
        "new_fact": "Un fait de la vidéo qui n'est pas dans le texte :",
        "article_headline": "Titre et source :",
        "article_keywords": "Trois mots-clés de l'article (avec traduction) :",
        "article_facts": "Deux faits nouveaux par rapport au texte :",
        "article_summary": "Résume l'article en deux phrases :",
        "fact_task": "Une information sur « {term} » :",
        "fact_source": "Quelle(s) source(s) as-tu utilisée(s) ?",
    },
    "es": {
        "video_instruction": (
            "Busca un vídeo corto o un documental en {lang} sobre el tema. "
            "Aquí no hay enlace a propósito — buscar en {lang} es parte de "
            "la tarea. Míralo y rellena después los campos."
        ),
        "article_instruction": (
            "Busca un artículo o una entrada de enciclopedia en {lang} sobre "
            "el tema. Aquí no hay enlace a propósito — buscar en {lang} es "
            "parte de la tarea. Léelo y rellena después los campos."
        ),
        "research_instruction": (
            "Investiga lo siguiente. Cualquier fuente en {lang} vale — "
            "enciclopedia, sitio de noticias o vídeo. Anota lo que encuentres."
        ),
        "search_ideas": "Ideas de búsqueda",
        "video_title": "Título del vídeo:",
        "video_source": "Canal o fuente:",
        "video_length": "Duración:",
        "new_words": "Tres palabras nuevas que escuchaste (con traducción):",
        "new_fact": "Un dato del vídeo que no está en el texto:",
        "article_headline": "Titular y fuente:",
        "article_keywords": "Tres palabras clave del artículo (con traducción):",
        "article_facts": "Dos datos nuevos respecto al texto:",
        "article_summary": "Resume el artículo en dos frases:",
        "fact_task": "Una información sobre «{term}»:",
        "fact_source": "¿Qué fuente(s) usaste?",
    },
}


def _media_strings(source_lang: str) -> dict[str, str]:
    return _MEDIA_STRINGS.get(source_lang, _MEDIA_STRINGS["en"])


def _key_terms(text: SourceText, count: int = 3) -> list[VocabularyItem]:
    """Most frequent vocabulary nouns in the text — the topic anchors."""
    if not text.vocabulary:
        return []
    content_low = text.content.lower()
    scored: list[tuple[int, int, VocabularyItem]] = []
    for idx, v in enumerate(text.vocabulary.items):
        if v.pos != "noun":
            continue
        stem = _strip_article(v.term).lower()
        occurrences = content_low.count(stem)
        if occurrences:
            scored.append((occurrences, idx, v))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [v for _, _, v in scored[:count]]


def _search_suggestions(text: SourceText, media_kind: str) -> list[str]:
    terms = [_strip_article(v.term) for v in _key_terms(text, 3)]
    if not terms:
        return []
    words = _MEDIA_SEARCH_WORDS.get(text.target_lang, _MEDIA_SEARCH_WORDS["en"])
    kind_word = words.get(media_kind, "")
    suggestions: list[str] = []
    if kind_word:
        suggestions.append(f"{terms[0]} {kind_word}")
    if len(terms) >= 2:
        suggestions.append(f"{terms[0]} {terms[1]}")
    if len(terms) >= 3:
        suggestions.append(f"{terms[0]} {terms[2]}")
    return suggestions


def _generate_media(node: ExerciseNode, text: SourceText) -> ExerciseInstance | None:
    s = _media_strings(text.source_lang)
    lang = _lang_noun(text.target_lang, text.source_lang)
    items: list[dict] = []
    context_text = ""

    suggestions = _search_suggestions(text, node.media_kind or "")
    if suggestions and node.media_kind in ("video", "article"):
        quoted = "   ".join(f"“{sug}”" for sug in suggestions)
        context_text = f"{s['search_ideas']}: {quoted}"

    if node.media_kind == "video":
        instruction = s["video_instruction"].format(lang=lang)
        tasks = [
            (s["video_title"], 1),
            (s["video_source"], 1),
            (s["video_length"], 1),
            (s["new_words"], 3),
            (s["new_fact"], 2),
        ]
        items = [{"number": i, "task": task, "lines": lines}
                 for i, (task, lines) in enumerate(tasks, 1)]

    elif node.media_kind == "article":
        instruction = s["article_instruction"].format(lang=lang)
        tasks = [
            (s["article_headline"], 1),
            (s["article_keywords"], 3),
            (s["article_facts"], 2),
            (s["article_summary"], 2),
        ]
        items = [{"number": i, "task": task, "lines": lines}
                 for i, (task, lines) in enumerate(tasks, 1)]

    elif node.media_kind == "research":
        key_terms = _key_terms(text, 3)
        if not key_terms:
            return None
        instruction = s["research_instruction"].format(lang=lang)
        tasks = [(s["fact_task"].format(term=v.term), 2) for v in key_terms]
        tasks.append((s["fact_source"], 1))
        items = [{"number": i, "task": task, "lines": lines}
                 for i, (task, lines) in enumerate(tasks, 1)]

    else:
        return None

    if not items:
        return None

    return ExerciseInstance(
        node_id=node.id,
        title=node.name,
        instruction=instruction,
        items=items,
        context_text=context_text,
    )
