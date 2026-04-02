"""Vocabulary matching exercise — match terms to definitions/translations."""

from __future__ import annotations

import json
import random
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class VocabMatchingExercise(Exercise):
    """Match vocabulary terms to their translations or definitions.

    Config options
    ──────────────
    num_items : int (default 10)
        Number of term–translation pairs to include.
    shuffle_translations : bool (default True)
        Whether to randomise the order of translations.
    """

    @property
    def exercise_type(self) -> str:
        return "vocab_matching"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        num_items = self.config.get("num_items", 10)
        selected = random.sample(vocabulary, min(num_items, len(vocabulary)))

        items: list[dict[str, Any]] = []
        solutions: list[dict[str, Any]] = []
        for i, entry in enumerate(selected, 1):
            translations = json.loads(entry.translations_json) if entry.translations_json else ["—"]
            items.append({
                "number": i,
                "term": entry.term,
                "translation": translations[0] if translations else "—",
            })
            solutions.append({"number": i, "term": entry.term, "answer": translations[0]})

        # Shuffle translations for the student version
        if self.config.get("shuffle_translations", True):
            translation_list = [it["translation"] for it in items]
            random.shuffle(translation_list)
            for i, item in enumerate(items):
                item["shuffled_translation"] = translation_list[i]

        return ExerciseContent(
            title="Vocabulary Matching",
            instructions="Match each term on the left with its translation on the right.",
            items=items,
            solution=solutions,
            metadata={"level": level.value},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import body_style, instruction_style

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.4 * cm))

        # Build two-column table: terms | shuffled translations
        table_data = []
        for item in content.items:
            term_text = f"{item['number']}. {item['term']}"
            trans_text = item.get("shuffled_translation", item["translation"])
            table_data.append([term_text, trans_text])

        if table_data:
            table = Table(table_data, colWidths=[8 * cm, 8 * cm])
            table.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 11),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                ("LINEBELOW", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]))
            flowables.append(table)

        return flowables
