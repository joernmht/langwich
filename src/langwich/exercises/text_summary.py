"""Text summary exercise — read a text and write a condensed summary."""

from __future__ import annotations

import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class TextSummaryExercise(Exercise):
    """Ask students to summarise a passage in a target word count.

    Config: max_passage_sentences (default 6), summary_lines (default 5)
    """

    @property
    def exercise_type(self) -> str:
        return "text_summary"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        max_sentences = self.config.get("max_passage_sentences", 12)
        passage_phrases = random.sample(phrases, min(max_sentences, len(phrases)))
        passage = " ".join(p.text for p in passage_phrases)

        return ExerciseContent(
            title="Text Summary",
            instructions="Read the text below and write a summary in 2\u20133 sentences. Focus on the key facts and any evidence presented.",
            items=[],
            solution=[],
            metadata={
                "level": level.value,
                "passage": passage,
                "summary_lines": self.config.get("summary_lines", 5),
            },
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import instruction_style
        from langwich.rendering.components import info_box, writing_lines

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        passage = content.metadata.get("passage", "")
        flowables.extend(info_box(passage, min_height=350))
        flowables.append(Spacer(1, 0.3 * cm))

        line_count = content.metadata.get("summary_lines", 5)
        flowables.extend(writing_lines(count=line_count))
        return flowables
