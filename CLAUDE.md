# langwich

Story worksheets for language learners, for e-paper and print. An LLM writes a short story in
scenes (true facts woven into fiction, optionally one episode of a series) plus every task and
its answer as `langwich/3` JSON. Python validates the file, orders the tasks along a lesson arc
and renders a monochrome PDF. Human docs: `README.md`; design and validation rules:
`docs/architecture.md`.

## Setup

Python 3.11+, in a virtual environment (Ubuntu, Debian and Homebrew refuse a bare `pip install`,
PEP 668):

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

Every Bash call starts a fresh shell, so `activate` does not carry over: call `.venv/bin/langwich`,
`.venv/bin/pytest` and so on (or `.venv/bin/python -m …`) whenever `.venv` exists. Runtime deps:
weasyprint, pydantic, pillow, fonttools. PDFs need Pango and HarfBuzz for WeasyPrint
(Debian/Ubuntu: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`, macOS:
`brew install pango`); without them `langwich render` writes only the HTML. `prompt`,
`validate`, `schema` and `kinds` work regardless. Optional: `pillow-heif` reads iPhone HEIC
photos (`pip install -e ".[heic]"`); poppler (`pdftoppm`) lets the Read tool open single PDF
pages — PyMuPDF from the dev extra does the same job (see the slash command).

## `/langwich`

`.claude/commands/langwich.md` is the interactive worksheet companion and the main way to make a
worksheet here: profile → story idea from the user → `langwich prompt` → JSON in `data/` →
validate and repair → render → check the picture page.

## The LLM writes all content; Python checks, orders and renders

There is no content generator in Python and there must never be one: no text slicing, no
fallback items. If a task needs an item, the JSON contains it, with its answer. The planner only
arranges (before you read → scene by scene: gist, detail, picture, form, practice → your turn →
take it further) and makes seeded shuffles, so the same JSON and seed give the same PDF;
`crossword.py` lays out a crossword's grid from the words the JSON gives (arrangement, not
content, and seed-free). Picture tasks follow comprehension because they are about the scene just
read; form and practice items move the story on. Word boxes: a `word_bank` cloze or table and a
dialogue with `bank` hold the gap answers plus `distractors`; a classify task with
`"layout": "columns"` boxes its item texts; a label box shows the terms without articles (the
answer key keeps them).

The brief is level-aware (`prompt.LEVELS`, one `LevelSpec` per CEFR level): it prints the
recommended task set of the learner's level only, the item rules of that level's kinds, and a
task budget that follows the scene count (`validate.task_range`, the `task-count` warning). The
field reference still lists all 20 kinds, and the validator accepts any kind at any level.

## Golden rules

1. **Never write langwich JSON from memory.** Run `langwich prompt …` with `-o` to a file, read
   the brief completely and follow it; look fields up with `langwich schema` and
   `langwich kinds`. Unknown fields are errors.
2. **Always validate before rendering.** Run `langwich validate FILE`, fix every error and every
   warning (`--prompt` turns them into repair instructions) until it prints
   `OK: no problems found.`, then `langwich render FILE`. `image-not-found` and
   `image-unreadable` are file problems, not JSON problems: the repair prompt leaves them out.
   `wrapped-json` and `normalized` warnings mean the file was read leniently (a code fence or
   prose around the object, a kind such as `multiple-choice`): write it cleanly instead.
3. **The topic or premise comes from the user** (or the interests in their profile). Offer ideas;
   never pick one silently. Facts must be true; only the characters are fiction.
4. **langwich 2 and 1 are gone.** `archive/`, the exercise graph (21 exercise types), the
   heuristic generator and the ReportLab engine were removed. Old docs mentioning them are wrong.
   v2 JSON files are upgraded with `langwich prompt --from-json OLD.json`.
5. **Changing the contract** (`src/langwich/model.py`): update `validate.py`, `prompt.py` and
   `render/` to match (a new kind also needs `answers.py`, `cli.KIND_INFO`, its locale strings
   and a place in the `LEVELS` that should recommend it), run `python scripts/export_schema.py`,
   and keep every example free of errors and warnings.
6. **Docs must match the code.** `tests/test_docs.py` parses every `langwich …` command and flag
   in README.md, CLAUDE.md, the slash command, docs/index.html and docs/architecture.md, checks
   that README.md lists every CLI option and every task kind, that stage sequences follow the
   lesson order, and every complete JSON worksheet in them. Fence partial JSON excerpts as
   `jsonc`.
7. **Rebuild the showcase after changing the renderer, the planner or an example.** Run
   `python3 scripts/build_showcase.py` and commit `docs/examples/` and `docs/assets/`;
   `python3 scripts/build_showcase.py --check` (CI) fails when the committed PDFs no longer match
   a fresh render, and notes preview images that neither README.md nor docs/index.html shows.
8. **The renderer stays offline.** WeasyPrint may fetch only `data:` URIs and the bundled fonts
   (`render/__init__.py`, `is_allowed_url`); SVG is sanitised (`images.sanitize_svg`). The only
   outside resource is a `picture.image` the JSON names, loaded by `images.py`.

## Module map (`src/langwich/`)

| Module | Responsibility |
|---|---|
| `model.py` | the contract (pydantic), lenient loading (`load_worksheet`, `parse_worksheet`; `KIND_ALIASES`), `worksheet_from_dict`, `json_schema`, `TASK_KINDS`, `STAGES` |
| `validate.py` | semantic checks (`CHECKS`); `check_file(path) -> Report` with JSON-pointer issues and fix hints; `ENVIRONMENT_CODES`; `task_range(level, scenes)` |
| `plan.py` | lesson arc, glosses, grammar and fact sidebars, word boxes, seeded shuffles |
| `crossword.py` | the grid of a crossword task (`layout(answers)`): deterministic, no seed |
| `markup.py` | `{{answer\|alternative::hint}}` gap markup; `{{right::wrong1\|wrong2}}` choice gaps, `{{correct::wrong}}` proofread mistakes |
| `answers.py` | renderer-neutral answer key (`answer_key`, `answer_key_runs`); quoted words in the marks of their language (`quoted_passage`) |
| `images.py` | load, convert (greyscale), sanitise and embed pictures; never crash |
| `locale.py` | page labels in en, de, fr, es, it, pt; others via the worksheet's `ui`; quotation marks (`quoted`, `QUOTE_MARKS`) |
| `prompt.py` | authoring brief (`build_prompt`; per-level `LEVELS`, `KIND_FIELDS`, `KIND_RULES`) and repair prompt (`repair_prompt`) for any LLM |
| `series.py` | context for the next episode (`continuation`), file names |
| `profile.py` | `.langwich/profile.json` (source_lang, target_lang, level, color, device; `frame` only by hand) |
| `render/` | HTML + print CSS → PDF via WeasyPrint (offline URL fetcher); bundled fonts in `fonts/` |
| `cli.py` | `render`, `validate`, `schema`, `prompt`, `kinds`; legacy `--from-json` alias |

## CLI

```bash
langwich prompt --source en --target de --level B1 --topic "night trains" -o .langwich/prompt.md
langwich prompt --continue data/lena_02_en_de.json -o .langwich/prompt.md   # next episode
langwich prompt --image ~/Pictures/market.jpg -o .langwich/prompt.md        # story around a photo
langwich prompt --from-text .langwich/source.txt -o .langwich/prompt.md     # story from a text
langwich validate data/night_trains_en_de.json            # add --prompt, --json or --strict
langwich render data/night_trains_en_de.json --page epaper --solutions separate
```

Other prompt options: `--frame`, `--series`/`--no-series` (a series in any frame / a one-off
`episode`), `--scenes N` (2–7), `--notes TEXT`, `--color`, `--device {epaper,print,color}`,
`--data-dir DIR`, `--compact` (small local models), `--save-profile` (languages, level, colour,
device — never the frame). `--image FILE` copies the picture to `data/pictures/<slug>.<ext>`
(JPEG unless it is JPEG/PNG/WebP/GIF) and the brief tells the LLM to write
`"picture": {"image": "pictures/<file>"}`, so the JSON belongs in `data/`; a URL is passed through.
Other render options: `-o OUT`, `--one-task-per-page`, `--no-translations`, `--allow-color`,
`--seed N`, `--html-only`, `--strict` (also exit 1 when rendering produced warnings; they are
printed before the `Rendered` line). `validate --prompt` prints problems the LLM cannot fix to
stderr, and exits 1 without a prompt for a `NO PICTURE ATTACHED` reply. Output goes to
`data/<json name>.pdf` and `.html`; `.langwich/` holds the profile and scratch briefs; `data/` is
not in git.

## Tests

```bash
.venv/bin/pytest                                   # LANGWICH_REQUIRE_PDF=1: PDF tests fail, not skip
.venv/bin/ruff check src tests scripts             # pinned rule set in pyproject.toml
.venv/bin/mypy
.venv/bin/python scripts/export_schema.py --check
.venv/bin/python scripts/update_page_stats.py --check
.venv/bin/python scripts/build_showcase.py --check
```

The version lives only in `src/langwich/__init__.py` (`__version__`).
