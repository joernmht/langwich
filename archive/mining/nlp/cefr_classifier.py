"""CEFR level classifier with rule-based lookup and LLM fallback.

Strategy
────────
  1. Look up the word in bundled frequency lists (Oxford 5000, English Profile,
     Kelly list for Swedish/other languages).
  2. If found → return the mapped CEFR level and method ``FREQUENCY_LIST``.
  3. If not found → call scads.ai (OpenAI-compatible) to classify the word
     and return method ``LLM_FALLBACK``.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from langwich.config import ScadsConfig
from langwich.db.models import CEFRLevel, ClassificationMethod

logger = logging.getLogger(__name__)


# ── Bundled frequency list format ────────────────────────────────────
# Each list is a dict mapping lowercase lemma → CEFR level string.
# Lists are loaded lazily from JSON files in data/frequency_lists/.

_FREQUENCY_LIST_DIR = Path(__file__).parent.parent.parent / "data" / "frequency_lists"


class CEFRClassifier:
    """Classifies words and phrases to CEFR levels.

    Parameters
    ----------
    scads_config : ScadsConfig
        Configuration for the scads.ai LLM fallback endpoint.
    frequency_list_dir : Path | None
        Override the directory containing frequency list JSON files.
    """

    def __init__(
        self,
        scads_config: ScadsConfig,
        frequency_list_dir: Path | None = None,
    ) -> None:
        self.scads = scads_config
        self._list_dir = frequency_list_dir or _FREQUENCY_LIST_DIR
        self._lists: dict[str, CEFRLevel] | None = None

    # ── Public API ───────────────────────────────────────────────────

    def classify(self, lemma: str) -> tuple[CEFRLevel, ClassificationMethod]:
        """Return the CEFR level for a single word/lemma.

        Returns
        -------
        tuple[CEFRLevel, ClassificationMethod]
            The level and the method used to determine it.
        """
        level = self._lookup_frequency_list(lemma)
        if level is not None:
            return level, ClassificationMethod.FREQUENCY_LIST

        # LLM fallback
        level = self._classify_via_llm(lemma)
        return level, ClassificationMethod.LLM_FALLBACK

    def classify_phrase(self, phrase: str) -> tuple[CEFRLevel, ClassificationMethod]:
        """Classify a phrase by the highest CEFR level of its constituent words.

        Falls back to LLM classification if most words are unknown.
        """
        words = phrase.lower().split()
        levels: list[CEFRLevel] = []
        unknown_count = 0

        for word in words:
            level = self._lookup_frequency_list(word)
            if level is not None:
                levels.append(level)
            else:
                unknown_count += 1

        # If more than half the words are unknown, use LLM for the whole phrase
        if unknown_count > len(words) / 2:
            level = self._classify_via_llm(phrase)
            return level, ClassificationMethod.LLM_FALLBACK

        if not levels:
            return CEFRLevel.UNKNOWN, ClassificationMethod.FREQUENCY_LIST

        # The phrase level is the highest level among its known words
        level_order = [CEFRLevel.A1, CEFRLevel.A2, CEFRLevel.B1,
                       CEFRLevel.B2, CEFRLevel.C1, CEFRLevel.C2]
        max_level = max(levels, key=lambda lv: level_order.index(lv) if lv in level_order else -1)
        return max_level, ClassificationMethod.FREQUENCY_LIST

    # ── Frequency list lookup ────────────────────────────────────────

    def _load_lists(self) -> dict[str, CEFRLevel]:
        """Lazily load and merge all frequency list JSON files."""
        if self._lists is not None:
            return self._lists

        merged: dict[str, CEFRLevel] = {}
        if self._list_dir.is_dir():
            for json_file in sorted(self._list_dir.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    for lemma, level_str in data.items():
                        try:
                            merged[lemma.lower()] = CEFRLevel(level_str)
                        except ValueError:
                            pass
                except Exception as exc:
                    logger.warning("Failed to load %s: %s", json_file, exc)
        else:
            logger.info("No frequency list directory at %s", self._list_dir)

        self._lists = merged
        logger.info("Loaded %d entries from frequency lists", len(merged))
        return merged

    def _lookup_frequency_list(self, lemma: str) -> Optional[CEFRLevel]:
        """Look up a lemma in the merged frequency lists."""
        lists = self._load_lists()
        return lists.get(lemma.lower())

    # ── LLM fallback ─────────────────────────────────────────────────

    def _classify_via_llm(self, text: str) -> CEFRLevel:
        """Call scads.ai to classify a word or phrase.

        Uses a structured prompt asking for a JSON response with the CEFR level.
        """
        if not self.scads.api_key:
            logger.warning("No SCADS API key configured — returning UNKNOWN for %r", text)
            return CEFRLevel.UNKNOWN

        try:
            from openai import OpenAI

            client = OpenAI(
                api_key=self.scads.api_key,
                base_url=self.scads.base_url,
            )

            response = client.chat.completions.create(
                model=self.scads.model,
                temperature=self.scads.temperature,
                max_tokens=self.scads.max_tokens,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a CEFR language level classifier. "
                            "Given a word or phrase, respond with ONLY a JSON object: "
                            '{"level": "A1"|"A2"|"B1"|"B2"|"C1"|"C2"}. '
                            "Base your assessment on vocabulary frequency, "
                            "complexity, and typical learner exposure."
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Classify this: {text}",
                    },
                ],
            )

            content = response.choices[0].message.content or ""
            data = json.loads(content)
            return CEFRLevel(data["level"])
        except Exception as exc:
            logger.warning("LLM classification failed for %r: %s", text, exc)
            return CEFRLevel.UNKNOWN
