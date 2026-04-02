"""Reading comprehension exercise — read a passage and answer questions."""

from __future__ import annotations

import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class ReadingComprehensionExercise(Exercise):
    """Present a text passage and comprehension questions.

    The passage is assembled from example phrases in the database.
    Config: num_questions (default 4), max_passage_sentences (default 8)
    """

    @property
    def exercise_type(self) -> str:
        return "reading_comprehension"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        max_sentences = self.config.get("max_passage_sentences", 8)
        num_questions = self.config.get("num_questions", 4)

        passage_phrases = random.sample(phrases, min(max_sentences, len(phrases)))
        passage = " ".join(p.text for p in passage_phrases)

        # Generate simple comprehension question stubs
        question_templates = [
            "What is the main topic of this passage?",
            "Explain the meaning of a key term from the text.",
            "Summarise the passage in your own words.",
            "What did you learn from this text?",
            "Which vocabulary words were new to you?",
            "How does this topic relate to your experience?",
        ]
        questions = random.sample(question_templates, min(num_questions, len(question_templates)))

        items = [{"number": i, "question": q} for i, q in enumerate(questions, 1)]

        return ExerciseContent(
            title="Reading Comprehension",
            instructions="Read the passage below, then answer the questions.",
            items=items,
            solution=[],
            metadata={"level": level.value, "passage": passage},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import body_style, instruction_style
        from langwich.rendering.components import info_box, writing_lines

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        # Passage in an info box
        passage = content.metadata.get("passage", "")
        flowables.extend(info_box(passage))
        flowables.append(Spacer(1, 0.4 * cm))

        for item in content.items:
            flowables.append(
                Paragraph(f"{item['number']}. {item['question']}", body_style())
            )
            flowables.extend(writing_lines(count=3))
            flowables.append(Spacer(1, 0.2 * cm))

        return flowables
