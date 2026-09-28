"""Authoring and repair prompts for any LLM.

langwich never writes learner-facing text itself. :func:`build_prompt`
returns one self-contained Markdown prompt that any capable model — Claude,
ChatGPT, Gemini or a local model (Llama, Qwen, Mistral via Ollama or
LM Studio) — can follow without access to this repository to write a
complete ``langwich/3`` worksheet: a short story that carries true facts,
and the tasks that walk a learner through it.

The prompt covers story craft, CEFR calibration, which language goes where,
vocabulary and grammar, the lesson arc with the recommended task set of the
learner's level, item quality (the rules of that level's task kinds), pictures
(including a picture attached to the conversation), series continuation, a
compact field reference for every task kind, a short example that validates,
a self-check and the output rule. ``compact=True`` gives a shorter variant
for small local models (7–14B) with the same contract.

:func:`repair_prompt` turns a validation report into a short "fix these
problems" prompt for the model that wrote the file (problems only the user
can fix, such as a missing photo, are left out).

Languages, level and frame are resolved in one place, :func:`resolve_options`
(given value > previous episode > langwich 2 file > profile > defaults).
"""

from __future__ import annotations

import copy
import json
import re
import textwrap
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from langwich import locale
from langwich.model import (
    CEFR_LEVELS,
    NO_PICTURE_SENTINEL,
    SCHEMA_ID,
    STAGES,
    TASK_KINDS,
    ContractError,
    Worksheet,
    parse_json_text,
)
from langwich.series import Continuation, continuation, slugify
from langwich.validate import ENVIRONMENT_CODES, PAIRED_SCENE_LEVELS, SCENES_MAX, SCENES_MIN

#: Built-in defaults when nothing else gives languages or level.
DEFAULT_SOURCE_LANG = "en"
DEFAULT_TARGET_LANG = "de"
DEFAULT_LEVEL = "B1"


@dataclass
class PromptOptions:
    """What the learner wants. ``None`` means "not given" (for the topic,
    frame and scene count: the LLM or the level decides).

    Languages, level and frame are resolved once, by :func:`resolve_options`:
    a value given here > the previous episode (``continue_from``) > the
    langwich 2 file (``from_legacy``) > ``profile`` > the built-in defaults
    (en → de, B1; no frame).
    """

    source_lang: str | None = None
    target_lang: str | None = None
    level: str | None = None
    topic: str | None = None
    frame: str | None = None
    #: number of scenes, SCENES_MIN–SCENES_MAX (the range the validator accepts)
    scenes: int | None = None
    #: what the LLM writes as the scene's ``picture.image``, copied into the
    #: prompt exactly: a path relative to the worksheet JSON (``langwich prompt
    #: --image`` copies a local photo to ``data/pictures/`` and passes
    #: ``pictures/<file>``) or a URL. The user attaches the picture itself to
    #: the conversation.
    image: str | None = None
    #: a text to build the worksheet on
    from_text: str | None = None
    #: a langwich v2 JSON (content/vocabulary/grammar/picture_scene) to upgrade
    from_legacy: dict | None = None
    #: the previous episode of a series
    continue_from: Worksheet | None = None
    #: start a series (episode 1 with a teaser): True / False; None = only
    #: when the frame is "episode"
    series: bool | None = None
    color: bool = False
    compact: bool = False
    notes: str | None = None
    #: remembered defaults (``.langwich/profile.json``): ``source_lang``,
    #: ``target_lang``, ``level`` and ``frame`` fill in what nothing above gives
    profile: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ResolvedOptions:
    """Languages, level and frame as the prompt uses them (see :func:`resolve_options`)."""

    source_lang: str
    target_lang: str
    level: str
    frame: str | None


# ---------------------------------------------------------------------------
# Languages and levels
# ---------------------------------------------------------------------------

#: English names, so the (English) prompt can say "German (de)".
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "nl": "Dutch", "pl": "Polish", "sv": "Swedish", "da": "Danish",
    "no": "Norwegian", "nb": "Norwegian", "nn": "Norwegian (Nynorsk)", "fi": "Finnish",
    "cs": "Czech", "sk": "Slovak", "sl": "Slovenian", "hr": "Croatian", "sr": "Serbian",
    "hu": "Hungarian", "ro": "Romanian", "bg": "Bulgarian", "tr": "Turkish", "el": "Greek",
    "ru": "Russian", "uk": "Ukrainian", "ar": "Arabic", "he": "Hebrew", "fa": "Persian",
    "hi": "Hindi", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian", "ms": "Malay", "ca": "Catalan", "eu": "Basque",
    "gl": "Galician", "ga": "Irish", "cy": "Welsh", "is": "Icelandic", "et": "Estonian",
    "lv": "Latvian", "lt": "Lithuanian", "sw": "Swahili", "eo": "Esperanto", "la": "Latin",
}

#: Quotation marks for direct speech — typographic quotes need no escaping in JSON.
QUOTES: dict[str, str] = {
    "de": "„…“", "fr": "« … »", "es": "«…»", "it": "«…»", "pt": "“…” or «…»",
    "en": "“…”", "nl": "“…”", "pl": "„…”", "cs": "„…“", "sk": "„…“", "hu": "„…”",
    "ro": "„…”", "ru": "«…»", "uk": "«…»", "el": "«…»", "sv": "”…”", "fi": "”…”",
    "da": "»…«", "no": "«…»", "nb": "«…»", "tr": "“…”", "ja": "「…」", "zh": "“…”",
    "ko": "“…”", "ca": "«…»",
}

#: Languages whose nouns are listed with their article (the validator checks
#: it): how a noun and its plural look.
_ARTICLE_EXAMPLES: dict[str, str] = {
    "de": '"die Bohne", plural "die Bohnen"',
    "fr": '"la tasse", plural "les tasses" (for l\' add the gender to "note": "f")',
    "es": '"la taza", plural "las tazas"',
    "it": '"la tazza", plural "le tazze" (for l\' add the gender to "note": "f")',
    "pt": '"a casa", plural "as casas"',
}

#: The articles a label instruction may ask for.
_ARTICLE_WORDS: dict[str, str] = {
    "de": "der, die or das", "fr": "le, la or l'", "es": "el, la, los or las",
    "it": "il, lo, la or l'", "pt": "o, a, os or as",
}

#: Languages whose word lists give nouns without an article (English has
#: articles, but a dictionary says "apron", not "the apron").
_NO_ARTICLE_LANGS = frozenset({
    "en", "ru", "uk", "be", "pl", "cs", "sk", "sl", "hr", "sr", "bs", "bg", "mk", "fi", "et",
    "lv", "lt", "hu", "tr", "ja", "zh", "ko", "vi", "th", "id", "ms", "hi", "fa", "la",
})

#: Irregular verbs — and separable or reflexive ones where the language has
#: them — with the "forms" a learner needs.
_FORMS_EXAMPLES: dict[str, str] = {
    "de": '"wachsen": "wächst, wuchs, ist gewachsen"; "anziehen": "zieht an, zog an, hat '
          'angezogen"; "sich freuen": "freut sich, freute sich, hat sich gefreut"',
    "nl": '"lopen": "loopt, liep, heeft gelopen"; "opbellen": "belt op, belde op, heeft '
          'opgebeld"; "zich wassen": "wast zich, waste zich, heeft zich gewassen"',
    "fr": '"prendre": "je prends, nous prenons, j\'ai pris"; "se lever": "je me lève, nous nous '
          'levons, je me suis levé(e)"',
    "es": '"tener": "tengo, tuve, he tenido"; "levantarse": "me levanto, me levanté, me he '
          'levantado"',
    "it": '"prendere": "prendo, presi, ho preso"; "alzarsi": "mi alzo, mi alzai, mi sono '
          'alzato/a"',
    "pt": '"fazer": "faço, fiz, feito"; "levantar-se": "levanto-me, levantei-me, levantado"',
    "en": '"grow": "grew, grown"',
}
#: Languages with separable verbs ("anziehen": "zieht … an").
_SEPARABLE_LANGS = frozenset({"de", "nl"})
#: Languages with reflexive verbs whose forms a learner must see.
_REFLEXIVE_LANGS = frozenset({
    "de", "nl", "fr", "es", "it", "pt", "ca", "ro", "pl", "cs", "sk", "sl", "hr", "sr", "ru",
    "uk", "sv", "da", "no", "nb", "nn",
})


def _indefinite(word: object) -> str:
    """``"an"`` before a vowel sound as in "an A2 learner", "an Italian video";
    else ``"a"``."""
    return "an" if str(word)[:1].upper() in "AEIO" else "a"


def _plural_word(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _noun_rules(tgt: str) -> dict[str, str]:
    """How nouns, label terms and a label task's word box work in ``tgt``."""
    base = locale.base_lang(tgt)
    name = _short_name(tgt)
    if base in _ARTICLE_EXAMPLES:
        return {
            "nouns": f"Nouns with their definite article and plural: {_ARTICLE_EXAMPLES[base]}.",
            "label_term": "in T with its article, as in vocabulary.items",
            "noun_check": "Nouns with article and plural.",
            "label_bank": (
                "A label task's word box shows the terms without their articles, so its "
                f"instruction may ask for the article (\"with {_ARTICLE_WORDS[base]}\"); the "
                "solutions show the full term."
                + (" Then prefer label terms whose article shows the gender (not l')."
                   if base in ("fr", "it") else "")
            ),
        }
    if base in _NO_ARTICLE_LANGS:
        return {
            "nouns": (f"Nouns without an article, as {_indefinite(name)} {name} word list gives "
                      "them; irregular plurals in \"plural\"."),
            "label_term": "in T without an article, as in vocabulary.items",
            "noun_check": "Nouns without article, irregular plurals in \"plural\".",
            "label_bank": "",
        }
    return {
        "nouns": (f"Nouns as {_indefinite(name)} {name} dictionary gives them — with the "
                  "article or gender it marks — and irregular plurals in \"plural\"."),
        "label_term": "in T, spelt as in vocabulary.items",
        "noun_check": "Nouns as a dictionary gives them, plurals where irregular.",
        "label_bank": "",
    }


def _verb_kinds(tgt: str) -> str:
    """"irregular", "irregular and reflexive", "irregular, separable and reflexive" …"""
    base = locale.base_lang(tgt)
    kinds = ["irregular"]
    if base in _SEPARABLE_LANGS:
        kinds.append("separable")
    if base in _REFLEXIVE_LANGS:
        kinds.append("reflexive")
    return _and_list(kinds)


def _forms_rule(tgt: str) -> str:
    base = locale.base_lang(tgt)
    form = "infinitive" if base in _FORMS_EXAMPLES else "dictionary form"
    head = f"Verbs in the {form}" + (' (without "to")' if base == "en" else "")
    example = f" (e.g. {_FORMS_EXAMPLES[base]})" if base in _FORMS_EXAMPLES else ""
    return (f'{head}. "forms" is REQUIRED for every {_verb_kinds(tgt)} verb{example}: learners '
            f"cannot build those forms from the {form}.")


def _and_list(items: Iterable[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


#: Examples in the target language for the gap markup and grammar rules
#: (alternatives, a base-form hint, a structure).
_TARGET_EXAMPLES: dict[str, tuple[str, str, str]] = {
    "de": ("{{Laib|Brotlaib}}", "{{wird::werden}}", "werden + past participle"),
    "fr": ("{{commencer|débuter}}", "{{prend::prendre}}", "avoir/être + past participle"),
    "es": ("{{empezar|comenzar}}", "{{tiene::tener}}", "ir a + infinitive"),
    "it": ("{{cominciare|iniziare}}", "{{prende::prendere}}", "avere/essere + past participle"),
    "pt": ("{{começar|iniciar}}", "{{tem::ter}}", "ir + infinitive"),
    "en": ("{{start|begin}}", "{{took::take}}", "have + past participle"),
}
_GENERIC_EXAMPLES = ("{{answer|alternative}}", "{{inflected form::base form}}",
                     "auxiliary + participle")

#: One word in several languages, for the translation-hint example {{T::S}}.
_FLOUR: dict[str, str] = {
    "en": "flour", "de": "Mehl", "fr": "farine", "es": "harina", "it": "farina", "pt": "farinha",
    "nl": "meel", "pl": "mąka", "sv": "mjöl", "da": "mel", "no": "mel", "cs": "mouka",
}

_LEVEL_NAMES: dict[str, str] = {
    "A1": "beginner", "A2": "elementary", "B1": "intermediate",
    "B2": "upper intermediate", "C1": "advanced", "C2": "proficient",
}


@dataclass(frozen=True)
class LevelSpec:
    """How a story and its tasks scale with the CEFR level."""

    words: tuple[int, int]          # story words in total (all scenes)
    scenes: int                     # default number of scenes
    sentences: str
    structures: str
    dialogue: str
    tasks: tuple[int, int]          # tasks in total (the validator's TASK_COUNT)
    writing: tuple[int, int]        # words for the production writing task
    target_words: tuple[int, int]   # size of vocabulary.target
    plot_facts: tuple[int, int]     # true facts woven into the story itself
    #: the recommended task set, one numbered line per step of the lesson arc
    #: (markers such as ``<<picture_tasks>>`` are filled like the rest of the brief)
    recipe: str
    #: the kinds whose rules the brief prints: every kind the recipe and the
    #: level-independent sections name, in :data:`TASK_KINDS` order
    kinds: tuple[str, ...]


# Recommended task sets. The steps are the same at every level (the lesson
# arc); what changes is which kinds, and which of their fields, fit the level.
# Only the learner's level is printed, so each recipe stands on its own.

_RECIPE_A1 = """\
1. warm_up · match: the key words (left, T) with their S meanings (right), plus 1–2 "extra";
   optionally one prediction about the stakes (questions, no model answer).
2. gist/detail, one task <<per_scene>>: true_false, multiple_choice, classify ("who does what?",
   the characters as "categories") or questions with a "starter" (no open why or how questions;
   "question_lang": "source" is allowed).
3. picture: <<picture_tasks>>
4. form, one per grammar point with "grammar": scramble (word order) or a cloze with "hint":
   "choice" or "first_letter".
5. practice: a table (a form, ticket or menu with the story's facts as {{gaps}}) or a
   word-bank cloze.
6. production: writing, a short message with a "starter" and 2–3 "points"; plus one personal
   question.
7. epilogue (optional): a crossword of the key words (S clues); media_search with "media":
   "image" or "video" ("find <<a_T>> <<T>> video about …")."""

_RECIPE_A2 = """\
1. warm_up · match: the key words (left, T) with their S meanings (right), plus 1–2 "extra";
   optionally one prediction about the stakes (questions, no model answer).
2. gist/detail, one task <<per_scene>>: true_false, multiple_choice, classify ("who does what?"),
   questions with a "starter", find_in_text with S clues, order_events (events from the whole
   story; "scene": the last scene).
3. picture: <<picture_tasks>>
4. form, one per grammar point with "grammar": scramble, a cloze with "hint": "choice" or
   "base_form", or transform (its "cue" says what to change).
5. practice: a table (a timetable, receipt or form with the story's facts), a dialogue with
   "bank": true, or a word-bank cloze.
6. production: writing that answers a character's "input" message and covers its 3 "points",
   with a "starter"; plus one personal question.
7. epilogue (optional): a crossword of the key words (S clues); media_search as homework
   ("find <<a_T>> <<T>> video about …")."""

_RECIPE_B1 = """\
1. warm_up · match: the key words (left, T) with their S meanings (right), plus 1–2 "extra";
   optionally one prediction about the stakes (questions, no model answer).
2. gist/detail, one task <<per_scene>>: true_false (with "not_given" if it fits), multiple_choice,
   questions that need the story (why? how?), classify (who said what?), find_in_text with T
   synonyms as clues, order_events (events from the whole story; "scene": the last scene).
3. picture: <<picture_tasks>>
4. form, one per grammar point with "grammar": a cloze with "hint": "base_form", transform
   (its "cue" says what to change) or word_building.
5. practice: a word-bank cloze, a dialogue, or proofread ("marked": true) — a character's
   message with mistakes in the grammar point.
6. production: writing from a character's point of view — a message, a diary entry, or an
   email that answers an "input" and covers its "points" — with a "starter"; plus one personal
   question.
7. epilogue (optional): media_search as homework ("find <<a_T>> <<T>> video about …")."""

_RECIPE_B2 = """\
1. warm_up · match: the key words (left, T) with their S meanings (right), plus 1–2 "extra";
   optionally one prediction about the stakes (questions, no model answer).
2. gist/detail, one task <<per_scene>>: true_false with "not_given", questions on inference (what
   does it show? why?), classify as multiple matching (which character …?), multiple_choice,
   gapped_text (another character's account of the scene).
3. picture: <<picture_tasks>>
4. form, one per grammar point with "grammar": a cloze with "hint": "choice" and
   "choice_layout": "below", an open cloze ("hint": "none"), transform with "keyword", "frame"
   and "max_words", or word_building (word formation).
5. practice: proofread ("marked": false) or an open cloze.
6. production: writing with "register", "audience", 3–4 "points" and "paragraphs": true — a
   character's opinion essay, formal complaint or review; plus one personal question.
7. epilogue (optional): media_search as homework ("find <<a_T>> <<T>> video about …")."""

_RECIPE_C1 = """\
1. warm_up · match: key words or collocations (left, T) with T definitions (right), plus 1–2
   "extra"; optionally one prediction about the stakes (questions, no model answer).
2. gist/detail, one task <<per_scene>>: true_false with "not_given" and "justify",
   gapped_text (another character's account), find_in_text with "explain" (idioms, irony,
   connotation), multiple_choice or questions on inference and the writer's intent.
3. picture (optional): <<picture_tasks>>
4. form, one per grammar point with "grammar": transform as key word transformation
   ("keyword", "frame", "max_words") or an open cloze ("hint": "none").
5. practice: proofread ("marked": false).
6. production: writing from an "input": a summary or a mediation (into S: "output_lang":
   "source"), or a register rewrite (a text message as a formal email); plus one personal
   question.
7. epilogue (optional): media_search as homework ("find <<a_T>> <<T>> podcast about …")."""

_RECIPE_C2 = """\
1. warm_up · match: key words or collocations (left, T) with T definitions (right), plus 1–2
   "extra"; optionally one prediction about the stakes (questions, no model answer).
2. gist/detail, one task <<per_scene>>: true_false with "not_given" and "justify",
   gapped_text (another character's account), find_in_text with "explain" (wordplay, style,
   irony), multiple_choice or questions on the writer's intent and tone.
3. picture (optional): <<picture_tasks>>
4. form, one per grammar point with "grammar": transform as key word transformation
   ("keyword", "frame", "max_words") or an open cloze ("hint": "none").
5. practice: proofread ("marked": false).
6. production: writing from an "input": a genre or voice rewrite (a scene as a news report, or
   in another character's voice), a summary or a mediation (into S: "output_lang": "source");
   plus one personal question.
7. epilogue (optional): media_search as homework ("find <<a_T>> <<T>> podcast about …")."""

#: Kinds that the brief asks for at every level: the warm-up match, the
#: picture task (label or draw), questions, the writing task, the epilogue.
_ARC_KINDS = ("match", "questions", "label", "writing", "media_search", "draw")


def _kinds(*kinds: str) -> tuple[str, ...]:
    """``kinds`` and :data:`_ARC_KINDS` in :data:`TASK_KINDS` order."""
    wanted = set(kinds) | set(_ARC_KINDS)
    return tuple(k for k in TASK_KINDS if k in wanted)


LEVELS: dict[str, LevelSpec] = {
    "A1": LevelSpec((60, 200), 3, "4–8 words; main clauses", "present tense; and, but, because; "
                    "simple questions; can, want", "short exchanges", (8, 11), (25, 40), (6, 8),
                    (2, 3), _RECIPE_A1,
                    _kinds("true_false", "multiple_choice", "classify", "cloze", "scramble",
                           "table", "crossword")),
    "A2": LevelSpec((120, 300), 3, "5–12 words; simple because/when clauses", "present, the "
                    "everyday past, modal verbs, comparisons", "about a third", (8, 12),
                    (40, 70), (6, 8), (2, 4), _RECIPE_A2,
                    _kinds("true_false", "multiple_choice", "order_events", "classify",
                           "find_in_text", "cloze", "transform", "scramble", "table", "dialogue",
                           "crossword")),
    "B1": LevelSpec((220, 450), 4, "up to ~15 words; subordinate and relative clauses",
                    "narrative past tenses, simple passive, reported speech, real conditionals",
                    "a quarter to a third", (10, 14), (60, 100), (8, 12), (3, 5), _RECIPE_B1,
                    _kinds("true_false", "multiple_choice", "order_events", "classify",
                           "find_in_text", "cloze", "transform", "word_building", "proofread",
                           "dialogue")),
    "B2": LevelSpec((350, 700), 4, "varied; complex sentences", "all tenses, passive, "
                    "conditionals, subjunctive in reported speech where it exists",
                    "distinct voices, some register contrast", (10, 14), (100, 150), (8, 12),
                    (3, 6), _RECIPE_B2,
                    _kinds("true_false", "multiple_choice", "classify", "gapped_text", "cloze",
                           "transform", "word_building", "proofread")),
    "C1": LevelSpec((500, 1000), 5, "complex, idiomatic", "nuanced connectors, participle "
                    "clauses, idioms, irony", "characterful, with subtext", (10, 14), (150, 220),
                    (8, 12), (4, 7), _RECIPE_C1,
                    _kinds("true_false", "multiple_choice", "find_in_text", "gapped_text",
                           "cloze", "transform", "proofread")),
    "C2": LevelSpec((600, 1200), 5, "literary, varied rhythm", "the full range, stylistic "
                    "devices, wordplay", "as the story needs", (10, 14), (180, 260), (8, 12),
                    (4, 8), _RECIPE_C2,
                    _kinds("true_false", "multiple_choice", "find_in_text", "gapped_text",
                           "cloze", "transform", "proofread")),
}
assert set(LEVELS) == set(CEFR_LEVELS)

COMPACT_SCENES = 3

FRAMES: dict[str, str] = {
    "episode": "a character's small adventure with a goal and a deadline (can grow into a series)",
    "reportage": "a named reporter follows one object or person station by station (e.g. a "
                 "banana from the plantation to a breakfast table); the reporter's own problem "
                 "drives the plot",
    "case_study": "one person faces a real kind of problem; we follow how it is solved",
    "diary": "dated entries by the protagonist, one entry per scene",
    "letters": "letters or messages between two characters, one per scene",
    "mystery": "a small puzzle the protagonist solves with the facts: clues early, "
               "solution at the end",
    "dialogue": "mostly conversation (an interview, a phone call, a guided tour) with short "
                "narration",
    "other": "any frame that fits, as long as there are characters, a goal and a turn",
}


def language_name(code: str) -> str:
    """``"de"`` → ``"German (de)"``; unknown codes fall back to the endonym or the code."""
    base = locale.base_lang(code)
    name = LANGUAGE_NAMES.get(base) or locale.endonym(code)
    return f"{name} ({code})" if name != code else code


def _short_name(code: str) -> str:
    base = locale.base_lang(code)
    return LANGUAGE_NAMES.get(base) or locale.endonym(code)


# ---------------------------------------------------------------------------
# Field reference (keep in sync with model.py — tests check every field)
# ---------------------------------------------------------------------------

#: One line per task kind: the fields that kind adds to the common task fields.
KIND_FIELDS: dict[str, str] = {
    "match": '"pairs": [{"left": T, "right": S or T}] (≥ 2), "extra": [S or T]? (distractors)',
    "true_false": '"not_given": true | false? (third box "not in the text"), "justify": true | '
                  'false? (learners copy the proof), "items": [{"statement": T, "answer": true | '
                  'false | "not_given", "correction": T? (for false ones), "quote": T? (words of '
                  "the story that prove it)}]",
    "multiple_choice": '"items": [{"question": T, "options": [T, T, T], "answer": T '
                       "(copied exactly from options)}]",
    "order_events": '"events": [T] (≥ 3, in the correct order — langwich shuffles them)',
    "questions": '"question_lang": "target" | "source"? (default target), "items": [{"question": '
                 'T or S, "starter": T? (sentence frame on the answer line), "answer": T? (model '
                 'answer), "lines": 0–20? (answer lines, default 2)}]',
    "classify": '"categories": [T or S] (2–6, printed in this order), "layout": "grid" | '
                '"columns"? (grid: tick a column per line; columns: write the words into '
                'columns), "items": [{"text": T, "answer": category (copied exactly)}]',
    "find_in_text": '"clue_lang": "target" | "source"?, "explain": true | false?, "items": '
                    '[{"clue": T or S, "answer": T (exactly as in the scene), "explanation": T '
                    "or S?}]",
    "gapped_text": '"text": T with each removed sentence in place as {{sentence}} (3–8), '
                   '"extra": [T] (1–2 sentences that fit no gap)',
    "cloze": '"text": T with gaps OR "items": [T with gaps] (exactly one of the two), '
             '"hint": "word_bank" | "first_letter" | "base_form" | "translation" | "choice" | '
             '"none", "choice_layout": "inline" | "below"? (choice: {{right::wrong|wrong}}), '
             '"distractors": [T]?',
    "transform": '"max_words": n? (gap length limit), "items": [{"prompt": T, "cue": S or T? '
                 '(what to change), "answer": T (the new sentence; omit with "frame"), '
                 '"keyword": T? (must be used), "frame": T? (the new sentence with one {{gap}})}]',
    "scramble": '"items": [{"chunks": [T] (3–12 tiles in the CORRECT order; langwich shuffles), '
                '"end": "." | "?" | "!" | "…" | ""?, "alternatives": [[T]]? (other correct '
                'orders), "cue": S?}]',
    "word_building": '"items": [{"parts": [T, T, …], "answer": T}]',
    "table": '"caption": T?, "head": [T]? (none = form: field | value), "rows": [[T with '
             '{{gaps}} or null (open cell)]], "hint": "none" | "word_bank" | "first_letter" | '
             '"base_form" | "translation"?, "distractors": [T]?',
    "proofread": '"text": T with each mistake as {{correct::wrong}}, "marked": true | false? '
                 "(false: only the number of mistakes is given)",
    "label": '"scene": scene id (required; its picture has labels), "bank": true | false? '
             "(default true: a word box with the terms, printed without their articles)",
    "writing": '"prompt": S, "input": T or S? (text to answer, in a box), "input_lang": '
               '"target" | "source"?, "output_lang": "target" | "source"?, "register": '
               '"informal" | "neutral" | "formal"?, "audience": S?, "points": [{"point": S, '
               '"covered_by": words of model_answer}]? (2–5), "paragraphs": true | false?, '
               '"starter": T?, "must_use": [T]?, "min_words": n?, "max_words": n?, "lines": '
               '1–40?, "model_answer": T?',
    "dialogue": '"lines": [{"speaker": name, "text": T with gaps?, "cue": S?, "answer": T?}] '
                '(≥ 2; a line without "text" is written by the learner from its "cue"), '
                '"bank": true | false? (a word box of the gap answers), "distractors": [T]? '
                "(extra words for the box)",
    "crossword": '"clue_lang": "source" | "target"?, "entries": [{"answer": T (one word, no '
                 'article), "clue": S or T}] (4–16; langwich builds the grid)',
    "media_search": '"media": "video" | "article" | "podcast" | "image", "queries": [T], '
                    '"questions": [T]',
    "draw": '"prompt": S, "labels": [T]?',
}
assert set(KIND_FIELDS) == set(TASK_KINDS)

#: The item rules of each task kind (T/S-neutral English), printed in the
#: item-quality section for the kinds a brief asks for (see :func:`kind_rules`).
#: Markers such as ``<<ex_base>>`` are filled like the rest of the brief.
KIND_RULES: dict[str, str] = {
    "match": 'every entry unique, "extra" included.',
    "true_false": '3–5 statements, both kinds; a false one changes one detail and has a '
                  '"correction". From B1, "not_given": true with 1–2 statements about details '
                  "the story never mentions (never about real-world facts); with \"justify\", "
                  'every true and false item has a "quote" copied exactly from the story.',
    "multiple_choice": '3 similar options, one right, "answer" copied exactly.',
    "order_events": "4–6 events from different scenes, in the correct order.",
    "questions": 'need the story (why? how?), with a model "answer". At A1–A2 give a "starter" '
                 '(e.g. "Lena is sad because …") and a model answer that begins with it.',
    "classify": '2–4 categories (names, der/die/das, formal/informal …), 5–10 items, every '
                'category used, the items mixed; "answer" copied exactly from "categories".',
    "find_in_text": "the answer is written exactly as in the scene; clues in S at A1–A2, T "
                    "synonyms or paraphrases from B1, idioms or irony with \"explain\" and "
                    '"explanation" at C1–C2.',
    "gapped_text": "a new text of 5–12 sentences with 3–6 sentences removed ({{…}} in place) "
                   'plus 1–2 "extra" sentences; each removed sentence fits only its gap (by '
                   "reference words, connectors, time).",
    "cloze": '"hint": word_bank (a box of the answers + distractors), first_letter, base_form '
             "(<<ex_base>>), translation (<<ex_translation>>, the hint in S) — these two need "
             'the ::hint — or none. "choice": every gap {{right::wrong1|wrong2}} with 1–3 wrong '
             'options of the same word class that are wrong in this sentence (at the start of a '
             'sentence all capitalised); "choice_layout": "below" from B2.',
    "transform": 'key word transformation (B2+): "frame" is the second sentence with one {{gap}} '
                 'of 2–5 words that must include "keyword"; set "max_words".',
    "scramble": "3–10 tiles per sentence, one word or a fixed group per tile, in the correct "
                "order; the first tile in lower case unless it is always capitalised; "
                'punctuation only in "end"; list every other correct order in "alternatives".',
    "word_building": '"parts" (words, prefixes, suffixes) that join into one new word, the '
                     '"answer".',
    "table": "a form, timetable, price list or verb/word-family table with 3–8 rows and at "
             'most 5 columns; every row as long as "head" (2 cells for a form); {{gaps}} for '
             "facts from the story or forms; null for the learner's own answer.",
    "proofread": "a character's draft (message, note, review) of 60–150 words with 4–8 mistakes "
                 "of the kinds practised, each {{correct::wrong}} around only the words that "
                 'change, with one wrong form; "marked": false from B2.',
    "label": 'only on a scene whose picture has "labels" and an "image" or "svg" (else draw).',
    "writing": 'the model answer keeps to the word range and uses every "must_use" word; the '
               "instruction does not repeat the word range (langwich prints it). To answer a "
               'message, give it as "input" and 2–5 "points" the reply must cover, each with '
               '"covered_by": the words of the model answer that cover it. For a summary or '
               'mediation, "input" is the text and "output_lang" the language to write in; '
               '"register" and "audience" say who it is for.',
    "dialogue": 'the characters in a new situation; gaps in "text", or a line without "text" '
                'that the learner writes from its S "cue", with a model "answer".',
    "crossword": "6–12 key words (no articles, one word each) that share letters; clues in S "
                 "(A1–A2) or T definitions/gap sentences (B1).",
    "media_search": 'homework a character sets in the story: T "queries" and two T "questions".',
    "draw": 'the learner draws a scene from an S "prompt" and writes 4–6 T "labels" into it.',
}
assert list(KIND_RULES) == list(TASK_KINDS)


#: Where the first sentence of a rule ends (not after "e.g."): the sentences
#: after it add the options of some levels (not_given, "choice", "input" …).
_FIRST_SENTENCE_END_RE = re.compile(r'(?<!e\.g)\.\s+(?=["A-Z])')


def kind_rules(kinds: Iterable[str], core: bool = False) -> str:
    """The rules of ``kinds`` (in :data:`TASK_KINDS` order) as one paragraph:
    ``'true_false: … multiple_choice: …'``. ``core`` keeps only the first
    sentence of each rule, without the options that follow (compact prompt)."""
    wanted = set(kinds)
    rules = {k: KIND_RULES[k] for k in TASK_KINDS if k in wanted}
    if core:
        rules = {k: _FIRST_SENTENCE_END_RE.split(r, maxsplit=1)[0].rstrip(".") + "."
                 for k, r in rules.items()}
    return " ".join(f"{k}: {rule}" for k, rule in rules.items())


_FIELD_REFERENCE_HEAD = """\
`T` = text in <<T>>, `S` = text in <<S>>, `?` = optional (leave it out when unused),
`[…]` = list. Ids: letters, digits, `_` and `-`, unique. Use only these fields — any other
field is an error.

```
{
 "schema": "langwich/3",
 "title": T, "standfirst": S?,
 "source_lang": "<<src>>", "target_lang": "<<tgt>>", "cefr_level": "<<level>>",
 "topic": S (1–3 words), "frame": frame?,
 "series": Series?,
 "story": {"logline": S (who wants what), "setting": S?, "characters": [Character],
           "scenes": [Scene]},
 "facts": [Fact],
 "vocabulary": {"target": [T], "items": [VocabItem]},
 "grammar": [GrammarPoint],
 "tasks": [Task],
 "ui": {key: S}? (only when this prompt asks for it)
}
Character    {"id", "name", "role": S?}
Scene        {"id", "heading": T, "beat": beat?, "text": T (prose, paragraphs split by \\n\\n),
              "translation": S?, "picture": Picture?}
Picture      {"image": path or URL?, "svg": "<svg …>…</svg>"?, "caption": T?, "credit": text?,
              "prompt": English?, "labels": [Label]?, "numbers_in_image": true | false?}
Label        {"n": 1–30, "term": T, "x": 0–1, "y": 0–1}
Fact         {"id"?, "scene": scene id?, "title": T?, "text": T, "source": text?}
Series       {"id", "title": T, "episode": 1, 2, …, "previously": S?, "next": T?,
              "review": [T]}
VocabItem    {"term": T, "translation": S, "pos": pos, "plural": T?, "forms": T?, "note": S?,
              "scene": scene id?}
GrammarPoint {"id", "name": S, "explanation": S, "rule": text?,
              "table": {"head": [text], "rows": [[text]]}?, "examples": [T],
              "scene": scene id?}

frame: episode | reportage | case_study | diary | letters | mystery | dialogue | other
beat:  setup | development | complication | climax | resolution | epilogue
pos:   noun | verb | adjective | adverb | preposition | conjunction | pronoun | phrase | other
stage: <<stage_list>>

Every task: {"id", "kind", "stage", "scene": scene id or [scene ids]?, "title": S,
             "instruction": S, "grammar": grammar id?, … the fields of its kind}
"""


_PAREN_RE = re.compile(r" \((?:[^()]|\([^()]*\))*\)")


def field_reference(values: Mapping[str, object], terse: bool = False) -> str:
    """The compact field reference for every model and every task kind.
    ``terse`` drops the parenthetical explanations (same fields)."""
    width = max(len(k) for k in KIND_FIELDS) + 2
    kinds = "\n".join(f"{kind.ljust(width)}{KIND_FIELDS[kind]}" for kind in TASK_KINDS)
    text = _fill(_FIELD_REFERENCE_HEAD, {**values, "stage_list": " | ".join(STAGES)})
    text += kinds + "\n```"
    if terse:
        head, fence, code = text.partition("```")
        text = head + fence + _PAREN_RE.sub("", code)
    return text


# ---------------------------------------------------------------------------
# The example (validated by the tests; keep it short)
# ---------------------------------------------------------------------------

_EXAMPLE_SVG = (
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 100' fill='none' stroke='#000' "
    "stroke-width='1.5' stroke-linecap='round' stroke-linejoin='round'>"
    "<path d='M0 62 Q25 57 50 62 T100 62 T150 62 T200 62'/>"
    "<path d='M105 62 Q145 38 195 62'/>"
    "<path d='M150 51 L153 22 L161 22 L164 51'/>"
    "<rect x='152' y='14' width='10' height='8'/>"
    "<ellipse cx='48' cy='78' rx='14' ry='5'/>"
    "<circle cx='63' cy='73' r='4'/>"
    "<path d='M88 80 V95 H102 V91 H94 V80 Z'/>"
    "</svg>"
)

#: A short but complete English → German A2 worksheet (2 scenes, 8 tasks: the
#: fewest an A2 worksheet should have).
MINI_EXAMPLE: dict[str, Any] = {
    "schema": "langwich/3",
    "title": "Zu Fuß zur Insel",
    "standfirst": "Mia wants to walk across the seabed to an island — but at one o'clock the "
                  "sea comes back. Find out how the tides of the North Sea work.",
    "source_lang": "en",
    "target_lang": "de",
    "cefr_level": "A2",
    "topic": "tides",
    "frame": "episode",
    "story": {
        "logline": "Mia, on holiday on the North Sea coast, wants to walk to an island at low "
                   "tide — and must get there before the water returns.",
        "setting": "Cuxhaven and the island of Neuwerk, Germany, a Saturday in summer",
        "characters": [
            {"id": "mia", "name": "Mia", "role": "29, a nurse from Leeds, on holiday"},
            {"id": "jan", "name": "Jan", "role": "mudflat guide in Cuxhaven"},
        ],
        "scenes": [
            {
                "id": "s1",
                "heading": "Das Meer ist weg",
                "beat": "setup",
                "text": "Samstag, zehn Uhr. Mia steht am Strand von Cuxhaven und staunt: Das "
                        "Meer ist weg! Vor ihr liegt nur nasser, grauer Sand – das Watt. Heute "
                        "will sie zu Fuß zur Insel Neuwerk gehen.\n\n„Jetzt ist Ebbe“, sagt der "
                        "Wattführer Jan. „Aber um ein Uhr kommt die Flut zurück. Wir müssen "
                        "vorher auf der Insel sein.“ Mia zieht ihre Stiefel an. Der Schlick ist "
                        "kalt und weich wie Pudding.",
                "translation": "Saturday, ten o'clock. Mia is standing on the beach at "
                               "Cuxhaven, amazed: the sea has gone! In front of her there is "
                               "only wet, grey sand – the mudflats. Today she wants to walk to "
                               "the island of Neuwerk.\n\n“It's low tide now,” says Jan, the "
                               "mudflat guide. “But at one o'clock the tide comes back. We have "
                               "to be on the island before then.” Mia puts on her boots. The "
                               "mud is cold and soft like pudding.",
            },
            {
                "id": "s2",
                "heading": "Wettlauf mit dem Wasser",
                "beat": "resolution",
                "text": "Nach zwei Stunden sieht Mia drei Seehunde auf einer Sandbank. „Ich "
                        "will ein Foto machen!“ Sie läuft los. „Stopp!“, ruft Jan. „Wir dürfen "
                        "den Seehunden nicht zu nah kommen. Und die Flut wartet nicht.“ Da "
                        "sieht Mia es auch: In den Prielen fließt schon Wasser.\n\nUm halb eins "
                        "stehen sie vor dem alten Leuchtturm der Insel. Mias Stiefel sind voller "
                        "Schlick. Eine Stunde später ist der Weg verschwunden. Dort ist wieder "
                        "Meer.",
                "translation": "After two hours Mia sees three seals on a sandbank. “I want to "
                               "take a photo!” She runs off. “Stop!” Jan shouts. “We mustn't "
                               "get too close to the seals. And the tide won't wait.” Then Mia "
                               "sees it too: water is already flowing in the tidal creeks.\n\n"
                               "At half past twelve they are standing in front of the island's "
                               "old lighthouse. Mia's boots are covered in mud. An hour later "
                               "the path has disappeared. There is sea there again.",
                "picture": {
                    "svg": _EXAMPLE_SVG,
                    "caption": "Angekommen auf Neuwerk",
                    "prompt": "Black-and-white line drawing: a lighthouse on a low island, "
                              "mudflats, a seal on a sandbank, a rubber boot in front.",
                    "labels": [
                        {"n": 1, "term": "der Seehund", "x": 0.25, "y": 0.77},
                        {"n": 2, "term": "der Stiefel", "x": 0.475, "y": 0.88},
                        {"n": 3, "term": "die Insel", "x": 0.625, "y": 0.58},
                        {"n": 4, "term": "der Leuchtturm", "x": 0.785, "y": 0.34},
                    ],
                },
            },
        ],
    },
    "facts": [
        {"id": "f1", "scene": "s1", "title": "Ebbe und Flut",
         "text": "An der Nordsee kommt das Wasser ungefähr alle zwölf Stunden zurück. Man nennt "
                 "das die Gezeiten."},
        {"id": "f2", "scene": "s2",
         "text": "Das Wattenmeer an der Nordsee ist ein Weltnaturerbe der UNESCO. Die Insel "
                 "Neuwerk gehört zu Hamburg.",
         "source": "UNESCO"},
    ],
    "vocabulary": {
        "target": ["das Watt", "die Ebbe", "die Flut", "die Insel", "der Seehund",
                   "der Leuchtturm"],
        "items": [
            {"term": "staunen", "translation": "to be amazed", "pos": "verb"},
            {"term": "das Watt", "translation": "mudflats", "pos": "noun"},
            {"term": "die Insel", "translation": "island", "pos": "noun",
             "plural": "die Inseln"},
            {"term": "die Ebbe", "translation": "low tide", "pos": "noun"},
            {"term": "die Flut", "translation": "high tide, incoming tide", "pos": "noun"},
            {"term": "anziehen", "translation": "to put on (clothes)", "pos": "verb",
             "forms": "zieht an, zog an, hat angezogen"},
            {"term": "der Stiefel", "translation": "boot", "pos": "noun",
             "plural": "die Stiefel"},
            {"term": "der Schlick", "translation": "mud (of the mudflats)", "pos": "noun"},
            {"term": "der Seehund", "translation": "seal", "pos": "noun",
             "plural": "die Seehunde"},
            {"term": "die Sandbank", "translation": "sandbank", "pos": "noun",
             "plural": "die Sandbänke"},
            {"term": "der Priel", "translation": "tidal creek", "pos": "noun",
             "plural": "die Priele"},
            {"term": "der Leuchtturm", "translation": "lighthouse", "pos": "noun",
             "plural": "die Leuchttürme"},
            {"term": "verschwinden", "translation": "to disappear", "pos": "verb",
             "forms": "verschwindet, verschwand, ist verschwunden"},
        ],
    },
    "grammar": [
        {
            "id": "g1",
            "name": "Modal verbs",
            "explanation": "Modal verbs say what someone can, wants to, should, has to or may "
                           "do. The modal verb comes second; the main verb goes to the end, in "
                           "the infinitive. ich and er/sie/es have the same form, without an "
                           "ending.",
            "rule": "modal verb (2nd position) … infinitive (end)",
            "table": {
                "head": ["", "können", "wollen", "sollen"],
                "rows": [["ich", "kann", "will", "soll"],
                         ["er / sie / es", "kann", "will", "soll"],
                         ["ihr", "könnt", "wollt", "sollt"]],
            },
            "examples": ["Heute will sie zu Fuß zur Insel Neuwerk gehen.",
                         "Wir müssen vorher auf der Insel sein."],
            "scene": "s2",
        },
    ],
    "tasks": [
        {"id": "t1", "kind": "match", "stage": "warm_up", "title": "Words for the seabed",
         "instruction": "Match the German words to their meanings. Write the letter in the box. "
                        "One meaning is left over.",
         "pairs": [{"left": "das Watt", "right": "mudflats"},
                   {"left": "die Ebbe", "right": "low tide"},
                   {"left": "die Flut", "right": "high tide"},
                   {"left": "die Insel", "right": "island"},
                   {"left": "der Seehund", "right": "seal"},
                   {"left": "der Leuchtturm", "right": "lighthouse"}],
         "extra": ["harbour"]},
        {"id": "t2", "kind": "true_false", "stage": "gist", "scene": "s1",
         "title": "Saturday morning on the beach",
         "instruction": "Tick true or false. Correct the false sentences.",
         "items": [
             {"statement": "Am Morgen sieht Mia vor dem Strand viel Wasser.", "answer": False,
              "correction": "Das Meer ist weg, sie sieht nur nassen Sand."},
             {"statement": "Mia möchte mit dem Schiff nach Neuwerk fahren.", "answer": False,
              "correction": "Sie will zu Fuß zur Insel gehen."},
             {"statement": "Am Nachmittag ist der Weg zur Insel unter Wasser.", "answer": True},
         ]},
        {"id": "t3", "kind": "multiple_choice", "stage": "detail", "scene": "s2",
         "title": "The race against the water", "instruction": "Tick the right answer.",
         "items": [
             {"question": "Warum ruft Jan „Stopp!“?",
              "options": ["Mia läuft zu den Seehunden.", "Mia verliert einen Stiefel.",
                          "Mia geht in die falsche Richtung."],
              "answer": "Mia läuft zu den Seehunden."},
             {"question": "Wann stehen Mia und Jan vor dem Leuchtturm?",
              "options": ["um zehn Uhr", "um halb eins", "um ein Uhr"],
              "answer": "um halb eins"},
         ]},
        {"id": "t4", "kind": "cloze", "stage": "form", "scene": "s2", "grammar": "g1",
         "hint": "base_form", "title": "Jan's rules for the mudflats",
         "instruction": "Before every walk, Jan explains the rules. Complete them with the right "
                        "form of the verb in brackets.",
         "items": ["Im Watt {{müsst::müssen}} ihr immer bei der Gruppe bleiben.",
                   "Ihr {{dürft::dürfen}} die Seehunde nicht stören.",
                   "Um ein Uhr {{muss::müssen}} jeder auf der Insel sein."]},
        {"id": "t5", "kind": "cloze", "stage": "practice", "scene": "s2", "hint": "word_bank",
         "title": "Sunday: the way back",
         "instruction": "The next day Mia goes back to Cuxhaven. Fill the gaps with words from "
                        "the box. Two words are left over.",
         "text": "Am Sonntag fährt Mia mit einem Pferdewagen zurück. Die Pferde laufen langsam "
                 "durch das {{Watt}}. Es ist wieder {{Ebbe}}, aber der Boden ist noch nass. "
                 "Hinter Mia wird der {{Leuchtturm}} immer kleiner, und auf einer Sandbank "
                 "liegen wieder {{Seehunde}}. „Nächstes Mal bleibe ich länger auf der "
                 "{{Insel}}“, denkt Mia. „Und ich weiß jetzt: Wenn die {{Flut}} kommt, ist der "
                 "Weg weg.“",
         "distractors": ["Sonne", "Schlick"]},
        {"id": "t6", "kind": "label", "stage": "picture", "scene": "s2",
         "title": "Arriving on Neuwerk",
         "instruction": "Write the German word for each number — with der, die or das.",
         "bank": True},
        {"id": "t7", "kind": "writing", "stage": "production",
         "title": "Saturday night: a postcard to Leeds",
         "instruction": "Mia writes a postcard to her sister Emma. Write it in German.",
         "prompt": "What did Mia do today? What almost went wrong?",
         "starter": "Liebe Emma, heute bin ich zu Fuß …",
         "must_use": ["die Ebbe", "die Flut", "das Watt", "der Seehund", "der Leuchtturm"],
         "min_words": 40, "max_words": 60, "lines": 7,
         "model_answer": "Liebe Emma, heute bin ich zu Fuß zur Insel Neuwerk gegangen! Am "
                         "Morgen war Ebbe, und wir sind durch das Watt gelaufen. Ich wollte "
                         "einen Seehund fotografieren, aber Jan hat „Stopp!“ gerufen – die Flut "
                         "wartet nicht! Um halb eins waren wir am Leuchtturm. Liebe Grüße, Mia"},
        {"id": "t8", "kind": "questions", "stage": "production", "title": "And you?",
         "instruction": "Answer in German.",
         "items": [{"question": "Warst du schon einmal am Meer? Was hast du dort gemacht?",
                    "lines": 3}]},
    ],
}


#: Vocabulary items the compact example keeps besides the target words.
_COMPACT_EXTRA_ITEMS = ("der Stiefel", "der Priel", "verschwinden")


def compact_example() -> dict[str, Any]:
    """The example as the compact prompt shows it: shorter (no translations,
    no grammar table, one fact, fewer vocabulary and task items, but as many
    tasks) and with a draw task instead of an SVG drawing with a label task."""
    ex = copy.deepcopy(MINI_EXAMPLE)
    for scene in ex["story"]["scenes"]:
        scene.pop("translation", None)
        pic = scene.get("picture")
        if pic:
            pic.pop("svg", None)
            pic.pop("labels", None)
    ex["facts"] = ex["facts"][:1]
    for gp in ex["grammar"]:
        gp.pop("table", None)
    for task in ex["tasks"]:
        if task["kind"] == "true_false":
            task["items"] = task["items"][:2]
        elif task["kind"] == "multiple_choice":
            task["items"] = task["items"][:1]
    keep = {t.casefold() for t in ex["vocabulary"]["target"] + list(_COMPACT_EXTRA_ITEMS)}
    ex["vocabulary"]["items"] = [
        v for v in ex["vocabulary"]["items"] if v["term"].casefold() in keep
    ]
    for i, task in enumerate(ex["tasks"]):
        if task["kind"] == "label":
            ex["tasks"][i] = {
                "id": task["id"], "kind": "draw", "stage": "picture", "scene": task["scene"],
                "title": "Mia's view of the island",
                "instruction": "Draw what Mia sees when she arrives, and label it in German.",
                "prompt": "The island with its old lighthouse, the mudflats, a seal on a "
                          "sandbank — and Mia's muddy boots.",
                "labels": ["die Insel", "der Leuchtturm", "der Seehund", "der Stiefel"],
            }
    return ex


def format_json(value: Any, indent: int = 0, depth: int = 0) -> str:
    """Readable but compact JSON: objects are expanded down to the second
    level, list elements get a line each, everything deeper stays inline."""
    inline = json.dumps(value, ensure_ascii=False)
    if not isinstance(value, (dict, list)) or len(inline) + indent <= 96 or depth >= 3:
        return inline
    pad = " " * (indent + 1)
    if isinstance(value, dict):
        if depth >= 2:
            return inline
        body = ",\n".join(
            f"{pad}{json.dumps(k, ensure_ascii=False)}: {format_json(v, indent + 1, depth + 1)}"
            for k, v in value.items()
        )
        return "{\n" + body + "\n" + " " * indent + "}"
    if all(isinstance(v, str) for v in value):
        return inline
    body = ",\n".join(pad + format_json(v, indent + 1, depth + 1) for v in value)
    return "[\n" + body + "\n" + " " * indent + "]"


def example_json(compact: bool = False) -> str:
    return format_json(compact_example() if compact else MINI_EXAMPLE)


# ---------------------------------------------------------------------------
# Template filling
# ---------------------------------------------------------------------------

_MARK_RE = re.compile(r"<<(\w+)>>")


def _fill(template: str, values: Mapping[str, object]) -> str:
    """Replace ``<<name>>`` markers (single pass; values are not re-scanned)."""

    def sub(m: re.Match[str]) -> str:
        return str(values[m.group(1)])

    return _MARK_RE.sub(sub, template)


_ITEM_RE = re.compile(r"^(\s*)([-*]|\d+\.) ")
REFLOW_WIDTH = 96

#: A line that starts with this character is printed exactly as it is (minus
#: the marker): never re-wrapped, its whitespace never normalised — for text
#: the LLM must copy character for character, such as the picture path.
_KEEP = "\x1f"


def _keep(line: str) -> str:
    """Mark ``line`` to be printed verbatim by :func:`_reflow`."""
    return _KEEP + line


def _wrap(text: str, first: str, rest: str) -> str:
    return textwrap.fill(
        " ".join(text.split()), width=REFLOW_WIDTH, initial_indent=first,
        subsequent_indent=rest, break_long_words=False, break_on_hyphens=False,
    )


def _reflow(text: str) -> str:
    """Re-wrap prose paragraphs and list items after the markers are filled.
    Code fences, tables, headings and lines marked with :func:`_keep` are
    left exactly as they are."""
    out: list[str] = []
    buf: list[str] = []      # lines of the current paragraph or list item
    indent = ("", "")        # (first-line prefix, continuation prefix) of buf
    fence: str | None = None

    def flush() -> None:
        nonlocal buf
        if buf:
            out.append(_wrap(" ".join(buf), *indent))
            buf = []

    for line in text.split("\n"):
        stripped = line.strip()
        if line.startswith(_KEEP) and fence is None:
            flush()
            indent = ("", "")
            out.append(line[len(_KEEP):])
            continue
        if fence is not None:
            out.append(line)
            if stripped.startswith(fence) and stripped.strip("`") == "":
                fence = None
            continue
        if stripped.startswith("```"):
            flush()
            fence = stripped[: len(stripped) - len(stripped.lstrip("`"))]
            out.append(line)
            continue
        if not stripped or stripped.startswith(("#", "|")):
            flush()
            out.append(line)
            continue
        item = _ITEM_RE.match(line)
        if item:
            flush()
            marker = item.group(0)
            indent = (marker, " " * len(marker))
            buf = [line[len(marker):]]
        elif buf and line[:1].isspace():
            buf.append(stripped)
        elif buf and indent[0] == "":
            buf.append(stripped)
        else:
            flush()
            indent = ("", "")
            buf = [stripped]
    flush()
    return "\n".join(out)


def _fence(text: str, lang: str = "") -> str:
    fence = "```"
    while fence in text:
        fence += "`"
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}"


def _round5(n: float) -> int:
    return max(5, int(round(n / 5.0)) * 5)


# ---------------------------------------------------------------------------
# The brief: resolved options
# ---------------------------------------------------------------------------

_LEGACY_KEYS = (
    "title", "content", "source_lang", "target_lang", "cefr_level", "level", "topic",
    "picture_scene", "vocabulary", "phrases", "grammar", "reading",
)
_LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_FRAME_NAMES = frozenset(FRAMES)


@dataclass
class _Brief:
    src: str
    tgt: str
    level: str
    spec: LevelSpec
    scenes: int
    topic: str | None
    frame: str | None
    cont: Continuation | None
    opts: PromptOptions

    @property
    def per_scene(self) -> tuple[int, int]:
        low, high = self.spec.words
        return _round5(low / self.scenes), _round5(high / self.scenes)


def _legacy_value(legacy: dict | None, *keys: str) -> str | None:
    if not legacy:
        return None
    for key in keys:
        value = legacy.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _lang_code(value: object) -> str | None:
    """``"EN"`` → ``"en"``, ``"pt-BR"`` stays; ``None`` for anything else."""
    if not isinstance(value, str):
        return None
    head, sep, tail = value.strip().partition("-")
    code = head.lower() + sep + tail
    return code if _LANG_RE.match(code) else None


def _level_code(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    level = value.strip().upper()
    return level if level in LEVELS else None


def _first(explicit: object, fallbacks: Iterable[object], parse: Any, error: str) -> str:
    """``explicit`` if given (it must parse), else the first fallback that parses."""
    if explicit is not None:
        value = parse(explicit)
        if value is None:
            raise ValueError(error.format(explicit))
        return str(value)
    for candidate in fallbacks:
        value = parse(candidate)
        if value is not None:
            return str(value)
    raise ValueError(error.format(None))  # pragma: no cover - the defaults always parse


def resolve_options(opts: PromptOptions) -> ResolvedOptions:
    """The languages, level and frame the prompt for ``opts`` uses.

    Each is taken from the first of: the value in ``opts`` (``None`` = not
    given), the previous episode (``continue_from``), the langwich 2 file
    (``from_legacy``; languages and level only), ``profile``, the built-in
    defaults (en → de, B1; no frame). Values from files that are not usable
    (``"German"``, ``"B3"``) are skipped; an unusable value given in ``opts``
    raises :class:`ValueError`. :func:`build_prompt` calls this — callers use
    it to check or remember what the prompt asks for.
    """
    prev = opts.continue_from
    legacy = opts.from_legacy if isinstance(opts.from_legacy, dict) else None
    profile: Mapping[str, Any] = opts.profile if isinstance(opts.profile, Mapping) else {}
    src = _first(
        opts.source_lang,
        (prev.source_lang if prev else None, _legacy_value(legacy, "source_lang"),
         profile.get("source_lang"), DEFAULT_SOURCE_LANG),
        _lang_code, "{!r} is not a language code; use ISO 639-1 like en, de, fr, pt-BR",
    )
    tgt = _first(
        opts.target_lang,
        (prev.target_lang if prev else None, _legacy_value(legacy, "target_lang"),
         profile.get("target_lang"), DEFAULT_TARGET_LANG),
        _lang_code, "{!r} is not a language code; use ISO 639-1 like en, de, fr, pt-BR",
    )
    level = _first(
        opts.level,
        (prev.cefr_level if prev else None, _legacy_value(legacy, "cefr_level", "level"),
         profile.get("level"), DEFAULT_LEVEL),
        _level_code, "unknown CEFR level {!r}; use one of " + ", ".join(LEVELS),
    )
    frame = opts.frame
    if frame is None and prev is not None:
        frame = prev.frame
    if frame is None and profile.get("frame") in _FRAME_NAMES:
        frame = profile["frame"]
    return ResolvedOptions(src, tgt, level, frame)


def _brief(opts: PromptOptions) -> _Brief:
    resolved = resolve_options(opts)
    if opts.scenes is not None and not SCENES_MIN <= opts.scenes <= SCENES_MAX:
        raise ValueError(f"scenes must be between {SCENES_MIN} and {SCENES_MAX} (got "
                         f"{opts.scenes}); langwich checks stories of that length")
    cont = continuation(opts.continue_from) if opts.continue_from is not None else None
    legacy = opts.from_legacy if isinstance(opts.from_legacy, dict) else None
    spec = LEVELS[resolved.level]
    scenes = opts.scenes or (COMPACT_SCENES if opts.compact else spec.scenes)
    topic = opts.topic or _legacy_value(legacy, "topic")
    return _Brief(resolved.source_lang, resolved.target_lang, resolved.level, spec, scenes,
                  topic, resolved.frame, cont, opts)


def _beat_plan(n: int) -> str:
    """The beats for ``n`` scenes, e.g. 'setup → complication → resolution'."""
    if n <= 2:
        beats = ["setup", "resolution (with the complication in it)"][:max(n, 1)]
    elif n == 3:
        beats = ["setup", "complication", "resolution"]
    elif n == 4:
        beats = ["setup", "development", "complication", "resolution"]
    else:
        beats = ["setup"] + ["development"] * (n - 4) + ["complication", "climax", "resolution"]
    return " → ".join(beats)


def _values(b: _Brief) -> dict[str, object]:
    low, high = b.spec.words
    ps_low, ps_high = b.per_scene
    t_low, t_high = b.spec.tasks
    tw_low, tw_high = b.spec.target_words
    w_low, w_high = b.spec.writing
    tgt_base = locale.base_lang(b.tgt)
    src_base = locale.base_lang(b.src)
    quotes = QUOTES.get(tgt_base)
    alt, base_form, rule = _TARGET_EXAMPLES.get(tgt_base, _GENERIC_EXAMPLES)
    if tgt_base in _FLOUR and src_base in _FLOUR:
        translation_hint = "{{" + _FLOUR[tgt_base] + "::" + _FLOUR[src_base] + "}}"
    else:
        translation_hint = "{{T word::S meaning}}"
    t_name = _short_name(b.tgt)
    return {
        "ex_alt": alt, "ex_base": base_form, "ex_rule": rule, "ex_translation": translation_hint,
        "beat_plan": _beat_plan(b.scenes),
        "S": _short_name(b.src), "T": t_name,
        "S_full": language_name(b.src), "T_full": language_name(b.tgt),
        "a_T": _indefinite(t_name),
        "src": b.src, "tgt": b.tgt, "level": b.level, "a_level": _indefinite(b.level),
        "level_name": _LEVEL_NAMES[b.level], "n": b.scenes,
        "n_scenes": _plural_word(b.scenes, "scene"),
        "w_low": low, "w_high": high, "ps_low": ps_low, "ps_high": ps_high,
        "t_low": t_low, "t_high": t_high, "tw_low": tw_low, "tw_high": tw_high,
        "wr_low": w_low, "wr_high": w_high,
        "pf_low": b.spec.plot_facts[0], "pf_high": b.spec.plot_facts[1],
        "quotes": (f"{t_name} quotation marks ({quotes})" if quotes
                   else f"the usual {t_name} quotation marks"),
        **_noun_rules(b.tgt),
        "forms": _forms_rule(b.tgt),
        "scene_stages": " → ".join(s for s in STAGES if s in _SCENE_STAGES),
        "scene_stage_list": _and_list(s for s in STAGES if s in _SCENE_STAGES),
        "forms_check": f'"forms" for every {_verb_kinds(b.tgt)} verb.',
        "no_picture": NO_PICTURE_SENTINEL,
        "example_langs": _example_langs(b),
        "ex_tasks": len(MINI_EXAMPLE["tasks"]),
        "per_scene": "per one or two scenes" if b.level in PAIRED_SCENE_LEVELS else "per scene",
        "keep_simple": " Keep sentences simple." if b.level in _SIMPLE_LEVELS else "",
        "c_questions": ('questions with a "starter" (the first words of the answer)'
                        if b.level in _STARTER_LEVELS else "questions"),
    }


#: Stages of the tasks that follow a scene, in the planner's order.
_SCENE_STAGES = frozenset({"gist", "detail", "picture", "form", "practice"})

#: Levels at which the compact prompt asks for simple sentences.
_SIMPLE_LEVELS = frozenset({"A1", "A2", "B1"})
#: Levels at which the compact prompt asks for questions with a "starter" (it
#: prints only the first sentence of each rule, which leaves that out).
_STARTER_LEVELS = frozenset({"A1", "A2"})
#: The kinds the compact prompt's task list asks for, besides its picture task
#: (draw, or label with an attached picture); it prints only their rules.
_COMPACT_KINDS = frozenset({
    "match", "true_false", "multiple_choice", "questions", "cloze", "writing", "media_search",
})


def _example_langs(b: _Brief) -> str:
    if (b.src, b.tgt) == ("en", "de"):
        return "It has the same languages as yours."
    return (f"It is English → German; yours is {_short_name(b.src)} → {_short_name(b.tgt)}: "
            f"write every T field in {_short_name(b.tgt)} and every S field in "
            f"{_short_name(b.src)}, and follow {_short_name(b.tgt)} rules for articles, word "
            "order and quotation marks.")


# ---------------------------------------------------------------------------
# Sections — normal prompt
# ---------------------------------------------------------------------------

_INTRO = """\
# Write a langwich worksheet: a story-based lesson as JSON (schema "langwich/3")

You are an author of graded readers and an experienced language teacher. Write one printable
worksheet for an adult who speaks <<S>> and is learning <<T>> (<<level>>): a short story in
<<n_scenes>> that weaves true facts into fiction, plus the tasks that lead the learner through it —
before reading, scene by scene, and into writing of their own. Answer with one JSON object; the
program langwich checks it and typesets it in black and white for paper and e-paper. You write
every word the learner sees."""

_BRIEF = """\
## The brief

- Learner's language (source, `S` below): <<S_full>>
- Language being learned (target, `T` below): <<T_full>>
- Level: <<level>> (<<level_name>>)
- Topic: <<topic_line>>
- Frame: <<frame_line>>
- Story: <<n_scenes>>, <<w_low>>–<<w_high>> words in total (about <<ps_low>>–<<ps_high>> per scene)
- Tasks: <<t_low>>–<<t_high>>
- Pictures: <<picture_line>>"""

_QUALITY_BAR = """\
## The quality bar

Every sentence must earn its place: the sheet is worked through with a pen. The story is worth
reading for its own sake — the learner wants to know how it ends — and leaves them knowing a few
true, surprising things. Not an essay in costume: a story in which the facts matter to what
happens, with tasks that grow out of it and have clear, checkable answers."""

_CRAFT = """\
## 1. Story craft: fiction that carries facts

**Plan first.** Before you write, decide who wants what and what stands in the way, and pick
the <<pf_low>>–<<pf_high>> true facts the plot will turn on — and where each one enters the story. The
logline sums this up in one sentence.

**People and stakes.** A protagonist with a name, an age or job, and a concrete goal with
something at stake (a test, a deadline, a promise, a guest to impress); one to three others with
clear roles (mentor, rival, friend), each with a voice of their own.

**Beats.** One beat per scene, set in "beat" — for <<n_scenes>>: <<beat_plan>>. Link scenes by
*but* and *therefore*, not *and then*. Each scene has a concrete
place and time (heading or first sentence), something happens, one or two sensory details
(smell, sound, texture), some direct speech, and a small hook at the end.

**Complication and payoff.** Something goes wrong because of a choice or a real-world
constraint (the dough will not rise in the cold kitchen). The resolution uses something true
that the protagonist — and the learner — found out on the way. That is how facts become plot.

**Show, don't lecture.** Facts arrive through what characters see, do, ask, read and explain to
each other — a mentor at work, a sign, a phone call — not through a narrator's lecture. At most
two fact sentences in a row. No "as you know" dialogue, no moral at the end.

**Facts must be true** — in the story, the facts, the tasks and the model answers: correct and
checkable in a standard reference. Never invent numbers, statistics, dates, records, studies,
quotes or sources; claim a superlative (oldest, largest, first) only if you are certain. Vague
but true beats precise but wrong ("for centuries", not "since 1407"). If unsure, leave it out.
The characters and their plot are fiction; the world they live in is real. Never put invented
words into a real person's mouth.

**"Did you know?"** 1–3 "facts": short, surprising, true, not already told by the story, 1–3
sentences in T at the learner's level, placed beside a scene ("scene"). An optional "title" names
the fact (langwich prints "Did you know?" itself). A "source" only if you are sure of a real,
general one ("UNESCO"); otherwise none.

**Frame.** <<frame_advice>>

**Tone.** For adults: warm, specific, a little humour; no children's-book voice, no preaching.
Concrete nouns ("a jute sack from Ethiopia", not "some coffee"); a last line that echoes the
first. Title (T): short and evocative. Standfirst (S, 1–2 sentences): the stakes, and what the
learner will find out."""

_LEVEL_HEAD = """\
## 2. Level

| Level | Story words | Per scene | Sentences | Structures | Dialogue |
|---|---|---|---|---|---|"""

_LEVEL_TAIL = """\
Use the **<<level>>** row. Most words should be known at <<level>>; the key words (section 4)
occur in the story, ideally more than once."""

_LANGUAGES = """\
## 3. Which language where

- **T (<<T>>):** title, scene headings and texts, captions, label terms, facts, vocabulary
  terms, grammar examples, series title and teaser ("next"), and every task item — statements,
  questions, options, events, gap texts, dialogue lines, model answers, "must_use" words,
  search queries and questions.
- **S (<<S>>):** standfirst, logline, setting, roles, topic, scene translations (give every
  scene a faithful one; they are printed with the solutions), vocabulary translations, grammar
  names and explanations, the recap ("previously"), task titles and instructions, writing and
  draw prompts, dialogue cues. The picture "prompt" (never printed) is in English.
- Task titles (S) belong to the story, like "Thursday: a second chance" — never "Exercise 3".
  Instructions (S) set the scene ("Lena writes to her mum.") and say exactly what to do,
  including how many word-box words are left over.
- Direct speech in <<quotes>>; in JSON a straight double quote must be escaped as \\"."""

_VOCABULARY = """\
## 4. Vocabulary

- "target": the <<tw_low>>–<<tw_high>> key words — right for the level, carried by the story and
  the topic. Each occurs in the story (inflected is fine) and in at least three tasks (the
  warm-up match, a cloze gap, "must_use", a label …), spelt exactly like its "items" term.
- "items": every key word, plus every word in the story, facts and tasks that <<a_level>> <<level>> learner
  may not know (typically 15–40), with a short S "translation" and "pos". Words that no task
  tests are printed as glosses beside their scene, so be generous.
- <<nouns>> <<forms>>"""

_GRAMMAR = """\
## 5. Grammar

1–2 points the story really uses (at least twice), right for the level: "name" and
"explanation" (1–3 sentences) in S, a compact "rule" ("<<ex_rule>>"), an optional
small "table" (≤ 6 rows) and 2–3 "examples" from the story. Practise each point in a form task
(see the lesson arc) whose "grammar" is its id. The grammar box is printed beside that task, so
it must never show that task's answers — not in the rule, the table or the examples. It may show the same pattern with OTHER words: a table of other verbs
(or nouns) that follow the rule, examples from the story that the task does not ask for. The
example below shows können, wollen and sollen in its table; its form task asks for müssen and
dürfen."""

_ARC = """\
## 6. The lesson arc

langwich prints the tasks in lesson order, whatever their order in the JSON: **Before you
read** (every warm_up task) → **the story**: each scene, followed by the tasks whose "scene" is
that scene (several scenes: the last one), sorted <<scene_stages>> — so give each of these
tasks its scene → **Your turn** (production) → **Take it further** (epilogue). Picture tasks
come right after the comprehension tasks of their scene; form and practice tasks move on.

Recommended set for <<level>> (<<t_low>>–<<t_high>> tasks):
<<recipe>>

A practice text CONTINUES the story in new sentences — the next morning, a note, a message, a
moment the story skipped — and never copies it; a word-bank cloze has 5–7 key words as gaps.
The writing task: <<wr_low>>–<<wr_high>> words ("min_words", "max_words"), "lines" (about one per
8 words), "model_answer" and, when written in T, 4–7 key words in "must_use"; langwich prints
the word range and the lines itself — don't repeat them in the instruction. The personal
question (no model answer) links the topic to the learner's life."""

_ITEMS = """\
## 7. Item quality

- **One defensible answer.** Each gap's sentence forces its answer by meaning and grammar. If
  another word fits too, list it (<<ex_alt>>) or rewrite the sentence.
- **No give-aways.** No gap at the start of a sentence; the answer appears nowhere else in the
  task. In a word box — a cloze with "hint": "word_bank", a dialogue with "bank": true — each
  word fits exactly one gap, in the form the gap needs, and 2–3 "distractors" make sure the
  last gap is not free by elimination. Distractors match the answers in word class and form
  (capitals and endings reveal nothing) and are plausible but wrong in every gap.
- **New sentences** for form and practice items; comprehension items paraphrase, not quote.
- <<kind_rules>>

**Gap markup** only in cloze "text"/"items", dialogue "lines[].text", table "rows",
gapped_text and proofread "text" and transform "frame": {{answer}}, {{answer|alternative}},
{{answer::hint}}. Never in the story or any other field."""

_PICTURE_DRAWN = """\
## 8. The picture

One scene — the one with the richest setting, often the last — gets a picture. Choose A if you
can draw clean line art, otherwise B.

**A. Line drawing.** "svg": simple black line art, e.g. `<svg xmlns='http://www.w3.org/2000/svg'
viewBox='0 0 200 120' fill='none' stroke='#000' stroke-width='1.5' stroke-linecap='round'>…
</svg>` (single quotes inside need no JSON escaping). Stroke-only line, rect, circle, ellipse,
polyline and path; <<svg_colour>>, no text, no gradients or images, at most ~80 elements. Draw
a few large, recognisable objects that the scene mentions, apart from each other. Then
"labels": 4–8 of them, "term" <<label_term>>, numbered 1, 2, 3 …, "x"/"y" = the object's
centre as a fraction of the viewBox: x = (cx − min-x) / width, y = (cy − min-y) / height
(0, 0 = top-left). Use a label task. <<label_bank>>

**B. No drawing.** No "svg", no "labels"; a draw task on that scene instead: the learner draws
the scene and labels 4–6 T words.

Always add "caption" (T) and "prompt": an English description of the scene as a
<<prompt_style>>, for an illustrator or image generator (never printed). <<colour_rule>>"""

_PICTURE_ATTACHED = """\
## 8. The picture (attached)

A picture is attached to this conversation. Study it first and build the story around it.
- Take the setting, the topic<<and_topic>> and the facts from what is visible. Name a real place
  or thing only if you recognise it with certainty. People in it are fictional characters —
  never guess who they are.
- One scene describes exactly what the picture shows — people, place, objects, what is
  happening — so the learner can compare text and picture; nothing in it contradicts the
  picture. That scene gets "picture": {"image": …, "caption": T, "labels": […]}, no "svg".
  Copy this "image" into it exactly, character for character:

<<image_line>>

- "labels": 4–8 clearly visible objects that the scene text mentions, "term" <<label_term>>,
  numbered 1, 2, 3 …, "x"/"y" = the object's centre as fractions of the picture's width and
  height, estimated from the picture (0, 0 = top-left, 1, 1 = bottom-right; the middle of the
  lower-left quarter is x 0.25, y 0.75). The printed marker is about 7 mm wide: for a small
  object put the point just beside it, not on it. Add every label term to vocabulary.items.
  <<label_bank>>
- "credit": if the picture is not the learner's own (a photo from Wikimedia Commons, Flickr,
  a book …), write the attribution its licence requires, e.g. "Photo: Jane Doe, CC BY 2.0".
- Tasks: a label task on that scene and, if it fits, questions about the picture (where things
  are, what people are doing).
- If no picture is attached or you cannot see it, reply only with: <<no_picture>>"""

_SERIES_NEXT = """\
## 9. This is episode <<episode>> of the series "<<series_title>>"

The story so far:

<<story_so_far>>

How the last episode ended (its final scene):

<<last_scene>>

<<teaser_block>>Characters — list everyone who appears in "story.characters", reusing these ids and
names exactly (change a role only if the story changed it); new characters are welcome:

<<characters>>

Review words from earlier episodes: <<review_words>>

- "series": {"id": "<<series_id>>", "title": "<<series_title>>", "episode": <<episode>>,
  "previously": S (a 2–3 sentence recap of the story so far), "next": T (a one- or two-sentence
  teaser for episode <<next_episode>>), "review": [5–8 of the review words]}.
- <<pickup>> The characters keep their personalities and history; let something from the last
  episode matter again.
- <<topic_advice>> New facts and new key words ("target" repeats no review word).
- Recycle every word in "series.review" in the warm-up or practice tasks, and in the story
  where it fits naturally.
- A new title for this episode (T); end on a hook that makes the learner want the next one."""

_SERIES_FIRST = """\
## 9. This is episode 1 of a series

Add "series": {"id": a short slug such as "<<series_id_hint>>", "title": T (the series name, e.g.
the protagonist and the place), "episode": 1, "next": T (a one- or two-sentence teaser for
episode 2), "review": []}. Give the protagonist a life that can carry more episodes (a job, a place, people, an open
question), and end so that the learner wants the next one."""

_FROM_TEXT = """\
## 9. Build on the text in the Material section

- Keep its facts: every factual claim in the worksheet comes from the text or is common
  knowledge you are sure of. Take the topic and the key words from it.
- If it already is a story at about <<level>> level in <<T>>, keep its wording (fix only
  mistakes), split it into <<n_scenes>> with headings and beats, and translate them.
- Otherwise re-tell it as a story in the chosen frame — characters who experience, discover or
  explain its facts — in <<T>> at <<level>> level. If it is long, follow its most interesting
  thread."""

_FROM_LEGACY = """\
## 9. Upgrade the langwich 2 file in the Material section

It has a flat text ("content"), vocabulary, grammar notes and a picture description. Reuse its
topic, its facts (check them; drop anything you are not sure is true), its vocabulary (as "items" with articles, plurals and forms; choose the
key words from it), its grammar (as grammar points with explanation, rule and examples from
your story) and its picture scene: "picture_scene.description" becomes the picture of one scene
(caption, English prompt, and a drawing or draw task as in the picture section; its "elements" are good
label terms). Rewrite the text as a story — characters, goal, complication, resolution — and
write all tasks new.<<legacy_langs>>"""

_UI = """\
## Page labels in <<S>>

langwich has no built-in page labels in <<S>>. Add "ui": the object below with every value
translated into <<S>> (keep the keys and any {placeholders}):

<<ui_json>>"""

_EXAMPLE_HEAD = """\
## <<number>>. Example

A shortened English → German A2 worksheet (2 scenes, <<ex_tasks>> tasks) that shows the format and
the craft in miniature. <<example_langs>> Yours follows the brief: <<n_scenes>>,
<<t_low>>–<<t_high>> tasks, your own topic. Do not copy its story."""

_CHECKLIST = """\
## Before you answer, check

- Story: protagonist, goal, stakes, a real complication, a payoff that turns on a true fact;
  place, time, action and dialogue in every scene; <<w_low>>–<<w_high>> words in total.
- Facts: all true, nothing invented; 1–3 "facts" with a "scene".
- Key words: in "items" (same spelling), in the story, in at least three tasks.
  <<noun_check>> <<forms_check>>
- Languages: T and S in the right fields; every scene translated; task titles from the story.
- Tasks: unique ids; every <<scene_stage_list>> task has a "scene"; all
  references exist; one defensible answer per gap and none at the start of a sentence; practice
  texts are new; multiple_choice answers copied from the options; events in story order; the
  grammar box shows none of its task's answers; word boxes have distractors.
- Picture: labels on real objects (x, y between 0 and 1); a label task only with image or svg.
- JSON: double quotes, no trailing commas, no comments, \\n\\n between paragraphs, only the
  fields of the reference."""

_OUTPUT = """\
## Output

Reply with the JSON object only: start with { and end with }, with no Markdown code fence, no
comment and no text before or after it. "schema": "langwich/3". Write real UTF-8 characters
(ä, é, ñ), not escape codes."""

_WISHES = """\
## Learner's wishes

<<notes>>

(These wishes take priority over the defaults above, but not over the JSON format.)"""


# ---------------------------------------------------------------------------
# Sections — compact prompt
# ---------------------------------------------------------------------------

_C_INTRO = """\
# Write a langwich worksheet as JSON (schema "langwich/3") — short version

Write one worksheet for an adult who speaks <<S>> and learns <<T>> (<<level>>): a short story in
<<n_scenes>> that mixes true facts with fiction, and <<t_low>>–<<t_high>> tasks about it. Answer with
one JSON object."""

_C_BRIEF = """\
## Brief

- S = <<S_full>> (the learner's language), T = <<T_full>> (the language learned), level <<level>>
- Topic: <<topic_line>>
- Frame: <<frame_line>>
- Story: <<n_scenes>>, <<w_low>>–<<w_high>> words in total. Sentences: <<sentences>>; grammar:
  <<structures>>.<<keep_simple>>"""

_C_RULES = """\
## Rules

**Story.** A named main character wants something concrete. Beats: <<beat_plan>> — the goal,
then a real problem, then a solution that uses something true learned on the way. Each scene: a place, a time, action, a little
dialogue. Facts come through what the characters see, do and say — no lecture.

**Facts.** Every fact must be true. Never invent numbers, dates, records or sources; if unsure,
leave it out. Add 1–2 true "facts" (T) with a "scene".

**Languages.** T: title, headings, scene texts, facts, captions, labels, vocabulary terms,
grammar examples, every task item. S: standfirst, logline, roles, topic, scene translations
(optional), grammar name and explanation, task titles and instructions, writing and draw prompts.

**Vocabulary.** "target": <<tw_low>>–<<tw_high>> key words, each in the story and in at least three
tasks, spelt as in "items". "items": the key words plus other words the learner may not know
(15–25). <<nouns>> <<forms>>

**Grammar.** One point the story uses, practised by a form task whose "grammar" is its id. The
grammar box is printed beside that task: it may show the pattern with other words, never the
task's answers.

**Tasks.** <<t_low>>–<<t_high>> in all; every task except warm_up, production and epilogue gets a
"scene".
1. warm_up · match: the key words (T) and their meanings (S), plus 1 "extra".
2. gist/detail: one task <<per_scene>> (true_false, multiple_choice or <<c_questions>>).
3. picture: <<picture_tasks>>
4. form: a cloze that practises the grammar point; for verb forms "hint": "base_form"
   (<<ex_base>>).
5. practice: a word-bank cloze that CONTINUES the story in NEW sentences (never copy the story),
   with 5–6 key words and 2 distractors.
6. production: writing from a character's point of view: "starter", "must_use",
   <<wr_low>>–<<wr_high>> words ("min_words", "max_words"), "model_answer". langwich prints the
   word range itself — don't repeat it in the instruction. Plus one personal question
   (questions, no model answer).
7. epilogue: media_search.

**Items.** One right answer per gap; no gap at the start of a sentence. Titles (S) belong to
the story ("Sunday: the way back"). Gap markup {{answer}}, {{answer|other}}, {{answer::hint}}
only in cloze, dialogue, table, gapped_text, proofread and a transform "frame".

**Kinds.** <<kind_rules>>"""

_C_PICTURE_DRAWN = """\
**Picture.** Give one scene a "picture" with a "caption" (T) and an English "prompt" (a
<<prompt_style>> of the scene; not printed) — no "svg", no "labels". The picture task is a draw
task: the learner draws the scene and labels 4–6 T words."""

_C_PICTURE_ATTACHED = """\
**Picture.** A picture is attached to this conversation. Look at it first and build the story
around it: one scene describes exactly what it shows. That scene gets "picture": {"image": …,
"caption": T, "labels": [4–6 visible objects: {"n": 1, "term": T noun, "x": 0–1, "y": 0–1}]},
with this "image", copied exactly:

<<image_line>>

x and y are the object's centre as fractions of the picture's width and height (0, 0 =
top-left); for a small object, a point just beside it. Label terms <<label_term>>. Use a
label task on that scene. If the picture is not the learner's own, give its licence
attribution in "credit". People in it are fictional — never guess who they are. If you cannot
see a picture, reply only: <<no_picture>>"""

_C_CHECK = """\
## Check, then answer

Protagonist, goal, problem, solution? Facts true? Key words in items, story and three tasks?
Every gap has one answer? Valid JSON with only the fields above?

Reply with the JSON object only — start with {, end with }, no code fence, no comments."""


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _topic_line(b: _Brief) -> str:
    if b.topic:
        return b.topic + (" — and what the attached picture shows" if b.opts.image else "")
    if b.opts.image:
        return "derive it from the attached picture"
    if b.cont is not None:
        return "your choice — follow where the teaser points (see the series section)"
    if b.opts.from_text:
        return "take it from the text in the Material section"
    return ("not given — choose an engaging, concrete topic with real facts to discover (a food, "
            "a craft, a place, an animal, an invention, a job, a festival, a moment in history)")


def _frame_line(b: _Brief) -> str:
    if b.frame:
        return f"{b.frame} — {FRAMES.get(b.frame, 'as described')}"
    return 'your choice: pick the frame that fits the topic best and set "frame"'


def _frame_advice(b: _Brief) -> str:
    if b.frame:
        return (f"Your frame is **{b.frame}**: {FRAMES.get(b.frame, 'as described')}. Keep all "
                "of the craft above within it.")
    options = "; ".join(f"**{name}** — {desc}" for name, desc in FRAMES.items())
    return ("If the topic has no obvious story, a frame gives it one. Choose what fits the "
            f"topic and level and set \"frame\": {options}.")


def _level_rows(b: _Brief) -> str:
    """The learner's level between the levels below and above it: enough to
    calibrate, without the rows that are far away."""
    order = list(LEVELS)
    i = order.index(b.level)
    rows = []
    for level in order[max(i - 1, 0):i + 2]:
        spec = LEVELS[level]
        n = b.scenes
        low, high = spec.words
        mark = f"**{level}**" if level == b.level else level
        rows.append(
            f"| {mark} | {low}–{high} | {_round5(low / n)}–{_round5(high / n)} | "
            f"{spec.sentences} | {spec.structures} | {spec.dialogue} |"
        )
    return "\n".join(rows)


def _picture_values(b: _Brief) -> dict[str, object]:
    colour = b.opts.color
    return {
        "image_line": _image_line(b.opts.image),
        "and_topic": " (together with the topic in the brief)" if b.topic else "",
        "svg_colour": "colour only where it helps" if colour else "no colour",
        "prompt_style": "line drawing with a few colours" if colour
                        else "black-and-white line drawing",
        "colour_rule": ("Colour is allowed in the picture, but every task must work in "
                        "greyscale." if colour else
                        "The sheet is printed in black and white: no task may depend on "
                        "seeing a colour."),
    }


def _image_line(image: str | None) -> str:
    """The ``"image": …`` line the LLM copies: JSON-escaped (a Windows path's
    backslashes stay valid JSON) and printed verbatim (never re-wrapped, so a
    path with spaces is not split)."""
    if not image:
        return ""
    return _keep('"image": ' + json.dumps(image, ensure_ascii=False))


def _picture_line(b: _Brief) -> str:
    if b.opts.image:
        return "built around the attached picture (see the picture section)"
    if b.opts.color:
        return "colour allowed, but every task must work in greyscale"
    return "black and white only (printed on paper or e-paper)"


def _picture_tasks(b: _Brief) -> str:
    if b.opts.image:
        return ("a label task on the scene with the attached picture; optionally a questions "
                "task about the picture (where things are).")
    if b.opts.compact:
        return "a draw task on the scene with the picture."
    return ("on the scene with the picture: a label task (drawing A) or a draw task (B); "
            "optionally a questions task about the picture (where things are).")


def _series_section(b: _Brief, values: Mapping[str, object]) -> str | None:
    cont = b.cont
    if cont is not None:
        chars = "\n".join(
            f"- \"{c.id}\": {c.name}" + (f" — {c.role}" if c.role else "") for c in cont.characters
        ) or "- (none listed — introduce the protagonist again)"
        teaser = (f"The last episode ended with this teaser — pick it up:\n\"{cont.teaser}\"\n\n"
                  if cont.teaser else "")
        pickup = ("Start where the teaser points; keep the setting unless the teaser moves the "
                  "story." if cont.teaser else
                  "Start soon after the last scene, in the same setting or one that follows "
                  "naturally.")
        prev = b.opts.continue_from
        if b.topic:
            topic_advice = f"The topic of this episode: {b.topic}."
        else:
            old = f" (last time: {prev.topic})" if prev is not None else ""
            topic_advice = ("Choose a new topic the story leads to, or a new side of the old "
                            f"one{old}.")
        extra = {
            "episode": cont.episode, "next_episode": cont.episode + 1,
            "series_id": cont.series_id, "series_title": cont.series_title,
            "story_so_far": cont.story_so_far,
            "last_scene": _fence(cont.last_scene, "text"),
            "teaser_block": teaser, "characters": chars,
            "review_words": ", ".join(cont.review_words) or "(none)",
            "pickup": pickup, "topic_advice": topic_advice,
        }
        return _fill(_SERIES_NEXT, {**values, **extra})
    start_series = b.opts.series if b.opts.series is not None else b.frame == "episode"
    if start_series:
        hint = f"{slugify(b.topic)}-series" if b.topic else "anna-in-lyon"
        return _fill(_SERIES_FIRST, {**values, "series_id_hint": hint})
    return None


def _legacy_material(legacy: dict) -> str:
    kept = {k: legacy[k] for k in _LEGACY_KEYS if k in legacy}
    return json.dumps(kept or legacy, ensure_ascii=False)


def _source_sections(b: _Brief, values: Mapping[str, object]) -> list[str]:
    out = []
    series = _series_section(b, values)
    if series:
        out.append(series)
    if b.opts.from_text:
        out.append(_fill(_FROM_TEXT, values))
    if b.opts.from_legacy:
        legacy = b.opts.from_legacy
        langs = ""
        old = (legacy.get("source_lang"), legacy.get("target_lang"), legacy.get("cefr_level"))
        if all(isinstance(x, str) for x in old) and (
            old[0] != b.src or old[1] != b.tgt or str(old[2]).upper() != b.level
        ):
            langs = (f" The old file is {old[0]} → {old[1]}, {old[2]}; this worksheet follows the "
                     f"brief ({b.src} → {b.tgt}, {b.level}).")
        out.append(_fill(_FROM_LEGACY, {**values, "legacy_langs": langs}))
    if len(out) > 1:
        # several starting points: number them 9a, 9b, …
        out = [s.replace("## 9. ", f"## 9{chr(97 + i)}. ", 1) for i, s in enumerate(out)]
    return out


def _material(b: _Brief) -> str | None:
    parts = []
    if b.opts.from_text:
        parts.append("The text to build on:\n\n" + _fence(b.opts.from_text.strip(), "text"))
    if b.opts.from_legacy:
        parts.append("The langwich 2 file:\n\n" + _fence(_legacy_material(b.opts.from_legacy),
                                                         "json"))
    if not parts:
        return None
    return "## Material\n\n" + "\n\n".join(parts)


def _ui_section(b: _Brief, values: Mapping[str, object]) -> str | None:
    if locale.base_lang(b.src) in locale.BUILTIN_LANGUAGES:
        return None
    ui = json.dumps(locale.STRINGS["en"], ensure_ascii=False, indent=0)
    return _fill(_UI, {**values, "ui_json": _fence(ui, "json")})


class _Verbatim(str):
    """A section that is printed exactly as it is (never reflowed)."""


def _wishes(b: _Brief) -> str | None:
    if not b.opts.notes or not b.opts.notes.strip():
        return None
    return _Verbatim(_fill(_WISHES, {"notes": b.opts.notes.strip()}))


def build_prompt(opts: PromptOptions) -> str:
    """The complete authoring prompt (Markdown) for the options given."""
    b = _brief(opts)
    values: dict[str, object] = {
        **_values(b),
        **_picture_values(b),
        "topic_line": _topic_line(b),
        "frame_line": _frame_line(b),
        "picture_line": _picture_line(b),
        "picture_tasks": _picture_tasks(b),
        "sentences": b.spec.sentences,
        "structures": b.spec.structures,
    }
    # (the recipe and the rules contain markers themselves: fill them before
    # they are inserted)
    values["recipe"] = _fill(b.spec.recipe, values)
    values["kind_rules"] = _fill(kind_rules(b.spec.kinds), values)
    if opts.compact:
        sections = _compact_sections(b, values)
    else:
        sections = _normal_sections(b, values)
    parts = [
        str(s).strip() if isinstance(s, _Verbatim) else _reflow(s.strip())
        for s in sections if s and s.strip()
    ]
    return "\n\n".join(parts).replace(_KEEP, "") + "\n"


def _normal_sections(b: _Brief, values: dict[str, object]) -> list[str | None]:
    values = {**values, "frame_advice": _frame_advice(b)}
    picture = _PICTURE_ATTACHED if b.opts.image else _PICTURE_DRAWN
    sources = _source_sections(b, values)
    n_example = 11 if sources else 10
    n_reference = n_example - 1
    return [
        _fill(_INTRO, values),
        _fill(_BRIEF, values),
        _fill(_QUALITY_BAR, values),
        _fill(_CRAFT, values),
        _LEVEL_HEAD + "\n" + _level_rows(b) + "\n\n" + _fill(_LEVEL_TAIL, values),
        _fill(_LANGUAGES, values),
        _fill(_VOCABULARY, values),
        _fill(_GRAMMAR, values),
        _fill(_ARC, values),
        _fill(_ITEMS, values),
        _fill(picture, values),
        *sources,
        _ui_section(b, values),
        f"## {n_reference}. Field reference\n\n" + field_reference(values),
        _fill(_EXAMPLE_HEAD, {**values, "number": n_example})
        + "\n\n" + _fence(example_json(), "json"),
        _material(b),
        _wishes(b),
        _fill(_CHECKLIST, values),
        _fill(_OUTPUT, values),
    ]


def _compact_sections(b: _Brief, values: dict[str, object]) -> list[str | None]:
    picture = _C_PICTURE_ATTACHED if b.opts.image else _C_PICTURE_DRAWN
    # the rules of the kinds its task list asks for — a small model needs no more
    kinds = _COMPACT_KINDS | {"label" if b.opts.image else "draw"}
    values = {**values,
              "kind_rules": _fill(kind_rules((k for k in b.spec.kinds if k in kinds), core=True),
                                  values)}
    sources = [re.sub(r"^## 9[a-z]?\. ", "## ", s) for s in _source_sections(b, values)]
    return [
        _fill(_C_INTRO, values),
        _fill(_C_BRIEF, values),
        _fill(_C_RULES, values) + "\n\n" + _fill(picture, values),
        *sources,
        _ui_section(b, values),
        "## Field reference\n\n" + field_reference(values, terse=True),
        f"## Example (shortened: 2 scenes, {len(compact_example()['tasks'])} tasks — do not "
        "copy its story)\n\n" + _fence(example_json(compact=True), "json"),
        _material(b),
        _wishes(b),
        _C_CHECK,
    ]


# ---------------------------------------------------------------------------
# Repair
# ---------------------------------------------------------------------------


def _issue_lines(issues: Iterable[Any], level: str) -> list[str]:
    out = []
    for issue in issues:
        if getattr(issue, "level", "error") != level:
            continue
        where = getattr(issue, "where", "") or "/"
        code = getattr(issue, "code", "")
        message = getattr(issue, "message", str(issue))
        out.append(f"- `{where}`" + (f" [{code}]" if code else "") + f": {message}")
    return out


def _reference_values(json_text: str) -> dict[str, object]:
    """Language names and level for the field reference, read from a
    (possibly broken or wrapped) worksheet JSON."""
    try:
        data, _ = parse_json_text(json_text)
    except (ContractError, TypeError):
        data = None
    data = data if isinstance(data, dict) else {}

    def lang(key: str, fallback: str) -> tuple[str, str]:
        code = data.get(key)
        if isinstance(code, str) and _LANG_RE.match(code):
            return _short_name(code), code
        return fallback, "xx"

    s_name, src = lang("source_lang", "the learner's language")
    t_name, tgt = lang("target_lang", "the language being learned")
    level = data.get("cefr_level")
    return {"S": s_name, "T": t_name, "src": src, "tgt": tgt,
            "level": level if level in LEVELS else "B1"}


def repair_prompt(report: Any, json_text: str) -> str:
    """A short prompt asking the LLM to fix the problems in ``report``
    (anything with ``.issues`` of :class:`langwich.validate.Issue`).

    Problems only the user can fix (:data:`langwich.validate.ENVIRONMENT_CODES`,
    e.g. a photo that is missing or cannot be decoded) are left out. When the
    file does not match the schema (``contract`` issues), the terse field
    reference is appended, so a model in a fresh conversation can fix it too.

    Raises :class:`ValueError` when the file is the prompt's
    ``NO PICTURE ATTACHED`` reply (a ``no-picture-attached`` issue): the model
    could not see the picture, and a repair prompt would only make it invent
    a worksheet without it.
    """
    issues = list(getattr(report, "issues", []) or [])
    for issue in issues:
        if getattr(issue, "code", "") == "no-picture-attached":
            raise ValueError(getattr(issue, "message", str(issue)))
    issues = [i for i in issues if getattr(i, "code", "") not in ENVIRONMENT_CODES]
    errors = _issue_lines(issues, "error")
    warnings = _issue_lines(issues, "warning")
    parts = [
        f"# Fix this {SCHEMA_ID} worksheet",
        "Your langwich/3 JSON has the problems listed below. Errors must be fixed; warnings "
        "should be fixed too. Locations are JSON pointers (`/tasks/3/items/0` = the first item "
        "of the fourth task).",
    ]
    if errors:
        parts.append("## Errors\n\n" + "\n".join(errors))
    if warnings:
        parts.append("## Warnings\n\n" + "\n".join(warnings))
    if not errors and not warnings:
        parts.append("(No problems were reported — return the JSON unchanged.)")
    parts.append(
        "Fix every problem, keep everything else as it is (the story, the facts and the tasks "
        "that are fine), and return the complete corrected JSON — the JSON object only: start "
        "with {, end with }, no Markdown code fence, no comments."
    )
    if any(getattr(i, "code", "") == "contract" for i in issues):
        parts.append("## Field reference (langwich/3)\n\n"
                     + field_reference(_reference_values(json_text), terse=True))
    parts.append("## The JSON\n\n" + _fence(json_text.strip(), "json"))
    return "\n\n".join(parts) + "\n"
