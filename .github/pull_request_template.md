## Summary

<!-- What does this change, and why? Link the issue if there is one. -->

## Changes

<!-- The changes a reviewer should know about, grouped by area (contract, validator,
planner, renderer, prompt, CLI, docs). For a bug: what went wrong, for which input. -->

## How it was checked

<!-- The commands you ran and what they printed. For a bug fix: the reproduction,
failing before and passing after. For a renderer change: what the PDF looks like now. -->

## Checklist

- [ ] Tests cover the change; `LANGWICH_REQUIRE_PDF=1 pytest` passes (PDF tests fail instead of skipping)
- [ ] `ruff check src tests scripts` and `mypy` pass
- [ ] Every file in `examples/` still validates with `OK: no problems found.`
- [ ] Contract changed (`src/langwich/model.py`)? `validate.py`, `prompt.py` and `render/`
      match it, and `python scripts/export_schema.py` was run
- [ ] Renderer, planner or an example changed? `python3 scripts/build_showcase.py` was run and
      `docs/examples/` and `docs/assets/` are committed
- [ ] Task kinds, stages, page-label languages or examples changed?
      `python3 scripts/update_page_stats.py` was run
- [ ] Docs match the code: README.md (every CLI option), CLAUDE.md, docs/architecture.md,
      docs/index.html, `.claude/commands/langwich.md`; partial JSON excerpts are fenced as `jsonc`
- [ ] Python still writes no learner-facing content: every word comes from the JSON
- [ ] The renderer stays offline: WeasyPrint fetches only safe `data:` URIs and the bundled fonts
