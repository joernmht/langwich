"""Abstract base class for all exercise types.

Every exercise must implement two responsibilities:
  1. **Content generation** — select vocabulary and build the exercise data.
  2. **PDF rendering** — draw the exercise onto a ReportLab canvas/flowable.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Flowable

    from langwich.db.models import CEFRLevel, VocabularyEntry, PhraseEntry


@dataclass
class ExerciseContent:
    """Container for generated exercise content before rendering.

    Attributes
    ----------
    title : str
        Display title of the exercise section.
    instructions : str
        Student-facing instructions text.
    items : list[dict[str, Any]]
        Exercise-specific data items (questions, pairs, gaps, etc.).
    solution : list[dict[str, Any]]
        Answer key / solution data (used for teacher edition).
    metadata : dict[str, Any]
        Extra info (CEFR level, source URLs, etc.).
    """

    title: str = ""
    instructions: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    solution: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class Exercise(abc.ABC):
    """Abstract base for all exercise types.

    Subclasses must implement ``generate()`` and ``render()``.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    @property
    @abc.abstractmethod
    def exercise_type(self) -> str:
        """Return the exercise type identifier (matches ``ExerciseType`` enum value)."""
        ...

    @abc.abstractmethod
    def generate(
        self,
        vocabulary: list[VocabularyEntry],
        phrases: list[PhraseEntry],
        level: CEFRLevel,
    ) -> ExerciseContent:
        """Build the exercise content from available vocabulary and phrases.

        Parameters
        ----------
        vocabulary : list[VocabularyEntry]
            Available vocabulary entries filtered for the target level.
        phrases : list[PhraseEntry]
            Available example phrases filtered for the target level.
        level : CEFRLevel
            The target difficulty level for this exercise.

        Returns
        -------
        ExerciseContent
            The generated exercise data ready for rendering.
        """
        ...

    @abc.abstractmethod
    def render(self, content: ExerciseContent) -> list[Flowable]:
        """Render the exercise content as ReportLab flowables.

        Parameters
        ----------
        content : ExerciseContent
            Previously generated exercise content.

        Returns
        -------
        list[Flowable]
            ReportLab flowable objects to be added to the PDF story.
        """
        ...
