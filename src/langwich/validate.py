"""Semantic checks beyond the schema.

The pydantic models in :mod:`langwich.model` make sure a worksheet has the
right *shape*. This module checks what a schema cannot: that references
point somewhere, that every cloze has gaps, that the target words are
really practised, that the story is long enough for the level, and so on.

Every finding is an :class:`Issue` with

* a ``level`` — errors block rendering, warnings are printed (and fail the
  CLI with ``--strict``); picture problems (:data:`PICTURE_CODES`) are errors
  only when a task needs the picture,
* a stable kebab-case ``code`` (see :data:`CHECKS`),
* a JSON pointer ``where`` into the input file (``/tasks/3/items/1``),
* a ``message`` written so that an LLM can fix the file from it alone —
  ``langwich validate --prompt`` feeds these messages back to the model;
  problems only the user can fix (:data:`ENVIRONMENT_CODES`, e.g. a missing
  photo) are addressed to the user instead.

Files are read leniently (:func:`langwich.model.parse_worksheet`): a JSON
object inside a code fence or chat text, and known LLM quirks, are accepted
with a ``wrapped-json`` / ``normalized`` warning.
"""

from __future__ import annotations

import base64
import binascii
import difflib
import io
import json
import re
import string
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import unquote_to_bytes

from langwich import locale, markup
from langwich.answers import scramble_sentence, transform_sentence
from langwich.model import (
    CEFR_LEVELS,
    POS_VALUES,
    ClassifyTask,
    ClozeTask,
    ContractError,
    CrosswordTask,
    DialogueTask,
    DrawTask,
    FindInTextTask,
    GappedTextTask,
    GrammarPoint,
    LabelTask,
    MatchTask,
    MediaSearchTask,
    MultipleChoiceTask,
    OrderEventsTask,
    Picture,
    ProofreadTask,
    QuestionsTask,
    ScrambleTask,
    TableTask,
    Task,
    TransformTask,
    TrueFalseTask,
    VocabItem,
    WordBuildingTask,
    Worksheet,
    WritingTask,
    parse_worksheet,
)
from langwich.images import ImageSource, resolve_image  # noqa: F401 (re-exported)
from langwich.plan import plan as make_plan
from langwich.plan import strip_article, term_pattern

Level = Literal["error", "warning"]

#: Every check langwich runs: code -> (level, what it catches).
CHECKS: dict[str, tuple[Level, str]] = {
    # errors
    "contract": ("error", "the file is not valid JSON or does not match the langwich/3 schema"),
    "legacy-format": ("error", "a langwich v2 file; convert it with 'langwich prompt --from-json'"),
    "no-picture-attached": (
        "error", "the file is only the prompt's 'NO PICTURE ATTACHED' reply: the LLM could not "
        "see the picture",
    ),
    "duplicate-id": ("error", "two scenes, tasks, characters, facts or grammar points share an id"),
    "unknown-scene": ("error", "a reference to a scene id that does not exist"),
    "unknown-grammar": ("error", "a task references a grammar id that does not exist"),
    "target-not-in-items": ("error", "a vocabulary.target word has no entry in vocabulary.items"),
    "same-language": ("error", "source_lang and target_lang are the same"),
    "cloze-without-gaps": (
        "error", "a cloze, table, gapped_text or proofread text without {{gaps}}",
    ),
    "missing-gap-hint": (
        "error", "a gap without the ::hint its task needs (base_form/translation hint, choice "
        "options, proofread mistake)",
    ),
    "empty-gap": ("error", "an empty gap {{}}"),
    "unbalanced-braces": (
        "error", "a stray '{{' or '}}', a triple brace or a gap across a blank line in a cloze "
        "or dialogue text",
    ),
    "markup-in-story": ("error", "gap markup {{…}} inside a scene"),
    "label-without-labels": ("error", "a label task on a scene whose picture has no labels"),
    "duplicate-label-number": ("error", "two labels of one picture share a marker number"),
    "label-without-position": ("error", "a label without x/y on a picture with an image or svg"),
    "image-not-found": (
        "error", "a local picture.image file that cannot be found (a warning when no label or "
        "picture task needs the picture)",
    ),
    "image-unreadable": (
        "error", "a picture.image file that cannot be decoded, e.g. HEIC without pillow-heif (a "
        "warning when no label or picture task needs the picture)",
    ),
    "svg-invalid": (
        "error", "a picture svg that is not well-formed XML (a warning when no label or picture "
        "task needs the picture)",
    ),
    "duplicate-match-partner": ("error", "a match task lists the same entry twice in a column"),
    "duplicate-event": ("error", "an order_events task lists the same event twice"),
    "dialogue-nothing-to-do": ("error", "a dialogue task without gaps or lines to write"),
    "word-range": ("error", "a writing task with min_words > max_words"),
    "scramble-alternative": (
        "error", "a scramble alternative that does not use exactly the same tiles",
    ),
    "duplicate-entry": (
        "error", "a classify, gapped_text or crossword task lists the same entry twice",
    ),
    "table-shape": (
        "error", "a table row with a different number of cells than the head (2 without head)",
    ),
    "table-nothing-to-do": ("error", "a table without gaps or open (null) cells"),
    "frame-gaps": ("error", "a transform frame without exactly one {{gap}}"),
    "crossword-word": ("error", "a crossword answer that is not one word of letters"),
    "crossword-layout": ("error", "crossword answers that cannot all be joined into one grid"),
    # warnings
    "wrapped-json": ("warning", "text or a Markdown code fence around the JSON object (ignored)"),
    "normalized": (
        "warning", "a known LLM quirk was read leniently (a kind such as 'multiple-choice', a "
        "fact as a plain string, cefr_level 'b1')",
    ),
    "no-production": ("warning", "no production task"),
    "no-comprehension": ("warning", "no gist or detail task"),
    "task-without-scene": (
        "warning", "a gist/detail/picture/form/practice task without 'scene' (it would follow the "
        "last scene)",
    ),
    "scene-count": ("warning", "fewer than 2 or more than 7 scenes"),
    "story-length": ("warning", "the story is too short or too long for its CEFR level"),
    "target-count": ("warning", "fewer than 5 or more than 15 target words"),
    "duplicate-target": ("warning", "a word is listed twice in vocabulary.target"),
    "target-underused": ("warning", "a target word is practised in fewer than two tasks"),
    "target-not-in-story": ("warning", "a target word does not occur in the story"),
    "duplicate-item": ("warning", "the same word is listed twice in vocabulary.items"),
    "pos-missing": ("warning", "a vocabulary item without 'pos' (listed under 'Other words')"),
    "copies-story": (
        "warning", "a form, practice or production item copies a sentence from the story",
    ),
    "distractor-is-answer": (
        "warning", "a cloze, dialogue or table distractor or a gapped_text extra sentence is also "
        "one of the answers",
    ),
    "gap-starts-sentence": (
        "warning", "a word-box gap at the start of a sentence (its capital letter gives the "
        "position away)",
    ),
    "hint-is-answer": (
        "warning", "a hint that is the answer itself (a translation hint, a proofread 'mistake' "
        "that is correct)",
    ),
    "bank-without-gaps": ("warning", "a dialogue asks for a word bank but has no gaps"),
    "markup-outside-gaps": ("warning", "gap markup in a field where it is printed literally"),
    "tf-missing-correction": ("warning", "a false true_false statement without a 'correction'"),
    "model-answer-length": (
        "warning", "a writing model answer more than 15% outside min_words–max_words",
    ),
    "model-answer-missing-must-use": (
        "warning", "a writing must_use word that the model answer does not use",
    ),
    "no-facts": ("warning", "no 'Did you know?' facts"),
    "no-characters": ("warning", "no characters"),
    "review-unused": ("warning", "a series review word is not used anywhere"),
    "missing-previously": ("warning", "episode 2 or later without a 'previously' recap"),
    "unknown-ui-key": ("warning", "a ui key that is not a page-furniture string"),
    "ui-placeholders": ("warning", "a ui string whose {placeholders} differ from the built-in one"),
    "missing-ui-strings": ("warning", "page furniture would fall back to English"),
    "noun-without-article": ("warning", "a noun without its article"),
    "label-draws-instead": ("warning", "a label task printed as 'draw and label' (no image/svg)"),
    "picture-task-without-picture": (
        "warning", "a picture-stage task on a scene without image or svg",
    ),
    "svg-text": ("warning", "words drawn as <text> in the svg of a scene with a label task"),
    "svg-external": (
        "warning", "an svg that links external files or contains scripts (they are removed)",
    ),
    "grammar-gives-away": ("warning", "a grammar box beside a task shows one of its answers"),
    "scramble-punctuation": (
        "warning", "a scramble tile with sentence punctuation (it belongs in 'end')",
    ),
    "scramble-capital": (
        "warning", "a scramble whose first tile is capitalised (it shows where the sentence "
        "starts)",
    ),
    "category-unused": ("warning", "a classify category that no item belongs to"),
    "tf-no-not-given": (
        "warning", "a true_false task offers 'not in the text' but no statement needs it",
    ),
    "tf-quote-missing": (
        "warning", "a true/false statement without 'quote' in a task with 'justify'",
    ),
    "tf-quote-not-in-story": ("warning", "a true_false quote that the story does not contain"),
    "tf-not-given-correction": ("warning", "a 'not_given' statement with a correction or quote"),
    "writing-no-model-answer": (
        "warning", "a writing task with 'points' or 'input' but no model answer",
    ),
    "point-not-covered": (
        "warning", "a writing point whose 'covered_by' is not part of the model answer",
    ),
    "choice-options": (
        "warning", "a choice gap with more than 3 wrong options, a repeated option or a wrong "
        "option that is correct",
    ),
    "table-too-wide": ("warning", "a table with more than 5 columns (too wide for e-paper)"),
    "gapped-text-gaps": ("warning", "a gapped_text with fewer than 3 or more than 8 gaps"),
    "gapped-text-no-extra": (
        "warning", "a gapped_text without an extra sentence (the last gap is free by "
        "elimination)",
    ),
    "find-not-in-text": ("warning", "a find_in_text answer that its scenes do not contain"),
    "keyword-not-used": ("warning", "a transform key word that the answer does not contain"),
    "answer-too-long": ("warning", "a transform gap answer longer than max_words"),
    "frame-and-answer": (
        "warning", "a transform item with both 'frame' and 'answer' (the frame's gap holds the "
        "answer)",
    ),
    "answer-ignores-starter": (
        "warning", "a model answer that does not begin with its question's starter",
    ),
    "clue-is-answer": ("warning", "a crossword clue that contains its answer"),
    "task-count": ("warning", "fewer or more tasks than the brief recommends for the CEFR level"),
}

#: Problems in the user's environment (files, formats) rather than in the
#: JSON: an LLM cannot fix them, so repair prompts leave them out and the CLI
#: tells the user instead.
ENVIRONMENT_CODES: frozenset[str] = frozenset({"image-not-found", "image-unreadable"})

#: Picture problems that are errors when the picture is needed — it has
#: labels, or a label or picture-stage task uses its scene — and warnings
#: otherwise (the renderer just leaves the picture out).
PICTURE_CODES: frozenset[str] = frozenset({"image-not-found", "image-unreadable", "svg-invalid"})

#: Stages whose tasks belong to a scene (the planner prints them after it).
SCENE_STAGES: tuple[str, ...] = ("gist", "detail", "picture", "form", "practice")

#: Stages whose items must be new sentences, not copies of the story.
NEW_SENTENCE_STAGES: tuple[str, ...] = ("form", "practice", "production")

#: Shown when only syntax or contract errors are listed: the semantic checks
#: run once the file matches the contract.
MORE_CHECKS_NOTE = "More checks will run once these are fixed."

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

#: Tasks in total, per CEFR level (the recommended set of the brief).
TASK_COUNT: dict[str, tuple[int, int]] = {
    "A1": (8, 11),
    "A2": (8, 12),
    "B1": (10, 14),
    "B2": (10, 14),
    "C1": (10, 14),
    "C2": (10, 14),
}
assert set(TASK_COUNT) == set(CEFR_LEVELS)
#: Levels whose long stories need one comprehension task per one or two
#: scenes only; the other levels have one per scene.
PAIRED_SCENE_LEVELS = frozenset({"C1", "C2"})

SCENES_MIN, SCENES_MAX = 2, 7
TARGET_MIN, TARGET_MAX = 5, 15
COPY_RATIO = 0.85
#: Words (besides the answer) an example must share with a word-box item to
#: count as a near-copy of it.
NEAR_COPY_WORDS = 3
#: How far a writing model answer may stray outside min_words–max_words.
MODEL_ANSWER_SLACK = 0.15
#: The renderer leaves out picture files larger than this (images.MAX_BYTES).
MAX_IMAGE_BYTES = 25 * 1024 * 1024

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

    @property
    def partial(self) -> bool:
        """True when the file could not be read as a worksheet, so only
        syntax/contract problems are listed; the other checks run once
        those are fixed."""
        codes = {i.code for i in self.issues}
        return self.worksheet is None and "contract" in codes and "legacy-format" not in codes

    @property
    def environment_issues(self) -> list[Issue]:
        """Issues the user has to fix (a missing or unreadable picture file),
        not the LLM — see :data:`ENVIRONMENT_CODES`."""
        return [i for i in self.issues if i.code in ENVIRONMENT_CODES]

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
        if self.partial:
            lines += ["", MORE_CHECKS_NOTE]
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


def _data_uri_bytes(uri: str) -> bytes:
    header, _, payload = uri.partition(",")
    if ";base64" in header.lower():
        return base64.b64decode(payload, validate=False)
    return unquote_to_bytes(payload)


def _looks_like_svg(raw: bytes) -> bool:
    head = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head) or (
        head.startswith(b"<!doctype svg")
    )


_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")


def _raster_problem(raw: bytes) -> str | None:
    """Why Pillow (as the renderer uses it) cannot decode ``raw``; ``None``
    when it can — or when Pillow is not installed, so nothing can be said."""
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        return None
    try:  # the renderer can read HEIC photos when pillow-heif is installed
        import pillow_heif  # type: ignore[import-not-found]

        pillow_heif.register_heif_opener()
    except Exception:  # noqa: BLE001 - optional plugin, any failure means "not available"
        pass
    heif = raw[4:8] == b"ftyp" and raw[8:12] in _HEIF_BRANDS
    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe.verify()
        with Image.open(io.BytesIO(raw)) as img:
            img.draft("L", (512, 512))  # decode JPEGs at a small scale: fast, still complete
            img.load()
    except UnidentifiedImageError:
        if heif:
            return ("it is a HEIC/HEIF photo, which Pillow cannot read without the pillow-heif "
                    "plugin: export it as JPEG or PNG, or run 'pip install pillow-heif'")
        return "it is not an image format langwich can read: use JPEG, PNG, WebP or GIF"
    except Exception as exc:  # noqa: BLE001 - Pillow raises many types for bad data
        detail = re.sub(r"\s*<[^>]*BytesIO[^>]*>", "", str(exc)).strip() or type(exc).__name__
        return f"the file is damaged or incomplete ({detail}): export or download it again"
    return None


_SVG_NS = "http://www.w3.org/2000/svg"
_SVG_OPEN_RE = re.compile(r"<svg\b[^>]*>", re.IGNORECASE | re.DOTALL)
_CSS_URL_RE = re.compile(r"url\(\s*['\"]?\s*(?!#|data:)[^)'\"\s]|@import", re.IGNORECASE)


def _svg_element(text: str) -> tuple[str, int] | None:
    """The ``<svg>…</svg>`` element of ``text`` with the namespaces the
    renderer adds (see :func:`langwich.images.svg_from_text`), plus the
    number of characters added to its first line; ``None`` without one."""
    start = text.lower().find("<svg")
    end = text.lower().rfind("</svg>")
    if start < 0 or end < start:
        return None
    svg = text[start:end + len("</svg>")]
    added = 0
    opening = _SVG_OPEN_RE.match(svg)
    if opening and "xmlns=" not in opening.group(0):
        extra = f' xmlns="{_SVG_NS}"'
        svg, added = svg[:4] + extra + svg[4:], added + len(extra)
    if "xlink:" in svg and "xmlns:xlink" not in (opening.group(0) if opening else ""):
        extra = ' xmlns:xlink="http://www.w3.org/1999/xlink"'
        svg, added = svg[:4] + extra + svg[4:], added + len(extra)
    return svg, added


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _svg_external_parts(root: ET.Element) -> list[str]:
    """Links to other files, scripts and event handlers in an SVG (the
    renderer removes them and loads nothing from outside)."""
    found: list[str] = []
    for el in root.iter():
        tag = _local_name(str(el.tag))
        if tag in ("script", "foreignObject"):
            found.append(f"<{tag}>")
        if tag == "style" and _CSS_URL_RE.search("".join(el.itertext())):
            found.append("a url(…) in <style>")
        for attr, value in el.attrib.items():
            name = _local_name(attr)
            if name == "href" and not value.strip().startswith(("#", "data:")):
                found.append(f"{name}={_q(value, 40)}")
            elif name.lower().startswith("on"):
                found.append(f"{name}=…")
            elif name == "style" and _CSS_URL_RE.search(value):
                found.append("a url(…) in style")
    return list(dict.fromkeys(found))


def _svg_words(root: ET.Element) -> list[str]:
    """Texts of ``<text>`` elements that contain letters (marker numbers drawn
    into the picture are fine)."""
    words = []
    for el in root.iter():
        if _local_name(str(el.tag)) == "text":
            text = " ".join("".join(el.itertext()).split())
            if re.search(r"[^\W\d_]", text):
                words.append(text)
    return words


def _similar_file(path: Path) -> str:
    """' Did you mean …?' for a file in the same folder whose name differs only
    in extension or letter case."""
    try:
        siblings = [p for p in path.parent.iterdir() if p.is_file()]
    except OSError:
        return ""
    stem, name = path.stem.casefold(), path.name.casefold()
    close = [p.name for p in siblings if p.name.casefold() == name or p.stem.casefold() == stem]
    return f" A file named '{close[0]}' is there — did you mean that one?" if close else ""


#: Sample values for the placeholders of page-furniture strings, of the
#: types the renderer passes.
_UI_SAMPLES: dict[str, object] = {"min": 60, "max": 80, "scene": "Scene", "n": 5}


def _format_fields(text: str) -> list[str]:
    """Placeholder names in order of appearance (``ValueError`` for bad syntax)."""
    names = [name for _, name, _, _ in string.Formatter().parse(text) if name is not None]
    return list(dict.fromkeys(names))


def _placeholder_problem(text: str, english: str) -> str | None:
    """What is wrong with the {placeholders} of a ui override, or ``None``.

    Every override is tried with the placeholders its key is formatted with
    (the English string's), so anything that would fail at render time —
    ``{min[0]}``, ``{min.foo}``, ``{minimum}``, a single brace — is found."""
    needed = _format_fields(english)
    names = " and ".join("{" + n + "}" for n in needed)
    try:
        have = _format_fields(text)
    except ValueError as exc:
        if not needed:
            return None  # never formatted: printed as written
        return (f"is not a valid format string ({exc}), so langwich would print its built-in "
                "text instead; write a literal brace as {{ or }}")
    if not needed:
        if have:
            used = ", ".join("{" + n + "}" for n in have)
            return (f"contains {used}, but this string takes no placeholders, so the braces "
                    "would be printed as they are")
        return None
    try:
        text.format(**{n: _UI_SAMPLES.get(n, "x") for n in needed})
    except Exception as exc:  # noqa: BLE001 - any failure means the override is unusable
        return (f"cannot be filled in ({type(exc).__name__}: {exc}), so langwich would print its "
                f"built-in text instead; use only {names}")
    if set(have) != set(needed):
        missing = ", ".join("{" + n + "}" for n in needed if n not in have)
        odd = ", ".join("{" + n + "}" for n in have if n not in needed)
        parts = [f"uses {odd}" if odd else "", f"leaves out {missing}" if missing else ""]
        return f"{' and '.join(p for p in parts if p)}; it must contain exactly {names}"
    return None


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

    def picture_problem(self, code: str, where: str, message: str, needed: bool) -> None:
        """An error when a task needs the picture, else a warning (PICTURE_CODES)."""
        assert code in PICTURE_CODES, code
        self.issues.append(Issue("error" if needed else "warning", code, where, message))

    # -- examples for messages (in the worksheet's own target language) -------

    def example_word(self) -> str:
        terms = [*self.ws.vocabulary.target, *(v.term for v in self.ws.vocabulary.items)]
        for term in terms:
            word = strip_article(term, self.target_lang)
            if word and " " not in word:
                return word
        return "answer"

    def example_noun(self) -> str:
        return next(
            (v.term for v in self.ws.vocabulary.items if v.pos == "noun"), "<noun with article>",
        )

    # -- word search ---------------------------------------------------------

    def patterns(self, term: str) -> list[re.Pattern[str]]:
        # A word without a vocabulary item (e.g. a must_use phrase) is matched
        # as a noun when it has an article, otherwise exactly.
        guessed = "noun" if (
            self.target_lang in NOUN_ARTICLES and _has_article(term, self.target_lang)
        ) else "other"
        item = self.ws.vocab_item(term) or VocabItem.model_construct(
            term=term, translation="", pos=guessed, plural=None, forms=None,
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
        """The item strings of a task (gaps filled, hints kept): the
        target-language text the learner reads or writes. Titles and
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
            if task.question_lang == "target":
                out += [i.question for i in task.items]
            out += [i.starter or "" for i in task.items] + [i.answer or "" for i in task.items]
        elif isinstance(task, ClassifyTask):
            out += task.categories + [i.text for i in task.items]
        elif isinstance(task, FindInTextTask):
            if task.clue_lang == "target":
                out += [i.clue for i in task.items]
            out += [i.answer for i in task.items]
        elif isinstance(task, GappedTextTask):
            out += [_gap_text(task.text), *task.extra]
        elif isinstance(task, ClozeTask):
            texts = [task.text] if task.text is not None else list(task.items or [])
            out += [_gap_text(t) for t in texts] + task.distractors
        elif isinstance(task, TransformTask):
            out += [f"{i.prompt} {i.cue or ''} {transform_sentence(i)}" for i in task.items]
        elif isinstance(task, ScrambleTask):
            out += [c for i in task.items for c in i.chunks]
            out += [scramble_sentence(i.chunks, i.end, self.target_lang) for i in task.items]
        elif isinstance(task, WordBuildingTask):
            out += [p for i in task.items for p in i.parts] + [i.answer for i in task.items]
        elif isinstance(task, TableTask):
            out += [task.caption or "", *task.head]
            out += [_gap_text(cell) for row in task.rows for cell in row if cell]
            out += task.distractors
        elif isinstance(task, ProofreadTask):
            out.append(_filled(task.text))  # the correct forms, not the mistakes
        elif isinstance(task, LabelTask):
            scene = self.ws.scene(task.scene)
            if scene and scene.picture:
                out += [lb.term for lb in scene.picture.labels]
        elif isinstance(task, WritingTask):
            out += [task.prompt, *task.must_use]
            if task.input_lang == "target":
                out.append(task.input or "")
            if task.output_lang == "target":
                out += [task.starter or "", task.model_answer or ""]
                out += [p.covered_by or "" for p in task.points]
        elif isinstance(task, CrosswordTask):
            out += [e.answer for e in task.entries]
            if task.clue_lang == "target":
                out += [e.clue for e in task.entries]
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

    def _check_gap_text(
        self, hint: str | None, text: str, where: str, what: str, *, need_gaps: bool = True,
    ) -> None:
        """Checks shared by every text with gap markup: cloze texts/items,
        dialogue lines, table cells, gapped_text and proofread texts.

        ``hint`` is the task's hint ('base_form', 'choice', … or 'proofread'
        for a proofread text); ``None`` checks no hints (dialogue lines,
        gapped_text). ``need_gaps``: a text without gaps is an error."""
        if markup.has_unbalanced_braces(text):
            self.error(
                "unbalanced-braces", where,
                f"{what} has an unmatched '{{{{' or '}}}}'. Write every gap as {{{{answer}}}} "
                "with two opening and two closing braces, and use no other double braces.",
            )
        elif "{{{" in text or "}}}" in text or any(
            "{" in m.group(1) or "}" in m.group(1) for m in markup.GAP_RE.finditer(text)
        ):
            self.error(
                "unbalanced-braces", where,
                f"{what} has three braces in a row or a brace inside a gap, so a stray brace "
                "would be printed and would get into the word box and the answer key. Write "
                "every gap with exactly two braces on each side: {{answer}}.",
            )
        for m in markup.GAP_RE.finditer(text):
            if re.search(r"\n[ \t]*\n", m.group(1)):
                self.error(
                    "unbalanced-braces", where,
                    f"the gap {_q(m.group(0), 40)} in {what} runs across a blank line, which "
                    "splits it into two paragraphs with literal braces. Close every gap on the "
                    "line where it starts.",
                )
        found, problem = _parse_gaps(text)
        if problem is not None:
            self.error(
                "empty-gap", where,
                f"{what} contains an empty gap {{{{}}}}. Put the answer inside the braces, "
                f"e.g. {{{{{self.example_word()}}}}}, or with a hint {{{{answer::hint}}}}.",
            )
            return
        if need_gaps and not found:
            single = _SINGLE_BRACE_RE.search(text)
            extra = (
                f" It uses single braces ({single.group(0)}); gaps need double braces."
                if single else ""
            )
            if hint == "proofread":
                how = ("Write each mistake as {{correct::wrong}}: the correct form, then the "
                       "wrong form the character wrote.")
            else:
                how = (f"Mark each gap as {{{{answer}}}} inside the text, e.g. "
                       f"'… {{{{{self.example_word()}}}}} …'.")
            self.error(
                "cloze-without-gaps", where,
                f"{what} has no gaps, so there is nothing to fill in.{extra} {how}",
            )
        if hint in ("base_form", "translation"):
            kind = "base form" if hint == "base_form" else "meaning in the source language"
            for gap in found:
                if not gap.hint:
                    body = "|".join(gap.accepted)
                    self.error(
                        "missing-gap-hint", where,
                        f"the gap {{{{{body}}}}} has no hint, but the task uses hint "
                        f"'{hint}', which prints a hint in brackets after every gap. "
                        f"Write it as {{{{{body}::<{kind}>}}}}, or change the task's hint to "
                        "'word_bank'.",
                    )
        if hint == "translation":
            for gap in found:
                if gap.hint and gap.hint.casefold() in {a.casefold() for a in gap.accepted}:
                    self.warn(
                        "hint-is-answer", where,
                        f"the gap {{{{{gap.answer}::{gap.hint}}}}} prints its answer as the "
                        "translation hint, so the learner just copies it. Gap a word whose "
                        "translation differs from it, or give this task the hint 'base_form' "
                        "or 'word_bank'.",
                    )
        if hint == "choice":
            for gap in found:
                if not markup.wrong_options(gap):
                    body = "|".join(gap.accepted)
                    self.error(
                        "missing-gap-hint", where,
                        f"the gap {{{{{body}}}}} has no wrong options, but the task uses hint "
                        "'choice', which prints every gap as a choice between the right word "
                        f"and wrong ones. Write it as {{{{{body}::<wrong>|<wrong>}}}} with 1–3 "
                        "wrong options of the same word class, or change the task's hint to "
                        "'word_bank'.",
                    )
        if hint == "proofread":
            for gap in found:
                body = "|".join(gap.accepted)
                if not gap.hint:
                    self.error(
                        "missing-gap-hint", where,
                        f"the mistake {{{{{body}}}}} has no wrong form, so the text would show "
                        "the correct word and there is nothing to correct. Write it as "
                        f"{{{{{body}::<the wrong form the character wrote>}}}}.",
                    )
                elif gap.hint.casefold() in {a.casefold() for a in gap.accepted}:
                    self.warn(
                        "hint-is-answer", where,
                        f"the mistake {{{{{body}::{gap.hint}}}}} prints a correct form as the "
                        "mistake, so there is nothing to correct. Write the wrong form after the "
                        "'::' ({{correct::wrong}}), or remove the braces.",
                    )

    def check_cloze_and_dialogue(self) -> None:
        for i, task in enumerate(self.ws.tasks):
            if isinstance(task, ClozeTask):
                if task.text is not None:
                    self._check_gap_text(
                        task.hint, task.text, f"/tasks/{i}/text", "this cloze text",
                    )
                    answers = [a for g in _parse_gaps(task.text)[0] for a in g.accepted]
                else:
                    answers = []
                    for j, item in enumerate(task.items or []):
                        self._check_gap_text(
                            task.hint, item, f"/tasks/{i}/items/{j}", "this cloze item",
                        )
                        answers += [a for g in _parse_gaps(item)[0] for a in g.accepted]
                self._check_distractors(i, task.distractors, answers)
            elif isinstance(task, DialogueTask):
                has_gap = False
                writes = False
                answers = []
                for j, line in enumerate(task.lines):
                    if line.text is None:
                        writes = True
                        continue
                    self._check_gap_text(
                        None, line.text, f"/tasks/{i}/lines/{j}/text", "this line",
                        need_gaps=False,
                    )
                    line_gaps = _parse_gaps(line.text)[0]
                    answers += [a for g in line_gaps for a in g.accepted]
                    if line_gaps:
                        has_gap = True
                self._check_distractors(i, task.distractors, answers)
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

    def _check_distractors(
        self, i: int, distractors: list[str], answers: list[str], field: str = "distractors",
    ) -> None:
        """Distractors (or a gapped_text's ``extra`` sentences, ``field``) that
        are also the answer to a gap."""
        keys = {" ".join(a.casefold().split()) for a in answers}
        for k, word in enumerate(distractors):
            if " ".join(word.casefold().split()) not in keys:
                continue
            if field == "extra":
                message = (f"the extra sentence {_q(word)} is also one of the removed sentences, "
                           "so it is not a distractor. Replace it with a sentence that fits none "
                           "of the gaps.")
            else:
                message = (f"the distractor '{word}' is also the answer to a gap, so it is not "
                           "a distractor. Replace it with a word that fits none of the gaps.")
            self.warn("distractor-is-answer", f"/tasks/{i}/{field}/{k}", message)

    def check_markup_placement(self) -> None:
        data = self.ws.model_dump(by_alias=True, mode="json", exclude_none=True)
        story_fields = re.compile(r"^/story/scenes/\d+/(text|heading|translation)$")
        gap_fields = re.compile(
            r"^/tasks/\d+/(text|items/\d+|lines/\d+/text|rows/\d+/\d+|items/\d+/frame)$",
        )
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
                    "prose. Remove the braces here; put gaps only in task fields that take them, "
                    "such as cloze texts or dialogue lines (with new sentences, not copied from "
                    "the story).",
                )
            elif gap_fields.match(where) and self._is_gap_field(where):
                continue
            else:
                self.warn(
                    "markup-outside-gaps", where,
                    "gap markup '{{…}}' is only read in cloze texts/items, dialogue lines, "
                    "table cells, gapped_text and proofread texts and transform frames; here it "
                    "would be printed literally, braces included. Remove the braces (or turn "
                    "this into a cloze task).",
                )

    def _is_gap_field(self, where: str) -> bool:
        parts = where.split("/")
        task = self.ws.tasks[int(parts[2])]
        if isinstance(task, (ClozeTask, DialogueTask)):
            return True
        if isinstance(task, TableTask):
            return parts[3] == "rows"
        if isinstance(task, (GappedTextTask, ProofreadTask)):
            return parts[3] == "text"
        if isinstance(task, TransformTask):
            return parts[-1] == "frame"
        return False

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
            users = self.picture_users(scene.id)
            needed = bool(pic.labels or users)
            why = self._needed_because(pic, users)
            label_task = any(isinstance(t, LabelTask) for t in users)
            if pic.svg:  # the renderer uses the svg and ignores 'image'
                self._check_svg(pic.svg, f"{base}/svg", "the svg", needed, why, label_task)
            elif pic.image:
                self._check_image(pic, f"{base}/image", needed, why)

    def picture_users(self, scene_id: str) -> list[Task]:
        """Tasks that need the picture of a scene: its label tasks and its
        picture-stage tasks (except 'draw', which asks for a drawing)."""
        return [
            t for t in self.ws.tasks
            if (isinstance(t, LabelTask) and t.scene == scene_id)
            or (t.stage == "picture" and not isinstance(t, DrawTask) and scene_id in t.scene_ids)
        ]

    @staticmethod
    def _needed_because(pic: Picture, users: list[Task]) -> str:
        reasons = []
        if pic.labels:
            reasons.append("it has numbered labels")
        if users:
            ids = ", ".join(f"'{t.id}'" for t in users)
            reasons.append(f"task{'s' if len(users) > 1 else ''} {ids} use{'' if len(users) > 1 else 's'} it")
        if not reasons:
            return " (the picture is simply left out)"
        return f"; the picture is needed because {' and '.join(reasons)}"

    def _check_svg(
        self, text: str, where: str, what: str, needed: bool, why: str, label_task: bool,
        *, file: bool = False,
    ) -> None:
        """Parse an svg as the renderer does. An svg in the JSON is the LLM's
        to fix ('svg-invalid'); a broken .svg file is the user's
        ('image-unreadable'), and what it draws is not checked."""
        code = "image-unreadable" if file else "svg-invalid"
        element = _svg_element(text)
        if element is None:
            self.picture_problem(
                code, where,
                f"{what} has no complete <svg>…</svg> element (is the closing </svg> missing — "
                f"was the reply cut off?){why}. Write one complete <svg viewBox=\"…\">…</svg> "
                "element.",
                needed,
            )
            return
        svg, added = element
        try:
            root = ET.fromstring(svg)
        except ET.ParseError as exc:
            line, column = getattr(exc, "position", (0, 0))
            lines = svg.splitlines()
            snippet = lines[line - 1][max(0, column - 30):column + 30] if 0 < line <= len(lines) else ""
            if line == 1 and column > added:
                column -= added  # count as in the svg the LLM wrote
            reason = str(exc).split(": line", 1)[0]
            self.picture_problem(
                code, where,
                f"{what} is not well-formed XML ({reason} at line {line}, column {column}"
                + (f", near {_q(snippet, 60)}" if snippet.strip() else "")
                + f"), so the picture would be left out{why}. Fix the markup: write & as &amp; "
                "and < as &lt;, close every element (<path … />), put every attribute value in "
                "quotes, and end with </svg>.",
                needed,
            )
            return
        if file:
            return
        words = _svg_words(root)
        if label_task and words:
            self.warn(
                "svg-text", where,
                f"{what} writes words into the picture as <text> ("
                + ", ".join(_q(w, 30) for w in words[:3])
                + "), but a label task asks the learner to name the objects: words in the drawing "
                "can give the answers away and clash with the numbered markers. Remove the "
                "<text> elements; the markers and the word box name the objects.",
            )
        external = _svg_external_parts(root)
        if external:
            self.warn(
                "svg-external", where,
                f"{what} refers to things outside itself or contains code ("
                + ", ".join(external[:4])
                + "). langwich loads no other files and runs no scripts, so these parts are "
                "removed and may leave holes in the picture. Draw everything inside the svg with "
                "basic shapes (path, line, polyline, rect, circle, ellipse, polygon).",
            )

    def _check_image(self, pic: Picture, where: str, needed: bool, why: str) -> None:
        image = pic.image or ""
        source = resolve_image(image, self.base_dir)
        if source.kind == "url":
            return  # not fetched while validating
        if source.kind == "unsupported":
            self.picture_problem(
                "image-not-found", where,
                f"'{image}' is neither a local file nor an http(s) URL or data: URI, so the "
                f"picture cannot be loaded{why}. Use a path relative to the JSON file (e.g. "
                "'pictures/scene.jpg') or an https:// URL.",
                needed,
            )
            return
        name = "the data: URI" if source.kind == "data" else f"the picture file '{image}'"
        try:
            if source.kind == "data":
                raw = _data_uri_bytes(image.strip())
            else:
                path = source.path
                assert path is not None
                if not path.is_file():
                    self.picture_problem(
                        "image-not-found", where,
                        f"{name} was not found (looked for {path}){why}. Copy the picture "
                        "there, or correct the path in picture.image — a relative path starts "
                        f"at the folder of the JSON file.{_similar_file(path)}",
                        needed,
                    )
                    return
                if path.stat().st_size > MAX_IMAGE_BYTES:
                    self.picture_problem(
                        "image-unreadable", where,
                        f"{name} is larger than {MAX_IMAGE_BYTES // 2**20} MB, so the picture "
                        f"is left out{why}. Save a smaller copy (about 2000 pixels on the long "
                        "side is plenty for print).",
                        needed,
                    )
                    return
                raw = path.read_bytes()
        except (OSError, ValueError, binascii.Error) as exc:
            self.picture_problem(
                "image-unreadable", where,
                f"{name} cannot be read ({exc.__class__.__name__}: {exc}){why}.", needed,
            )
            return
        if not raw:
            self.picture_problem(
                "image-unreadable", where, f"{name} is empty{why}. Save the picture again.", needed,
            )
            return
        if _looks_like_svg(raw) or image.lower().split("?")[0].endswith(".svg"):
            is_file = source.kind == "file"
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                self.picture_problem(
                    "image-unreadable" if is_file else "svg-invalid", where,
                    f"{name} is not UTF-8 SVG text{why}.", needed,
                )
                return
            self._check_svg(text, where, name, needed, why, label_task=False, file=is_file)
            return
        problem = _raster_problem(raw)
        if problem:
            self.picture_problem(
                "image-unreadable", where, f"{name} cannot be used: {problem}{why}.", needed,
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
                        "picture.labels [{\"n\": 1, \"term\": "
                        + json.dumps(self.example_noun(), ensure_ascii=False)
                        + ", \"x\": 0.3, \"y\": 0.6}, …] to the scene (with an image or svg), "
                        "or use a different task kind.",
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
            elif isinstance(task, TrueFalseTask):
                for j, item in enumerate(task.items):
                    if item.answer is False and not (item.correction or "").strip():
                        self.warn(
                            "tf-missing-correction", f"{where}/items/{j}",
                            f"the statement {_q(item.statement)} is false but has no "
                            "'correction'. Add \"correction\": the true version in the target "
                            "language — the instruction asks learners to correct the false "
                            "statements, and the answer key prints the correction.",
                        )
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
                elif task.model_answer:
                    self._check_model_answer(task, where)
            if (
                task.stage == "picture"
                and not isinstance(task, (LabelTask, DrawTask))
            ):
                for ref in task.scene_ids:
                    scene = self.ws.scene(ref)
                    if scene is not None and not (scene.picture and scene.picture.has_visual):
                        self.warn(
                            "picture-task-without-picture", where,
                            f"this picture task is about the picture of scene '{ref}', but that "
                            "scene has no 'image' or 'svg', so there is nothing to look at. Add "
                            "picture.svg (simple black line art) or picture.image to the scene, "
                            "or give the task another stage.",
                        )

    # -- per-kind checks: one method per new kind or extension ---------------

    def check_scramble(self) -> None:
        """Scramble alternatives, punctuation in tiles, a capitalised first tile."""
        if not any(isinstance(task, ScrambleTask) for task in self.ws.tasks):
            return
        capitals = {"de": "a name or a noun", "en": "a name or 'I'"}.get(self.target_lang, "a name")
        # where the worksheet writes a word in lower case (a capital that it
        # never drops belongs to a name or a German noun, not to the start)
        texts = [s.text for s in self.ws.story.scenes] + [v.term for v in self.ws.vocabulary.items]
        texts += [t for task in self.ws.tasks for t in self.task_texts(task)]

        def difference(chunks: list[str], order: list[str]) -> tuple[list[str], list[str]]:
            """The tiles of ``chunks`` that ``order`` lacks, and the ones it adds."""
            extra = list(order)
            missing = []
            for chunk in chunks:
                if chunk in extra:
                    extra.remove(chunk)
                else:
                    missing.append(chunk)
            return missing, extra

        def gives_start_away(word: str) -> bool:
            if not word[:1].isupper() or any(ch.isupper() for ch in word[1:]):
                return False  # lower case, or an acronym or name (EU, McDonald)
            if self._capitalised_anyway(word):
                return False
            lower = re.compile(r"(?<!\w)" + re.escape(word[0].lower() + word[1:]) + r"(?!\w)")
            return any(lower.search(text) for text in texts)

        for i, task in enumerate(self.ws.tasks):
            if not isinstance(task, ScrambleTask):
                continue
            for j, item in enumerate(task.items):
                where = f"/tasks/{i}/items/{j}"
                starts = [0]  # the tiles that start a correct order
                for k, alternative in enumerate(item.alternatives):
                    missing, extra = difference(item.chunks, alternative)
                    if not (missing or extra):
                        starts.append(item.chunks.index(alternative[0]))
                        continue
                    wrong = " and ".join(
                        [f"lacks {_one_of(missing)}"] * bool(missing)
                        + [f"adds {_one_of(extra)}"] * bool(extra)
                    )
                    self.error(
                        "scramble-alternative", f"{where}/alternatives/{k}",
                        f"this alternative {wrong}, so it is not an order of the tiles in "
                        "'chunks'. An alternative is another correct order of the same tiles: "
                        "copy every tile of 'chunks' exactly (same spelling and capitals, each "
                        "as often as there) and change only the order — or remove the "
                        "alternative.",
                    )
                self._check_scramble_tiles(item.chunks, where)
                for k in sorted(set(starts)):
                    tile = item.chunks[k]
                    word = re.search(r"\w+(?:['’]\w+)*", tile)
                    if word is None or not gives_start_away(word.group(0)):
                        continue
                    at = word.start()
                    self.warn(
                        "scramble-capital", f"{where}/chunks/{k}",
                        f"the tile {_q(tile)} starts the sentence and has a capital letter, so "
                        "the learner can see which tile comes first. Write it in lower case "
                        f"({_q(tile[:at] + tile[at].lower() + tile[at + 1:])}) here and in every "
                        "alternative — the answer key capitalises the first word itself. Keep a "
                        f"capital only for {capitals}, which is capitalised wherever it stands.",
                    )

    def _check_scramble_tiles(self, chunks: list[str], where: str) -> None:
        """Sentence punctuation on a tile shows which tile ends the sentence
        (with Spanish ¿ ¡, which one starts it). A full stop on a tile inside
        the sentence ends an abbreviation or a German ordinal ('z. B.', 'am
        3. Mai') and is fine."""
        for k, chunk in enumerate(chunks):
            tile = chunk.strip()
            mark = re.search(r"[.?!…]+$", tile)
            if mark and mark.start() == 0:
                problem = (f"the tile {_q(tile)} is only punctuation, so it always comes last. "
                           "Remove it from 'chunks' and from every alternative")
            elif mark and (k == len(chunks) - 1 or mark.group(0) != "."):
                problem = (f"the tile {_q(tile)} ends with '{mark.group(0)}', so the learner can "
                           "see which tile ends the sentence. Write it as "
                           f"{_q(tile[:mark.start()])} here and in every alternative")
            elif tile[:1] in ("¿", "¡"):
                problem = (f"the tile {_q(tile)} starts with '{tile[0]}', so the learner can see "
                           f"which tile starts the sentence. Write it as {_q(tile[1:].lstrip())} "
                           "here and in every alternative (the answer key adds the opening mark)")
            else:
                continue
            marks = mark.group(0) if mark else {"¿": "?", "¡": "!"}[tile[0]]
            end = "…" if "…" in marks or ".." in marks else marks[-1]
            self.warn(
                "scramble-punctuation", f"{where}/chunks/{k}",
                f"{problem}, and set \"end\": \"{end}\" on the item — langwich prints the end "
                "mark after the learner's answer line.",
            )

    def check_classify(self) -> None:
        """Repeated classify items, unused categories."""

    def check_true_false_extras(self) -> None:
        """'not_given' and 'justify': the third box, quotes, corrections."""

    def check_writing_extras(self) -> None:
        """Writing 'input' and 'points': the model answer covers every point."""

    def check_choice_gaps(self) -> None:
        """The options of cloze gaps with hint 'choice'."""

    def check_tables(self) -> None:
        """Table shape, gaps, width and distractors."""

    def check_gapped_texts(self) -> None:
        """Gapped-text gaps and extra sentences."""

    def check_find_in_text(self) -> None:
        """Find-in-text answers occur in their scenes."""

    def check_proofread(self) -> None:
        """Proofread texts: every mistake as {{correct::wrong}}."""

    def check_transform_extras(self) -> None:
        """Transform frames, key words and max_words."""

    def check_question_starters(self) -> None:
        """Model answers begin with their question's starter."""

        quotes = str.maketrans("‘’‚„“”«»", "'''" + '"' * 5)

        def norm(text: str) -> str:
            """Casefolded, whitespace collapsed, one kind of quote mark each."""
            return " ".join(text.translate(quotes).casefold().split())

        for i, task in enumerate(self.ws.tasks):
            if not isinstance(task, QuestionsTask):
                continue
            for j, item in enumerate(task.items):
                if not (item.starter and item.answer):
                    continue
                # A '…' ('...', '___') in the starter is the learner's to fill:
                # the answer begins with the words before the first one and
                # has the words between them in the same order.
                parts = [norm(p) for p in re.split(r"…|\.{3,}|_{2,}", item.starter)]
                pattern = ".*?".join(re.escape(p) for p in parts)
                if re.match(pattern, norm(item.answer), flags=re.DOTALL):
                    continue
                verb, fill = (("follow", " and fill in each '…'") if any(parts[1:])
                              else ("begin with", " and complete the sentence"))
                self.warn(
                    "answer-ignores-starter", f"/tasks/{i}/items/{j}/answer",
                    f"the model answer {_q(item.answer)} does not {verb} the starter "
                    f"{_q(item.starter)}, which is printed on the learner's answer line. Begin "
                    f"the model answer with the starter, word for word,{fill} — or change the "
                    "starter so that it fits the answer.",
                )

    def check_crosswords(self) -> None:
        """Crossword words, repeats, the grid and clues that give the answer away."""

    def check_task_count(self) -> None:
        """The number of tasks against the level's recommended range."""
        level = self.ws.cefr_level
        low, high = TASK_COUNT[level]
        n = len(self.ws.tasks)
        if low <= n <= high:
            return
        per_scene = "per one or two scenes" if level in PAIRED_SCENE_LEVELS else "per scene"
        if n < low:
            fix = (f"Add {low - n} or more tasks, from what the lesson still lacks: a "
                   f"comprehension task {per_scene}, a picture task, a form task per grammar "
                   "point, a practice task that continues the story, a personal question after "
                   "the writing task, a warm_up prediction or a media_search epilogue.")
        else:
            fix = (f"Remove {n - high} or more tasks, the optional ones first (a prediction, a "
                   "second task of one stage about the same scene), or merge two tasks of the "
                   f"same kind; keep one comprehension task {per_scene}, the picture, form, "
                   "practice and production tasks.")
        article = "an" if level.startswith("A") else "a"
        self.warn(
            "task-count", "/tasks",
            f"the worksheet has {n} task{'s' if n != 1 else ''}; {article} {level} worksheet "
            f"should have {low}–{high}. {fix}",
        )

    def _check_model_answer(self, task: WritingTask, where: str) -> None:
        answer = task.model_answer or ""
        low, high = task.min_words, task.max_words
        if self.target_lang not in _NO_SPACE_LANGS and (low or high):
            n = _word_count(answer)
            too_short = low is not None and n < low * (1 - MODEL_ANSWER_SLACK)
            too_long = high is not None and n > high * (1 + MODEL_ANSWER_SLACK)
            if too_short or too_long:
                wanted = (
                    f"{low}–{high}" if low and high else f"at least {low}" if low else f"at most {high}"
                )
                self.warn(
                    "model-answer-length", f"{where}/model_answer",
                    f"the model answer has {n} words, but the task asks for {wanted} words. "
                    f"Rewrite it to {wanted} words, so the learner sees what a complete answer "
                    "of the right length looks like.",
                )
        for k, word in enumerate(task.must_use):
            if strip_article(word, self.target_lang) and not self.occurs(word, [answer]):
                self.warn(
                    "model-answer-missing-must-use", f"{where}/must_use/{k}",
                    f"the model answer does not use '{word}', which the learner must use. Work "
                    "it into the model answer (an inflected form is fine), or remove it from "
                    "must_use.",
                )

    # -- warnings -------------------------------------------------------------

    def check_arc(self) -> None:
        stages = {t.stage for t in self.ws.tasks}
        if "production" not in stages:
            self.warn(
                "no-production", "/tasks",
                "no task has stage 'production'. Add a 'writing' (or 'dialogue') task after the "
                "story where the learner uses the target words in a text of their own, tied to "
                "the story (e.g. a message, diary entry or reply written by one of the "
                "characters).",
            )
        if not stages & {"gist", "detail"}:
            self.warn(
                "no-comprehension", "/tasks",
                "no task has stage 'gist' or 'detail'. Add comprehension tasks about the story "
                "(true_false, multiple_choice, order_events or questions), anchored to their "
                "scenes with 'scene'.",
            )

    def check_task_scenes(self) -> None:
        ids = self.scene_ids
        if len(ids) < 2:
            return
        example = json.dumps(ids[:3])
        for i, task in enumerate(self.ws.tasks):
            if task.stage in SCENE_STAGES and not task.scene_ids:
                self.warn(
                    "task-without-scene", f"/tasks/{i}/scene",
                    f"this {task.stage} task has no 'scene', so it is printed after the last "
                    f"scene ('{ids[-1]}'), away from the text it is about. Add \"scene\": the id "
                    f"of the scene it is about ({_one_of(ids)}); a task about the whole story "
                    f"may list several scene ids, e.g. \"scene\": {example}.",
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
            if not strip_article(term, self.target_lang) or self.ws.vocab_item(term) is None:
                continue  # an unknown word is reported once, as target-not-in-items
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

        for i, task in enumerate(self.ws.tasks):
            if task.stage not in NEW_SENTENCE_STAGES:
                continue
            checks: list[tuple[str, str]] = []
            if isinstance(task, ClozeTask):
                if task.text is not None:
                    checks.append((f"/tasks/{i}/text", _filled(task.text)))
                checks += [(f"/tasks/{i}/items/{j}", _filled(t)) for j, t in enumerate(task.items or [])]
            elif isinstance(task, TransformTask):
                checks += [
                    (f"/tasks/{i}/items/{j}", transform_sentence(t))
                    for j, t in enumerate(task.items)
                ]
            elif isinstance(task, ScrambleTask):
                checks += [
                    (f"/tasks/{i}/items/{j}", scramble_sentence(t.chunks, t.end, self.target_lang))
                    for j, t in enumerate(task.items)
                ]
            elif isinstance(task, TableTask):
                checks += [
                    (f"/tasks/{i}/rows/{r}", " ".join(_filled(cell) for cell in row if cell))
                    for r, row in enumerate(task.rows)
                ]
            elif isinstance(task, (GappedTextTask, ProofreadTask)):
                checks.append((f"/tasks/{i}/text", _filled(task.text)))
            elif isinstance(task, DialogueTask):
                checks += [
                    (f"/tasks/{i}/lines/{j}/text", _filled(line.text))
                    for j, line in enumerate(task.lines)
                    if line.text and _parse_gaps(line.text)[0]
                ]
            for where, text in checks:
                hit = copied(text)
                if hit:
                    self.warn(
                        "copies-story", where,
                        f"this {task.stage} item is almost identical to the story sentence "
                        f"{_q(hit)}, so the learner can copy the answer from the page. Write a "
                        "new sentence in a new situation that practises the same word or "
                        "structure.",
                    )

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
        for key, text in ws.ui.items():
            if key in known_set:
                problem = _placeholder_problem(text, locale.STRINGS["en"][key])
                if problem:
                    self.warn(
                        "ui-placeholders", f"/ui/{_esc(key)}",
                        f"the ui string for '{key}' {problem}. The English original is "
                        f"{json.dumps(locale.STRINGS['en'][key], ensure_ascii=False)}.",
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

    def check_vocab_items(self) -> None:
        lang = self.target_lang
        items = self.ws.vocabulary.items
        exact: dict[str, int] = {}
        loose: dict[tuple[str, str], int] = {}
        for i, item in enumerate(items):
            where = f"/vocabulary/items/{i}"
            key = " ".join(item.term.casefold().split())
            pair = (
                strip_article(item.term, lang).casefold(),
                " ".join(item.translation.casefold().split()),
            )
            first = exact.get(key, loose.get(pair))
            if first is not None:
                self.warn(
                    "duplicate-item", f"{where}/term",
                    f"'{item.term}' is already listed at /vocabulary/items/{first} "
                    f"('{items[first].term}'), so the word list would print it twice. Remove the "
                    "repeat (move any plural, forms or note into the first entry).",
                )
            else:
                exact[key] = i
                loose.setdefault(pair, i)
            if "pos" not in item.model_fields_set:
                guess = (
                    " — it starts with an article, so probably \"pos\": \"noun\""
                    if lang in NOUN_ARTICLES and _has_article(item.term, lang) else ""
                )
                self.warn(
                    "pos-missing", f"{where}/pos",
                    f"'{item.term}' has no 'pos', so the word list puts it under 'Other words' "
                    "and the checks only find it written exactly like this. Add \"pos\": one of "
                    f"{', '.join(POS_VALUES)}{guess}.",
                )

    def check_gap_positions(self) -> None:
        """Word-box gaps must not start a sentence: the capital letter in the
        box would show where the word goes."""
        for i, task in enumerate(self.ws.tasks):
            if isinstance(task, ClozeTask) and task.hint == "word_bank":
                texts = (
                    [(f"/tasks/{i}/text", task.text)] if task.text is not None
                    else [(f"/tasks/{i}/items/{j}", t) for j, t in enumerate(task.items or [])]
                )
            elif isinstance(task, DialogueTask) and task.bank:
                texts = [
                    (f"/tasks/{i}/lines/{j}/text", line.text)
                    for j, line in enumerate(task.lines) if line.text
                ]
            else:
                continue
            for where, text in texts:
                for m in markup.GAP_RE.finditer(text):
                    try:
                        gap = markup.parse_gap(m.group(1))
                    except ValueError:
                        continue
                    if not gap.answer[:1].isupper() or not _at_sentence_start(_filled(text[:m.start()])):
                        continue
                    if self._capitalised_anyway(gap.answer):
                        continue
                    self.warn(
                        "gap-starts-sentence", where,
                        f"the gap {{{{{gap.answer}}}}} starts a sentence, so its capital letter "
                        "shows in the word box where it belongs. Gap a word inside the sentence "
                        "instead, or rephrase so that the sentence starts with another word.",
                    )

    def _capitalised_anyway(self, answer: str) -> bool:
        """Names, German nouns, English 'I': words that are capitalised
        wherever they stand, so the capital gives nothing away."""
        lang = self.target_lang
        if lang == "en" and re.match(r"I\b", answer):
            return True
        names = {w.casefold() for c in self.ws.story.characters for w in c.name.split()}
        if answer.casefold() in names:
            return True
        if lang == "de" and any(
            item.pos == "noun" and term_pattern(item, lang).fullmatch(answer)
            for item in self.ws.vocabulary.items
        ):
            return True
        mid_sentence = re.compile(r"[\w,;] +" + re.escape(answer) + r"(?!\w)")
        return any(mid_sentence.search(scene.text) for scene in self.ws.story.scenes)

    # -- run -------------------------------------------------------------------

    def run(self) -> list[Issue]:
        self.check_languages()
        self.check_duplicate_ids()
        self.check_references()
        self.check_target_in_items()
        self.check_vocab_items()
        self.check_cloze_and_dialogue()
        self.check_gap_positions()
        self.check_markup_placement()
        self.check_pictures()
        self.check_tasks()
        self.check_scramble()
        self.check_classify()
        self.check_true_false_extras()
        self.check_writing_extras()
        self.check_choice_gaps()
        self.check_tables()
        self.check_gapped_texts()
        self.check_find_in_text()
        self.check_proofread()
        self.check_transform_extras()
        self.check_question_starters()
        self.check_crosswords()
        self.check_task_count()
        self.check_arc()
        self.check_task_scenes()
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
            for side in pt.sidebars:
                gp = side.grammar
                if gp is None:
                    continue
                leaked = _grammar_leak(pt.task, gp, lang)
                if leaked:
                    self.warn(
                        "grammar-gives-away", f"/grammar/{grammar_index[gp.id]}",
                        f"the grammar box '{gp.name}' is printed beside task '{pt.task.id}' and "
                        f"shows its answer {_q(leaked)}. Use rule examples and table forms that "
                        "are not part of the task (other words, other sentences); a table may "
                        "show the forms of another word that follows the same pattern.",
                    )


def _at_sentence_start(prefix: str) -> bool:
    """True when text ending in ``prefix`` is at the start of a sentence
    (also after an opening quote, bracket or dash)."""
    rest = re.sub(r"[\s\"'„“”«»‹›‘’‚(\[¿¡\-–—]+$", "", prefix)
    return not rest or rest[-1] in ".!?…:"


def _contains(text: str, word: str) -> bool:
    word = word.strip().casefold()
    return bool(word) and re.search(
        r"(?<!\w)" + re.escape(word) + r"(?!\w)", text.casefold(),
    ) is not None


#: Articles, auxiliaries and similar closed-class words: a grammar box
#: about them cannot avoid them, so on their own they are no give-away.
_FUNCTION_WORDS = frozenset(
    # de
    "einen einem einer eines keine keinen keinem keiner keines sein bin bist ist sind seid war "
    "waren warst wart haben habe hast hat habt hatte hatten werden werde wirst wird werdet "
    "wurde wurden "
    # fr
    "être suis est sommes êtes sont avoir avons avez ont été étais était "
    # es
    "unos unas ser soy eres somos sois son estar estoy estás está estamos estáis están haber "
    "hemos habéis "
    # it
    "essere sono siamo siete avere abbiamo avete hanno della degli delle "
    # pt
    "umas uns sou somos são estou estamos estão tenho temos têm "
    # en
    "have were been does will would".split()
)


def _significant(answer: str) -> bool:
    """A give-away on its own: not a short or closed-class word (articles and
    auxiliaries occur in almost every example of a grammar point)."""
    answer = answer.strip()
    if " " in answer:
        return True
    return len(answer) >= 4 and answer.casefold() not in _FUNCTION_WORDS


_SUBJECT_PRONOUNS = frozenset(
    "ich du er sie es wir ihr man je j' j’ tu il elle on nous vous ils elles yo tú él ella "
    "usted nosotros nosotras vosotros vosotras ellos ellas ustedes io lui lei noi voi loro eu "
    "ele ela você nós vós eles elas vocês i you he she it we they".split()
)


def _drop_subject(cell: str) -> str:
    """A table cell without its leading subject pronoun(s): 'il a acheté' ->
    'a acheté', 'er / sie / es wird' -> 'wird', "j'ai mangé" -> 'ai mangé'."""
    words = cell.split()
    while words and (words[0] == "/" or all(
        p.casefold() in _SUBJECT_PRONOUNS for p in words[0].split("/") if p
    )):
        words = words[1:]
    if words and re.match(r"(?i)j['’]", words[0]):
        words[0] = words[0][2:]
    return " ".join(words)


def _gap_units(task: Task) -> list[tuple[str, list[markup.Gap]]]:
    """The gaps of a task grouped by item — a cloze item, a sentence of a
    cloze or proofread text, a dialogue line, a table cell, a transform
    frame — with the item's text (gaps filled)."""
    texts: list[str] = []
    if isinstance(task, ClozeTask):
        texts = _sentences(task.text) if task.text is not None else list(task.items or [])
    elif isinstance(task, DialogueTask):
        texts = [line.text for line in task.lines if line.text]
    elif isinstance(task, TableTask):
        texts = [cell for row in task.rows for cell in row if cell]
    elif isinstance(task, ProofreadTask):
        texts = _sentences(task.text)  # the box must not show the corrections
    elif isinstance(task, TransformTask):
        texts = [item.frame for item in task.items if item.frame]
    units = []
    for text in texts:
        gaps = _parse_gaps(text)[0]
        if gaps:
            units.append((_filled(text), gaps))
    return units


def _shared_words(a: str, b: str, leave_out: str) -> int:
    """How many words (three letters or more) two sentences share, apart
    from ``leave_out``."""
    def words(text: str) -> set[str]:
        return {w for w in _WORD_RE.findall(text.casefold()) if len(w) >= 3}
    return len((words(a) & words(b)) - words(leave_out))


def _grammar_leak(task: Task, gp: GrammarPoint, lang: str) -> str | None:
    """The first answer of ``task`` that the grammar box ``gp`` shows, or ``None``.

    * whole answers — built words, rewritten sentences, completed cloze
      items — anywhere in the rule, examples or table;
    * a table form (without its subject pronoun, two words or more) inside a
      rewritten sentence ('il a acheté' next to 'Mila a acheté des tomates');
    * a single gap answer the learner has to produce (it differs from its
      hint), in a table cell, the rule or an example — unless the hint word
      is what the grammar point is about, i.e. it appears in its name or
      rule ('wird::werden' beside 'werden + Partizip II' is the rule, not a
      leak; a table that conjugates the very verb a gap asks for is one).
      In a word-box task the words are printed anyway, so the rule or an
      example counts only when it is a near-copy of the item (it shares
      three more words);
    * a near-copy with several gaps: one example or table cell showing two
      answers of the same item ('werden … geröstet').

    Answers shorter than four letters (articles, auxiliaries) only count
    together with another answer.
    """
    cells = [c for row in gp.table.rows for c in row] if gp.table else []
    prose = [gp.rule or "", *gp.examples]
    box = [*prose, *cells]
    for answer in _leakable_answers(task, lang):
        if any(_contains(text, answer) for text in box):
            return answer
    if isinstance(task, TransformTask):
        for cell in cells:
            core = _drop_subject(cell)
            if len(core.split()) >= 2 and not re.search(r"…|\.\.\.", core):
                if any(_contains(transform_sentence(item), core) for item in task.items):
                    return core
    about = f"{gp.name} {gp.rule or ''}"
    bank = (isinstance(task, (ClozeTask, TableTask)) and task.hint == "word_bank") or (
        isinstance(task, DialogueTask) and task.bank
    )
    for item_text, unit in _gap_units(task):
        for gap in unit:
            if gap.hint and gap.hint.casefold() == gap.answer.casefold():
                continue  # the hint already shows it
            if (gap.hint and _contains(about, gap.hint)) or not _significant(gap.answer):
                continue
            if any(_contains(cell, gap.answer) for cell in cells):
                return gap.answer
            for text in prose:
                if _contains(text, gap.answer) and (
                    not bank or _shared_words(text, item_text, gap.answer) >= NEAR_COPY_WORDS
                ):
                    return gap.answer
        answers = list(dict.fromkeys(g.answer for g in unit))
        for text in box:
            hits = [a for a in answers if _contains(text, a)]
            if len(hits) >= 2 and any(_significant(a) for a in hits):
                return " … ".join(hits)
    return None


def _leakable_answers(task: Task, lang: str) -> list[str]:
    """Whole answers that must not appear in a grammar box beside the task:
    built words, rewritten sentences and completed gap sentences."""
    if isinstance(task, WordBuildingTask):
        return [strip_article(i.answer, lang) for i in task.items]
    if isinstance(task, TransformTask):
        return [transform_sentence(i).strip().rstrip(".!?…") for i in task.items]
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


def check_file(path: Path) -> Report:
    """Load a worksheet file and validate it; never raises for bad input.

    Unreadable files, invalid JSON and schema violations become ``contract``
    errors (plus a ``legacy-format`` error for langwich v2 files); the
    prompt's 'NO PICTURE ATTACHED' reply is a ``no-picture-attached`` error.
    Repairs of the lenient loader (a wrapped object, normalised quirks) are
    ``wrapped-json`` / ``normalized`` warnings.
    """
    path = Path(path)
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
    try:
        ws, notes = parse_worksheet(raw)
    except ContractError as exc:
        issues = [Issue("warning", n.code, n.where, n.message) for n in exc.notes]
        issues += [Issue("error", exc.code, loc or "/", msg) for loc, msg in exc.problems]
        if exc.hint:
            issues.append(Issue("error", "legacy-format", "/", exc.hint))
        return Report(issues, None)
    issues = [Issue("warning", n.code, n.where, n.message) for n in notes]
    report = validate(ws, base_dir=path.parent)
    return Report(issues + report.issues, ws)
