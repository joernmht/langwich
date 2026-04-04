"""YouTube task exercise — comprehension task based on a video transcript."""

from __future__ import annotations

from typing import Any

from reportlab.platypus import Flowable, Paragraph, Spacer
from reportlab.lib.units import cm

from langwich.db.models import CEFRLevel, PhraseEntry, VocabularyEntry
from langwich.exercises.base import Exercise, ExerciseContent


class YouTubeTaskExercise(Exercise):
    """Provides a QR code or URL to a YouTube video with comprehension questions.

    Config: video_url (str), num_questions (default 3)
    """

    @property
    def exercise_type(self) -> str:
        return "youtube_task"

    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        video_url = self.config.get("video_url", "")
        num_questions = self.config.get("num_questions", 3)

        # ── Prefer LLM-generated content ────────────────────────────
        llm = self.config.get("llm_content")
        if llm:
            url = llm.get("video_url", video_url)
            questions = llm.get("questions", [])[:num_questions]
            items = [{"number": i, "question": q} for i, q in enumerate(questions, 1)]
            return ExerciseContent(
                title="Video Comprehension",
                instructions=f"Watch the video, then answer the questions.\n{url}",
                items=items,
                solution=[],
                metadata={"level": level.value, "video_url": url},
            )

        # ── Fallback: generic questions ─────────────────────────────
        questions = [
            "What is the main topic of the video?",
            "List three new words you heard.",
            "Summarise the video in your own words.",
            "What surprised you in this video?",
            "How does this video relate to the topic?",
        ][:num_questions]

        items = [{"number": i, "question": q} for i, q in enumerate(questions, 1)]

        return ExerciseContent(
            title="Video Comprehension",
            instructions=f"Watch the video, then answer the questions.\n{video_url}",
            items=items,
            solution=[],
            metadata={"level": level.value, "video_url": video_url},
        )

    def render(self, content: ExerciseContent) -> list[Flowable]:
        from langwich.rendering.styles import body_style, instruction_style
        from langwich.rendering.components import writing_lines

        flowables: list[Flowable] = []
        flowables.append(Paragraph(content.instructions, instruction_style()))
        flowables.append(Spacer(1, 0.3 * cm))

        for item in content.items:
            flowables.append(
                Paragraph(f"{item['number']}. {item['question']}", body_style())
            )
            flowables.extend(writing_lines(count=3))
            flowables.append(Spacer(1, 0.2 * cm))

        return flowables
