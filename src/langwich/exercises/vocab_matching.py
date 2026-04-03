"""Vocabulary matching exercise — match terms to definitions/translations."""

from __future__ import annotations

import json
import random
import string
from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.units import cm, mm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent
from langwich.rendering.styles import (
    BORDER_GREY,
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_GREY,
    BRAND_LIGHT,
)


class VocabMatchingFlowable(Flowable):
    """Custom flowable that draws a visual matching exercise with boxes and dots."""

    BOX_HEIGHT = 28
    BOX_WIDTH = 6.2 * cm
    ROW_SPACING = 6
    DOT_RADIUS = 3.5
    CORNER_RADIUS = 6
    GAP = 2.8 * cm  # space between left and right columns

    def __init__(
        self,
        left_items: list[tuple[str, str]],
        right_items: list[tuple[str, str]],
    ) -> None:
        super().__init__()
        self.left_items = left_items    # [(label, text), ...]
        self.right_items = right_items  # [(label, text), ...]
        n = max(len(left_items), len(right_items))
        self.height = n * (self.BOX_HEIGHT + self.ROW_SPACING) - self.ROW_SPACING
        self.width = self.BOX_WIDTH * 2 + self.GAP

    def draw(self) -> None:
        c = self.canv
        n = max(len(self.left_items), len(self.right_items))
        right_x = self.BOX_WIDTH + self.GAP

        for i in range(n):
            y = self.height - (i + 1) * (self.BOX_HEIGHT + self.ROW_SPACING) + self.ROW_SPACING
            mid_y = y + self.BOX_HEIGHT / 2

            # ── Left box ────────────────────────────────────
            if i < len(self.left_items):
                label, text = self.left_items[i]
                self._draw_box(c, 0, y, self.BOX_WIDTH, self.BOX_HEIGHT, label, text, align="left")
                # Dot on right edge
                dot_x = self.BOX_WIDTH + 5 * mm
                self._draw_dot(c, dot_x, mid_y)

            # ── Right box ───────────────────────────────────
            if i < len(self.right_items):
                label, text = self.right_items[i]
                self._draw_box(c, right_x, y, self.BOX_WIDTH, self.BOX_HEIGHT, label, text, align="right")
                # Dot on left edge
                dot_x = right_x - 5 * mm
                self._draw_dot(c, dot_x, mid_y)

    def _draw_box(
        self,
        c: Any,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        text: str,
        align: str,
    ) -> None:
        # Filled rounded rectangle
        c.setStrokeColor(BORDER_GREY)
        c.setLineWidth(0.75)
        c.setFillColor(BRAND_LIGHT)
        c.roundRect(x, y, w, h, self.CORNER_RADIUS, fill=1, stroke=1)

        # Label badge (number or letter)
        badge_w = 22
        badge_h = 18
        badge_y = y + (h - badge_h) / 2
        if align == "left":
            badge_x = x + 6
        else:
            badge_x = x + w - badge_w - 6

        c.setFillColor(BRAND_ACCENT)
        c.roundRect(badge_x, badge_y, badge_w, badge_h, 4, fill=1, stroke=0)

        # Label text (white on accent)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(badge_x + badge_w / 2, badge_y + 5, label)

        # Main text
        c.setFillColor(BRAND_DARK)
        c.setFont("Helvetica", 11)
        text_y = y + (h - 11) / 2 + 1  # vertically centred
        if align == "left":
            c.drawString(badge_x + badge_w + 8, text_y, text)
        else:
            c.drawString(x + 8, text_y, text)

    def _draw_dot(self, c: Any, x: float, y: float) -> None:
        c.setFillColor(BRAND_ACCENT)
        c.setStrokeColor(colors.white)
        c.setLineWidth(1.5)
        c.circle(x, y, self.DOT_RADIUS, fill=1, stroke=1)


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
            instructions="Draw a line from each term on the left to its translation on the right.",
            items=items,
            solution=solutions,
            metadata={"level": level.value},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import instruction_style

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.5 * cm))

        # Build left items (numbered) and right items (lettered)
        left_items: list[tuple[str, str]] = []
        right_items: list[tuple[str, str]] = []
        letters = string.ascii_uppercase

        for i, item in enumerate(content.items):
            left_items.append((str(item["number"]), item["term"]))
            trans_text = item.get("shuffled_translation", item["translation"])
            letter = letters[i] if i < len(letters) else str(i + 1)
            right_items.append((letter, trans_text))

        if left_items:
            flowables.append(VocabMatchingFlowable(left_items, right_items))

        return flowables
