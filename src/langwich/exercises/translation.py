"""Translation exercise — translate sentences between languages."""

from __future__ import annotations

import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class TranslationExercise(Exercise):
    """Translate phrases from the source language into the target language (or vice versa).

    Config: num_items (default 6), direction ("forward" | "reverse")
    """

    @property
    def exercise_type(self) -> str:
        return "translation"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        num_items = self.config.get("num_items", 6)
        translatable = [p for p in phrases if p.translation]
        selected = random.sample(translatable, min(num_items, len(translatable)))

        direction = self.config.get("direction", "forward")
        items = []
        solutions = []
        for i, phrase in enumerate(selected, 1):
            if direction == "forward":
                items.append({"number": i, "source": phrase.text})
                solutions.append({"number": i, "answer": phrase.translation})
            else:
                items.append({"number": i, "source": phrase.translation})
                solutions.append({"number": i, "answer": phrase.text})

        return ExerciseContent(
            title="Translation",
            instructions="Translate each sentence.",
            items=items,
            solution=solutions,
            metadata={"level": level.value, "direction": direction},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import body_style, instruction_style
        from langwich.rendering.components import writing_lines

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        for item in content.items:
            flowables.append(
                Paragraph(f"{item['number']}. {item['source']}", body_style())
            )
            flowables.extend(writing_lines(count=2))
            flowables.append(Spacer(1, 0.2 * cm))

        return flowables
