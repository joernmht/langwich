# langwich

**When the user asks to generate a worksheet or runs `/langwich`, you MUST read and follow `.claude/commands/langwich.md` before doing anything else. That file defines a strict step-by-step interactive workflow. Do NOT skip steps, do NOT auto-generate content, and do NOT run CLI commands until the workflow tells you to.**

## Strict rules

1. Do NOT install packages, generate JSON, or run CLI commands until the user has confirmed their choices in all setup steps.
2. Do NOT auto-select languages, topics, CEFR levels, or exercises. Always ask the user.
3. Ask ONE question per message. Wait for the user's answer before proceeding.
4. If the user provides partial info (e.g. "make me a German worksheet"), extract what you can, then ask about the missing pieces one at a time.

## Interaction contract

When guiding a user through worksheet creation:

- Present numbered options at every step. Never ask open-ended questions without also showing concrete choices.
- End every option list with "Or type your own."
- ONE question per message. Never combine steps.
- Never auto-advance without the user's explicit answer.
- Show a summary of all choices before generating anything. Ask for confirmation.

## Workflow (follow in strict order)

### Phase 1 — Interactive setup (MUST complete before Phase 2)

Steps 1–8 from `.claude/commands/langwich.md`. Walk the user through: native language, target language, topics, CEFR level, learning path, grammar focus, exercise selection, and confirmation. Do not proceed until the user confirms the summary.

### Phase 2 — JSON generation (MUST complete before Phase 3)

Generate a JSON file at `./data/<domain>_<source>_<target>.json` with all vocabulary, grammar, reading, and exercise content. The JSON must contain at least 20 vocabulary items. See `data/example_travel_en_de.json` for a complete working example.

### Phase 3 — PDF rendering

Run: `langwich --from-json <file> --level <CEFR> --path <path>`
Report the output path to the user.

### Phase 4 — Skill creation (optional)

Ask the user if they want to save their preferences as a personal slash command for one-command reuse next time.

## Common mistakes to avoid

- Do not install the package and generate content immediately without asking the user any questions.
- Do not invent a topic, language pair, or CEFR level without asking.
- Do not generate a JSON file with only 2–3 vocabulary items (minimum is 20).
- Do not leave grammar.content empty or as a placeholder string.
- Do not skip the confirmation step before generation.
- Do not combine multiple setup questions into a single message.

## Slash commands

- `/langwich` (defined in `.claude/commands/langwich.md`) — Interactive worksheet generator. Walks the user through picking languages, topics, CEFR level, and exercises, then generates vocabulary JSON and renders a PDF worksheet. After generating, it offers to save the user's preferences as a personal skill for one-command reuse. This is the primary way to use the project with Claude Code. **Always follow the step-by-step workflow in the command file.**

## How it works

langwich is LLM-driven. Claude generates **all content** (vocabulary, grammar, reading passages, exercise items). Python handles only PDF rendering and database storage. There are no separate generator scripts.

## Getting started

```bash
pip install -e .
```

Requires Python 3.11+ and four packages: reportlab, sqlalchemy, pydantic, pydantic-settings.

## JSON format

The worksheet data must conform to the structure shown in `data/example_travel_en_de.json`. That file is a complete, realistic example you can use as a template.

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
