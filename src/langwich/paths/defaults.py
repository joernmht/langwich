"""Built-in learning path templates.

Each path defines a different pedagogical approach:
- **Vocabulary Focus**: Heavy on word work, light on production
- **Reading First**: Comprehension-led, then vocabulary consolidation
- **Balanced**: A mix of all skill areas
- **Production**: Emphasises writing and creative output
"""

from langwich.paths.template import ExerciseType, LearningPath, PathStep

VOCABULARY_FOCUS = LearningPath(
    name="Vocabulary Focus",
    description="Term-heavy path: matching, synonyms, fill-in-the-blanks, translation.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),
        PathStep(ExerciseType.SYNONYMS, "Synonyms & Antonyms"),
        PathStep(ExerciseType.FILL_BLANKS, "Fill in the Blanks"),
        PathStep(ExerciseType.TRANSLATION, "Translation Practice"),
    ],
)

READING_FIRST = LearningPath(
    name="Reading First",
    description="Comprehension-led path: read a text, then work on vocabulary.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),
        PathStep(ExerciseType.READING_COMPREHENSION, "Reading Passage"),
        PathStep(ExerciseType.FILL_BLANKS, "Vocabulary in Context"),
        PathStep(ExerciseType.TEXT_SUMMARY, "Summarise the Text"),
    ],
)

BALANCED = LearningPath(
    name="Balanced",
    description="A well-rounded mix of receptive and productive exercises.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),
        PathStep(ExerciseType.READING_COMPREHENSION, "Reading Passage"),
        PathStep(ExerciseType.FILL_BLANKS, "Fill in the Blanks"),
        PathStep(ExerciseType.SYNONYMS, "Word Relationships"),
        PathStep(ExerciseType.CREATIVE_WRITING, "Free Writing"),
    ],
)

PRODUCTION = LearningPath(
    name="Production",
    description="Output-focused path: creative writing, summaries, drawing.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),
        PathStep(ExerciseType.CREATIVE_WRITING, "Creative Writing"),
        PathStep(ExerciseType.TEXT_SUMMARY, "Text Summary"),
        PathStep(ExerciseType.DRAWING_TASK, "Visual Response"),
    ],
)

MULTIMEDIA = LearningPath(
    name="Multimedia",
    description="Incorporates YouTube tasks and varied media.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),
        PathStep(ExerciseType.YOUTUBE_TASK, "Video Comprehension"),
        PathStep(ExerciseType.FILL_BLANKS, "Key Terms"),
        PathStep(ExerciseType.CREATIVE_WRITING, "Reflection"),
    ],
)

BUILTIN_PATHS: dict[str, LearningPath] = {
    "vocabulary_focus": VOCABULARY_FOCUS,
    "reading_first": READING_FIRST,
    "balanced": BALANCED,
    "production": PRODUCTION,
    "multimedia": MULTIMEDIA,
}
