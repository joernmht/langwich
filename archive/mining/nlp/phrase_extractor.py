"""Phrase and collocation extraction from running text.

Extracts example sentences and multi-word expressions suitable for
language learning exercises.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)

# Sentence length bounds (in words) for quality filtering.
_MIN_SENTENCE_WORDS = 5
_MAX_SENTENCE_WORDS = 30


class PhraseExtractor:
    """Extracts well-formed example sentences from a body of text.

    Applies heuristic quality filters to ensure extracted phrases are
    suitable for language learning worksheets.
    """

    def __init__(
        self,
        min_words: int = _MIN_SENTENCE_WORDS,
        max_words: int = _MAX_SENTENCE_WORDS,
    ) -> None:
        self.min_words = min_words
        self.max_words = max_words

    def extract(self, text: str) -> list[str]:
        """Return a list of clean, well-formed sentences from *text*.

        Filters out:
        - Very short or very long sentences
        - Sentences with excessive punctuation or special characters
        - Sentences that look like references / citations
        - All-caps sentences (headings)
        """
        # Naive sentence splitting (for full accuracy, use SpaCy's sentencizer)
        raw_sentences = re.split(r'(?<=[.!?])\s+', text)
        results: list[str] = []

        for sent in raw_sentences:
            sent = sent.strip()
            if not sent:
                continue

            words = sent.split()
            word_count = len(words)

            # Length filter
            if word_count < self.min_words or word_count > self.max_words:
                continue

            # Quality heuristics
            if self._is_citation(sent):
                continue
            if self._is_heading(sent):
                continue
            if self._has_excessive_special_chars(sent):
                continue

            results.append(sent)

        return results

    @staticmethod
    def _is_citation(sentence: str) -> bool:
        """Detect reference-style text (e.g. ``[1]``, ``et al.``)."""
        return bool(re.search(r'\[\d+\]', sentence)) or "et al." in sentence

    @staticmethod
    def _is_heading(sentence: str) -> bool:
        """Detect all-caps headings."""
        alpha_chars = [c for c in sentence if c.isalpha()]
        if not alpha_chars:
            return False
        return sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars) > 0.8

    @staticmethod
    def _has_excessive_special_chars(sentence: str) -> bool:
        """Reject sentences with too many non-word characters."""
        special = sum(1 for c in sentence if not c.isalnum() and not c.isspace())
        return special / max(len(sentence), 1) > 0.2
