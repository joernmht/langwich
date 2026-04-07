"""Drawing task exercise — visual/sketch response to a prompt."""

from __future__ import annotations

import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class DrawingTaskExercise(Exercise):
    """Ask students to draw or sketch something related to the vocabulary.

    Renders a bordered blank area on the PDF for drawing.
    Config: box_height_cm (default 8)
    """

    @property
    def exercise_type(self) -> str:
        return "drawing_task"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        # ── Prefer LLM-generated content ────────────────────────────
        llm = self.config.get("llm_content")
        if llm and llm.get("prompt"):
            return ExerciseContent(
                title="Drawing Task",
                instructions=llm["prompt"],
                items=[],
                solution=[],
                metadata={
                    "level": level.value,
                    "box_height_cm": self.config.get("box_height_cm", 8),
                },
            )

        # ── Fallback: generate from database vocabulary ─────────────
        terms = [v.term for v in vocabulary[:5]]
        prompts = [
            f"Draw a scene that includes: {', '.join(terms)}.",
            f"Illustrate the meaning of the word '{terms[0]}' if you can.",
            f"Create a mind map connecting these words: {', '.join(terms)}.",
            f"Draw a diagram showing how these concepts relate: {', '.join(terms)}.",
            f"Sketch a process or experiment involving: {', '.join(terms)}.",
        ]

        return ExerciseContent(
            title="Drawing Task",
            instructions=random.choice(prompts),
            items=[],
            solution=[],
            metadata={
                "level": level.value,
                "box_height_cm": self.config.get("box_height_cm", 8),
            },
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import instruction_style
        from langwich.rendering.components import drawing_box

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        height = content.metadata.get("box_height_cm", 8)
        flowables.append(drawing_box(height_cm=height))
        return flowables
