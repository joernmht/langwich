# langwich

Story worksheets for language learners, for e-paper and print. An LLM writes a short story in
scenes (true facts woven into fiction, optionally one episode of a series) plus every task and
its answer as `langwich/3` JSON. Python validates the file, orders the tasks along a lesson arc
and renders a monochrome PDF. Human docs: `README.md`; design and validation rules:
`docs/architecture.md`.

## Setup

`pip install -e ".[dev]"` (Python 3.11+; runtime deps: weasyprint, pydantic, pillow). PDFs need
Pango for WeasyPrint (Debian/Ubuntu: `sudo apt install libpango-1.0-0 libpangoft2-1.0-0`, macOS:
`brew install pango`); without it `langwich render` writes only the HTML. `prompt`, `validate`,
`schema` and `kinds` work regardless.

## `/langwich`

`.claude/commands/langwich.md` is the interactive worksheet companion and the main way to make a
worksheet here: profile → story idea from the user → `langwich prompt` → JSON in `data/` →
validate and repair → render → check the picture page.

## The LLM writes all content; Python checks, orders and renders

There is no content generator in Python and there must never be one: no text slicing, no
fallback items. If a task needs an item, the JSON contains it, with its answer. The planner only
arranges (before you read → scene by scene: gist, detail, form, practice, picture → your turn →
take it further) and makes seeded shuffles, so the same JSON and seed give the same PDF.

## Golden rules

1. **Never write langwich JSON from memory.** Run `langwich prompt …` with `-o` to a file, read
   the brief completely and follow it; look fields up with `langwich schema` and
   `langwich kinds`. Unknown fields are errors.
2. **Always validate before rendering.** Run `langwich validate FILE`, fix every error and every
   warning (`--prompt` turns them into repair instructions) until it prints
   `OK: no problems found.`, then `langwich render FILE`.
3. **The topic or premise comes from the user** (or the interests in their profile). Offer ideas;
   never pick one silently. Facts must be true; only the characters are fiction.
4. **langwich 2 and 1 are gone.** `archive/`, the exercise graph (21 exercise types), the
   heuristic generator and the ReportLab engine were removed. Old docs mentioning them are wrong.
   v2 JSON files are upgraded with `langwich prompt --from-json OLD.json`.
5. **Changing the contract** (`src/langwich/model.py`): update `validate.py`, `prompt.py` and
   `render/` to match, run `python scripts/export_schema.py`, and keep every example free of
   errors and warnings.
6. **Docs must match the code.** `tests/test_docs.py` parses every `langwich …` command and flag
   in README.md, CLAUDE.md, the slash command and docs/index.html, and checks every complete JSON
   worksheet in them. Fence partial JSON excerpts as `jsonc`.

## Module map (`src/langwich/`)

| Module | Responsibility |
|---|---|
| `model.py` | the contract (pydantic), `load_worksheet`, `worksheet_from_dict`, `json_schema`, `TASK_KINDS`, `STAGES` |
| `validate.py` | semantic checks; `check_file(path) -> Report` with JSON-pointer issues and fix hints |
| `plan.py` | lesson arc, glosses, grammar and fact sidebars, seeded shuffles |
| `markup.py` | `{{answer\|alternative::hint}}` gap markup |
| `answers.py` | renderer-neutral answer key |
| `images.py` | load, convert (greyscale) and embed pictures; never crash |
| `locale.py` | page labels in en, de, fr, es, it, pt; others via the worksheet's `ui` |
| `prompt.py` | authoring brief (`build_prompt`) and repair prompt for any LLM |
| `series.py` | context for the next episode (`continuation`) |
| `profile.py` | `.langwich/profile.json` (source_lang, target_lang, level, frame, color, device) |
| `render/` | HTML + print CSS → PDF via WeasyPrint; bundled fonts in `fonts/` |
| `cli.py` | `render`, `validate`, `schema`, `prompt`, `kinds`; legacy `--from-json` alias |

## CLI

```bash
langwich prompt --source en --target de --level B1 --topic "night trains" -o .langwich/prompt.md
langwich prompt --continue data/lena_02_en_de.json -o .langwich/prompt.md   # next episode
langwich prompt --image data/market.jpg -o .langwich/prompt.md              # story around a photo
langwich prompt --from-text .langwich/source.txt -o .langwich/prompt.md     # story from a text
langwich validate data/night_trains_en_de.json            # add --prompt, --json or --strict
langwich render data/night_trains_en_de.json --page epaper --solutions separate
```

Other prompt options: `--frame`, `--scenes N`, `--notes TEXT`, `--color`, `--compact` (small local
models), `--save-profile`. Other render options: `-o OUT`, `--one-task-per-page`,
`--no-translations`, `--allow-color`, `--seed N`, `--html-only`, `--strict`. Output goes to
`data/<json name>.pdf` and `.html`; `.langwich/` holds the profile and scratch briefs.

## Tests

```bash
pytest
ruff check src tests scripts
python scripts/export_schema.py --check
python3 scripts/update_page_stats.py --check
```
