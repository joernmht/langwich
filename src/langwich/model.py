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

import difflib
import json
import re
import types
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal, Union, get_args, get_origin

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
            options = ", ".join(repr(o) for o in self.options)
            same = [o for o in self.options if o.casefold() == self.answer.casefold()]
            close = same or difflib.get_close_matches(self.answer, self.options, n=1, cutoff=0.6)
            guess = f" — did you mean {close[0]!r}?" if close else ""
            raise ValueError(
                f"answer {self.answer!r} is not one of the options ({options}); copy the right "
                f"option exactly, letter for letter{guess}"
            )
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

#: What the authoring prompt tells an LLM to reply when it cannot see the
#: attached picture. A file that holds only this is not a worksheet, and a
#: repair prompt would only make a model without the picture invent one.
NO_PICTURE_SENTINEL = "NO PICTURE ATTACHED"


@dataclass(frozen=True)
class LoadNote:
    """A repair the lenient loader made while reading a file.

    ``code`` is ``'wrapped-json'`` (text or a Markdown fence around the JSON
    object was ignored) or ``'normalized'`` (a known LLM quirk such as
    ``"kind": "multiple-choice"`` was read as the value the contract
    defines). ``langwich validate`` reports each note as a warning, so the
    LLM learns to write the file exactly.
    """

    code: str
    where: str
    message: str


class ContractError(Exception):
    """The input does not match the contract. ``problems`` holds
    ``(location, message)`` pairs, locations in JSON-pointer style.

    ``code`` is ``'contract'``, or ``'no-picture-attached'`` when the file is
    the prompt's :data:`NO_PICTURE_SENTINEL` reply. ``notes`` are the repairs
    the lenient loader made before the problem was found."""

    def __init__(
        self,
        problems: list[tuple[str, str]],
        hint: str | None = None,
        *,
        code: str = "contract",
        notes: list[LoadNote] | None = None,
    ):
        self.problems = problems
        self.hint = hint
        self.code = code
        self.notes: list[LoadNote] = list(notes or [])
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

NO_PICTURE_MESSAGE = (
    f"the file contains only the reply '{NO_PICTURE_SENTINEL}': the LLM could not see the "
    "picture the prompt refers to, so it wrote no worksheet. Attach the image to a model "
    "that accepts pictures and ask again, or make the prompt without --image."
)

#: Kind names LLMs use instead of the contract's (after lower-casing and
#: turning spaces and hyphens into underscores).
KIND_ALIASES: dict[str, str] = {
    "mcq": "multiple_choice",
    "multiplechoice": "multiple_choice",
    "multiple_choice_question": "multiple_choice",
    "multiple_choice_questions": "multiple_choice",
    "fill_in_the_blank": "cloze",
    "fill_in_the_blanks": "cloze",
    "fill_in_blanks": "cloze",
    "fill_blanks": "cloze",
    "fill_the_gaps": "cloze",
    "fill_in_the_gaps": "cloze",
    "gap_fill": "cloze",
    "gapfill": "cloze",
    "true_or_false": "true_false",
    "truefalse": "true_false",
    "matching": "match",
    "ordering": "order_events",
    "order": "order_events",
    "sequencing": "order_events",
    "short_answer": "questions",
    "short_answers": "questions",
    "open_questions": "questions",
    "essay": "writing",
    "drawing": "draw",
    "labelling": "label",
    "labeling": "label",
    "dialog": "dialogue",
    "transformation": "transform",
    "word_formation": "word_building",
}

#: Language names an LLM may write instead of a language code.
LANGUAGE_NAMES: dict[str, str] = {
    "english": "en", "german": "de", "deutsch": "de", "french": "fr", "français": "fr",
    "francais": "fr", "spanish": "es", "español": "es", "espanol": "es", "italian": "it",
    "italiano": "it", "portuguese": "pt", "português": "pt", "portugues": "pt",
    "dutch": "nl", "nederlands": "nl", "polish": "pl", "polski": "pl", "swedish": "sv",
    "danish": "da", "norwegian": "no", "finnish": "fi", "czech": "cs", "turkish": "tr",
    "greek": "el", "russian": "ru", "ukrainian": "uk", "arabic": "ar", "hebrew": "he",
    "japanese": "ja", "chinese": "zh", "mandarin": "zh", "korean": "ko",
}


def canonical_kind(kind: str) -> str | None:
    """The task kind an LLM meant (``'Multiple-Choice'`` -> ``'multiple_choice'``),
    or ``None`` when the name is unknown."""
    key = re.sub(r"[\s-]+", "_", kind.strip().lower())
    if key in TASK_KINDS:
        return key
    return KIND_ALIASES.get(key)


def _canonical_lang(code: str) -> str:
    primary, sep, rest = code.strip().replace("_", "-").partition("-")
    return primary.lower() + sep + rest


def normalize_quirks(data: Any) -> list[LoadNote]:
    """Fix known LLM quirks in raw worksheet data *in place*; one note per repair.

    * task kinds written differently (``multiple-choice``, ``mcq``,
      ``fill_in_the_blanks``, ``true_or_false``, ``matching``, ``ordering``,
      ``short_answer``, ``essay``, ``drawing``, …);
    * facts given as plain strings (read as ``{"text": …}``);
    * a lower-case CEFR level (``b1``) and upper-case language codes (``DE``).

    Nothing else is guessed: everything else is reported by the contract.
    """
    notes: list[LoadNote] = []
    if not isinstance(data, dict):
        return notes
    level = data.get("cefr_level")
    if isinstance(level, str) and level not in CEFR_LEVELS and level.strip().upper() in CEFR_LEVELS:
        data["cefr_level"] = level.strip().upper()
        notes.append(LoadNote(
            "normalized", "/cefr_level",
            f"cefr_level {level!r} was read as {data['cefr_level']!r}; write the level in "
            "capitals: A1, A2, B1, B2, C1 or C2.",
        ))
    for key in ("source_lang", "target_lang"):
        value = data.get(key)
        if isinstance(value, str) and not re.fullmatch(_LANG_PATTERN, value):
            fixed = _canonical_lang(value)
            if re.fullmatch(_LANG_PATTERN, fixed):
                data[key] = fixed
                notes.append(LoadNote(
                    "normalized", f"/{key}",
                    f"{key} {value!r} was read as {fixed!r}; write language codes in lower "
                    "case, e.g. 'en', 'de', 'pt-BR'.",
                ))
    facts = data.get("facts")
    if isinstance(facts, list):
        plain = [i for i, f in enumerate(facts) if isinstance(f, str) and f.strip()]
        for i in plain:
            facts[i] = {"text": facts[i].strip()}
        if plain:
            notes.append(LoadNote(
                "normalized", "/facts",
                f"{len(plain)} fact{'s were' if len(plain) != 1 else ' was'} written as a plain "
                "string and read as {\"text\": …}; write every fact as an object, e.g. "
                "{\"scene\": \"s1\", \"text\": \"…\", \"source\": \"…\"}.",
            ))
    tasks = data.get("tasks")
    if isinstance(tasks, list):
        for i, task in enumerate(tasks):
            if not isinstance(task, dict) or not isinstance(task.get("kind"), str):
                continue
            kind = task["kind"]
            canon = canonical_kind(kind)
            if canon is not None and canon != kind:
                task["kind"] = canon
                notes.append(LoadNote(
                    "normalized", f"/tasks/{i}/kind",
                    f"the task kind {kind!r} was read as {canon!r}; write it exactly as "
                    f"{canon!r}.",
                ))
    return notes


# -- friendly contract messages ----------------------------------------------


def _pointer(loc: tuple[Any, ...]) -> str:
    return "/" + "/".join(str(p) for p in loc) if loc else "/"


def _json_location(loc: tuple[Any, ...], data: Any) -> tuple[Any, ...]:
    """The part of a pydantic error location that points into the input.

    pydantic adds union member tags to locations (the task kind ``'match'``,
    ``'str'``, ``'list[constrained-str]'``, ``'function-after[…]'``); they
    are not keys of the file. A location part is kept when it is a key or
    index of the data at that point (or the missing last field)."""
    out: list[Any] = []
    node: Any = data
    for i, part in enumerate(loc):
        last = i == len(loc) - 1
        if isinstance(node, dict) and isinstance(part, str) and part in node:
            out.append(part)
            node = node[part]
        elif isinstance(node, list) and isinstance(part, int) and 0 <= part < len(node):
            out.append(part)
            node = node[part]
        elif last and isinstance(node, dict) and isinstance(part, str):
            out.append(part)  # a missing field
            node = None
        # anything else is a union tag: drop it
    return tuple(out)


def _unwrap(annotation: Any, value: Any) -> Any:
    """The model class or ``list[…]`` an annotation stands for, given the value."""
    origin = get_origin(annotation)
    if origin is Annotated:
        return _unwrap(get_args(annotation)[0], value)
    if origin in (Union, types.UnionType):
        members = [a for a in get_args(annotation) if a is not type(None)]
        models: list[type[BaseModel]] = [
            a for a in members if isinstance(a, type) and issubclass(a, BaseModel)
        ]
        if len(models) > 1:
            kind = value.get("kind") if isinstance(value, dict) else None
            return next(
                (m for m in models
                 if "kind" in m.model_fields and get_args(m.model_fields["kind"].annotation) == (kind,)),
                None,
            )
        if models:
            return models[0]
        return next((a for a in members if get_origin(a) is list), None)
    return annotation


def _field(model: type[BaseModel], key: str) -> Any:
    for name, info in model.model_fields.items():
        if key in (name, info.alias):
            return info
    return None


def _model_at(data: Any, parts: tuple[Any, ...]) -> Any:
    """The model class (or ``list[…]``) that describes ``data`` at ``parts``."""
    ann: Any = Worksheet
    node: Any = data
    for part in parts:
        if isinstance(ann, type) and issubclass(ann, BaseModel):
            info = _field(ann, part) if isinstance(part, str) else None
            if info is None:
                return None
            node = node.get(part) if isinstance(node, dict) else None
            ann = _unwrap(info.annotation, node)
        elif get_origin(ann) is list and isinstance(part, int):
            node = node[part] if isinstance(node, list) and part < len(node) else None
            ann = _unwrap(get_args(ann)[0], node)
        else:
            return None
    return ann


def _field_names(model: type[BaseModel]) -> list[str]:
    return [info.alias or name for name, info in model.model_fields.items()]


def _did_you_mean(value: str, options: list[str]) -> str:
    lowered = {o.casefold(): o for o in options}
    if value.casefold() in lowered:
        return f" (did you mean '{lowered[value.casefold()]}'?)"
    close = difflib.get_close_matches(value, options, n=1, cutoff=0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


def _object_example(model: Any) -> str:
    if not (isinstance(model, type) and issubclass(model, BaseModel)):
        return ""
    cls: type[BaseModel] = model
    fields = cls.model_fields
    required = [info.alias or name for name, info in fields.items() if info.is_required()]
    if not required:
        return ""
    body = ", ".join(f'"{name}": …' for name in required)
    return f", e.g. {{{body}}}"


def _describe(value: Any) -> str:
    if isinstance(value, str):
        return "a plain string"
    if isinstance(value, bool):
        return "true/false"
    if isinstance(value, (int, float)):
        return "a number"
    if isinstance(value, list):
        return "a list"
    if isinstance(value, dict):
        return "an object {…}"
    if value is None:
        return "null"
    return "a different type"


_KINDS_TEXT = ", ".join(f"'{k}'" for k in TASK_KINDS)


def _friendly(error: dict[str, Any], parts: tuple[Any, ...], data: Any) -> str:
    """An LLM-actionable message for one pydantic error."""
    kind = error["type"]
    msg = str(error["msg"])
    ctx = error.get("ctx") or {}
    value = error.get("input")
    name = next((p for p in reversed(parts) if isinstance(p, str)), "")
    subject = f"each entry of '{name}'" if parts and isinstance(parts[-1], int) else f"'{name}'"
    if kind == "missing":
        parent = _model_at(data, parts[:-1])
        info = _field(parent, name) if isinstance(parent, type) and issubclass(parent, BaseModel) else None
        about = f" ({info.description})" if info is not None and info.description else ""
        return f"the required field '{name}' is missing{about}; add it (see 'langwich schema')."
    if kind == "extra_forbidden":
        parent = _model_at(data, parts[:-1])
        if isinstance(parent, type) and issubclass(parent, BaseModel):
            fields = _field_names(parent)
            return (
                f"'{name}' is not a field here{_did_you_mean(name, fields)}; remove it, or move "
                f"its content into one of the fields defined here: {', '.join(fields)}."
            )
        return f"'{name}' is not a field here; remove it (see 'langwich schema')."
    if kind == "union_tag_not_found":
        return f"every task needs a 'kind': one of {_KINDS_TEXT}."
    if kind == "union_tag_invalid":
        tag = str(ctx.get("tag", value))
        guess = canonical_kind(tag)
        hint = f" (did you mean '{guess}'?)" if guess else _did_you_mean(tag, list(TASK_KINDS))
        return f"'{tag}' is not a task kind{hint}. Use one of {_KINDS_TEXT}."
    if kind in ("model_type", "model_attributes_type", "dict_type"):
        example = _object_example(_model_at(data, parts))
        return f"this must be a JSON object {{…}}{example}, not {_describe(value)}."
    if kind == "literal_error":
        options = re.findall(r"'([^']*)'", str(ctx.get("expected", "")))
        hint = _did_you_mean(str(value), options) if isinstance(value, str) else ""
        return f"{value!r} is not allowed for '{name}'{hint}; use one of {', '.join(repr(o) for o in options)}."
    if kind == "string_pattern_mismatch":
        if name in ("source_lang", "target_lang") and isinstance(value, str):
            code = LANGUAGE_NAMES.get(value.strip().casefold())
            guess = f" (did you mean '{code}'?)" if code else ""
            return (
                f"{value!r} is not a language code{guess}; write an ISO 639-1 code such as "
                "'en', 'de', 'fr', 'es', optionally with a region: 'pt-BR'."
            )
        if ctx.get("pattern") == _ID_PATTERN:
            return (
                f"{value!r} is not a valid id: use only letters, digits, '_' and '-', starting "
                "with a letter or digit (e.g. 's1', 'lena', 'g-passive')."
            )
    if name == "scene" and kind in ("string_type", "list_type"):
        return "'scene' must be a scene id such as \"s1\", or a list of scene ids such as [\"s1\", \"s2\"]."
    if kind in ("string_type", "string_sub_type"):
        return f"{subject} must be text in double quotes, not {_describe(value)}."
    if kind == "list_type":
        return f"{subject} must be a list [ … ], not {_describe(value)}."
    if kind in ("bool_type", "bool_parsing"):
        return f"{subject} must be true or false (without quotes)."
    if kind in ("int_type", "int_parsing", "int_from_float"):
        return f"{subject} must be a whole number."
    if kind == "string_too_short":
        return f"{subject} must not be empty."
    if kind == "too_short":
        return f"'{name}' needs at least {ctx.get('min_length')} entries."
    if kind == "value_error":
        return re.sub(r"^Value error, ", "", msg)
    return msg


def _problems(exc: ValidationError, data: Any) -> list[tuple[str, str]]:
    grouped: dict[str, list[str]] = {}
    type_only: dict[str, bool] = {}
    for error in exc.errors():
        parts = _json_location(tuple(error["loc"]), data)
        where = _pointer(parts)
        messages = grouped.setdefault(where, [])
        text = _friendly(error, parts, data)
        if text not in messages:
            messages.append(text)
        type_only[where] = type_only.get(where, True) and str(error["type"]).endswith("_type")
    # A union member that did not even have the right type (scene: 'a string'
    # when a list was given) is noise when another member got further.
    deeper = {w for w in grouped if any(o.startswith(w.rstrip("/") + "/") for o in grouped if o != w)}
    return [
        (where, " Or: ".join(messages)) for where, messages in grouped.items()
        if not (where in deeper and type_only[where])
    ]


def worksheet_from_dict(data: Any) -> Worksheet:
    """Check parsed JSON against the contract (strictly: no quirks are fixed —
    :func:`parse_worksheet` does that first)."""
    if not isinstance(data, dict):
        raise ContractError([("/", "the top level must be a JSON object {…}")])
    if "story" not in data and "content" in data:
        raise ContractError([("/story", "the required field 'story' is missing")], hint=LEGACY_HINT)
    if data.get("schema") not in (None, SCHEMA_ID) and "schema" in data:
        raise ContractError(
            [("/schema", f"expected {SCHEMA_ID!r}, got {data.get('schema')!r}")],
        )
    try:
        return Worksheet.model_validate(data)
    except ValidationError as exc:
        raise ContractError(_problems(exc, data)) from None


# -- reading text ----------------------------------------------------------------


def strip_code_fence(raw: str) -> str | None:
    """The JSON inside a Markdown ```json … ``` fence that wraps the whole
    text, or ``None`` when the text is not fenced."""
    text = raw.strip()
    if not text.startswith("```"):
        return None
    body = text.splitlines()[1:]
    if body and body[-1].strip().startswith("```"):
        body = body[:-1]
    return "\n".join(body)


def is_no_picture_reply(raw: str) -> bool:
    """True when the whole text is the prompt's :data:`NO_PICTURE_SENTINEL`."""
    text = raw.strip().strip("`'\"“”„ \t\r\n").rstrip(".!").strip()
    return text.upper() == NO_PICTURE_SENTINEL


_FENCE_LINE_RE = re.compile(r"^[ \t]*(```|~~~)")


def _fenced_blocks(text: str) -> list[tuple[int, str]]:
    """``(offset, content)`` of every Markdown code fence (an unclosed last
    fence runs to the end of the text)."""
    blocks: list[tuple[int, str]] = []
    offset = 0
    start: int | None = None
    for line in text.splitlines(keepends=True):
        if _FENCE_LINE_RE.match(line):
            if start is None:
                start = offset + len(line)
            else:
                blocks.append((start, text[start:offset]))
                start = None
        offset += len(line)
    if start is not None:
        blocks.append((start, text[start:]))
    return blocks


def _object_end(text: str, start: int) -> int | None:
    """Index after the ``}`` that closes the ``{`` at ``start`` (strings respected)."""
    depth = 0
    in_string = escaped = False
    for i in range(start, len(text)):
        c = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif c == "\\":
                escaped = True
            elif c == '"':
                in_string = False
        elif c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return None


def _candidates(text: str) -> list[tuple[int, str]]:
    """Places where a wrapped JSON object may be: fenced blocks first, then
    the balanced ``{…}`` from the first brace (or the first line that starts
    with one), then everything from the first ``{`` to the last ``}``."""
    out: list[tuple[int, str]] = []
    for offset, body in _fenced_blocks(text):
        lead = len(body) - len(body.lstrip())
        if body.strip().startswith("{"):
            out.append((offset + lead, body.strip()))
    starts = []
    first = text.find("{")
    if first >= 0:
        starts.append(first)
    line_start = re.search(r"^[ \t]*\{", text, re.MULTILINE)
    if line_start is not None:
        starts.append(line_start.end() - 1)
    for start in dict.fromkeys(starts):
        end = _object_end(text, start)
        if end is not None:
            out.append((start, text[start:end]))
    last = text.rfind("}")
    if first >= 0 and last > first:
        out.append((first, text[first:last + 1]))
    return list(dict.fromkeys(out))


def _quote(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return "'" + (text[: limit - 1] + "…" if len(text) > limit else text) + "'"


def _wrapped_note(text: str, start: int, end: int) -> LoadNote:
    outside = [
        line.strip() for line in (text[:start] + "\n" + text[end:]).splitlines() if line.strip()
    ]
    prose = [line for line in outside if not _FENCE_LINE_RE.match(line)]
    fenced = len(prose) < len(outside)
    if fenced and not prose:
        what = "a Markdown code fence"
    elif fenced:
        what = f"a Markdown code fence and other text ({_quote(prose[0])})"
    else:
        what = f"other text ({_quote(prose[0])})"
    return LoadNote(
        "wrapped-json", "/",
        f"the JSON object is wrapped in {what}; only the object was read. Save only the JSON "
        "object: start with { and end with }, no code fence, no other text.",
    )


#: Top-level keys that tell a worksheet (or a langwich v2 file) from one of
#: its nested objects.
_WORKSHEET_KEYS = frozenset({"schema", "story", "tasks", "vocabulary", "content"})


def json_error_message(text: str, exc: json.JSONDecodeError, where: str = "") -> str:
    """A friendly message for a JSON syntax error (positions refer to ``text``)."""
    if not text.strip():
        return "the file is empty; it must contain the worksheet JSON object, starting with {."
    lines = text.splitlines()
    snippet = lines[exc.lineno - 1].strip() if 0 < exc.lineno <= len(lines) else ""
    before = text[: exc.pos].rstrip()
    hint = ""
    if before.endswith(",") and ("Expecting property name" in exc.msg or "Expecting value" in exc.msg):
        hint = " (a trailing comma before } or ]? Remove the comma after the last entry)"
    elif "Expecting property name" in exc.msg:
        hint = " (names and strings need double quotes \"…\", not single quotes)"
    elif "Expecting ',' delimiter" in exc.msg:
        hint = (" (a missing comma, or an unescaped \" inside a string? Use „…“ or \\\")"
                if exc.pos < len(text.rstrip()) else " (the JSON ends too early: was it cut off?)")
    elif "Unterminated string" in exc.msg:
        hint = " (a string without its closing \" — was the reply cut off?)"
    elif "Invalid control character" in exc.msg:
        hint = " (a raw line break inside a string? Write it as \\n)"
    elif "Extra data" in exc.msg:
        hint = " (text after the JSON object? Save only the object, from { to })"
    elif "Expecting value" in exc.msg and not before:
        hint = " (the file must contain only the JSON object, starting with {)"
    message = f"invalid JSON{where} at line {exc.lineno}, column {exc.colno}: {exc.msg}{hint}"
    if snippet:
        message += f". The line reads: {_quote(snippet, 90)}"
    return message


def parse_json_text(text: str) -> tuple[Any, list[LoadNote]]:
    """Parse the text of a worksheet file leniently.

    Strict JSON first; if that fails, a JSON object inside a Markdown fence
    or surrounded by chat text is extracted (only when it parses as an
    object) and reported as a ``wrapped-json`` note. Nothing inside the JSON
    is repaired. Raises :class:`ContractError` for the prompt's
    :data:`NO_PICTURE_SENTINEL` reply and for text without a readable object
    (the error position refers to the file, the hint to the likely cause).
    """
    if is_no_picture_reply(text):
        raise ContractError([("/", NO_PICTURE_MESSAGE)], code="no-picture-attached")
    try:
        return json.loads(text), []
    except json.JSONDecodeError as exc:
        first_error = exc
    candidates = _candidates(text)
    for start, body in candidates:
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and _WORKSHEET_KEYS & set(data):
            return data, [_wrapped_note(text, start, start + len(body))]
    if text.lstrip().startswith("{") or not candidates:
        if not candidates and text.strip() and "{" not in text:
            raise ContractError([(
                "/",
                "the file contains no JSON object: it must be the worksheet JSON, starting "
                f"with {{ and ending with }}. It starts with {_quote(text.strip().splitlines()[0])}.",
            )])
        raise ContractError([("/", json_error_message(text, first_error))])
    # Report the error inside the most likely object, at its place in the file.
    start, body = candidates[0]
    try:
        json.loads(body)
    except json.JSONDecodeError as inner:
        mapped = json.JSONDecodeError(inner.msg, text, start + inner.pos)
        fenced = any(offset <= start < offset + len(b) + 1 for offset, b in _fenced_blocks(text))
        where = " inside the code fence" if fenced else " in the JSON object"
        raise ContractError([(
            "/",
            json_error_message(text, mapped, where)
            + " (the text around the object is ignored once the object itself is valid JSON)",
        )]) from None
    raise ContractError([("/", json_error_message(text, first_error))])  # pragma: no cover


def parse_worksheet(text: str) -> tuple[Worksheet, list[LoadNote]]:
    """Read worksheet JSON text leniently: extract a wrapped object, fix known
    quirks (see :func:`normalize_quirks`), then check it against the contract.

    Returns the worksheet and the repairs made; raises :class:`ContractError`
    (carrying those repairs as ``notes``) when the text cannot be read."""
    data, notes = parse_json_text(text)
    notes += normalize_quirks(data)
    try:
        return worksheet_from_dict(data), notes
    except ContractError as exc:
        exc.notes = notes + exc.notes
        raise


def load_worksheet(path: str | Path, notes: list[LoadNote] | None = None) -> Worksheet:
    """Load and check a worksheet file; every failure is a :class:`ContractError`.

    Loading is lenient (see :func:`parse_worksheet`); pass a list as
    ``notes`` to receive the repairs that were made."""
    path = Path(path)
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        raise ContractError([("/", f"file not found: {path}")]) from None
    except IsADirectoryError:
        raise ContractError([("/", f"{path} is a folder, not a file")]) from None
    except UnicodeDecodeError as exc:
        raise ContractError([(
            "/", f"{path} is not UTF-8 text (undecodable byte at position {exc.start}); save it "
            "as UTF-8.",
        )]) from None
    except OSError as exc:
        raise ContractError([("/", f"cannot read {path}: {exc.strerror or exc}")]) from None
    ws, found = parse_worksheet(raw)
    if notes is not None:
        notes.extend(found)
    return ws


def json_schema() -> dict[str, Any]:
    schema = Worksheet.model_json_schema(by_alias=True)
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["$id"] = "https://joernmht.github.io/langwich/schema/langwich-3.json"
    schema["title"] = "langwich worksheet (langwich/3)"
    return schema
