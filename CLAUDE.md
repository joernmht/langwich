# langwich

**When the user asks to generate a worksheet or runs `/langwich`, you MUST read and follow `.claude/commands/langwich.md` before doing anything else. That file defines a strict step-by-step interactive workflow. Do NOT skip steps, do NOT auto-generate content, and do NOT run CLI commands until the workflow tells you to.**

Automated language learning worksheet generator for e-paper devices and print.

## Getting started

Install the project in development mode:

```bash
pip install -e .
```

Requires Python 3.11+ and four packages: reportlab, sqlalchemy, pydantic, pydantic-settings.

## Slash commands

- `/langwich` (defined in `.claude/commands/langwich.md`) — Interactive worksheet generator. Walks the user through picking languages, topics, CEFR level, and exercises, then generates vocabulary JSON and renders a PDF worksheet. After generating, it offers to save the user's preferences as a personal skill for one-command reuse. This is the primary way to use the project with Claude Code. **Always follow the step-by-step workflow in the command file.**

## How it works

langwich is LLM-driven. Claude generates **all content** (vocabulary, grammar, reading passages, exercise items). Python handles only PDF rendering and database storage. There are no separate generator scripts.

### Workflow

1. User runs `/langwich`
2. Claude guides through setup: native language, target language, topics, CEFR level, learning path, grammar focus, exercise selection
3. Claude generates a JSON file at `./data/<domain>_<source>_<target>.json` with vocabulary, phrases, grammar, reading passages, and exercise content
4. Claude runs `langwich --from-json <file> --level <CEFR> --path <path>` to render the PDF

## Project structure

- `src/langwich/` — main package
  - `generator.py` — CLI entry point and WorksheetGenerator
  - `import_data.py` — JSON vocabulary import
  - `db/` — SQLAlchemy models and per-domain database manager
  - `exercises/` — exercise type implementations (35 types)
  - `paths/` — learning path templates
  - `rendering/` — Cupertino-style PDF renderer
  - `mining/` — optional corpus mining pipeline (requires `pip install -e ".[mining]"`)
- `.claude/commands/langwich.md` — the `/langwich` slash command definition
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
