"""Synonyms exercise — identify words with similar meanings."""

from __future__ import annotations

import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class SynonymsExercise(Exercise):
    """Present a word and ask students to identify or write synonyms.

    Config: num_items (default 6)
    """

    @property
    def exercise_type(self) -> str:
        return "synonyms"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        num_items = self.config.get("num_items", 6)
        selected = random.sample(vocabulary, min(num_items, len(vocabulary)))

        items = [
            {"number": i, "term": v.term, "pos": v.part_of_speech.value}
            for i, v in enumerate(selected, 1)
        ]

        # Adapt task complexity to CEFR level.
        is_beginner = level in (CEFRLevel.A1, CEFRLevel.A2)

        if is_beginner:
            title = "Word Associations"
            instructions = (
                "For each word, write one word that has a similar meaning "
                "and one word that has the opposite meaning. "
                "You can answer in your native language if needed."
            )
        else:
            title = "Synonyms & Antonyms"
            instructions = "Write one synonym and one antonym for each word."

        return ExerciseContent(
            title=title,
            instructions=instructions,
            items=items,
            solution=[],
            metadata={"level": level.value, "is_beginner": is_beginner},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import body_style, instruction_style

        is_beginner = content.metadata.get("is_beginner", False)

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        if is_beginner:
            similar_label = "Similar"
            opposite_label = "Opposite"
        else:
            similar_label = "Synonym"
            opposite_label = "Antonym"

        for item in content.items:
            text = (
                f"{item['number']}. <b>{item['term']}</b> ({item['pos']})"
                f"<br/>{similar_label}: ________________ &nbsp; {opposite_label}: ________________"
            )
            flowables.append(Paragraph(text, body_style()))
            flowables.append(Spacer(1, 0.3 * cm))

        return flowables
