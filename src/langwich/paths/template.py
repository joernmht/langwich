"""Learning path data model — defines the sequence of exercises in a worksheet.

A ``LearningPath`` is an ordered list of ``PathStep`` objects, each specifying
an exercise type and its configuration.  Paths can be serialised to/from JSON
for user customisation.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class ExerciseType(str, enum.Enum):
    """Registry of all supported exercise types."""

    VOCAB_MATCHING = "vocab_matching"
    FILL_BLANKS = "fill_blanks"
    SYNONYMS = "synonyms"
    TRANSLATION = "translation"
    READING_COMPREHENSION = "reading_comprehension"
    CREATIVE_WRITING = "creative_writing"
    TEXT_SUMMARY = "text_summary"
    YOUTUBE_TASK = "youtube_task"
    DRAWING_TASK = "drawing_task"


@dataclass
class PathStep:
    """A single step in a learning path.

    Attributes
    ----------
    exercise_type : ExerciseType
        Which exercise class to instantiate.
    title : str
        Human-readable step title (rendered on the worksheet).
    config : dict[str, Any]
        Exercise-specific configuration (e.g. ``{"num_items": 10}``).
    required : bool
        Whether this step must be included even if vocabulary is scarce.
    """

    exercise_type: ExerciseType
    title: str = ""
    config: dict[str, Any] = field(default_factory=dict)
    required: bool = False

    def __post_init__(self) -> None:
        if not self.title:
            self.title = self.exercise_type.value.replace("_", " ").title()


@dataclass
class LearningPath:
    """An ordered sequence of exercise steps that forms a worksheet.

    Parameters
    ----------
    name : str
        Human-readable path name (e.g. ``"Vocabulary Focus"``).
    description : str
        Short description for UI display.
    steps : list[PathStep]
        Ordered list of exercises. A vocabulary page is always prepended
        if not already present.
    difficulty_progression : bool
        If *True*, the generator will increase CEFR levels across multiple
        worksheets in a curriculum sequence.
    """

    name: str
    description: str = ""
    steps: list[PathStep] = field(default_factory=list)
    difficulty_progression: bool = True

    def ensure_vocab_first(self) -> None:
        """Guarantee that a VocabMatching step is the first step."""
        if not self.steps or self.steps[0].exercise_type != ExerciseType.VOCAB_MATCHING:
            vocab_step = PathStep(
                exercise_type=ExerciseType.VOCAB_MATCHING,
                title="Key Vocabulary",
                required=True,
            )
            self.steps.insert(0, vocab_step)

    def exercise_types(self) -> list[ExerciseType]:
        """Return the ordered list of exercise types in this path."""
        return [step.exercise_type for step in self.steps]

    def to_dict(self) -> dict:
        """Serialise the path to a JSON-friendly dict."""
        return {
            "name": self.name,
            "description": self.description,
            "difficulty_progression": self.difficulty_progression,
            "steps": [
                {
                    "exercise_type": step.exercise_type.value,
                    "title": step.title,
                    "config": step.config,
                    "required": step.required,
                }
                for step in self.steps
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> LearningPath:
        """Deserialise a path from a dict (e.g. loaded from JSON)."""
        steps = [
            PathStep(
                exercise_type=ExerciseType(s["exercise_type"]),
                title=s.get("title", ""),
                config=s.get("config", {}),
                required=s.get("required", False),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
            difficulty_progression=data.get("difficulty_progression", True),
        )
