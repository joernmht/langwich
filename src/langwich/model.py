"""The langwich worksheet contract — schema ``langwich/3``.

A worksheet is a short **story** told in scenes, plus the **tasks** that
walk a learner through it. The LLM in use (Claude, ChatGPT, a local model —
any of them) writes every learner-facing word: the story, the facts woven
into it, the vocabulary, the grammar notes and every task item with its
answer. Python only checks, orders, lays out and renders.

The models below are the single source of truth. ``langwich schema`` prints
them as JSON Schema, ``langwich validate`` checks a file against them (plus
the semantic rules in :mod:`langwich.validate`), and ``langwich prompt``
explains them to an LLM.

Language conventions (the learner reads the *source* language natively and
is learning the *target* language):

* target language: title, scene headings and texts, vocabulary terms,
  grammar examples, task items;
* source language: logline, character roles, translations, grammar
  explanations, task titles and instructions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

SCHEMA_ID = "langwich/3"

CefrLevel = Literal["A1", "A2", "B1", "B2", "C1", "C2"]
CEFR_LEVELS: tuple[str, ...] = ("A1", "A2", "B1", "B2", "C1", "C2")

Stage = Literal[
    "warm_up", "gist", "detail", "picture", "form", "practice", "production", "epilogue",
]
#: Stages in lesson order. The planner sorts tasks by this rank. Picture
#: tasks come right after comprehension: they are about the scene just read,
#: while form and practice items move the story on.
STAGES: tuple[str, ...] = (
    "warm_up", "gist", "detail", "picture", "form", "practice", "production", "epilogue",
)

Beat = Literal["setup", "development", "complication", "climax", "resolution", "epilogue"]

Frame = Literal[
    "episode", "reportage", "case_study", "diary", "letters", "mystery", "dialogue", "other",
]

POS_VALUES: tuple[str, ...] = (
    "noun", "verb", "adjective", "adverb", "preposition", "conjunction",
    "pronoun", "phrase", "other",
)

ClozeHint = Literal["word_bank", "first_letter", "base_form", "translation", "none"]

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9_-]*$"
_LANG_PATTERN = r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$"


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ---------------------------------------------------------------------------
# Story
# ---------------------------------------------------------------------------


class Character(_Model):
    """A recurring person in the story (reused across a series)."""

    id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1)
    role: str | None = Field(
        default=None, description="One line in the source language, e.g. '23, gap year in Vienna'.",
    )


class Label(_Model):
    """A numbered object in a scene picture."""

    n: int = Field(ge=1, le=30, description="Marker number printed on the picture.")
    term: str = Field(min_length=1, description="Target-language answer, nouns with article.")
    x: float | None = Field(
        default=None, ge=0, le=1,
        description="Marker position, 0 = left edge, 1 = right edge of the picture.",
    )
    y: float | None = Field(
        default=None, ge=0, le=1,
        description="Marker position, 0 = top edge, 1 = bottom edge of the picture.",
    )


class Picture(_Model):
    """The picture of a scene.

    Provide ``image`` (a local path or URL — e.g. the photo the story was
    built from, or an open-access image), or ``svg`` (simple black line art
    drawn by the LLM), or neither. ``prompt`` is an image-generation prompt
    for later use; it is never printed on the learner's sheet.
    """

    image: str | None = None
    svg: str | None = Field(default=None, description="A complete <svg>…</svg> element.")
    credit: str | None = Field(default=None, description="Attribution the image licence requires.")
    caption: str | None = None
    prompt: str | None = Field(default=None, description="Image-generation prompt (not printed).")
    labels: list[Label] = Field(default_factory=list)
    numbers_in_image: bool = Field(
        default=False,
        description="True when the image itself already shows the marker numbers.",
    )

    @field_validator("svg")
    @classmethod
    def _svg_is_svg(cls, v: str | None) -> str | None:
        if v is not None and "<svg" not in v.lower():
            raise ValueError("svg must contain a complete <svg>…</svg> element")
        return v

    @property
    def has_visual(self) -> bool:
        return bool(self.image or self.svg)


class Scene(_Model):
    id: str = Field(pattern=_ID_PATTERN)
    heading: str = Field(min_length=1, description="Short target-language heading.")
    beat: Beat | None = None
    text: str = Field(min_length=1, description="Target-language text; blank lines split paragraphs.")
    translation: str | None = Field(default=None, description="Source-language translation.")
    picture: Picture | None = None

    @property
    def paragraphs(self) -> list[str]:
        return [p.strip() for p in self.text.split("\n\n") if p.strip()]


class Story(_Model):
    logline: str = Field(min_length=1, description="One source-language sentence: who wants what.")
    setting: str | None = None
    characters: list[Character] = Field(default_factory=list)
    scenes: list[Scene] = Field(min_length=1)


class Fact(_Model):
    """A true, checkable fact shown as a 'Did you know?' sidebar."""

    id: str | None = Field(default=None, pattern=_ID_PATTERN)
    scene: str | None = None
    title: str | None = None
    text: str = Field(min_length=1)
    source: str | None = Field(default=None, description="Short citation, e.g. 'ICO, 2023'.")


class Series(_Model):
    """Present when the worksheet is one episode of a continuing story."""

    id: str = Field(pattern=_ID_PATTERN)
    title: str = Field(min_length=1)
    episode: int = Field(ge=1)
    previously: str | None = Field(default=None, description="'Previously…' recap (episode ≥ 2).")
    next: str | None = Field(default=None, description="Teaser for the next episode.")
    review: list[str] = Field(
        default_factory=list, description="Target words from earlier episodes to recycle.",
    )


# ---------------------------------------------------------------------------
# Vocabulary and grammar
# ---------------------------------------------------------------------------


class VocabItem(_Model):
    term: str = Field(min_length=1, description="Target language; nouns with article.")
    translation: str = Field(min_length=1)
    pos: str = Field(default="other")
    plural: str | None = None
    forms: str | None = Field(default=None, description="Irregular forms, e.g. 'wächst, wuchs, ist gewachsen'.")
    note: str | None = None
    scene: str | None = None

    @field_validator("pos")
    @classmethod
    def _pos(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in POS_VALUES:
            raise ValueError(f"pos must be one of {', '.join(POS_VALUES)}")
        return v


class Vocabulary(_Model):
    target: list[str] = Field(
        default_factory=list,
        description="The 6–15 key terms the tasks practise; each must also appear in items.",
    )
    items: list[VocabItem] = Field(min_length=1)


class GrammarTable(_Model):
    head: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(min_length=1)


class GrammarPoint(_Model):
    id: str = Field(pattern=_ID_PATTERN)
    name: str = Field(min_length=1)
    explanation: str = Field(min_length=1, description="Source language, 1–3 sentences.")
    rule: str | None = Field(default=None, description="Compact pattern, e.g. 'werden + Partizip II'.")
    table: GrammarTable | None = None
    examples: list[str] = Field(default_factory=list)
    scene: str | None = None


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------


class _TaskBase(_Model):
    id: str = Field(pattern=_ID_PATTERN)
    stage: Stage
    scene: str | list[str] | None = Field(
        default=None, description="Scene id(s) the task belongs to; the task follows the last one.",
    )
    title: str | None = Field(default=None, description="Source-language title tied to the story.")
    instruction: str | None = Field(default=None, description="Source-language instruction.")
    grammar: str | None = Field(default=None, description="Id of a grammar point shown beside it.")

    @property
    def scene_ids(self) -> list[str]:
        if self.scene is None:
            return []
        return [self.scene] if isinstance(self.scene, str) else list(self.scene)


class Pair(_Model):
    left: str = Field(min_length=1)
    right: str = Field(min_length=1)


class MatchTask(_TaskBase):
    kind: Literal["match"]
    pairs: list[Pair] = Field(min_length=2)
    extra: list[str] = Field(default_factory=list, description="Distractors for the right column.")


class TrueFalseItem(_Model):
    statement: str = Field(min_length=1)
    answer: bool
    correction: str | None = Field(default=None, description="The true version, for false statements.")


class TrueFalseTask(_TaskBase):
    kind: Literal["true_false"]
    items: list[TrueFalseItem] = Field(min_length=1)


class ChoiceItem(_Model):
    question: str = Field(min_length=1)
    options: list[str] = Field(min_length=2)
    answer: str = Field(min_length=1)

    @model_validator(mode="after")
    def _answer_in_options(self) -> ChoiceItem:
        if self.answer not in self.options:
            raise ValueError(f"answer {self.answer!r} is not one of the options")
        if len({o.casefold() for o in self.options}) != len(self.options):
            raise ValueError("options must be distinct")
        return self


class MultipleChoiceTask(_TaskBase):
    kind: Literal["multiple_choice"]
    items: list[ChoiceItem] = Field(min_length=1)


class OrderEventsTask(_TaskBase):
    kind: Literal["order_events"]
    events: list[str] = Field(min_length=3, description="In the correct order; shown shuffled.")


class QuestionItem(_Model):
    question: str = Field(min_length=1)
    answer: str | None = Field(default=None, description="Model answer for the answer key.")
    lines: int = Field(default=2, ge=0, le=20)


class QuestionsTask(_TaskBase):
    kind: Literal["questions"]
    items: list[QuestionItem] = Field(min_length=1)


class ClozeTask(_TaskBase):
    """Gap text. Mark every gap as ``{{answer}}``, ``{{answer|alternative}}``
    or ``{{answer::hint}}`` (the hint is required for ``base_form`` and
    ``translation`` hints)."""

    kind: Literal["cloze"]
    text: str | None = Field(default=None, description="One connected passage with gaps.")
    items: list[str] | None = Field(default=None, description="Separate sentences with gaps.")
    hint: ClozeHint = "word_bank"
    distractors: list[str] = Field(default_factory=list, description="Extra word-bank words.")

    @model_validator(mode="after")
    def _text_or_items(self) -> ClozeTask:
        if (self.text is None) == (self.items is None):
            raise ValueError("a cloze task needs exactly one of 'text' or 'items'")
        if self.items is not None and not self.items:
            raise ValueError("'items' must not be empty")
        return self


class TransformItem(_Model):
    prompt: str = Field(min_length=1)
    cue: str | None = None
    answer: str = Field(min_length=1)


class TransformTask(_TaskBase):
    kind: Literal["transform"]
    items: list[TransformItem] = Field(min_length=1)


class WordBuildingItem(_Model):
    parts: list[str] = Field(min_length=2)
    answer: str = Field(min_length=1)


class WordBuildingTask(_TaskBase):
    kind: Literal["word_building"]
    items: list[WordBuildingItem] = Field(min_length=1)


class LabelTask(_TaskBase):
    """Name the numbered objects in a scene picture (``scene`` is required)."""

    kind: Literal["label"]
    scene: str
    bank: bool = Field(default=True, description="Show the terms as a word bank.")


class WritingTask(_TaskBase):
    kind: Literal["writing"]
    prompt: str = Field(min_length=1)
    starter: str | None = None
    must_use: list[str] = Field(default_factory=list)
    min_words: int | None = Field(default=None, ge=1)
    max_words: int | None = Field(default=None, ge=1)
    lines: int | None = Field(default=None, ge=1, le=40)
    model_answer: str | None = None


class DialogueLine(_Model):
    speaker: str = Field(min_length=1)
    text: str | None = Field(default=None, description="May contain {{gaps}}; null = learner writes it.")
    cue: str | None = Field(default=None, description="Source-language cue for a line the learner writes.")
    answer: str | None = Field(default=None, description="Model answer for a line the learner writes.")


class DialogueTask(_TaskBase):
    kind: Literal["dialogue"]
    lines: list[DialogueLine] = Field(min_length=2)
    bank: bool = False
    distractors: list[str] = Field(default_factory=list, description="Extra word-bank words.")


class MediaSearchTask(_TaskBase):
    kind: Literal["media_search"]
    media: Literal["video", "article", "podcast", "image"] = "video"
    queries: list[str] = Field(min_length=1, description="Target-language search terms.")
    questions: list[str] = Field(min_length=1, description="What to find out or note.")


class DrawTask(_TaskBase):
    kind: Literal["draw"]
    prompt: str = Field(min_length=1)
    labels: list[str] = Field(default_factory=list)


Task = Annotated[
    Union[
        MatchTask, TrueFalseTask, MultipleChoiceTask, OrderEventsTask, QuestionsTask,
        ClozeTask, TransformTask, WordBuildingTask, LabelTask, WritingTask,
        DialogueTask, MediaSearchTask, DrawTask,
    ],
    Field(discriminator="kind"),
]

TASK_KINDS: tuple[str, ...] = (
    "match", "true_false", "multiple_choice", "order_events", "questions", "cloze",
    "transform", "word_building", "label", "writing", "dialogue", "media_search", "draw",
)


# ---------------------------------------------------------------------------
# Worksheet
# ---------------------------------------------------------------------------


class Worksheet(_Model):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, populate_by_name=True)

    schema_id: Literal["langwich/3"] = Field(alias="schema")
    title: str = Field(min_length=1, description="Target-language title.")
    standfirst: str | None = Field(default=None, description="Source-language intro line.")
    source_lang: str = Field(pattern=_LANG_PATTERN, description="The learner's language (ISO 639-1).")
    target_lang: str = Field(pattern=_LANG_PATTERN, description="The language being learned.")
    cefr_level: CefrLevel
    topic: str = Field(min_length=1)
    frame: Frame | None = None
    series: Series | None = None
    story: Story
    facts: list[Fact] = Field(default_factory=list)
    vocabulary: Vocabulary
    grammar: list[GrammarPoint] = Field(default_factory=list)
    tasks: list[Task] = Field(min_length=1)
    ui: dict[str, str] = Field(
        default_factory=dict,
        description="Overrides for page furniture strings (for languages without built-in labels).",
    )

    def scene(self, scene_id: str) -> Scene | None:
        return next((s for s in self.story.scenes if s.id == scene_id), None)

    def grammar_point(self, grammar_id: str) -> GrammarPoint | None:
        return next((g for g in self.grammar if g.id == grammar_id), None)

    def vocab_item(self, term: str) -> VocabItem | None:
        key = term.casefold()
        return next((v for v in self.vocabulary.items if v.term.casefold() == key), None)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


class ContractError(Exception):
    """The input does not match the contract. ``problems`` holds
    ``(location, message)`` pairs, locations in JSON-pointer style."""

    def __init__(self, problems: list[tuple[str, str]], hint: str | None = None):
        self.problems = problems
        self.hint = hint
        lines = [f"{loc or '/'}: {msg}" for loc, msg in problems]
        if hint:
            lines.append(hint)
        super().__init__("\n".join(lines))


LEGACY_HINT = (
    "This looks like a langwich v2 file (flat 'content' text without a 'story'). "
    "langwich 3 renders stories whose tasks are written by an LLM. Run "
    "'langwich prompt --from-json <file>' and give the printed prompt to your LLM "
    "to turn it into a langwich/3 worksheet."
)


def _pointer(loc: tuple[Any, ...]) -> str:
    return "/" + "/".join(str(p) for p in loc) if loc else "/"


def _discriminator_prefix_ok(loc: tuple[Any, ...]) -> tuple[Any, ...]:
    # pydantic inserts the discriminator tag ('match', 'cloze', …) into the
    # location of union members; drop it so pointers match the JSON.
    out = []
    for i, part in enumerate(loc):
        if (
            isinstance(part, str)
            and part in TASK_KINDS
            and i >= 2
            and loc[i - 2] == "tasks"
        ):
            continue
        out.append(part)
    return tuple(out)


def worksheet_from_dict(data: Any) -> Worksheet:
    if not isinstance(data, dict):
        raise ContractError([("/", "the top level must be a JSON object")])
    if "story" not in data and "content" in data:
        raise ContractError([("/story", "missing")], hint=LEGACY_HINT)
    if data.get("schema") not in (None, SCHEMA_ID) and "schema" in data:
        raise ContractError(
            [("/schema", f"expected {SCHEMA_ID!r}, got {data.get('schema')!r}")],
        )
    try:
        return Worksheet.model_validate(data)
    except ValidationError as exc:
        problems = [
            (_pointer(_discriminator_prefix_ok(tuple(e["loc"]))), e["msg"])
            for e in exc.errors()
        ]
        raise ContractError(problems) from None


def strip_code_fence(raw: str) -> str | None:
    """The JSON inside a Markdown ```json … ``` fence (LLMs like to add one),
    or ``None`` when the text is not fenced."""
    text = raw.strip()
    if not text.startswith("```"):
        return None
    body = text.splitlines()[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body)


def load_worksheet(path: str | Path) -> Worksheet:
    """Load and check a worksheet file; every failure is a :class:`ContractError`."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ContractError([("/", f"file not found: {path}")]) from None
    except UnicodeDecodeError:
        raise ContractError([("/", f"{path} is not UTF-8 text")]) from None
    except OSError as exc:
        raise ContractError([("/", f"cannot read {path}: {exc.strerror or exc}")]) from None
    fenced = strip_code_fence(raw)
    if fenced is not None:
        raw = fenced
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ContractError(
            [("/", f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}")],
        ) from None
    return worksheet_from_dict(data)


def json_schema() -> dict[str, Any]:
    schema = Worksheet.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://joernmht.github.io/langwich/schema/langwich-3.json"
    schema["title"] = "langwich worksheet (langwich/3)"
    return schema
