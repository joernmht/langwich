"""Exercise classes — each knows how to generate content and render to PDF."""

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

__all__ = [
    "Exercise",
    "ExerciseContent",
    "VocabMatchingExercise",
    "FillBlanksExercise",
    "SynonymsExercise",
    "TranslationExercise",
    "ReadingComprehensionExercise",
    "CreativeWritingExercise",
    "TextSummaryExercise",
    "YouTubeTaskExercise",
    "DrawingTaskExercise",
]
