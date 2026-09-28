"""The ``langwich`` command line.

::

    langwich prompt --target de --level B1 --topic coffee > prompt.txt
    # give prompt.txt to any LLM, save its answer as data/coffee_en_de.json
    langwich validate data/coffee_en_de.json    # --prompt: a repair prompt for the LLM
    langwich render data/coffee_en_de.json      # -> data/coffee_en_de.pdf
    langwich schema                             # the langwich/3 JSON Schema
    langwich kinds                              # task kinds and lesson stages

The renderer and the prompt builder are imported only by the commands that
need them, so ``validate``, ``schema`` and ``kinds`` work even when
WeasyPrint's system libraries are missing.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NoReturn, get_args

from langwich import __version__
from langwich.model import (
    CEFR_LEVELS,
    STAGES,
    TASK_KINDS,
    ContractError,
    Frame,
    Worksheet,
    json_schema,
    load_worksheet,
)
from langwich.profile import SAVED_KEYS, load_profile, save_profile
from langwich.series import (
    next_episode,
    next_episode_filename,
    slugify,
    worksheet_filename,
)
from langwich.validate import (
    ENVIRONMENT_CODES,
    MAX_IMAGE_BYTES,
    SCENES_MAX,
    SCENES_MIN,
    Report,
    check_file,
)

if TYPE_CHECKING:
    from langwich.prompt import ResolvedOptions

SUBCOMMANDS: tuple[str, ...] = ("render", "validate", "schema", "prompt", "kinds")
FRAMES: tuple[str, ...] = tuple(get_args(Frame))
PageSize = Literal["a4", "epaper"]
PAGES: tuple[PageSize, ...] = ("a4", "epaper")

#: kind -> (what the learner does, key JSON fields)
KIND_INFO: dict[str, tuple[str, str]] = {
    "match": ("match left to right (letters in boxes)", "pairs[{left, right}], extra[]"),
    "true_false": ("tick true/false (or not in the text), correct the false ones",
                   "not_given, justify, items[{statement, answer, correction, quote}]"),
    "multiple_choice": ("tick one option", "items[{question, options[], answer}]"),
    "order_events": ("number events in story order", "events[] (in the correct order)"),
    "questions": ("answer in writing", "question_lang, items[{question, starter, answer, lines}]"),
    "classify": ("tick a column per line, or sort words into columns",
                 "categories[], layout, items[{text, answer}]"),
    "find_in_text": ("find the word in the story that fits a clue",
                     "clue_lang, explain, items[{clue, answer, explanation}]"),
    "gapped_text": ("put removed sentences back (letters)", "text with {{sentences}}, extra[]"),
    "cloze": ("fill gaps, or circle the right word (choice)",
              "text | items[] with {{answer|alt::hint}}, hint, choice_layout, distractors[]"),
    "transform": ("rewrite sentences, or complete them with a key word",
                  "max_words, items[{prompt, cue, answer, keyword, frame}]"),
    "scramble": ("put word tiles in order, write the sentence",
                 "items[{chunks[], end, alternatives[][], cue}]"),
    "word_building": ("combine parts into a word", "items[{parts[], answer}]"),
    "table": ("fill the gaps in a table or form",
              "caption, head[], rows[[cell|null]], hint, distractors[]"),
    "proofread": ("correct the mistakes in a draft", "text with {{correct::wrong}}, marked"),
    "label": ("name numbered objects in a scene picture",
              "scene, bank (a word box of the terms without articles)"),
    "writing": ("write a text (a reply, a summary, an essay)",
                "prompt, input, input_lang, output_lang, register, audience, "
                "points[{point, covered_by}], paragraphs, starter, must_use[], min_words, "
                "max_words, lines, model_answer"),
    "dialogue": ("fill or write dialogue lines",
                 "lines[{speaker, text | cue, answer}], bank, distractors[]"),
    "crossword": ("solve a crossword built from the answers", "clue_lang, entries[{answer, clue}]"),
    "media_search": ("search online in the target language", "media, queries[], questions[]"),
    "draw": ("draw and label", "prompt, labels[]"),
}

_STAGE_TEXT: dict[str, str] = {
    "warm_up": "before you read: pre-teach the key words, make a prediction",
    "gist": "first reading of a scene: the main events",
    "detail": "close reading: facts, reasons, feelings",
    "picture": "the scene picture, right after reading it (label, describe, positions)",
    "form": "notice the grammar or word formation the scene uses",
    "practice": "use the new words and forms in new sentences",
    "production": "your turn: write or speak about the story or yourself",
    "epilogue": "take it further: media search, homework, the next episode",
}
#: stage -> what it is for, in lesson order (the order of model.STAGES).
STAGE_INFO: dict[str, str] = {stage: _STAGE_TEXT[stage] for stage in STAGES}

#: Folder (inside the data folder) that ``prompt --image`` copies pictures to;
#: the worksheet JSON in the data folder refers to them as "pictures/<file>".
PICTURES_DIR = "pictures"
#: Picture formats copied as they are; anything else Pillow can read is
#: converted to JPEG.
_KEPT_FORMATS: dict[str, str] = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp", "GIF": ".gif"}
#: Longest edge of a picture that had to be converted or shrunk.
_MAX_PICTURE_EDGE = 3000
_HEIF_BRANDS = (b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1")

_LANG_RE = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")

_EPAPER_DEVICES = ("epaper", "e-paper", "e_paper", "eink", "e-ink", "remarkable", "kindle",
                   "kobo", "boox", "supernote", "pocketbook", "tolino")
_PRINT_DEVICES = ("a4", "print", "printer", "paper", "pdf")

_LEGACY_IGNORED: dict[str, str] = {
    "--exercises": "the LLM now writes the tasks into the JSON",
    "--image": "set the scene's picture.image in the JSON instead",
    "--image-credit": "set picture.credit in the JSON instead",
    "--engine": "langwich 3 always renders HTML and converts it with WeasyPrint",
}

_WEASYPRINT_HELP = """\
To get PDFs, install WeasyPrint's system libraries (Pango):
  Linux (Debian/Ubuntu): sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0
  macOS:                 brew install pango  (if it is still not found:
                         export DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib)
  Windows:               see https://doc.courtbouillon.org/weasyprint/stable/first_steps.html
Or open the HTML file in a browser and print it to PDF."""


class CliError(Exception):
    """A problem to report as a one-line 'error: …' instead of a traceback."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


def _err(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr)


def _fail(message: str, code: int = 1) -> NoReturn:
    raise CliError(message, code)


# ---------------------------------------------------------------------------
# Argument types and small helpers
# ---------------------------------------------------------------------------


def _lang(value: str) -> str:
    code = value.strip()
    head, sep, tail = code.partition("-")
    code = head.lower() + sep + tail
    if not _LANG_RE.match(code):
        raise argparse.ArgumentTypeError(
            f"'{value}' is not a language code; use ISO 639-1 like en, de, fr, pt-BR",
        )
    return code


def _level(value: str) -> str:
    level = value.strip().upper()
    if level not in CEFR_LEVELS:
        raise argparse.ArgumentTypeError(f"'{value}' is not a CEFR level; use one of "
                                         + ", ".join(CEFR_LEVELS))
    return level


def _scene_count(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{value}' is not a number") from None
    if not SCENES_MIN <= n <= SCENES_MAX:
        raise argparse.ArgumentTypeError(
            f"use between {SCENES_MIN} and {SCENES_MAX} scenes (the range 'langwich validate' "
            "accepts)",
        )
    return n


def _is_url(value: str) -> bool:
    return bool(_URL_RE.match(value)) or value.startswith("data:")


def _page(choice: str | None, device: Any) -> PageSize:
    """--page if given, else the profile's device, else A4."""
    value = choice or _page_from_device(device)
    return "epaper" if value == "epaper" else "a4"


def _page_from_device(device: Any) -> PageSize | None:
    if not isinstance(device, str):
        return None
    d = device.strip().lower()
    if any(k in d for k in _EPAPER_DEVICES):
        return "epaper"
    if d in _PRINT_DEVICES:
        return "a4"
    return None


def _profile() -> dict[str, Any]:
    """The profile, with values langwich cannot use dropped (and reported)."""
    raw = load_profile()
    clean: dict[str, Any] = {}
    for key, value in raw.items():
        ok = True
        if key in ("source_lang", "target_lang"):
            try:
                value = _lang(value) if isinstance(value, str) else value
                ok = isinstance(value, str)
            except argparse.ArgumentTypeError:
                ok = False
        elif key == "level":
            ok = isinstance(value, str) and value.upper() in CEFR_LEVELS
            value = value.upper() if ok else value
        elif key == "frame":
            ok = value is None or value in FRAMES
        elif key == "color":
            ok = isinstance(value, bool)
        if ok:
            clean[key] = value
        else:
            _err(f"note: ignoring profile value {key}={value!r} (not usable)")
    return clean


def _pick(*values: Any) -> Any:
    return next((v for v in values if v is not None), None)


def _read_text(path_arg: str, what: str) -> str:
    if path_arg == "-":
        return sys.stdin.read()
    path = Path(path_arg)
    try:
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        _fail(f"{what} not found: {path}")
    except IsADirectoryError:
        _fail(f"{what} {path} is a folder, not a file")
    except UnicodeDecodeError:
        _fail(f"{what} {path} is not UTF-8 text; save it as UTF-8")
    except OSError as exc:
        _fail(f"cannot read {path}: {exc.strerror or exc}")


def _read_json(path_arg: str, what: str) -> Any:
    raw = _read_text(path_arg, what)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        _fail(f"{what} {path_arg} is not valid JSON (line {exc.lineno}, column {exc.colno}: "
              f"{exc.msg})")


def _output_path(output: str | None, source: Path) -> tuple[Path, bool]:
    """(PDF path, html_only) for the render command's -o option."""
    if output is None:
        return Path("data") / f"{source.stem}.pdf", False
    out = Path(output)
    if out.is_dir() or output.endswith(("/", os.sep)):
        return out / f"{source.stem}.pdf", False
    suffix = out.suffix.lower()
    if suffix in (".html", ".htm"):
        return out.with_suffix(".pdf"), True
    if suffix != ".pdf":
        out = out.with_name(out.name + ".pdf")
    return out, False


def _is_legacy_report(report: Report) -> bool:
    return any(i.code == "legacy-format" for i in report.issues)


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


def _cmd_render(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        _fail(f"file not found: {path}")
    if not path.is_file():
        _fail(f"{path} is not a file")

    report = check_file(path)
    if report.issues:
        _err(f"{path}: {report.format_text()}")
    if not report.ok or report.worksheet is None:
        if _is_legacy_report(report):
            _err("", f"Not rendered. Upgrade the file with 'langwich prompt --from-json {path}' "
                 "and give the printed prompt to your LLM.")
        else:
            _err("", f"Not rendered. Fix the errors above, or run 'langwich validate {path} "
                 "--prompt' and give the printed repair prompt to your LLM.")
        return 1
    if args.strict and report.warnings:
        _err("", "Not rendered: --strict treats warnings as errors.")
        return 1
    ws: Worksheet = report.worksheet

    try:
        from langwich.render import RenderOptions, render_worksheet
    except ImportError as exc:
        _fail(f"the renderer could not be loaded ({exc}); reinstall langwich with "
              "'pip install -e .'")

    profile = _profile()
    page = _page(args.page, profile.get("device"))
    color = bool(args.allow_color or profile.get("color") is True)
    out_pdf, html_only = _output_path(args.output, path)
    options = RenderOptions(
        page=page,
        one_task_per_page=args.one_task_per_page,
        solutions=args.solutions,
        translations=not args.no_translations,
        monochrome=not color,
        seed=args.seed,
        base_dir=path.parent.resolve(),
        html_only=bool(args.html_only or html_only),
    )
    try:
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        result = render_worksheet(ws, out_pdf, options)
    except OSError as exc:
        _fail(f"could not write the worksheet: {exc}")
    except Exception as exc:  # a renderer bug must not look like a user error
        if os.environ.get("LANGWICH_DEBUG"):
            raise
        _fail(f"rendering failed ({type(exc).__name__}: {exc}). This is a bug in langwich; "
              "please report it together with the JSON file (LANGWICH_DEBUG=1 shows a traceback).")

    # Warnings first: they explain what the success line and the files lack.
    for warning in result.warnings:
        _err(f"warning: {warning}")

    bits = [_plural(len(ws.tasks), "task")]
    if result.pages:
        bits.append(_plural(result.pages, "page"))
    main_out = result.pdf or result.html
    extras = []
    if result.solutions_pdf:
        extras.append(f"solutions: {result.solutions_pdf}")
    if result.pdf:
        extras.append(f"HTML: {result.html}")
    tail = f" ({'; '.join(extras)})" if extras else ""
    print(f"Rendered '{ws.title}': {', '.join(bits)} -> {main_out}{tail}", flush=True)

    _report_image_prompts(ws, result.image_prompts)

    if result.weasyprint_error:
        _err(f"PDF not created: WeasyPrint could not be loaded ({result.weasyprint_error}).",
             f"The worksheet HTML is ready: {result.html}", _WEASYPRINT_HELP)
        return 1
    if args.strict and result.warnings:
        _err("", f"--strict: rendering produced {_plural(len(result.warnings), 'warning')} "
             "(above), so the exit status is 1. The files were written; fix the cause and "
             "render again.")
        return 1
    return 0


def _report_image_prompts(ws: Worksheet, prompts: list[tuple[str, str]]) -> None:
    """Print the image prompts of pictures that have no image yet. A picture
    that has an image or svg which could not be used is not "missing": the
    warnings above say what is wrong with it, and it needs fixing, not a new
    picture."""
    scenes = {scene.id: scene for scene in ws.story.scenes}
    missing: list[tuple[str, str]] = []
    broken: list[str] = []
    for scene_id, prompt in prompts:
        scene = scenes.get(scene_id)
        picture = scene.picture if scene is not None else None
        if picture is not None and (picture.image or picture.svg):
            broken.append(scene_id)
        else:
            missing.append((scene_id, prompt))
    if missing:
        print("Some pictures have no image yet. Generate or find one (black-and-white line art "
              f"prints best), save it in the {PICTURES_DIR}/ folder next to the JSON file and set "
              f"the scene's picture.image to \"{PICTURES_DIR}/<file>\":")
        for scene_id, prompt in missing:
            print(f"Image prompt for scene {scene_id}: {prompt}")
    for scene_id in broken:
        _err(f"The picture of scene {scene_id} was given but could not be used (see the warning "
             "above). Fix its picture.image file or its svg; it does not need a new picture.")


# ---------------------------------------------------------------------------
# validate / schema / kinds
# ---------------------------------------------------------------------------


def _cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    report = check_file(path)
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    elif args.prompt:
        return _print_repair_prompt(path, report, strict=args.strict)
    else:
        print(f"{path}: {report.format_text()}")
    if not report.ok:
        return 1
    return 1 if args.strict and report.warnings else 0


def _print_repair_prompt(path: Path, report: Report, strict: bool = False) -> int:
    """``validate --prompt``: the repair prompt on stdout; problems the LLM
    cannot fix (a missing or unreadable photo, the 'NO PICTURE ATTACHED'
    reply) go to the user on stderr instead."""
    if not path.is_file():
        _fail(f"file not found: {path}")
    if not report.issues:
        _err(f"{path}: OK: no problems found; nothing to repair.")
        return 0
    if _is_legacy_report(report):
        _fail(f"{path} is a langwich v2 file; it cannot be repaired, only upgraded. Run "
              f"'langwich prompt --from-json {path}' and give that prompt to your LLM.")
    for_user = report.environment_issues
    for_llm = [i for i in report.issues if i.code not in ENVIRONMENT_CODES]
    if for_user:
        _err(f"{path}: {_plural(len(for_user), 'problem')} for you to fix (not for the LLM):")
        for issue in for_user:
            _err(f"  {issue.where}  [{issue.code}]", f"      {issue.message}")
    if not for_llm:
        _err("", "Nothing for the LLM to repair. Fix the picture file(s) above, then run "
             f"'langwich validate {path}' again.")
        return 1
    try:
        from langwich.prompt import repair_prompt
    except ImportError as exc:
        _fail(f"the prompt builder could not be loaded ({exc})")
    text = _read_text(str(path), "file")
    try:
        prompt = repair_prompt(report, text)
    except ValueError as exc:  # e.g. the 'NO PICTURE ATTACHED' reply: no prompt can fix that
        _err(f"{path}: no repair prompt: {exc}")
        return 1
    print(prompt)
    if for_user:
        _err("", "The repair prompt above leaves out the picture problems; fix those yourself.")
    return 1 if not report.ok or (strict and report.warnings) else 0


def _schema_text() -> str:
    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


def _cmd_schema(args: argparse.Namespace) -> int:
    text = _schema_text()
    if args.output:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write {out}: {exc.strerror or exc}")
        _err(f"Schema written to {out}")
    else:
        sys.stdout.write(text)
    return 0


#: Line width of 'langwich kinds' (long field lists wrap).
_KINDS_WIDTH = 96


def _cmd_kinds(args: argparse.Namespace | None = None) -> int:
    width = max(len(k) for k in TASK_KINDS) + 2
    lines = [f"Task kinds ({len(TASK_KINDS)}): what the learner does, and the key JSON fields", ""]
    for kind in TASK_KINDS:
        does, fields = KIND_INFO[kind]
        lines.append(f"  {kind:<{width}}{does}")
        lines += textwrap.wrap(fields, width=_KINDS_WIDTH, initial_indent=" " * (width + 2),
                               subsequent_indent=" " * (width + 4), break_long_words=False,
                               break_on_hyphens=False)
    swidth = max(len(s) for s in STAGES) + 2
    lines += ["", f"Stages ({len(STAGES)}), in lesson order", ""]
    for stage in STAGES:
        lines.append(f"  {stage:<{swidth}}{STAGE_INFO[stage]}")
    lines += [
        "",
        "Every task has a 'stage'. Story tasks (gist … practice) follow the scene named in",
        "'scene'; warm_up comes before the story, production and epilogue after it.",
        "Full schema: langwich schema",
    ]
    print("\n".join(lines))
    return 0


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------


def _cmd_prompt(args: argparse.Namespace) -> int:
    profile = _profile()
    data_dir = Path(args.data_dir)

    prev: Worksheet | None = None
    if args.continue_from:
        try:
            prev = load_worksheet(args.continue_from)
        except ContractError as exc:
            _fail(f"cannot continue from {args.continue_from}: it is not a valid langwich/3 "
                  f"worksheet.\n{exc}")
        except (OSError, UnicodeDecodeError) as exc:
            _fail(f"cannot read {args.continue_from}: {exc}")

    legacy = None
    if args.from_json:
        legacy = _read_json(args.from_json, "file")
        if not isinstance(legacy, dict):
            _fail(f"{args.from_json} does not contain a JSON object")
        if legacy.get("schema") == "langwich/3":
            _err(f"note: {args.from_json} is already a langwich/3 worksheet; to write the next "
                 "episode of its story use --continue instead.")

    from_text = None
    if args.from_text:
        from_text = _read_text(args.from_text, "text file")
        if not from_text.strip():
            _fail(f"{args.from_text} is empty")

    try:
        from langwich.prompt import PromptOptions, build_prompt, resolve_options
    except ImportError as exc:
        _fail(f"the prompt builder could not be loaded ({exc})")

    device = _pick(args.device, profile.get("device"))
    if args.color is not None:
        color = args.color
    elif args.device is not None:
        color = args.device == "color"
    else:
        color = profile.get("color") is True

    # Languages, level and frame are resolved once, by the prompt builder:
    # explicit flags > previous episode > legacy file > profile > defaults.
    opts = PromptOptions(
        source_lang=args.source, target_lang=args.target, level=args.level,
        topic=args.topic, frame=args.frame, scenes=args.scenes,
        from_text=from_text, from_legacy=legacy, continue_from=prev, series=args.series,
        color=bool(color), compact=args.compact, notes=args.notes, profile=profile,
    )
    try:
        resolved = resolve_options(opts)
    except ValueError as exc:
        _fail(str(exc))
    if resolved.source_lang == resolved.target_lang:
        _fail(f"source and target language are both '{resolved.source_lang}'; --source is your "
              "own language, --target the one you are learning")
    if (args.frame is None and (prev is None or prev.frame is None)
            and resolved.frame is not None and resolved.frame == profile.get("frame")):
        why = (" — every brief starts a series; remove \"frame\" from the profile if you do "
               "not want that" if resolved.frame == "episode" else "")
        _err(f"note: the frame '{resolved.frame}' comes from .langwich/profile.json{why}.")

    picture: str | None = None      # what the user attaches to the LLM
    if args.image:
        if _is_url(args.image):
            opts.image = picture = args.image
        else:
            copied = _import_picture(args.image, data_dir)
            opts.image = f"{PICTURES_DIR}/{copied.name}"
            picture = str(copied)
            _err(f"Picture copied to {copied}; the prompt tells the LLM to write "
                 f"{json.dumps(opts.image)} as picture.image.")

    text = build_prompt(opts)
    if not text.endswith("\n"):
        text += "\n"

    if args.output:
        out = Path(args.output)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(text, encoding="utf-8")
        except OSError as exc:
            _fail(f"could not write {out}: {exc.strerror or exc}")
        _err(f"Prompt written to {out}")
    else:
        sys.stdout.write(text)

    if args.save_profile:
        data = load_profile()
        chosen = {"source_lang": resolved.source_lang, "target_lang": resolved.target_lang,
                  "level": resolved.level, "color": bool(color), "device": device}
        # Never the frame: it is a choice per story ("episode" would make every
        # later brief the start of a series). One added by hand is kept.
        data.update({k: v for k, v in chosen.items() if k in SAVED_KEYS and v is not None})
        _err(f"Profile saved to {save_profile(data)}")

    target_file = _suggested_json(args, prev, legacy, resolved, data_dir)
    attach = f" with the picture {picture} attached," if picture else ""
    where = (f"in {data_dir}/ (the picture path is relative to that folder), e.g. as"
             if args.image and not _is_url(args.image) else "e.g. as")
    _err(f"Next: give this prompt to your LLM{attach} and save the JSON it writes {where} "
         f"{target_file}. Then run 'langwich validate {target_file}' and "
         f"'langwich render {target_file}'.")
    return 0


def _suggested_json(args: argparse.Namespace, prev: Worksheet | None, legacy: dict | None,
                    resolved: ResolvedOptions, data_dir: Path) -> Path:
    """Where to save the LLM's JSON, by the documented naming convention:
    ``<data>/<slug>_<src>_<tgt>.json``, episodes ``<series>_<nn>_<src>_<tgt>.json``."""
    src, tgt = resolved.source_lang, resolved.target_lang
    if prev is not None:
        name = Path(next_episode_filename(
            args.continue_from, next_episode(prev), source_lang=src, target_lang=tgt,
            prev_langs=(prev.source_lang, prev.target_lang),
        )).name
        path = data_dir / name
        if path.exists():
            _err(f"note: {path} already exists; save the new episode under another name so it "
                 "is not overwritten.")
        return path
    episode = 1 if (args.series if args.series is not None else resolved.frame == "episode") else None
    base = args.topic or (legacy.get("topic") if legacy and isinstance(legacy.get("topic"), str)
                          else None)
    if not base and args.image and not _is_url(args.image):
        base = _file_stem(args.image)
    if not base and args.from_json:
        stem = _file_stem(args.from_json)
        base = re.sub(rf"_{re.escape(src)}_{re.escape(tgt)}$", "", stem) or stem
    base = base or "story"
    variant = 1
    path = data_dir / worksheet_filename(base, src, tgt, episode)
    while path.exists():  # never suggest overwriting an earlier worksheet
        variant += 1
        path = data_dir / worksheet_filename(base, src, tgt, episode, variant=variant)
    return path


def _file_stem(path_arg: str) -> str:
    """The file name without extension, also for Windows paths on other systems."""
    name = re.split(r"[\\/]", path_arg.rstrip("\\/"))[-1]
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def _import_picture(arg: str, data_dir: Path) -> Path:
    """Copy a local picture for ``prompt --image`` to
    ``<data_dir>/pictures/<ascii-slug>.<ext>`` and return the copy's path.

    JPEG, PNG, WebP and GIF are copied as they are (after checking that they
    decode); other formats Pillow can read are converted to JPEG. The worksheet
    JSON in ``data_dir`` then refers to the copy as ``pictures/<file>`` — a
    short, portable path without spaces or home folders.
    """
    source = Path(arg).expanduser()
    if not source.is_file():
        if source.exists():
            _fail(f"{arg} is a folder, not a picture file")
        _fail(f"picture not found: {arg}. Give the path of a picture file on this computer, "
              "or a URL.")
    try:
        raw = source.read_bytes()
    except OSError as exc:
        _fail(f"cannot read the picture {arg}: {exc.strerror or exc}")
    data, ext = _picture_bytes(raw, arg)
    folder = data_dir / PICTURES_DIR
    slug = slugify(_file_stem(arg), fallback="picture")
    try:
        folder.mkdir(parents=True, exist_ok=True)
        dest, n = folder / f"{slug}{ext}", 2
        while dest.exists() and dest.read_bytes() != data:
            dest, n = folder / f"{slug}-{n}{ext}", n + 1
        if not dest.exists():
            dest.write_bytes(data)
    except OSError as exc:
        _fail(f"could not copy the picture to {folder}: {exc.strerror or exc}")
    return dest


def _register_heif() -> None:
    """Let Pillow read HEIC/HEIF photos when the optional pillow-heif is installed."""
    try:
        import pillow_heif  # type: ignore[import-not-found]

        pillow_heif.register_heif_opener()
    except Exception:  # not installed or not working: HEIC stays unreadable
        pass


def _picture_bytes(raw: bytes, what: str) -> tuple[bytes, str]:
    """``(bytes to save, extension)`` for a picture, or a clear error."""
    head = raw[:4096].lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return raw, ".svg"
    from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

    _register_heif()
    lenient = ImageFile.LOAD_TRUNCATED_IMAGES  # WeasyPrint turns this on when imported
    ImageFile.LOAD_TRUNCATED_IMAGES = False     # a cut-off download must be reported
    try:
        with Image.open(io.BytesIO(raw)) as img:
            fmt = img.format or ""
            if fmt in _KEPT_FORMATS and len(raw) <= MAX_IMAGE_BYTES:
                img.draft("RGB", (512, 512))  # JPEG: decode small, still checks the whole file
                img.load()
                return raw, _KEPT_FORMATS[fmt]
            img.load()
            picture = ImageOps.exif_transpose(img)
            if picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info:
                rgba = picture.convert("RGBA")
                picture = Image.new("RGB", rgba.size, "white")
                picture.paste(rgba, mask=rgba.getchannel("A"))
            else:
                picture = picture.convert("RGB")
            picture.thumbnail((_MAX_PICTURE_EDGE, _MAX_PICTURE_EDGE))
            out = io.BytesIO()
            picture.save(out, "JPEG", quality=90)
            return out.getvalue(), ".jpg"
    except UnidentifiedImageError:
        if raw[4:8] == b"ftyp" and raw[8:12] in _HEIF_BRANDS:
            _fail(f"cannot read the picture {what}: it is a HEIC/HEIF photo, which langwich can "
                  "read only with the pillow-heif plugin. Export it as JPEG (or PNG) and try "
                  "again, or run 'pip install pillow-heif'.")
        _fail(f"cannot read the picture {what}: it is not an image format langwich can read. "
              "Use a JPEG, PNG, WebP or GIF file (or export the picture as JPEG).")
    except (OSError, ValueError, SyntaxError) as exc:  # Pillow's errors for damaged files
        _fail(f"cannot read the picture {what}: the file seems damaged or incomplete "
              f"({exc}). Export or download it again.")
    finally:
        ImageFile.LOAD_TRUNCATED_IMAGES = lenient


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="langwich",
        description="Story-driven language-learning worksheets for e-paper and print. "
                    "Any LLM writes the story and the tasks as langwich/3 JSON; langwich "
                    "checks, arranges and typesets them.",
    )
    parser.add_argument("--version", action="version", version=f"langwich {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    r = sub.add_parser("render", help="validate a worksheet JSON and render it to PDF",
                       description="Validate a langwich/3 worksheet and render it to PDF "
                                   "(and HTML).")
    r.add_argument("file", metavar="FILE", help="worksheet JSON (langwich/3)")
    r.add_argument("-o", "--output", metavar="OUT",
                   help="output PDF (default: data/<json name>.pdf); a .html name implies "
                        "--html-only, a folder keeps the default name")
    r.add_argument("--page", choices=PAGES, default=None,
                   help="page size: a4 (default) or epaper (157.8 x 210.4 mm); default from "
                        "the profile's 'device'")
    r.add_argument("--one-task-per-page", action="store_true",
                   help="start every task on a new page (roomy for annotation on e-paper)")
    r.add_argument("--solutions", choices=("append", "separate", "none"), default="append",
                   help="solutions at the end (default), as <name>-solutions.pdf, or none")
    r.add_argument("--no-translations", action="store_true",
                   help="leave the scene translations out of the answer section")
    r.add_argument("--allow-color", action="store_true",
                   help="keep images in colour (default: high-contrast greyscale)")
    r.add_argument("--seed", type=int, default=None,
                   help="seed for shuffles (default: derived from the JSON)")
    r.add_argument("--html-only", action="store_true", help="write the HTML only, no PDF")
    r.add_argument("--strict", action="store_true",
                   help="exit with status 1 on warnings: validation warnings stop the rendering, "
                        "rendering warnings (e.g. a picture left out) fail it afterwards")
    r.set_defaults(func=_cmd_render)

    v = sub.add_parser("validate", help="check a worksheet JSON and report problems",
                       description="Check a worksheet against the langwich/3 schema and the "
                                   "semantic rules. Exit status 0 = renderable.")
    v.add_argument("file", metavar="FILE")
    fmt = v.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true", help="print the report as JSON")
    fmt.add_argument("--prompt", action="store_true",
                     help="print a repair prompt to give to the LLM that wrote the file "
                          "(problems only you can fix, like a missing photo, go to stderr)")
    v.add_argument("--strict", action="store_true", help="exit with status 1 on warnings too")
    v.set_defaults(func=_cmd_validate)

    s = sub.add_parser("schema", help="print the langwich/3 JSON Schema",
                       description="Print the langwich/3 JSON Schema.")
    s.add_argument("-o", "--output", metavar="FILE", help="write it to FILE instead")
    s.set_defaults(func=_cmd_schema)

    p = sub.add_parser(
        "prompt", help="print an authoring prompt for any LLM",
        description="Print a self-contained prompt that makes any LLM (also a local one) write "
                    "a langwich/3 worksheet. Defaults come from .langwich/profile.json.",
    )
    p.add_argument("--source", type=_lang, default=None, metavar="LANG",
                   help="your language (default: profile, else en)")
    p.add_argument("--target", type=_lang, default=None, metavar="LANG",
                   help="the language you learn (default: profile, else de)")
    p.add_argument("--level", type=_level, default=None, metavar="CEFR",
                   help="A1 … C2 (default: profile, else B1)")
    p.add_argument("--topic", default=None, help="what the story and its facts are about")
    p.add_argument("--frame", choices=FRAMES, default=None,
                   help="story frame (default: profile, else the LLM chooses)")
    p.add_argument("--scenes", type=_scene_count, default=None, metavar="N",
                   help=f"number of scenes, {SCENES_MIN}-{SCENES_MAX} (default: set by the level)")
    p.add_argument("--image", default=None, metavar="PATH_OR_URL",
                   help="a picture the story is built around; a local file is copied to "
                        "DATA_DIR/pictures/ (converted to JPEG unless it is JPEG, PNG, WebP or "
                        "GIF) and the prompt names it 'pictures/<file>'; attach it to your LLM. "
                        "A URL is used as it is")
    p.add_argument("--data-dir", default="data", metavar="DATA_DIR",
                   help="the folder the worksheet JSON goes into (default: data); --image "
                        "copies the picture into its pictures/ subfolder")
    p.add_argument("--from-text", default=None, metavar="FILE",
                   help="build the worksheet on this text ('-' reads stdin)")
    p.add_argument("--from-json", default=None, metavar="LEGACY_FILE",
                   help="upgrade a langwich v2 JSON file")
    p.add_argument("--continue", dest="continue_from", default=None, metavar="PREV_JSON",
                   help="write the next episode after this langwich/3 worksheet")
    p.add_argument("--color", action=argparse.BooleanOptionalAction, default=None,
                   help="allow colour in pictures (default: profile, else no)")
    p.add_argument("--device", choices=("epaper", "print", "color"), default=None,
                   help="where the sheet is used: epaper, print or color; saved with "
                        "--save-profile (epaper makes 'render' default to --page epaper; color "
                        "implies --color)")
    p.add_argument("--series", action=argparse.BooleanOptionalAction, default=None,
                   help="--series: make this episode 1 of a series (with a teaser), in any "
                        "frame; --no-series: a one-off even with --frame episode (default: a "
                        "series only with --frame episode)")
    p.add_argument("--compact", action="store_true", help="a shorter prompt for small models")
    p.add_argument("--notes", default=None, metavar="TEXT", help="extra wishes for the LLM")
    p.add_argument("-o", "--output", metavar="FILE", help="write the prompt to FILE")
    p.add_argument("--save-profile", action="store_true",
                   help="remember languages, level, colour and device in "
                        ".langwich/profile.json (never the frame: it is a choice per story)")
    p.set_defaults(func=_cmd_prompt)

    k = sub.add_parser("kinds", help="list task kinds and lesson stages",
                       description="List the task kinds and lesson stages.")
    k.set_defaults(func=_cmd_kinds)
    return parser


# ---------------------------------------------------------------------------
# Backward compatibility: langwich --from-json FILE / --list-exercises
# ---------------------------------------------------------------------------


def _is_legacy(argv: list[str]) -> bool:
    if argv and argv[0] in SUBCOMMANDS:
        return False
    return any(
        a == "--from-json" or a.startswith("--from-json=") or a == "--list-exercises"
        for a in argv
    )


def _legacy(argv: list[str]) -> int:
    lp = argparse.ArgumentParser(prog="langwich", add_help=False)
    lp.add_argument("--from-json", dest="file", default=None)
    lp.add_argument("-o", "--output", default=None)
    lp.add_argument("--allow-color", action="store_true")
    lp.add_argument("--list-exercises", action="store_true")
    for flag in _LEGACY_IGNORED:
        lp.add_argument(flag, default=None)
    try:
        args, unknown = lp.parse_known_args(argv)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2

    if args.list_exercises:
        _err("note: '--list-exercises' is deprecated; use 'langwich kinds'.")
        return _cmd_kinds()
    if not args.file:
        _fail("--from-json needs a file: langwich render FILE", 2)
    _err(f"note: 'langwich --from-json FILE' is deprecated; use 'langwich render {args.file}'.")
    for flag, why in _LEGACY_IGNORED.items():
        if getattr(args, flag.lstrip("-").replace("-", "_")) is not None:
            _err(f"note: {flag} is ignored: {why}.")
    if unknown:
        _err(f"note: ignored: {' '.join(unknown)}")
    return _cmd_render(argparse.Namespace(
        file=args.file, output=args.output, page=None, one_task_per_page=False,
        solutions="append", no_translations=False, allow_color=args.allow_color,
        seed=None, html_only=False, strict=False,
    ))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _tolerant_streams() -> None:
    # Consoles that cannot encode a character (e.g. cp437) print '?' instead
    # of crashing: worksheets are full of „quotes“, umlauts and accents.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError, OSError):
            pass


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    _tolerant_streams()
    try:
        if _is_legacy(argv):
            return _legacy(argv)
        parser = build_parser()
        if not argv:
            parser.print_help()
            return 0
        if argv[0].lower().endswith(".json") and not argv[0].startswith("-"):
            _fail(f"missing command; did you mean 'langwich render {argv[0]}' or "
                  f"'langwich validate {argv[0]}'?", 2)
        try:
            args = parser.parse_args(argv)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 2)
        if getattr(args, "func", None) is None:
            parser.print_help()
            return 0
        return int(args.func(args))
    except CliError as exc:
        _err(f"error: {exc}")
        return exc.code
    except KeyboardInterrupt:
        _err("interrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
