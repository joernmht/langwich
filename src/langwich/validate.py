"""Semantic checks beyond the schema.

The pydantic models in :mod:`langwich.model` make sure a worksheet has the
right *shape*. This module checks what a schema cannot: that references
point somewhere, that every cloze has gaps, that the target words are
really practised, that the story is long enough for the level, and so on.

Every finding is an :class:`Issue` with

* a ``level`` — errors block rendering, warnings are printed (and fail the
  CLI with ``--strict``),
* a stable kebab-case ``code`` (see :data:`CHECKS`),
* a JSON pointer ``where`` into the input file (``/tasks/3/items/1``),
* a ``message`` written so that an LLM can fix the file from it alone —
  ``langwich validate --prompt`` feeds these messages back to the model.
"""

from __future__ import annotations

import difflib
import json
import re
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote, urlparse

from langwich import locale, markup
from langwich.model import (
    CEFR_LEVELS,
    TASK_KINDS,
    ClozeTask,
    ContractError,
    DialogueTask,
    DrawTask,
    LabelTask,
    MatchTask,
    MediaSearchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    QuestionsTask,
    Task,
    TransformTask,
    TrueFalseTask,
    VocabItem,
    WordBuildingTask,
    Worksheet,
    WritingTask,
    strip_code_fence,
    worksheet_from_dict,
)
from langwich.plan import plan as make_plan
from langwich.plan import strip_article, term_pattern

Level = Literal["error", "warning"]

#: Every check langwich runs: code -> (level, what it catches).
CHECKS: dict[str, tuple[Level, str]] = {
    # errors
    "contract": ("error", "the file is not valid JSON or does not match the langwich/3 schema"),
    "legacy-format": ("error", "a langwich v2 file; convert it with 'langwich prompt --from-json'"),
    "duplicate-id": ("error", "two scenes, tasks, characters, facts or grammar points share an id"),
    "unknown-scene": ("error", "a reference to a scene id that does not exist"),
    "unknown-grammar": ("error", "a task references a grammar id that does not exist"),
    "target-not-in-items": ("error", "a vocabulary.target word has no entry in vocabulary.items"),
    "same-language": ("error", "source_lang and target_lang are the same"),
    "cloze-without-gaps": ("error", "a cloze text or item without {{gaps}}"),
    "missing-gap-hint": ("error", "a base_form/translation cloze gap without a ::hint"),
    "empty-gap": ("error", "an empty gap {{}}"),
    "unbalanced-braces": ("error", "a stray '{{' or '}}' in a cloze or dialogue text"),
    "markup-in-story": ("error", "gap markup {{…}} inside a scene"),
    "label-without-labels": ("error", "a label task on a scene whose picture has no labels"),
    "duplicate-label-number": ("error", "two labels of one picture share a marker number"),
    "label-without-position": ("error", "a label without x/y on a picture with an image or svg"),
    "duplicate-match-partner": ("error", "a match task lists the same entry twice in a column"),
    "duplicate-event": ("error", "an order_events task lists the same event twice"),
    "dialogue-nothing-to-do": ("error", "a dialogue task without gaps or lines to write"),
    "word-range": ("error", "a writing task with min_words > max_words"),
    # warnings
    "code-fence": ("warning", "the JSON is wrapped in a Markdown code fence"),
    "no-production": ("warning", "no production task"),
    "no-comprehension": ("warning", "no gist or detail task"),
    "scene-count": ("warning", "fewer than 2 or more than 7 scenes"),
    "story-length": ("warning", "the story is too short or too long for its CEFR level"),
    "target-count": ("warning", "fewer than 5 or more than 15 target words"),
    "duplicate-target": ("warning", "a word is listed twice in vocabulary.target"),
    "target-underused": ("warning", "a target word is practised in fewer than two tasks"),
    "target-not-in-story": ("warning", "a target word does not occur in the story"),
    "copies-story": ("warning", "a practice item copies a sentence from the story"),
    "distractor-is-answer": ("warning", "a cloze distractor is also one of the answers"),
    "bank-without-gaps": ("warning", "a dialogue asks for a word bank but has no gaps"),
    "markup-outside-gaps": ("warning", "gap markup in a field where it is printed literally"),
    "no-facts": ("warning", "no 'Did you know?' facts"),
    "no-characters": ("warning", "no characters"),
    "review-unused": ("warning", "a series review word is not used anywhere"),
    "missing-previously": ("warning", "episode 2 or later without a 'previously' recap"),
    "unknown-ui-key": ("warning", "a ui key that is not a page-furniture string"),
    "missing-ui-strings": ("warning", "page furniture would fall back to English"),
    "noun-without-article": ("warning", "a noun without its article"),
    "image-not-found": ("warning", "a picture.image file that cannot be found"),
    "label-draws-instead": ("warning", "a label task printed as 'draw and label' (no image/svg)"),
    "grammar-gives-away": ("warning", "a grammar box beside a task shows one of its answers"),
}

#: Problems in the user's environment (files, formats) rather than in the
#: JSON: an LLM cannot fix them, so repair prompts leave them out and the CLI
#: tells the user instead.
ENVIRONMENT_CODES: frozenset[str] = frozenset({"image-not-found", "image-unreadable"})

#: Total words across all scenes, per CEFR level.
STORY_WORDS: dict[str, tuple[int, int]] = {
    "A1": (60, 200),
    "A2": (120, 300),
    "B1": (220, 450),
    "B2": (350, 700),
    "C1": (500, 1000),
    "C2": (600, 1200),
}
assert set(STORY_WORDS) == set(CEFR_LEVELS)

SCENES_MIN, SCENES_MAX = 2, 7
TARGET_MIN, TARGET_MAX = 5, 15
COPY_RATIO = 0.85

#: Articles a noun must start with, per target language.
NOUN_ARTICLES: dict[str, tuple[str, ...]] = {
    "de": ("der", "die", "das"),
    "fr": ("le", "la", "les", "un", "une", "des"),
    "es": ("el", "la", "los", "las", "un", "una", "unos", "unas"),
    "it": ("il", "lo", "la", "i", "gli", "le", "un", "uno", "una"),
    "pt": ("o", "a", "os", "as", "um", "uma"),
}
_ELIDED_ARTICLES: dict[str, tuple[str, ...]] = {
    "fr": ("l'", "l’"),
    "it": ("l'", "l’", "un'", "un’"),
}
_ARTICLE_EXAMPLE: dict[str, str] = {
    "de": "der/die/das",
    "fr": "le/la/l'/les",
    "es": "el/la/los/las",
    "it": "il/lo/la/l'/i/gli/le",
    "pt": "o/a/os/as",
}

#: Scripts written without spaces between words: word counts are meaningless.
_NO_SPACE_LANGS = frozenset({"zh", "ja", "th", "lo", "km", "my", "bo"})

_WORD_RE = re.compile(r"\w+(?:['’-]\w+)*")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
_SINGLE_BRACE_RE = re.compile(r"(?<!\{)\{[^{}\n]+\}(?!\})")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


# ---------------------------------------------------------------------------
# Issue and report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Issue:
    level: Literal["error", "warning"]
    code: str
    where: str
    message: str


@dataclass
class Report:
    issues: list[Issue]
    worksheet: Worksheet | None

    @property
    def errors(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def ok(self) -> bool:
        """True when nothing blocks rendering (warnings are allowed)."""
        return not self.errors

    def summary(self) -> str:
        e, w = len(self.errors), len(self.warnings)
        if not e and not w:
            return "OK: no problems found."
        parts = []
        if e:
            parts.append(f"{e} error{'s' if e != 1 else ''}")
        if w:
            parts.append(f"{w} warning{'s' if w != 1 else ''}")
        text = ", ".join(parts)
        return text if e else f"OK with {text}."

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [asdict(i) for i in self.issues],
        }

    def format_text(self) -> str:
        lines = [self.summary()]
        groups = (
            ("error", "Errors (must be fixed before rendering):"),
            ("warning", "Warnings (worth fixing; rendering still works):"),
        )
        for level, title in groups:
            group = [i for i in self.issues if i.level == level]
            if not group:
                continue
            lines += ["", title]
            for issue in group:
                lines.append(f"  {issue.where}  [{issue.code}]")
                lines.append(f"      {issue.message}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _esc(key: str) -> str:
    """Escape one JSON-pointer reference token (RFC 6901)."""
    return key.replace("~", "~0").replace("/", "~1")


def _q(text: str, limit: int = 70) -> str:
    text = " ".join(text.split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return f"'{text}'"


def _did_you_mean(value: str, options: list[str]) -> str:
    close = difflib.get_close_matches(value, options, n=1, cutoff=0.6)
    return f" (did you mean '{close[0]}'?)" if close else ""


def _one_of(options: list[str]) -> str:
    return ", ".join(f"'{o}'" for o in options) if options else "(none defined)"


def _parse_gaps(text: str) -> tuple[list[markup.Gap], str | None]:
    """Gaps of a text, or an error message instead of raising."""
    try:
        return markup.gaps(text), None
    except ValueError as exc:
        return [], str(exc)


def _gap_text(text: str) -> str:
    """Filled text plus the hints, for word searches."""
    try:
        parts = markup.split(text)
    except ValueError:
        return markup.GAP_RE.sub(" ", text)
    out: list[str] = []
    for p in parts:
        if isinstance(p, markup.Gap):
            out.append(p.answer)
            if p.hint:
                out.append(f" ({p.hint})")
        else:
            out.append(p)
    return "".join(out)


def _filled(text: str) -> str:
    try:
        return markup.fill(text)
    except ValueError:
        return markup.GAP_RE.sub(" ", text)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _norm_sentence(text: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", text).casefold().split())


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT_RE.split(text) if s and s.strip()]


def _is_url(value: str) -> bool:
    return bool(_URL_RE.match(value)) or value.startswith("data:")


def _local_image_path(image: str, base_dir: Path | None) -> Path | None:
    """Where a local picture.image should be, or None for remote URLs."""
    if image.startswith("file://"):
        return Path(unquote(urlparse(image).path))
    if _is_url(image):
        return None
    path = Path(image).expanduser()
    if not path.is_absolute():
        path = (base_dir if base_dir is not None else Path.cwd()) / path
    return path


def _has_article(term: str, lang: str) -> bool:
    low = term.strip().lower()
    if any(low.startswith(e) and len(low) > len(e) for e in _ELIDED_ARTICLES.get(lang, ())):
        return True
    first, _, rest = low.partition(" ")
    if not rest.strip():
        return False
    parts = [p.strip() for p in first.split("/")]
    return all(p in NOUN_ARTICLES[lang] for p in parts if p)


def _verb_participle_pattern(item: VocabItem) -> re.Pattern[str] | None:
    """German participles of regular verbs ('rösten' -> 'geröstet', 'aufgemacht')."""
    term = strip_article(item.term, "de")
    if " " in term or len(term) < 4:
        return None
    if term.endswith(("eln", "ern")):
        stem = term[:-1]
    elif term.endswith("en"):
        stem = term[:-2]
    elif term.endswith("n"):
        stem = term[:-1]
    else:
        return None
    return re.compile(
        r"(?<!\w)\w{0,6}?ge" + re.escape(stem) + r"(?:t|et|en)\w{0,2}(?!\w)", re.IGNORECASE,
    )


# ---------------------------------------------------------------------------
# The checker
# ---------------------------------------------------------------------------


class _Checker:
    def __init__(self, ws: Worksheet, base_dir: Path | None):
        self.ws = ws
        self.base_dir = base_dir
        self.issues: list[Issue] = []
        self.target_lang = locale.base_lang(ws.target_lang)
        self.scene_ids = [s.id for s in ws.story.scenes]
        self.scene_index = {s.id: i for i, s in enumerate(ws.story.scenes)}
        self.grammar_ids = [g.id for g in ws.grammar]

    # -- recording ----------------------------------------------------------

    def error(self, code: str, where: str, message: str) -> None:
        assert CHECKS[code][0] == "error", code
        self.issues.append(Issue("error", code, where, message))

    def warn(self, code: str, where: str, message: str) -> None:
        assert CHECKS[code][0] == "warning", code
        self.issues.append(Issue("warning", code, where, message))

    # -- word search ---------------------------------------------------------

    def patterns(self, term: str) -> list[re.Pattern[str]]:
        item = self.ws.vocab_item(term) or VocabItem.model_construct(
            term=term, translation="", pos="other", plural=None, forms=None,
            note=None, scene=None,
        )
        out = [term_pattern(item, self.target_lang)]
        if self.target_lang == "de" and item.pos in ("verb", "other"):
            extra = _verb_participle_pattern(item)
            if extra is not None:
                out.append(extra)
        return out

    def occurs(self, term: str, texts: list[str]) -> bool:
        if not strip_article(term, self.target_lang):
            return False
        pats = self.patterns(term)
        return any(p.search(t) for p in pats for t in texts)

    def task_texts(self, task: Task) -> list[str]:
        """The item strings of a task (gaps filled, hints kept). Titles and
        instructions are source-language furniture and do not count."""
        out: list[str] = []
        if isinstance(task, MatchTask):
            out += [p.left for p in task.pairs] + [p.right for p in task.pairs] + task.extra
        elif isinstance(task, TrueFalseTask):
            out += [i.statement for i in task.items] + [i.correction or "" for i in task.items]
        elif isinstance(task, MultipleChoiceTask):
            out += [i.question for i in task.items] + [o for i in task.items for o in i.options]
        elif isinstance(task, OrderEventsTask):
            out += task.events
        elif isinstance(task, QuestionsTask):
            out += [i.question for i in task.items] + [i.answer or "" for i in task.items]
        elif isinstance(task, ClozeTask):
            texts = [task.text] if task.text is not None else list(task.items or [])
            out += [_gap_text(t) for t in texts] + task.distractors
        elif isinstance(task, TransformTask):
            out += [f"{i.prompt} {i.cue or ''} {i.answer}" for i in task.items]
        elif isinstance(task, WordBuildingTask):
            out += [p for i in task.items for p in i.parts] + [i.answer for i in task.items]
        elif isinstance(task, LabelTask):
            scene = self.ws.scene(task.scene)
            if scene and scene.picture:
                out += [lb.term for lb in scene.picture.labels]
        elif isinstance(task, WritingTask):
            out += [task.prompt, task.starter or "", task.model_answer or "", *task.must_use]
        elif isinstance(task, DialogueTask):
            for line in task.lines:
                out += [_gap_text(line.text or ""), line.cue or "", line.answer or ""]
        elif isinstance(task, MediaSearchTask):
            out += task.queries + task.questions
        elif isinstance(task, DrawTask):
            out += [task.prompt, *task.labels]
        return [t for t in out if t]

    # -- errors ---------------------------------------------------------------

    def check_languages(self) -> None:
        ws = self.ws
        if ws.source_lang.casefold() == ws.target_lang.casefold():
            self.error(
                "same-language", "/target_lang",
                f"source_lang and target_lang are both '{ws.source_lang}'. source_lang is the "
                "learner's own language (translations, instructions); target_lang is the "
                "language being learned (story, tasks). Set them to two different languages.",
            )

    def check_duplicate_ids(self) -> None:
        ws = self.ws
        groups: list[tuple[str, str, list[str | None]]] = [
            ("scene", "/story/scenes", [s.id for s in ws.story.scenes]),
            ("task", "/tasks", [t.id for t in ws.tasks]),
            ("character", "/story/characters", [c.id for c in ws.story.characters]),
            ("grammar point", "/grammar", [g.id for g in ws.grammar]),
            ("fact", "/facts", [f.id for f in ws.facts]),
        ]
        for kind, base, ids in groups:
            first: dict[str, int] = {}
            for i, ident in enumerate(ids):
                if ident is None:
                    continue
                if ident in first:
                    self.error(
                        "duplicate-id", f"{base}/{i}/id",
                        f"the {kind} id '{ident}' is already used at {base}/{first[ident]}; "
                        f"give every {kind} a unique id (e.g. '{ident}b') and update any "
                        "references to it.",
                    )
                else:
                    first[ident] = i

    def _check_scene_ref(self, ref: str, where: str) -> bool:
        if ref in self.scene_index:
            return True
        self.error(
            "unknown-scene", where,
            f"there is no scene with id '{ref}'{_did_you_mean(ref, self.scene_ids)}. "
            f"Use one of the ids in story.scenes: {_one_of(self.scene_ids)}.",
        )
        return False

    def check_references(self) -> None:
        ws = self.ws
        for i, task in enumerate(ws.tasks):
            if isinstance(task.scene, list):
                for k, ref in enumerate(task.scene):
                    self._check_scene_ref(ref, f"/tasks/{i}/scene/{k}")
            elif task.scene is not None:
                self._check_scene_ref(task.scene, f"/tasks/{i}/scene")
            if task.grammar is not None and task.grammar not in self.grammar_ids:
                self.error(
                    "unknown-grammar", f"/tasks/{i}/grammar",
                    f"there is no grammar point with id '{task.grammar}'"
                    f"{_did_you_mean(task.grammar, self.grammar_ids)}. Use one of the ids in "
                    f"'grammar' ({_one_of(self.grammar_ids)}), add a grammar point with this id, "
                    "or remove the 'grammar' field from the task.",
                )
        for i, fact in enumerate(ws.facts):
            if fact.scene is not None:
                self._check_scene_ref(fact.scene, f"/facts/{i}/scene")
        for i, gp in enumerate(ws.grammar):
            if gp.scene is not None:
                self._check_scene_ref(gp.scene, f"/grammar/{i}/scene")
        for i, item in enumerate(ws.vocabulary.items):
            if item.scene is not None:
                self._check_scene_ref(item.scene, f"/vocabulary/items/{i}/scene")

    def check_target_in_items(self) -> None:
        lang = self.target_lang
        stems = {strip_article(v.term, lang).casefold(): v.term for v in self.ws.vocabulary.items}
        for k, term in enumerate(self.ws.vocabulary.target):
            if self.ws.vocab_item(term) is not None:
                continue
            near = stems.get(strip_article(term, lang).casefold())
            hint = (
                f" vocabulary.items has '{near}': write the target word exactly the same way "
                "in both places."
                if near else
                " Add an item with exactly this term (with translation and pos), or remove "
                "the word from vocabulary.target."
            )
            self.error(
                "target-not-in-items", f"/vocabulary/target/{k}",
                f"'{term}' is listed in vocabulary.target but not in vocabulary.items.{hint}",
            )

    def _check_gap_text(self, task: ClozeTask | None, text: str, where: str, what: str) -> None:
        """Checks shared by cloze texts/items and dialogue lines."""
        if markup.has_unbalanced_braces(text):
            self.error(
                "unbalanced-braces", where,
                f"{what} has an unmatched '{{{{' or '}}}}'. Write every gap as {{{{answer}}}} "
                "with two opening and two closing braces, and use no other double braces.",
            )
        found, problem = _parse_gaps(text)
        if problem is not None:
            self.error(
                "empty-gap", where,
                f"{what} contains an empty gap {{{{}}}}. Put the answer inside the braces, "
                "e.g. {{geröstet}} or {{geröstet::rösten}}.",
            )
            return
        if task is None:
            return
        if not found and problem is None:
            single = _SINGLE_BRACE_RE.search(text)
            extra = (
                f" It uses single braces ({single.group(0)}); gaps need double braces."
                if single else ""
            )
            self.error(
                "cloze-without-gaps", where,
                f"{what} has no gaps, so there is nothing to fill in.{extra} Mark each gap as "
                "{{answer}}, e.g. 'Die Bohnen werden {{geröstet}}.'",
            )
        if task.hint in ("base_form", "translation"):
            kind = "base form" if task.hint == "base_form" else "meaning in the source language"
            for gap in found:
                if not gap.hint:
                    body = "|".join(gap.accepted)
                    self.error(
                        "missing-gap-hint", where,
                        f"the gap {{{{{body}}}}} has no hint, but the task uses hint "
                        f"'{task.hint}', which prints a hint in brackets after every gap. "
                        f"Write it as {{{{{body}::<{kind}>}}}}"
                        + (", e.g. {{geröstet::rösten}}." if task.hint == "base_form" else ".")
                        + " Or change the task's hint to 'word_bank'.",
                    )

    def check_cloze_and_dialogue(self) -> None:
        for i, task in enumerate(self.ws.tasks):
            if isinstance(task, ClozeTask):
                if task.text is not None:
                    self._check_gap_text(task, task.text, f"/tasks/{i}/text", "this cloze text")
                    answers = [g.answer for g in _parse_gaps(task.text)[0]]
                else:
                    answers = []
                    for j, item in enumerate(task.items or []):
                        self._check_gap_text(task, item, f"/tasks/{i}/items/{j}", "this cloze item")
                        answers += [g.answer for g in _parse_gaps(item)[0]]
                keys = {a.casefold() for a in answers}
                for k, word in enumerate(task.distractors):
                    if word.casefold() in keys:
                        self.warn(
                            "distractor-is-answer", f"/tasks/{i}/distractors/{k}",
                            f"the distractor '{word}' is also the answer to a gap, so it is not "
                            "a distractor. Replace it with a word that fits none of the gaps.",
                        )
            elif isinstance(task, DialogueTask):
                has_gap = False
                writes = False
                for j, line in enumerate(task.lines):
                    if line.text is None:
                        writes = True
                        continue
                    self._check_gap_text(None, line.text, f"/tasks/{i}/lines/{j}/text", "this line")
                    if _parse_gaps(line.text)[0]:
                        has_gap = True
                if not has_gap and not writes:
                    self.error(
                        "dialogue-nothing-to-do", f"/tasks/{i}/lines",
                        "every line of this dialogue is already complete, so the learner has "
                        "nothing to do. Add {{gaps}} to some lines, or set 'text' to null (with "
                        "a source-language 'cue' and a model 'answer') for lines the learner "
                        "writes.",
                    )
                elif task.bank and not has_gap:
                    self.warn(
                        "bank-without-gaps", f"/tasks/{i}/bank",
                        "bank is true but no line has {{gaps}}, so the word box would be empty. "
                        "Add gaps to some lines or set bank to false.",
                    )

    def check_markup_placement(self) -> None:
        data = self.ws.model_dump(by_alias=True, mode="json", exclude_none=True)
        story_fields = re.compile(r"^/story/scenes/\d+/(text|heading|translation)$")
        gap_fields = re.compile(r"^/tasks/\d+/(text|items/\d+|lines/\d+/text)$")
        skip = re.compile(r"^/story/scenes/\d+/picture/(svg|prompt)$")

        def walk(obj: Any, where: str) -> Iterator[tuple[str, str]]:
            if isinstance(obj, str):
                yield where, obj
            elif isinstance(obj, dict):
                for key, value in obj.items():
                    yield from walk(value, f"{where}/{_esc(str(key))}")
            elif isinstance(obj, list):
                for n, value in enumerate(obj):
                    yield from walk(value, f"{where}/{n}")

        for where, text in walk(data, ""):
            if "{{" not in text and "}}" not in text:
                continue
            if skip.match(where):
                continue
            if story_fields.match(where):
                self.error(
                    "markup-in-story", where,
                    "the story contains gap markup '{{…}}', but scenes are printed as plain "
                    "prose. Remove the braces here; put gaps only in cloze tasks or dialogue "
                    "lines (with new sentences, not copied from the story).",
                )
            elif gap_fields.match(where) and self._is_gap_field(where):
                continue
            else:
                self.warn(
                    "markup-outside-gaps", where,
                    "gap markup '{{…}}' is only read in cloze texts/items and dialogue lines; "
                    "here it would be printed literally, braces included. Remove the braces "
                    "(or turn this into a cloze task).",
                )

    def _is_gap_field(self, where: str) -> bool:
        index = int(where.split("/")[2])
        task = self.ws.tasks[index]
        return isinstance(task, (ClozeTask, DialogueTask))

    def check_pictures(self) -> None:
        for si, scene in enumerate(self.ws.story.scenes):
            pic = scene.picture
            if pic is None:
                continue
            base = f"/story/scenes/{si}/picture"
            seen: dict[int, int] = {}
            for j, lb in enumerate(pic.labels):
                if lb.n in seen:
                    self.error(
                        "duplicate-label-number", f"{base}/labels/{j}/n",
                        f"marker number {lb.n} is already used by labels/{seen[lb.n]} "
                        f"('{pic.labels[seen[lb.n]].term}'); number the labels 1, 2, 3 … "
                        "without repeats.",
                    )
                else:
                    seen[lb.n] = j
                if pic.has_visual and not pic.numbers_in_image and (lb.x is None or lb.y is None):
                    self.error(
                        "label-without-position", f"{base}/labels/{j}",
                        f"label {lb.n} ('{lb.term}') has no x/y position, but the picture has "
                        "an image or svg, so langwich cannot place its marker. Add x and y "
                        "(fractions 0–1 of the picture width/height, measured from the top-left "
                        "corner), or set numbers_in_image: true if the numbers are already "
                        "drawn in the image.",
                    )
            if pic.image:
                path = _local_image_path(pic.image, self.base_dir)
                if path is not None and not path.is_file():
                    self.warn(
                        "image-not-found", f"{base}/image",
                        f"the picture file '{pic.image}' was not found (looked for {path}). "
                        "Put the file next to the JSON file, fix the path, use an http(s) URL, "
                        "or remove 'image' (then add a simple black line-art 'svg', or the "
                        "label task is printed as 'draw and label').",
                    )

    def check_tasks(self) -> None:
        for i, task in enumerate(self.ws.tasks):
            where = f"/tasks/{i}"
            if isinstance(task, LabelTask):
                scene = self.ws.scene(task.scene)
                if scene is None:
                    continue  # reported as unknown-scene
                if scene.picture is None or not scene.picture.labels:
                    self.error(
                        "label-without-labels", f"{where}/scene",
                        f"this label task names the objects in the picture of scene "
                        f"'{task.scene}', but that scene has no picture labels. Add "
                        "picture.labels [{\"n\": 1, \"term\": \"die Tasse\", \"x\": 0.3, "
                        "\"y\": 0.6}, …] to the scene (with an image or svg), or use a "
                        "different task kind.",
                    )
                elif not scene.picture.has_visual:
                    self.warn(
                        "label-draws-instead", where,
                        f"the picture of scene '{task.scene}' has labels but neither 'image' "
                        "nor 'svg', so this task is printed as 'draw and label'. Add an image "
                        "path/URL or simple black line-art svg with the label positions, if a "
                        "real labelling task is wanted.",
                    )
            elif isinstance(task, MatchTask):
                lefts: dict[str, int] = {}
                for j, pair in enumerate(task.pairs):
                    key = pair.left.casefold()
                    if key in lefts:
                        self.error(
                            "duplicate-match-partner", f"{where}/pairs/{j}/left",
                            f"'{pair.left}' is already in the left column (pairs/{lefts[key]}); "
                            "every left entry must be unique.",
                        )
                    else:
                        lefts[key] = j
                rights: dict[str, str] = {}
                entries = [(f"pairs/{j}/right", p.right) for j, p in enumerate(task.pairs)]
                entries += [(f"extra/{k}", e) for k, e in enumerate(task.extra)]
                for rel, value in entries:
                    key = value.casefold()
                    if key in rights:
                        self.error(
                            "duplicate-match-partner", f"{where}/{rel}",
                            f"'{value}' is already in the right column ({rights[key]}); every "
                            "right entry, including 'extra' distractors, must be unique, or "
                            "the learner cannot tell which letter is meant.",
                        )
                    else:
                        rights[key] = rel
            elif isinstance(task, OrderEventsTask):
                seen: dict[str, int] = {}
                for j, event in enumerate(task.events):
                    key = " ".join(event.casefold().split())
                    if key in seen:
                        self.error(
                            "duplicate-event", f"{where}/events/{j}",
                            f"the event {_q(event)} is already listed (events/{seen[key]}); "
                            "each event must be different, or the order is ambiguous.",
                        )
                    else:
                        seen[key] = j
            elif isinstance(task, WritingTask):
                if (
                    task.min_words is not None
                    and task.max_words is not None
                    and task.min_words > task.max_words
                ):
                    self.error(
                        "word-range", f"{where}/min_words",
                        f"min_words ({task.min_words}) is greater than max_words "
                        f"({task.max_words}); swap them so that min_words ≤ max_words.",
                    )

    # -- warnings -------------------------------------------------------------

    def check_arc(self) -> None:
        stages = {t.stage for t in self.ws.tasks}
        if "production" not in stages:
            self.warn(
                "no-production", "/tasks",
                "no task has stage 'production'. Add a 'writing' (or 'dialogue') task after the "
                "story where the learner uses the target words in a text of their own, tied to "
                "the story (e.g. 'Lena texts her mum about her week').",
            )
        if not stages & {"gist", "detail"}:
            self.warn(
                "no-comprehension", "/tasks",
                "no task has stage 'gist' or 'detail'. Add comprehension tasks about the story "
                "(true_false, multiple_choice, order_events or questions), anchored to their "
                "scenes with 'scene'.",
            )

    def check_story(self) -> None:
        ws = self.ws
        n = len(ws.story.scenes)
        if not SCENES_MIN <= n <= SCENES_MAX:
            self.warn(
                "scene-count", "/story/scenes",
                f"the story has {n} scene{'s' if n != 1 else ''}; use {SCENES_MIN}–{SCENES_MAX} "
                "(4 is typical: setup, development, complication, resolution)"
                + (" — split the text into scenes with their own headings." if n < SCENES_MIN
                   else " — merge some scenes or move the rest to the next episode."),
            )
        if self.target_lang not in _NO_SPACE_LANGS:
            words = sum(_word_count(s.text) for s in ws.story.scenes)
            low, high = STORY_WORDS[ws.cefr_level]
            if not low <= words <= high:
                verb = "Lengthen" if words < low else "Shorten"
                self.warn(
                    "story-length", "/story/scenes",
                    f"the story has {words} words in total; a {ws.cefr_level} story should have "
                    f"{low}–{high}. {verb} the scene texts (not the tasks) accordingly.",
                )
        if not ws.facts:
            self.warn(
                "no-facts", "/facts",
                "the worksheet has no facts. Add 1–3 true, checkable facts about the topic in "
                "the target language (with 'scene' and a short 'source'); they appear as "
                "'Did you know?' sidebars next to the story.",
            )
        if not ws.story.characters:
            self.warn(
                "no-characters", "/story/characters",
                "story.characters is empty. Add the protagonist and 1–3 other people (id, name, "
                "a one-line role in the source language) so the story has people to follow.",
            )

    def check_target_words(self) -> None:
        ws = self.ws
        target = ws.vocabulary.target
        n = len(target)
        if not TARGET_MIN <= n <= TARGET_MAX:
            self.warn(
                "target-count", "/vocabulary/target",
                f"vocabulary.target has {n} word{'s' if n != 1 else ''}; choose "
                f"{TARGET_MIN}–{TARGET_MAX} key words that the story uses and the tasks practise.",
            )
        story_texts = [s.text for s in ws.story.scenes]
        task_texts = [(t.id, self.task_texts(t)) for t in ws.tasks]
        seen: dict[str, int] = {}
        for k, term in enumerate(target):
            key = term.casefold()
            if key in seen:
                self.warn(
                    "duplicate-target", f"/vocabulary/target/{k}",
                    f"'{term}' is already listed at /vocabulary/target/{seen[key]}; remove the "
                    "repeat.",
                )
                continue
            seen[key] = k
            if not strip_article(term, self.target_lang):
                continue
            if not self.occurs(term, story_texts):
                self.warn(
                    "target-not-in-story", f"/vocabulary/target/{k}",
                    f"the target word '{term}' does not occur in any scene text. Work it into "
                    "the story (an inflected form is fine), or remove it from vocabulary.target.",
                )
            used = [tid for tid, texts in task_texts if self.occurs(term, texts)]
            if len(used) < 2:
                in_tasks = f" (only in {', '.join(used)})" if used else ""
                self.warn(
                    "target-underused", f"/vocabulary/target/{k}",
                    f"the target word '{term}' is practised in {len(used)} task"
                    f"{'s' if len(used) != 1 else ''}{in_tasks}; use every target word in at "
                    "least two tasks (e.g. a match pair and a cloze gap or writing must_use), "
                    "or remove it from vocabulary.target.",
                )

    def check_copies_story(self) -> None:
        story = [
            (s, _norm_sentence(s))
            for scene in self.ws.story.scenes
            for s in _sentences(scene.text)
        ]
        story = [(s, n) for s, n in story if len(n.split()) >= 4]

        def copied(text: str) -> str | None:
            for sentence in _sentences(text):
                norm = _norm_sentence(sentence)
                if len(norm.split()) < 4:
                    continue
                for original, other in story:
                    sm = difflib.SequenceMatcher(None, norm, other, autojunk=False)
                    if sm.real_quick_ratio() < COPY_RATIO or sm.quick_ratio() < COPY_RATIO:
                        continue
                    if sm.ratio() >= COPY_RATIO:
                        return original
            return None

        def warn(where: str, original: str) -> None:
            self.warn(
                "copies-story", where,
                f"this practice item is almost identical to the story sentence {_q(original)}, "
                "so the learner can copy the answer from the page. Write a new sentence in a "
                "new situation that practises the same word or structure.",
            )

        for i, task in enumerate(self.ws.tasks):
            if task.stage != "practice":
                continue
            if isinstance(task, ClozeTask):
                if task.text is not None:
                    hit = copied(_filled(task.text))
                    if hit:
                        warn(f"/tasks/{i}/text", hit)
                for j, item in enumerate(task.items or []):
                    hit = copied(_filled(item))
                    if hit:
                        warn(f"/tasks/{i}/items/{j}", hit)
            elif isinstance(task, TransformTask):
                for j, titem in enumerate(task.items):
                    hit = copied(titem.answer)
                    if hit:
                        warn(f"/tasks/{i}/items/{j}", hit)

    def check_series(self) -> None:
        series = self.ws.series
        if series is None:
            return
        if series.episode >= 2 and not series.previously:
            self.warn(
                "missing-previously", "/series/previously",
                f"this is episode {series.episode} but series.previously is empty. Add a 2–3 "
                "sentence 'Previously…' recap of the story so far, so the learner can pick up "
                "the thread.",
            )
        texts = [s.text for s in self.ws.story.scenes]
        for task in self.ws.tasks:
            texts += self.task_texts(task)
        for k, word in enumerate(series.review):
            if not self.occurs(word, texts):
                self.warn(
                    "review-unused", f"/series/review/{k}",
                    f"the review word '{word}' (from an earlier episode) appears neither in the "
                    "story nor in any task. Recycle it in a scene or a task item, or remove it "
                    "from series.review.",
                )

    def check_ui(self) -> None:
        ws = self.ws
        known = list(locale.STRINGS["en"])
        known_set = set(known)
        for key in ws.ui:
            if key not in known_set:
                self.warn(
                    "unknown-ui-key", f"/ui/{_esc(key)}",
                    f"'{key}' is not a page-furniture key and will be ignored"
                    f"{_did_you_mean(key, known)}. Use only the keys langwich knows "
                    "(for example 'solutions', 'word_list', 'kind.cloze.title').",
                )
        missing = locale.missing_keys(ws.source_lang, ws.ui)
        if missing:
            english = {k: locale.STRINGS["en"][k] for k in missing}
            self.warn(
                "missing-ui-strings", "/ui",
                f"langwich has no built-in page labels for source language '{ws.source_lang}', "
                f"so {len(missing)} strings would be printed in English. Add them to 'ui', "
                f"translated into '{ws.source_lang}' (keep the keys and any {{placeholders}}): "
                + json.dumps(english, ensure_ascii=False),
            )

    def check_articles(self) -> None:
        lang = self.target_lang
        if lang not in NOUN_ARTICLES:
            return
        example = _ARTICLE_EXAMPLE[lang]
        for i, item in enumerate(self.ws.vocabulary.items):
            if item.pos == "noun" and not _has_article(item.term, lang):
                self.warn(
                    "noun-without-article", f"/vocabulary/items/{i}/term",
                    f"the noun '{item.term}' has no article. Write it with its correct "
                    f"definite article in front ({example} + noun) so the learner learns the "
                    "gender with the word; for a proper name use pos 'other'.",
                )
        for si, scene in enumerate(self.ws.story.scenes):
            if scene.picture is None:
                continue
            for j, lb in enumerate(scene.picture.labels):
                if not _has_article(lb.term, lang):
                    self.warn(
                        "noun-without-article",
                        f"/story/scenes/{si}/picture/labels/{j}/term",
                        f"the label '{lb.term}' has no article. Label terms are the answers to "
                        f"the label task: write nouns with their definite article ({example} …).",
                    )

    # -- run -------------------------------------------------------------------

    def run(self) -> list[Issue]:
        self.check_languages()
        self.check_duplicate_ids()
        self.check_references()
        self.check_target_in_items()
        self.check_cloze_and_dialogue()
        self.check_markup_placement()
        self.check_pictures()
        self.check_tasks()
        self.check_arc()
        self.check_story()
        self.check_target_words()
        self.check_copies_story()
        self.check_series()
        self.check_ui()
        self.check_articles()
        self.check_grammar_leaks()
        return self.issues

    def check_grammar_leaks(self) -> None:
        """A grammar box is printed right beside a task (see plan.py); its rule,
        table and examples must not show that task's answers."""
        lang = self.target_lang
        grammar_index = {g.id: i for i, g in enumerate(self.ws.grammar)}
        try:
            planned = make_plan(self.ws).tasks
        except ValueError:  # e.g. an empty {{}} gap, reported by its own check
            return
        for pt in planned:
            answers = _leakable_answers(pt.task, lang)
            if not answers:
                continue
            for side in pt.sidebars:
                gp = side.grammar
                if gp is None:
                    continue
                cells = [c for row in gp.table.rows for c in row] if gp.table else []
                box = "\n".join([gp.rule or "", *gp.examples, *cells]).casefold()
                leaked = next(
                    (a for a in answers
                     if re.search(r"(?<!\w)" + re.escape(a.casefold()) + r"(?!\w)", box)),
                    None,
                )
                if leaked:
                    self.warn(
                        "grammar-gives-away", f"/grammar/{grammar_index[gp.id]}",
                        f"the grammar box '{gp.name}' is printed beside task '{pt.task.id}' and "
                        f"shows its answer {_q(leaked)}. Use rule examples that are not part of "
                        "the task (other words, other sentences).",
                    )


def _leakable_answers(task: Task, lang: str) -> list[str]:
    """Answers that must not appear in a grammar box beside the task: built
    words, rewritten sentences and completed gap sentences (single gap words
    such as a conjugated 'werden' may legitimately appear in a rule table)."""
    if isinstance(task, WordBuildingTask):
        return [strip_article(i.answer, lang) for i in task.items]
    if isinstance(task, TransformTask):
        return [i.answer.rstrip(".!?…") for i in task.items]
    if isinstance(task, ClozeTask) and task.items:
        out = []
        for item in task.items:
            try:
                out.append(markup.fill(item).strip().rstrip(".!?…"))
            except ValueError:
                continue
        return out
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate(ws: Worksheet, base_dir: Path | None = None) -> Report:
    """Run every semantic check on a (schema-valid) worksheet.

    ``base_dir`` is the folder of the JSON file; relative ``picture.image``
    paths are looked up there (the current directory when ``None``).
    """
    return Report(issues=_Checker(ws, base_dir).run(), worksheet=ws)


def _contract_message(where: str, message: str) -> str:
    field_name = where.rstrip("/").rsplit("/", 1)[-1] if where not in ("", "/") else ""
    if message in ("Field required", "missing") and field_name:
        return f"the required field '{field_name}' is missing; add it (see 'langwich schema')."
    if message == "Extra inputs are not permitted" and field_name:
        return (
            f"'{field_name}' is not a field here; remove it, or move its content into a field "
            "the langwich/3 schema defines (see 'langwich schema')."
        )
    if message.startswith("Unable to extract tag using discriminator 'kind'"):
        kinds = ", ".join(f"'{k}'" for k in TASK_KINDS)
        return f"every task needs a 'kind': one of {kinds}."
    return message


def _json_error(raw: str, exc: json.JSONDecodeError) -> str:
    lines = raw.splitlines()
    snippet = lines[exc.lineno - 1].strip() if 0 < exc.lineno <= len(lines) else ""
    hint = ""
    if "Expecting property name" in exc.msg or "Expecting value" in exc.msg:
        hint = " (a trailing comma before } or ], or a missing value?)"
    elif "Expecting ',' delimiter" in exc.msg:
        hint = " (a missing comma, or an unescaped \" inside a string? Use „…“ or \\\")"
    elif "Invalid control character" in exc.msg:
        hint = " (a raw line break inside a string? Write it as \\n)"
    text = f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}{hint}"
    if snippet:
        text += f". The line reads: {_q(snippet, 90)}"
    return text


def check_file(path: Path) -> Report:
    """Load a worksheet file and validate it; never raises for bad input.

    Unreadable files, invalid JSON and schema violations become ``contract``
    errors (plus a ``legacy-format`` error for langwich v2 files).
    """
    path = Path(path)
    issues: list[Issue] = []
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return Report([Issue("error", "contract", "/", f"file not found: {path}")], None)
    except IsADirectoryError:
        return Report([Issue("error", "contract", "/", f"{path} is a folder, not a file")], None)
    except UnicodeDecodeError as exc:
        return Report([Issue(
            "error", "contract", "/",
            f"{path} is not UTF-8 text (undecodable byte at position {exc.start}); save it "
            "as UTF-8.",
        )], None)
    except OSError as exc:
        return Report(
            [Issue("error", "contract", "/", f"cannot read {path}: {exc.strerror or exc}")], None,
        )
    fenced = strip_code_fence(raw)
    if fenced is not None:
        raw = fenced
        issues.append(Issue(
            "warning", "code-fence", "/",
            "the file is wrapped in a Markdown code fence (```). Save only the JSON object, "
            "starting with { and ending with }.",
        ))
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return Report(issues + [Issue("error", "contract", "/", _json_error(raw, exc))], None)
    try:
        ws = worksheet_from_dict(data)
    except ContractError as exc:
        issues += [
            Issue("error", "contract", loc or "/", _contract_message(loc, msg))
            for loc, msg in exc.problems
        ]
        if exc.hint:
            issues.append(Issue("error", "legacy-format", "/", exc.hint))
        return Report(issues, None)
    report = validate(ws, base_dir=path.parent)
    return Report(issues + report.issues, ws)
