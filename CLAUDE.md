# langwich

Graph-based language-learning **worksheet generator**. One source text → a
printable PDF worksheet whose exercises are all derived deterministically from
that text via an **exercise knowledge graph**.

## Getting started

```bash
pip install -e .          # Python 3.11+, single dependency: reportlab
langwich --from-json examples/coffee_en_de.json
langwich --list-exercises
pytest                    # or:  PYTHONPATH=src python3 -m pytest -q
```

The package lives under `src/`; if it isn't installed, run tooling with
`PYTHONPATH=src`.

## How it works

A `SourceText` (the JSON input) carries the story plus structured material:
vocabulary, grammar phenomena, an optional picture scene, and optional compounds.
The **exercise graph** (`graph.py`) defines what exercises exist and how they
relate. The **planner** (`plan.py`) chooses an order and threads one
`MaterialLedger` through generation so **no sentence or word is reused across
exercises** — the sheet reads as one developing story. The **renderer**
(`render.py`) lays it out with a single, consistent design system.

```
SourceText (JSON)
   │  vocabulary · grammar · picture_scene · compounds
   ▼
ExerciseGraph ──select_exercises()──▶ ordered node ids
   ▼
plan.build_worksheet()  ── shared MaterialLedger (no overlap) ──▶ [ExerciseInstance]
   ▼
render_worksheet() ──▶ PDF  (story · numbered exercises · grammar · vocab · answer key)
```

**Claude generates the content; Python never invents any.** The complete schema
and content rules are in `README.md` and the `/langwich` slash command
(`.claude/commands/langwich.md`). Two working inputs to mirror:
`examples/coffee_en_de.json` (EN→DE) and `examples/cinema_de_fr.json` (DE→FR).

## The `/langwich` skill — hard guardrails

`/langwich` runs a structured interview, then writes the JSON and renders it.
**The user always chooses the topic and the grammar focus; Claude must never
infer or default them.** The generated text must be one coherent story that
*develops* and that deliberately exhibits the chosen grammatical phenomena. See
the command file for the full rules.

## Source layout

- `src/langwich/graph.py` — node hierarchy, the 18 exercise subclasses, edges,
  CEFR/difficulty/focus metadata, and the learner-facing titles/instructions.
- `src/langwich/text.py` — `SourceText`, `PictureScene` + structured
  `SceneElement` (name/color/position), `Compound`. JSON (de)serialisation.
- `src/langwich/generate.py` — deterministic, **data-driven** generators (no
  hard-coded content) + the `MaterialLedger`.
- `src/langwich/plan.py` — ordering + no-overlap orchestration.
- `src/langwich/render.py` — the PDF design system (ReportLab).
- `src/langwich/cli.py` — argument parsing, CEFR/focus-aware auto-selection,
  `--list-exercises`.
- `archive/` — the previous (DB + mining + SQLAlchemy) implementation, kept for
  reference only. Not imported by anything live.

## CLI reference

```bash
langwich --from-json text.json            # auto-select by CEFR + combinability
langwich --from-json text.json --focus grammar,morphology
langwich --from-json text.json --exercises wc_translation,fib_word_bank,pic_color_query
langwich --from-json text.json --seed 7   # reproducible alternative selection
langwich --list-exercises                 # catalogue with CEFR range / minutes / focus
```

## Conventions

- **Determinism**: same JSON + same `--seed` ⇒ identical worksheet. Don't
  introduce wall-clock or unseeded randomness into generation.
- **No hard-coded content**: a generator must read facts from the `SourceText`
  (e.g. an element's `color`), never assume topic-specific values. The picture
  generators are the canonical example — they only emit what the scene declares.
- **Graph is the source of truth**: learner-facing titles, instructions,
  difficulty, CEFR ranges and focus all live on `ExerciseNode`.
