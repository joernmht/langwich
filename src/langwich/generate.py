"""Exercise generation from a :class:`SourceText`.

The text is the gold mine.  Every exercise is cut from it deterministically:

* **Fill-in-Blanks** — blank vocabulary words out of real sentences, in story
  order, and attach the requested kind of hint.
* **Picture** — query the *structured* facts of the scene (an element's colour,
  position, or name).  Nothing here is hard-coded: a fact that isn't in the
  scene simply yields no item.
* **Word Connections** — pair vocabulary by translation, synonym, antonym,
  semantic category, or compound parts.

A shared :class:`MaterialLedger` lets a whole worksheet be generated without any
two exercises reusing the same sentence or testing the same word — so the sheet
reads as one developing story rather than the same lines over and over.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

from langwich.graph import ExerciseNode, ExerciseType, VocabularyItem
from langwich.text import SourceText


# ---------------------------------------------------------------------------
# Exercise instance + shared ledger
# ---------------------------------------------------------------------------

@dataclass
class ExerciseInstance:
    """A concrete exercise generated from a text, ready to render."""

    node_id: str
    exercise_type: str
    title: str
    instruction: str
    items: list[dict] = field(default_factory=list)
    solution: list[dict] = field(default_factory=list)
    word_bank: list[str] = field(default_factory=list)
    picture_prompt: str = ""
    picture_caption: str = ""
    estimated_minutes: int = 5
    difficulty: int = 1
    focus: str = ""


@dataclass
class MaterialLedger:
    """Tracks material already spent so exercises don't overlap."""

    used_sentences: set[str] = field(default_factory=set)
    used_terms: set[str] = field(default_factory=set)  # lowercased, article-stripped

    def reserve(self, sentence: str, term: str) -> None:
        self.used_sentences.add(_norm(sentence))
        self.used_terms.add(term.lower())

    def sentence_free(self, sentence: str) -> bool:
        return _norm(sentence) not in self.used_sentences

    def term_free(self, term: str) -> bool:
        return term.lower() not in self.used_terms


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------------
# Small text helpers
# ---------------------------------------------------------------------------

_ARTICLES = ("der ", "die ", "das ", "den ", "dem ", "ein ", "eine ", "le ", "la ",
             "les ", "l'", "el ", "los ", "las ", "il ", "lo ", "gli ")
_PUNCT = re.compile(r"[.,;:!?»«\"'„“”()]")


def _strip_article(term: str) -> str:
    low = term.lower()
    for art in _ARTICLES:
        if low.startswith(art):
            return term[len(art):]
    return term


def _clean(word: str) -> str:
    return _PUNCT.sub("", word).strip()


def _blank(sentence: str, answer: str) -> str:
    """Replace the first whole-word occurrence of ``answer`` with a gap,
    leaving surrounding punctuation (e.g. a trailing comma) intact."""
    if not answer:
        return sentence
    return re.sub(rf"\b{re.escape(answer)}\b", "______", sentence, count=1)


def _split_sentences(paragraphs: list[str]) -> list[tuple[int, str]]:
    out: list[tuple[int, str]] = []
    for pi, para in enumerate(paragraphs):
        for sent in re.split(r"(?<=[.!?])\s+", para):
            s = sent.strip()
            if s:
                out.append((pi, s))
    return out


def _sentences(text: SourceText) -> list[tuple[int, str]]:
    """All sentences of the story, in order, tagged with their paragraph index."""
    return _split_sentences(text.paragraphs)


def _cloze_sentences(text: SourceText) -> list[tuple[int, str]]:
    """Sentences gap-fills draw from.

    Prefers the reworded ``summary`` when present, so the worksheet practises the
    material in fresh wording instead of re-printing the opening text verbatim.
    Falls back to the article itself.
    """
    if text.summary:
        return _split_sentences(text.summary_paragraphs)
    return _sentences(text)


def _vocab_index(text: SourceText) -> dict[str, VocabularyItem]:
    """Map article-stripped lowercase term -> vocabulary item."""
    idx: dict[str, VocabularyItem] = {}
    if text.vocabulary:
        for v in text.vocabulary.items:
            idx[_strip_article(v.term).lower()] = v
    return idx


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_exercise(
    node: ExerciseNode,
    text: SourceText,
    rng: random.Random | None = None,
    ledger: MaterialLedger | None = None,
) -> ExerciseInstance | None:
    """Generate one exercise instance from a node + text.

    ``ledger`` is shared across a whole worksheet to prevent overlap; when called
    standalone (e.g. in tests) a fresh ledger is used.
    """
    if rng is None:
        rng = random.Random(0)
    if ledger is None:
        ledger = MaterialLedger()

    if node.exercise_type == ExerciseType.FILL_IN_BLANKS:
        inst = _generate_fib(node, text, rng, ledger)
    elif node.exercise_type == ExerciseType.PICTURE_INTERACTION:
        inst = _generate_picture(node, text, rng, ledger)
    elif node.exercise_type == ExerciseType.WORD_CONNECTIONS:
        inst = _generate_word_connections(node, text, rng, ledger)
    elif node.exercise_type == ExerciseType.COMPREHENSION:
        inst = _generate_comprehension(node, text)
    else:
        inst = None

    if inst is not None:
        inst.estimated_minutes = node.estimated_minutes
        inst.difficulty = node.difficulty
        inst.focus = node.focus_label
        if not inst.instruction:
            inst.instruction = node.short_instruction
    return inst


def _shell(node: ExerciseNode) -> ExerciseInstance:
    return ExerciseInstance(
        node_id=node.id,
        exercise_type=node.exercise_type.value,
        title=node.title,
        instruction=node.short_instruction,
    )


# ---------------------------------------------------------------------------
# Fill-in-Blanks
# ---------------------------------------------------------------------------

def _pick_blank_targets(
    text: SourceText, ledger: MaterialLedger, count: int
) -> list[tuple[str, str, VocabularyItem]]:
    """Pick (sentence, original_word, vocab_item) triples in story order.

    Skips sentences and words already spent on other exercises.
    """
    vocab = _vocab_index(text)
    if not vocab:
        return []

    results: list[tuple[str, str, VocabularyItem]] = []
    for _pi, sentence in _cloze_sentences(text):
        if not ledger.sentence_free(sentence):
            continue
        words = sentence.split()
        for pos, word in enumerate(words):
            # Never blank the first word — its capital letter would give it away.
            if pos == 0:
                continue
            key = _clean(word).lower()
            item = vocab.get(key)
            if not item or len(key) <= 2 or not ledger.term_free(key):
                continue
            # Prefer content words; prepositions are better tested in the
            # picture/position task, not as a gap.
            if item.pos == "preposition":
                continue
            ledger.reserve(sentence, key)
            results.append((sentence, word, item))
            break
        if len(results) >= count:
            break
    return results


def _generate_fib(
    node: ExerciseNode, text: SourceText, rng: random.Random, ledger: MaterialLedger
) -> ExerciseInstance | None:
    if node.hint_type == "base_form":
        return _generate_fib_base_form(node, text, ledger)

    targets = _pick_blank_targets(text, ledger, count=6)
    if not targets:
        return None

    ex = _shell(node)
    bank_words: list[str] = []

    for i, (sentence, word, item) in enumerate(targets, 1):
        answer = _clean(word)
        blanked = _blank(sentence, answer)
        out: dict = {"number": i, "sentence": blanked}

        if node.hint_type == "first_letter":
            out["hint"] = f"{answer[0]} …"
        elif node.hint_type == "multiple_choice":
            out["choices"] = _choices(answer, text, rng)
        elif node.hint_type == "translation":
            out["hint"] = f"({item.translation})"
        elif node.hint_type == "full_translation":
            tp = text.translation_paragraphs
            pi = _paragraph_of(sentence, text)
            if pi is not None and pi < len(tp):
                out["translation"] = tp[pi]

        bank_words.append(answer)
        ex.items.append(out)
        ex.solution.append({"number": i, "answer": answer})

    if node.hint_type == "word_bank":
        extras = [
            _strip_article(v.term)
            for v in (text.vocabulary.items if text.vocabulary else [])
            if _strip_article(v.term).lower() not in {w.lower() for w in bank_words}
        ]
        rng.shuffle(extras)
        bank = bank_words + extras[:3]
        rng.shuffle(bank)
        ex.word_bank = bank

    return ex


def _generate_fib_base_form(
    node: ExerciseNode, text: SourceText, ledger: MaterialLedger
) -> ExerciseInstance | None:
    targets = _pick_verb_targets(text, ledger, count=6)
    if not targets:
        return None
    ex = _shell(node)
    for i, (sentence, inflected, base) in enumerate(targets, 1):
        blanked = _blank(sentence, _clean(inflected))
        ex.items.append({"number": i, "sentence": blanked, "hint": f"({base})"})
        ex.solution.append({"number": i, "answer": _clean(inflected)})
    return ex


def _pick_verb_targets(
    text: SourceText, ledger: MaterialLedger, count: int
) -> list[tuple[str, str, str]]:
    """Find sentences with an inflected form of a vocabulary verb."""
    if not text.vocabulary:
        return []
    verbs = {_strip_article(v.term).lower(): v.term
             for v in text.vocabulary.items if v.pos == "verb"}
    non_verbs = {_strip_article(v.term).lower()
                 for v in text.vocabulary.items if v.pos != "verb"}
    endings = ("t", "e", "st", "en", "et", "te", "tet", "ten")

    results: list[tuple[str, str, str]] = []
    for _pi, sentence in _cloze_sentences(text):
        if not ledger.sentence_free(sentence):
            continue
        for word in sentence.split():
            clean = _clean(word).lower()
            if len(clean) < 3 or clean in non_verbs:
                continue
            if not any(clean.endswith(e) for e in endings):
                continue
            for stem, base in verbs.items():
                if not ledger.term_free(stem):
                    continue
                root = stem[:-2] if stem.endswith("en") else stem[:-1]
                if len(root) < 3:
                    continue
                if clean.startswith(root) and clean != stem and len(clean) <= len(stem) + 2:
                    ledger.reserve(sentence, stem)
                    results.append((sentence, word, base))
                    break
            else:
                continue
            break
        if len(results) >= count:
            break
    return results


def _choices(answer: str, text: SourceText, rng: random.Random) -> list[str]:
    pool = [
        _strip_article(v.term)
        for v in (text.vocabulary.items if text.vocabulary else [])
        if _strip_article(v.term).lower() != answer.lower()
    ]
    rng.shuffle(pool)
    opts = [answer] + pool[:3]
    rng.shuffle(opts)
    return opts


def _paragraph_of(sentence: str, text: SourceText) -> int | None:
    for i, para in enumerate(text.paragraphs):
        if _norm(sentence) in _norm(para):
            return i
    return None


# ---------------------------------------------------------------------------
# Picture
# ---------------------------------------------------------------------------

def _generate_picture(
    node: ExerciseNode, text: SourceText, rng: random.Random, ledger: MaterialLedger
) -> ExerciseInstance | None:
    scene = text.picture_scene
    if scene is None:
        return None

    ex = _shell(node)
    ex.picture_prompt = scene.description
    ex.picture_caption = scene.caption or ""

    if node.id == "pic_color_query":
        for i, el in enumerate(scene.colored(), 1):
            ex.items.append({"number": i, "term": el.name})
            ex.solution.append({"number": i, "answer": el.color})

    elif node.id == "pic_element_marking":
        names = [el.name for el in scene.key_elements()]
        if names:
            ex.items.append({"mark": names})

    elif node.id == "pic_position":
        for i, el in enumerate(scene.positioned(), 1):
            ex.items.append({"number": i, "term": el.name})
            ex.solution.append({"number": i, "answer": el.position})

    elif node.id == "pic_object_naming":
        for i, el in enumerate(scene.key_elements(), 1):
            ex.items.append({"number": i})
            ex.solution.append({"number": i, "answer": el.name})

    elif node.id == "pic_scene_description":
        ex.items.append({"write_lines": 6})

    elif node.id == "pic_fib":
        para = text.picture_paragraph
        answers: list[str] = []
        if para:
            blanked = para
            # Blank the colour words as they actually appear (declined forms),
            # matching on the colour stem so "weiß" finds "weiße", etc.
            for el in scene.colored():
                m = re.search(rf"\b{re.escape(el.color)}\w*\b", blanked)
                if m:
                    answers.append(m.group(0))
                    blanked = blanked[:m.start()] + "______" + blanked[m.end():]
            if answers:
                ex.items.append({"text": blanked})
                ex.solution.append({"answers": answers})

    return ex if ex.items else None


# ---------------------------------------------------------------------------
# Word Connections
# ---------------------------------------------------------------------------

def _generate_word_connections(
    node: ExerciseNode, text: SourceText, rng: random.Random, ledger: MaterialLedger
) -> ExerciseInstance | None:
    if node.id == "wc_compound":
        return _generate_compounds(node, text, rng)

    if not text.vocabulary or not text.vocabulary.items:
        return None

    vocab = text.vocabulary.items
    ex = _shell(node)

    if node.id == "wc_translation":
        # Prefer words not already tested elsewhere, to keep exercises distinct.
        fresh = [v for v in vocab if ledger.term_free(_strip_article(v.term))]
        pool = fresh if len(fresh) >= 6 else vocab
        selected = rng.sample(pool, min(8, len(pool)))
        for v in selected:
            ledger.used_terms.add(_strip_article(v.term).lower())
        left = [{"number": i, "term": v.term} for i, v in enumerate(selected, 1)]
        order = list(range(len(selected)))
        rng.shuffle(order)
        right = [{"letter": chr(65 + pos), "term": selected[src].translation}
                 for pos, src in enumerate(order)]
        ex.items.append({"left": left, "right": right})
        for i in range(1, len(selected) + 1):
            pos = order.index(i - 1)
            ex.solution.append({"number": i, "letter": chr(65 + pos)})

    elif node.id == "wc_synonym":
        sel = [v for v in vocab if v.synonym][:6]
        if len(sel) < 2:
            return None
        for i, v in enumerate(sel, 1):
            ex.items.append({"number": i, "term": v.term})
            ex.solution.append({"number": i, "term": v.term, "synonym": v.synonym})

    elif node.id == "wc_antonym":
        sel = [v for v in vocab if v.antonym][:6]
        if len(sel) < 2:
            return None
        for i, v in enumerate(sel, 1):
            ex.items.append({"number": i, "term": v.term})
            ex.solution.append({"number": i, "term": v.term, "antonym": v.antonym})

    elif node.id == "wc_category":
        by_type: dict[str, list[VocabularyItem]] = {}
        for v in vocab:
            st = v.semantic_type.value if v.semantic_type else "other"
            if st == "other":
                continue
            by_type.setdefault(st, []).append(v)
        cats = {k: vs for k, vs in by_type.items() if len(vs) >= 2}
        if len(cats) < 2:
            return None
        words = [_strip_article(v.term) for vs in cats.values() for v in vs]
        rng.shuffle(words)
        ex.items.append({"words": words, "categories": [_pretty(k) for k in cats]})
        for k, vs in cats.items():
            ex.solution.append(
                {"category": _pretty(k), "words": [_strip_article(v.term) for v in vs]}
            )

    return ex if ex.items else None


def _generate_compounds(
    node: ExerciseNode, text: SourceText, rng: random.Random
) -> ExerciseInstance | None:
    if not text.compounds:
        return None
    ex = _shell(node)
    rights = [c.right for c in text.compounds]
    shuffled = rights[:]
    rng.shuffle(shuffled)
    ex.items.append({
        "left": [c.left for c in text.compounds],
        "right": shuffled,
    })
    for c in text.compounds:
        sol: dict = {"left": c.left, "right": c.right, "compound": c.compound}
        if c.translation:
            sol["translation"] = c.translation
        ex.solution.append(sol)
    return ex


def _pretty(semantic_type: str) -> str:
    return semantic_type.replace("_", " ").title()


# ---------------------------------------------------------------------------
# Comprehension
# ---------------------------------------------------------------------------

def _generate_comprehension(
    node: ExerciseNode, text: SourceText
) -> ExerciseInstance | None:
    ex = _shell(node)

    if node.id == "comp_questions":
        if not text.questions:
            return None
        for i, q in enumerate(text.questions, 1):
            item: dict = {"number": i, "prompt": q.prompt}
            if q.kind:
                item["kind"] = q.kind
            ex.items.append(item)
            if q.answer:
                ex.solution.append({"number": i, "answer": q.answer})

    elif node.id == "comp_true_false":
        if not text.true_false:
            return None
        for i, s in enumerate(text.true_false, 1):
            ex.items.append({"number": i, "text": s.text})
            ex.solution.append(
                {"number": i, "answer": "True" if s.is_true else "False"}
            )

    return ex if ex.items else None
