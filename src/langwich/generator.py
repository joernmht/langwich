"""Main worksheet generator — ties the database, learning paths, and PDF rendering together.

This is the primary entry point for generating worksheets. It:
  1. Loads vocabulary from a per-domain SQLite database.
  2. Selects exercises based on the chosen learning path.
  3. Generates content for each exercise.
  4. Renders everything into a styled PDF.
"""

from __future__ import annotations

import logging
import random
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
from langwich.paths.template import ExerciseType, LearningPath, TaskSize
from langwich.rendering.components import (
    ai_upload_recommendation,
    grammar_reference_page,
    vocab_recommendation_box,
    vocab_reference_page,
)
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
        include_vocab_page: bool = True,
        include_grammar_page: bool = True,
        grammar_topic: str | None = None,
        vocab_position: str = "end",
        include_ai_recommendation: bool = True,
    ) -> None:
        self.db = db
        self.path = path
        self.level = level
        self.cfg = config or settings
        self.include_vocab_page = include_vocab_page
        self.include_grammar_page = include_grammar_page
        self.grammar_topic = grammar_topic
        self.vocab_position = vocab_position
        self.include_ai_recommendation = include_ai_recommendation
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
        self.path.validate_half_pairing()

        # Load vocabulary and phrases from the database
        vocabulary = self.db.query_vocabulary(level=self.level, limit=100)
        phrases = self.db.query_phrases(level=self.level, limit=50)

        if not vocabulary:
            logger.warning("No vocabulary found for level %s — using all levels", self.level)
            vocabulary = self.db.query_vocabulary(limit=100)
            phrases = self.db.query_phrases(limit=50)

        # Vocabulary reference page (opt-out with include_vocab_page=False)
        all_flowables: list[list[Any]] = []
        all_sizes: list[TaskSize | None] = []

        # Vocab at the start (legacy behaviour) if requested
        if self.include_vocab_page and vocabulary and self.vocab_position == "start":
            vocab_flowables = vocab_reference_page(
                vocabulary,
                source_lang=self.db.source_lang,
                target_lang=self.db.target_lang,
            )
            all_flowables.append(vocab_flowables)
            all_sizes.append(None)  # reference pages use free-flow layout

        # Grammar reference page (opt-out with include_grammar_page=False)
        if self.include_grammar_page:
            topic = self.grammar_topic or getattr(self.db, "grammar_topic", None)
            content = getattr(self.db, "grammar_content", None)
            grammar_flowables = grammar_reference_page(
                level=self.level,
                target_lang=self.db.target_lang,
                topic=topic,
                content=content,
            )
            all_flowables.append(grammar_flowables)
            all_sizes.append(None)

        # Partition phrases so text-consuming exercises get disjoint sets.
        # This prevents the reading passage and fill-in-the-blanks from
        # showing the same sentences.
        TEXT_PASSAGE_TYPES = {
            ExerciseType.READING_COMPREHENSION,
            ExerciseType.FILL_BLANKS,
            ExerciseType.TEXT_SUMMARY,
        }
        text_steps = [s for s in self.path.steps if s.exercise_type in TEXT_PASSAGE_TYPES]

        phrase_pools: dict[int, list] = {}
        if text_steps and phrases:
            shuffled = list(phrases)
            random.shuffle(shuffled)
            pool_size = max(1, len(shuffled) // len(text_steps))
            for i, step in enumerate(text_steps):
                start = i * pool_size
                end = start + pool_size if i < len(text_steps) - 1 else len(shuffled)
                phrase_pools[id(step)] = shuffled[start:end]

        # Generate content for each exercise step
        for step in self.path.steps:
            exercise_cls = EXERCISE_REGISTRY.get(step.exercise_type)
            if exercise_cls is None:
                logger.warning("Unknown exercise type: %s", step.exercise_type)
                continue

            # Use the partitioned phrase pool for text exercises, full set otherwise
            step_phrases = phrase_pools.get(id(step), phrases)

            # Inject domain context and pre-generated content into exercise config.
            exercise_config = {**step.config, "domain": self.db.domain}
            if self.db.reading_passage:
                exercise_config["reading_passage"] = self.db.reading_passage
            if self.db.reading_questions:
                exercise_config["reading_questions"] = self.db.reading_questions

            # Pass pre-generated exercise content from LLM (if available)
            if self.db.exercises:
                ex_key = step.exercise_type.value
                if ex_key in self.db.exercises:
                    exercise_config["llm_content"] = self.db.exercises[ex_key]
            exercise = exercise_cls(config=exercise_config)
            try:
                content = exercise.generate(vocabulary, step_phrases, self.level)
                flowables = exercise.render(content)
                all_flowables.append(flowables)
                all_sizes.append(step.resolved_size)
            except Exception as exc:
                logger.error("Exercise %s failed: %s", step.exercise_type, exc)

        # Vocabulary reference page at the end (new default behaviour)
        if self.include_vocab_page and vocabulary and self.vocab_position == "end":
            vocab_flowables = vocab_reference_page(
                vocabulary,
                source_lang=self.db.source_lang,
                target_lang=self.db.target_lang,
            )
            vocab_flowables.extend(vocab_recommendation_box())
            all_flowables.append(vocab_flowables)
            all_sizes.append(None)

        # AI upload recommendation at the very end
        if self.include_ai_recommendation:
            all_flowables.append(ai_upload_recommendation())
            all_sizes.append(None)

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
            exercise_sizes=all_sizes,
        )


def main() -> None:
    """CLI entry point for worksheet generation.

    Supports two modes:
      1. ``--from-json <file>`` — import LLM-generated vocabulary from JSON, then render.
      2. ``--domain <name>``   — use an existing database (requires prior mining or import).
    """
    import argparse

    from langwich.paths.defaults import BUILTIN_PATHS

    parser = argparse.ArgumentParser(
        description="Generate a language learning worksheet",
        epilog=(
            "Quick start:  langwich --from-json vocab.json\n"
            "With mining:  pip install langwich[mining]  then use --domain"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # ── Input mode ──────────────────────────────────────────────────
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--from-json",
        metavar="FILE",
        help="Path to a JSON file with vocabulary and phrases (LLM-generated)",
    )
    input_group.add_argument(
        "--domain",
        help="Knowledge domain slug (uses existing database in ./data/)",
    )

    # ── Common options ──────────────────────────────────────────────
    parser.add_argument("--source-lang", default="en", help="Source language ISO code (default: en)")
    parser.add_argument("--target-lang", default="de", help="Target language ISO code (default: de)")
    parser.add_argument(
        "--level", default="B1",
        choices=["A1", "A2", "B1", "B2", "C1", "C2"],
        help="CEFR proficiency level (default: B1)",
    )
    parser.add_argument(
        "--path", default="balanced",
        choices=list(BUILTIN_PATHS.keys()),
        help="Learning path template (default: balanced)",
    )
    parser.add_argument("--output", help="Output PDF path (auto-generated if omitted)")
    parser.add_argument(
        "--no-vocab-page",
        action="store_true",
        help="Skip the vocabulary reference page at the beginning",
    )
    parser.add_argument(
        "--no-grammar-page",
        action="store_true",
        help="Skip the grammar reference page",
    )
    parser.add_argument(
        "--grammar-topic",
        help="Grammar focus topic (e.g. 'present tense', 'articles')",
    )
    parser.add_argument(
        "--vocab-position",
        choices=["start", "end"],
        default="end",
        help="Position of the vocabulary reference page (default: end)",
    )
    parser.add_argument(
        "--no-ai-recommendation",
        action="store_true",
        help="Skip the AI upload recommendation at the end",
    )
    parser.add_argument(
        "--custom-exercises",
        help=(
            "Comma-separated exercise selections as type:count pairs. "
            "E.g. 'vocab_matching:15,reading_comprehension:4,fill_blanks:10'"
        ),
    )

    args = parser.parse_args()

    # ── Resolve database ────────────────────────────────────────────
    if args.from_json:
        from langwich.import_data import import_json_file

        db = import_json_file(args.from_json)
        print(f"Imported vocabulary from {args.from_json}")
    else:
        db = DomainDatabase(
            domain=args.domain,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
        )
        db.initialize()

    level = CEFRLevel(args.level)

    # Build learning path — custom exercises override the named path
    if args.custom_exercises:
        from langwich.paths.template import PathStep

        steps: list[PathStep] = []
        for part in args.custom_exercises.split(","):
            part = part.strip()
            if ":" in part:
                ex_type_str, count_str = part.split(":", 1)
                config = {"num_items": int(count_str)}
            else:
                ex_type_str = part
                config = {}
            ex_type = ExerciseType(ex_type_str.strip())
            steps.append(PathStep(exercise_type=ex_type, config=config))
        learning_path = LearningPath(
            name="Custom",
            description="User-selected exercises",
            steps=steps,
        )
    else:
        learning_path = BUILTIN_PATHS[args.path]

    generator = WorksheetGenerator(
        db=db,
        path=learning_path,
        level=level,
        include_vocab_page=not args.no_vocab_page,
        include_grammar_page=not args.no_grammar_page,
        grammar_topic=args.grammar_topic,
        vocab_position=args.vocab_position,
        include_ai_recommendation=not args.no_ai_recommendation,
    )
    result = generator.generate(output_path=args.output)
    print(f"Worksheet generated: {result}")


if __name__ == "__main__":
    main()
