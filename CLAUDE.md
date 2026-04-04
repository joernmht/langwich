# langwich

Automated language learning worksheet generator for e-paper devices and print.

## Getting started

Install the project in development mode:

```bash
pip install -e .
```

Requires Python 3.11+ and four packages: reportlab, sqlalchemy, pydantic, pydantic-settings.

## Slash commands

- `/langwich` — Interactive worksheet generator. Walks the user through picking languages, topics, CEFR level, and exercises, then generates vocabulary JSON and renders a PDF worksheet. This is the primary way to use the project with Claude Code.

## How it works

langwich is LLM-driven. Claude generates **all content** (vocabulary, grammar, reading passages, exercise items). Python handles only PDF rendering and database storage. There are no separate generator scripts.

**Important for LLM agents outside Claude Code:** The complete JSON schema, content generation guidelines, and per-exercise content format are documented in two places:
1. **[`README.md`](README.md)** — full JSON schema with field reference and a working example
2. **[`.claude/commands/langwich.md`](.claude/commands/langwich.md)** — detailed content guidelines (grammar quality, reading passage length by CEFR level, exercise item formats)
3. **[`examples/film_de_fr.json`](examples/film_de_fr.json)** — a complete, working example JSON that produces a valid worksheet

Read these files before generating any JSON. The Python code does **not** generate content — if your JSON is missing `grammar`, `reading`, or `exercises` sections, those parts of the worksheet will be empty or use low-quality fallbacks.

### Workflow

1. User runs `/langwich` (or an LLM generates JSON directly)
2. Claude guides through setup: native language, target language, topics, CEFR level, learning path, grammar focus, exercise selection
3. Claude generates a JSON file at `./data/<domain>_<source>_<target>.json` with vocabulary, phrases, grammar, reading passages, and exercise content
4. Claude runs `langwich --from-json <file> --level <CEFR> --path <path>` to render the PDF

### Only 9 of 35 exercise types are currently implemented

The `ExerciseType` enum defines 35 types, but only these 9 have Python rendering classes: `vocab_matching`, `fill_blanks`, `synonyms`, `translation`, `reading_comprehension`, `creative_writing`, `text_summary`, `youtube_task`, `drawing_task`. The remaining 26 are planned but will be skipped with a warning. Stick to the implemented types when generating worksheets.

## Project structure

- `src/langwich/` — main package
  - `generator.py` — CLI entry point and WorksheetGenerator
  - `import_data.py` — JSON vocabulary import
  - `db/` — SQLAlchemy models and per-domain database manager
  - `exercises/` — exercise type implementations (9 implemented, 26 planned)
  - `paths/` — learning path templates
  - `rendering/` — Cupertino-style PDF renderer
  - `mining/` — optional corpus mining pipeline (requires `pip install -e ".[mining]"`)
- `.claude/commands/langwich.md` — the `/langwich` slash command definition (detailed content guidelines)
- `examples/` — working example JSON files
- `data/` — generated JSON and PDF output directory

## CLI reference

```bash
# Generate from JSON (primary usage)
langwich --from-json vocab.json --level B1 --path balanced

# Optional flags
--vocab-position start    # vocabulary at start instead of end
--no-grammar-page         # skip grammar reference page
--no-ai-recommendation    # skip AI upload suggestion
--custom-exercises type:count,type:count  # custom exercise selection
```

## Testing

```bash
pytest
```
