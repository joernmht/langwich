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
        num_vocab = self.config.get("num_vocab_to_use", 5)
        target_words = random.sample(vocabulary, min(num_vocab, len(vocabulary)))
        word_list = [v.term for v in target_words]

        prompts = [
            f"Write a short paragraph using these words: {', '.join(word_list)}. Try to include a real-world fact or scientific detail.",
            f"Imagine you are a science journalist explaining this topic to a curious reader. Use at least {num_vocab} new words.",
            f"Write a short report about a recent discovery or finding using: {', '.join(word_list)}.",
            f"Describe how the words {', '.join(word_list)} connect to a real-world phenomenon or scientific concept.",
            f"Write a diary entry about visiting a research lab or museum, using: {', '.join(word_list)}.",
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
