"""Main worksheet generator — ties the database, learning paths, and PDF rendering together.

This is the primary entry point for generating worksheets. It:
  1. Loads vocabulary from a per-domain SQLite database.
  2. Selects exercises based on the chosen learning path.
  3. Generates content for each exercise.
  4. Renders everything into a styled PDF.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import Any

from langwich.config import AppConfig, settings
from langwich.db.manager import DomainDatabase
from langwich.db.models import CEFRLevel
from langwich.exercises.base import Exercise, ExerciseContent
from langwich.exercises.vocab_matching import VocabMatchingExercise
from langwich.exercises.fill_blanks import FillBlanksExercise
from langwich.exercises.synonyms import SynonymsExercise
from langwich.exercises.translation import TranslationExercise
from langwich.exercises.reading import ReadingComprehensionExercise
from langwich.exercises.creative_writing import CreativeWritingExercise
from langwich.exercises.text_summary import TextSummaryExercise
from langwich.exercises.youtube_task import YouTubeTaskExercise
from langwich.exercises.drawing_task import DrawingTaskExercise
from langwich.paths.template import ExerciseType, LearningPath
from langwich.rendering.pdf_renderer import PDFRenderer

logger = logging.getLogger(__name__)

# ── Exercise type → class mapping ────────────────────────────────────

EXERCISE_REGISTRY: dict[ExerciseType, type[Exercise]] = {
    ExerciseType.VOCAB_MATCHING: VocabMatchingExercise,
    ExerciseType.FILL_BLANKS: FillBlanksExercise,
    ExerciseType.SYNONYMS: SynonymsExercise,
    ExerciseType.TRANSLATION: TranslationExercise,
    ExerciseType.READING_COMPREHENSION: ReadingComprehensionExercise,
    ExerciseType.CREATIVE_WRITING: CreativeWritingExercise,
    ExerciseType.TEXT_SUMMARY: TextSummaryExercise,
    ExerciseType.YOUTUBE_TASK: YouTubeTaskExercise,
    ExerciseType.DRAWING_TASK: DrawingTaskExercise,
}


class WorksheetGenerator:
    """Generates a complete language learning worksheet.

    Parameters
    ----------
    db : DomainDatabase
        An initialised per-domain vocabulary database.
    path : LearningPath
        The learning path defining which exercises to include.
    level : CEFRLevel
        Target CEFR difficulty level.
    config : AppConfig | None
        Application configuration.
    """

    def __init__(
        self,
        db: DomainDatabase,
        path: LearningPath,
        level: CEFRLevel = CEFRLevel.B1,
        config: AppConfig | None = None,
    ) -> None:
        self.db = db
        self.path = path
        self.level = level
        self.cfg = config or settings
        self.renderer = PDFRenderer(config=self.cfg.pdf)

    def generate(
        self,
        output_path: Path | str | None = None,
        title: str | None = None,
        worksheet_date: date | None = None,
    ) -> Path:
        """Generate the worksheet PDF.

        Parameters
        ----------
        output_path : Path | str | None
            Where to save the PDF. Auto-generates a filename if *None*.
        title : str | None
            Worksheet title; defaults to the domain name.
        worksheet_date : date | None
            Date printed on the worksheet; defaults to today.

        Returns
        -------
        Path
            Path to the generated PDF file.
        """
        self.path.ensure_vocab_first()

        # Load vocabulary and phrases from the database
        vocabulary = self.db.query_vocabulary(level=self.level, limit=100)
        phrases = self.db.query_phrases(level=self.level, limit=50)

        if not vocabulary:
            logger.warning("No vocabulary found for level %s — using all levels", self.level)
            vocabulary = self.db.query_vocabulary(limit=100)
            phrases = self.db.query_phrases(limit=50)

        # Generate content for each exercise step
        all_flowables: list[list[Any]] = []
        for step in self.path.steps:
            exercise_cls = EXERCISE_REGISTRY.get(step.exercise_type)
            if exercise_cls is None:
                logger.warning("Unknown exercise type: %s", step.exercise_type)
                continue

            exercise = exercise_cls(config=step.config)
            try:
                content = exercise.generate(vocabulary, phrases, self.level)
                flowables = exercise.render(content)
                all_flowables.append(flowables)
            except Exception as exc:
                logger.error("Exercise %s failed: %s", step.exercise_type, exc)

        # Determine output path
        if output_path is None:
            today = (worksheet_date or date.today()).isoformat()
            filename = f"{self.db.domain}_{self.level.value}_{today}.pdf"
            output_path = self.cfg.pdf.output_dir / filename

        ws_title = title or f"{self.db.domain.replace('-', ' ').title()} — {self.level.value}"

        return self.renderer.render(
            exercise_flowables=all_flowables,
            output_path=output_path,
            title=ws_title,
            domain=self.db.domain,
            level=self.level,
            worksheet_date=worksheet_date,
        )


def main() -> None:
    """CLI entry point for quick worksheet generation."""
    import argparse

    from langwich.paths.defaults import BUILTIN_PATHS

    parser = argparse.ArgumentParser(description="Generate a language learning worksheet")
    parser.add_argument("--domain", required=True, help="Knowledge domain (e.g. railway-operations)")
    parser.add_argument("--source-lang", default="en", help="Source language code")
    parser.add_argument("--target-lang", default="de", help="Target language code")
    parser.add_argument("--level", default="B1", choices=["A1", "A2", "B1", "B2", "C1", "C2"])
    parser.add_argument("--path", default="balanced", choices=list(BUILTIN_PATHS.keys()))
    parser.add_argument("--output", help="Output PDF path")
    args = parser.parse_args()

    db = DomainDatabase(
        domain=args.domain,
        source_lang=args.source_lang,
        target_lang=args.target_lang,
    )
    db.initialize()

    learning_path = BUILTIN_PATHS[args.path]
    level = CEFRLevel(args.level)

    generator = WorksheetGenerator(db=db, path=learning_path, level=level)
    result = generator.generate(output_path=args.output)
    print(f"Worksheet generated: {result}")


if __name__ == "__main__":
    main()
