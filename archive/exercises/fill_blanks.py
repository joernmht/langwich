"""Fill-in-the-blanks exercise — complete sentences with missing vocabulary."""

from __future__ import annotations

import random
import re
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class FillBlanksExercise(Exercise):
    """Remove a target word from example sentences and ask the student to fill it in.

    Config options
    ──────────────
    num_items : int (default 8)
    show_word_bank : bool (default True)
    """

    @property
    def exercise_type(self) -> str:
        return "fill_blanks"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        # ── Prefer LLM-generated content ────────────────────────────
        llm = self.config.get("llm_content")
        if llm and llm.get("items"):
            items = llm["items"]
            word_bank = llm.get("word_bank", [t["target"] for t in items])
            random.shuffle(word_bank)
            solutions = [{"number": it["number"], "answer": it["target"]} for it in items]
            return ExerciseContent(
                title="Fill in the Blanks",
                instructions="Complete each sentence with the correct word from the word bank.",
                items=items,
                solution=solutions,
                metadata={"level": level.value, "word_bank": word_bank},
            )

        # ── Fallback: generate from database phrases ────────────────
        num_items = self.config.get("num_items", 8)

        # Deduplicate phrases by text to avoid identical blanked sentences.
        seen_texts: set[str] = set()
        usable_phrases: list[PhraseEntry] = []
        for p in phrases:
            if len(p.text.split()) >= 5 and p.text not in seen_texts:
                seen_texts.add(p.text)
                usable_phrases.append(p)
        selected = random.sample(usable_phrases, min(num_items, len(usable_phrases)))

        items_fb: list[dict[str, Any]] = []
        solutions_fb: list[dict[str, Any]] = []
        word_bank_fb: list[str] = []
        used_targets: set[str] = set()

        for i, phrase in enumerate(selected, 1):
            # Pick a content word as the blank, avoiding duplicates.
            words = phrase.text.split()
            content_words = [w for w in words if len(w) > 3 and w.isalpha() and w.lower() not in used_targets]
            if not content_words:
                # Fall back to any content word if all are already used
                content_words = [w for w in words if len(w) > 3 and w.isalpha()]
            if not content_words:
                continue
            target = random.choice(content_words)
            used_targets.add(target.lower())
            blanked = re.sub(
                re.escape(target), "_" * max(len(target), 6), phrase.text, count=1
            )
            items_fb.append({"number": i, "sentence": blanked, "target": target})
            solutions_fb.append({"number": i, "answer": target})
            word_bank_fb.append(target)

        random.shuffle(word_bank_fb)

        return ExerciseContent(
            title="Fill in the Blanks",
            instructions="Complete each sentence with the correct word from the word bank.",
            items=items_fb,
            solution=solutions_fb,
            metadata={"level": level.value, "word_bank": word_bank_fb},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import body_style, instruction_style

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        # Word bank
        word_bank = content.metadata.get("word_bank", [])
        if word_bank and self.config.get("show_word_bank", True):
            bank_text = " &nbsp; | &nbsp; ".join(f"<b>{w}</b>" for w in word_bank)
            flowables.append(Paragraph(f"Word bank: {bank_text}", body_style()))
            flowables.append(Spacer(1, 0.3 * cm))

        for item in content.items:
            flowables.append(
                Paragraph(f"{item['number']}. {item['sentence']}", body_style())
            )
            flowables.append(Spacer(1, 0.2 * cm))

        return flowables
