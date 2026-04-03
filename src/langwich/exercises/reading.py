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
    Config: num_questions (default 4), max_passage_sentences (default 20)
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
        max_sentences = self.config.get("max_passage_sentences", 20)
        num_questions = self.config.get("num_questions", 4)

        # Deduplicate phrases by text to avoid repeated sentences in the passage.
        seen_texts: set[str] = set()
        unique_phrases: list[PhraseEntry] = []
        for p in phrases:
            if p.text not in seen_texts:
                seen_texts.add(p.text)
                unique_phrases.append(p)
        passage_phrases = random.sample(unique_phrases, min(max_sentences, len(unique_phrases)))
        passage = " ".join(p.text for p in passage_phrases)

        # Build questions that reference the actual passage content.
        # Pick a few concrete terms from the text so questions feel relevant.
        all_words = [w for p in passage_phrases for w in p.text.split() if len(w) > 4 and w.isalpha()]
        sample_terms = random.sample(all_words, min(3, len(all_words))) if all_words else []

        questions: list[str] = []

        # First question always asks about the topic
        questions.append("What is the main topic of this text? Write 1–2 sentences.")

        # Term-specific question using a word from the passage
        if len(sample_terms) >= 1:
            questions.append(
                f"The word \u201c{sample_terms[0]}\u201d appears in the text. "
                f"Explain what it means in this context."
            )

        # Factual question
        questions.append(
            "Name two facts or details mentioned in the text."
        )

        # Comprehension / inference question
        if len(sample_terms) >= 2:
            questions.append(
                f"How does the text connect \u201c{sample_terms[1]}\u201d "
                f"to the overall topic?"
            )

        # Personal response
        questions.append(
            "What is the most important thing you learned from this text? Why?"
        )

        # Extra pool for variety
        extra = [
            "Summarise the text in 2\u20133 sentences using your own words.",
            "Which sentence in the text do you find most interesting? Explain why.",
            "Write one question you would like to ask the author of this text.",
        ]
        random.shuffle(extra)

        # Fill up to num_questions
        for q in extra:
            if len(questions) >= num_questions:
                break
            questions.append(q)

        questions = questions[:num_questions]
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

        # Passage in an info box — min half page height (~350pt on A4)
        passage = content.metadata.get("passage", "")
        flowables.extend(info_box(passage, min_height=350))
        flowables.append(Spacer(1, 0.4 * cm))

        for item in content.items:
            flowables.append(
                Paragraph(f"{item['number']}. {item['question']}", body_style())
            )
            flowables.extend(writing_lines(count=3))
            flowables.append(Spacer(1, 0.2 * cm))

        return flowables
