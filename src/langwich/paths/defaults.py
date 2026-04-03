"""Built-in learning path templates.

Each path defines a different pedagogical approach:
- **Vocabulary Focus**: Heavy on word work, light on production
- **Reading First**: Comprehension-led, then vocabulary consolidation
- **Balanced**: A mix of all skill areas
- **Production**: Emphasises writing and creative output
"""

from langwich.paths.template import ExerciseType, LearningPath, PathStep, TaskSize

VOCABULARY_FOCUS = LearningPath(
    name="Vocabulary Focus",
    description="Term-heavy path: matching, synonyms, fill-in-the-blanks, translation.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),  # half
        PathStep(ExerciseType.SYNONYMS, "Synonyms & Antonyms"),                  # half (pair)
        PathStep(ExerciseType.FILL_BLANKS, "Fill in the Blanks"),                # half
        PathStep(ExerciseType.TRANSLATION, "Translation Practice"),              # half (pair)
    ],
)

READING_FIRST = LearningPath(
    name="Reading First",
    description="Comprehension-led path: read a text, then work on vocabulary.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),  # half
        PathStep(ExerciseType.TRANSLATION, "Translation Practice"),              # half (pair)
        PathStep(ExerciseType.READING_COMPREHENSION, "Reading Passage"),         # double
        PathStep(ExerciseType.FILL_BLANKS, "Vocabulary in Context"),             # half
        PathStep(ExerciseType.SYNONYMS, "Word Relationships"),                   # half (pair)
    ],
)

BALANCED = LearningPath(
    name="Balanced",
    description="A well-rounded mix of receptive and productive exercises.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),  # half
        PathStep(ExerciseType.SYNONYMS, "Word Relationships"),                   # half (pair)
        PathStep(ExerciseType.READING_COMPREHENSION, "Reading Passage"),         # double
        PathStep(ExerciseType.FILL_BLANKS, "Fill in the Blanks"),                # half
        PathStep(ExerciseType.DRAWING_TASK, "Visual Response"),                  # half (pair)
        PathStep(ExerciseType.CREATIVE_WRITING, "Free Writing"),                 # full
    ],
)

PRODUCTION = LearningPath(
    name="Production",
    description="Output-focused path: creative writing, summaries, drawing.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),  # half
        PathStep(ExerciseType.DRAWING_TASK, "Visual Response"),                  # half (pair)
        PathStep(ExerciseType.CREATIVE_WRITING, "Creative Writing"),             # full
        PathStep(ExerciseType.TEXT_SUMMARY, "Text Summary"),                     # full
        PathStep(ExerciseType.TRANSLATION, "Translation Practice"),              # half
        PathStep(ExerciseType.SYNONYMS, "Word Relationships"),                   # half (pair)
    ],
)

MULTIMEDIA = LearningPath(
    name="Multimedia",
    description="Incorporates YouTube tasks and varied media.",
    steps=[
        PathStep(ExerciseType.VOCAB_MATCHING, "Key Vocabulary", required=True),  # half
        PathStep(ExerciseType.FILL_BLANKS, "Key Terms"),                         # half (pair)
        PathStep(ExerciseType.YOUTUBE_TASK, "Video Comprehension"),              # full
        PathStep(ExerciseType.DRAWING_TASK, "Visual Response"),                  # half
        PathStep(ExerciseType.TRANSLATION, "Translation Practice"),              # half (pair)
        PathStep(ExerciseType.CREATIVE_WRITING, "Reflection"),                   # full
    ],
)

BUILTIN_PATHS: dict[str, LearningPath] = {
    "vocabulary_focus": VOCABULARY_FOCUS,
    "reading_first": READING_FIRST,
    "balanced": BALANCED,
    "production": PRODUCTION,
    "multimedia": MULTIMEDIA,
}
