"""Import vocabulary and phrases from JSON — the LLM-friendly data path.

When langwich is used via an AI assistant (e.g. Claude Code), the LLM itself
acts as the NLP engine: it generates domain-relevant vocabulary, translations,
CEFR levels, and example phrases directly.  This module imports that structured
data into the per-domain SQLite database so the worksheet generator can use it.

See ``examples/film_de_fr.json`` for a complete working example.

Expected JSON format
────────────────────
{
  "domain": "railway-operations",
  "source_lang": "en",
  "target_lang": "de",

  "vocabulary": [
    {
      "term": "platform",
      "lemma": "platform",
      "pos": "NOUN",
      "cefr": "A2",
      "translations": ["Bahnsteig", "Gleis"],
      "frequency": 0.85
    }
  ],

  "phrases": [
    {
      "text": "The train departs from platform 3.",
      "translation": "Der Zug fährt von Gleis 3 ab.",
      "cefr": "A2"
    }
  ],

  "grammar": {
    "topic": "Present Tense",
    "content": "Complete grammar explanation — rules, tables, examples.
                Rendered directly onto the PDF grammar page."
  },

  "reading": {
    "passage": "Coherent multi-paragraph reading text in the target language.",
    "questions": ["Comprehension question 1", "...up to 5 questions"]
  },

  "exercises": {
    "vocab_matching": { "items": [{"number": 1, "term": "...", "translation": "..."}] },
    "fill_blanks":    { "items": [{"number": 1, "sentence": "...", "target": "..."}],
                        "word_bank": ["word1", "word2"] },
    "synonyms":       { "items": [{"number": 1, "term": "...", "pos": "ADJ",
                                    "synonym": "...", "antonym": "..."}] },
    "translation":    { "items": [{"number": 1, "source": "Sentence to translate."}] },
    "creative_writing": { "prompt": "Writing prompt text",
                          "vocab_required": ["word1", "word2"] },
    "text_summary":   { "passage": "Text for the student to summarise." },
    "youtube_task":   { "video_url": "https://...",
                        "questions": ["Question about the video"] },
    "drawing_task":   { "prompt": "Draw a scene showing..." }
  }
}

The ``grammar``, ``reading``, and ``exercises`` sections are optional but
strongly recommended.  Without them, the worksheet will use low-quality
fallbacks or skip content entirely.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from langwich.db.manager import DomainDatabase
from langwich.db.models import CEFRLevel, ClassificationMethod, PartOfSpeech

logger = logging.getLogger(__name__)

# Map short POS strings to the enum
_POS_MAP: dict[str, PartOfSpeech] = {
    "NOUN": PartOfSpeech.NOUN,
    "VERB": PartOfSpeech.VERB,
    "ADJ": PartOfSpeech.ADJECTIVE,
    "ADJECTIVE": PartOfSpeech.ADJECTIVE,
    "ADV": PartOfSpeech.ADVERB,
    "ADVERB": PartOfSpeech.ADVERB,
    "PREP": PartOfSpeech.PREPOSITION,
    "PREPOSITION": PartOfSpeech.PREPOSITION,
    "CONJ": PartOfSpeech.CONJUNCTION,
    "CONJUNCTION": PartOfSpeech.CONJUNCTION,
    "PRON": PartOfSpeech.PRONOUN,
    "PRONOUN": PartOfSpeech.PRONOUN,
    "DET": PartOfSpeech.DETERMINER,
    "DETERMINER": PartOfSpeech.DETERMINER,
    "INTJ": PartOfSpeech.INTERJECTION,
    "NUM": PartOfSpeech.NUMERAL,
    "PART": PartOfSpeech.PARTICLE,
    "OTHER": PartOfSpeech.OTHER,
}

_CEFR_MAP: dict[str, CEFRLevel] = {v.value: v for v in CEFRLevel}


def _parse_pos(raw: str) -> PartOfSpeech:
    return _POS_MAP.get(raw.upper(), PartOfSpeech.OTHER)


def _parse_cefr(raw: str) -> CEFRLevel:
    return _CEFR_MAP.get(raw.upper(), CEFRLevel.UNKNOWN)


def import_json(
    data: dict[str, Any],
    db_dir: Path | str = Path("./data"),
) -> DomainDatabase:
    """Import vocabulary and phrases from a JSON dict into a domain database.

    Parameters
    ----------
    data : dict
        JSON-compatible dict matching the schema described in this module's
        docstring.
    db_dir : Path | str
        Directory for SQLite files.

    Returns
    -------
    DomainDatabase
        The initialised and populated database.
    """
    domain = data["domain"]
    source_lang = data.get("source_lang", "en")
    target_lang = data.get("target_lang", "de")

    db = DomainDatabase(
        domain=domain,
        source_lang=source_lang,
        target_lang=target_lang,
        db_dir=db_dir,
    )
    db.initialize()

    vocab_count = 0
    for item in data.get("vocabulary", []):
        db.add_vocabulary(
            term=item["term"],
            lemma=item.get("lemma", item["term"].lower()),
            pos=_parse_pos(item.get("pos", "OTHER")),
            level=_parse_cefr(item.get("cefr", "UNKNOWN")),
            method=ClassificationMethod.LLM_FALLBACK,
            frequency=item.get("frequency", 0.5),
            translations=item.get("translations"),
        )
        vocab_count += 1

    phrase_count = 0
    for item in data.get("phrases", []):
        db.add_phrase(
            text=item["text"],
            translation=item.get("translation"),
            level=_parse_cefr(item.get("cefr", "UNKNOWN")),
            method=ClassificationMethod.LLM_FALLBACK,
        )
        phrase_count += 1

    # Grammar section (optional)
    grammar = data.get("grammar")
    if grammar:
        db.grammar_topic = grammar.get("topic", "")
        db.grammar_content = grammar.get("content", "")

    # Reading comprehension section (optional)
    reading = data.get("reading")
    if reading:
        db.reading_passage = reading.get("passage", "")
        db.reading_questions = reading.get("questions", [])

    # Pre-generated exercise content (LLM-driven workflow)
    exercises = data.get("exercises")
    if exercises:
        db.exercises = exercises

    logger.info(
        "Imported %d vocabulary + %d phrases into %s",
        vocab_count, phrase_count, db.db_path,
    )
    return db


def import_json_file(
    path: Path | str,
    db_dir: Path | str = Path("./data"),
) -> DomainDatabase:
    """Load a JSON file and import it. Convenience wrapper around ``import_json``."""
    path = Path(path)
    with open(path) as f:
        data = json.load(f)
    return import_json(data, db_dir=db_dir)
