"""Creative writing exercise — open-ended writing prompts using target vocabulary."""

from __future__ import annotations

import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class CreativeWritingExercise(Exercise):
    """Provide a writing prompt that encourages use of target vocabulary.

    Config: num_vocab_to_use (default 5), line_count (default 10)
    """

    @property
    def exercise_type(self) -> str:
        return "creative_writing"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        # ── Prefer LLM-generated content ────────────────────────────
        llm = self.config.get("llm_content")
        if llm and llm.get("prompt"):
            vocab_required = llm.get("vocab_required", [])
            return ExerciseContent(
                title="Creative Writing",
                instructions=llm["prompt"],
                items=[{"vocab_required": vocab_required}],
                solution=[],
                metadata={"level": level.value, "line_count": self.config.get("line_count", 10)},
            )

        # ── Fallback: generate from database vocabulary ─────────────
        num_vocab = self.config.get("num_vocab_to_use", 5)
        domain = self.config.get("domain", "").replace("-", " ") or "this topic"
        target_words = random.sample(vocabulary, min(num_vocab, len(vocabulary)))
        word_list = [v.term for v in target_words]

        prompts = [
            f"Write a short paragraph about {domain} using these words: {', '.join(word_list)}.",
            f"Imagine you are explaining {domain} to a curious reader. Use at least {num_vocab} of these words: {', '.join(word_list)}.",
            f"Write a short report about {domain} using: {', '.join(word_list)}.",
            f"Describe how the words {', '.join(word_list)} connect to {domain}.",
            f"Write a diary entry about a personal experience with {domain}, using: {', '.join(word_list)}.",
        ]

        return ExerciseContent(
            title="Creative Writing",
            instructions=random.choice(prompts),
            items=[{"vocab_required": word_list}],
            solution=[],
            metadata={"level": level.value, "line_count": self.config.get("line_count", 10)},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import instruction_style
        from langwich.rendering.components import writing_lines

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))
        line_count = content.metadata.get("line_count", 10)
        flowables.extend(writing_lines(count=line_count))
        return flowables
