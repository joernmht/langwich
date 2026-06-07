# langwich — Architecture

## Overview

langwich generates language-learning worksheets as PDFs. It is **text-first**
and **deterministic**: a single source text is the gold mine, and every exercise
is cut from it by rule. The same JSON input always produces the same worksheet
(modulo an explicit `--seed`).

There is no database and no network access at runtime. The previous mining +
SQLAlchemy implementation has been retired to `archive/` and is not imported by
any live code.

## The five subsystems

```
            ┌──────────────┐
  JSON ───▶ │  text.py     │  SourceText: story, vocabulary, grammar,
            │  (model)     │  picture scene (structured), compounds
            └──────┬───────┘
                   │
            ┌──────▼───────┐
            │  graph.py    │  ExerciseGraph: 18 ExerciseNode subclasses with
            │  (knowledge) │  CEFR range, difficulty, focus, edges, titles
            └──────┬───────┘
                   │ select_exercises()  (cli.py: CEFR + focus + combinability)
            ┌──────▼───────┐
            │  plan.py     │  order by type→difficulty; thread ONE
            │  (orchestr.) │  MaterialLedger so nothing overlaps
            └──────┬───────┘
                   │ generate_exercise() per node  (generate.py, data-driven)
            ┌──────▼───────┐
            │ render.py    │  one design system → PDF
            └──────────────┘
```

### 1. Text model (`text.py`)

`SourceText` is the whole input. Besides the story (`content` + `translation`),
it holds:

- `vocabulary` → `VocabularyNode` of `VocabularyItem`s (term, translation, pos,
  semantic type, optional synonym/antonym);
- `grammar` → `GrammarNode` of `GrammarPhenomenon`s (the "grammatical twists");
- `picture_scene` → `PictureScene` of **structured** `SceneElement`s, each with
  an optional target-language `color` and `position`;
- `compounds` → optional `Compound`s for the morphology exercise.

The structured scene is the key to topic-agnosticism: a picture exercise reads
an element's declared colour/position rather than assuming anything.

### 2. Knowledge graph (`graph.py`)

`ExerciseGraph` holds resource nodes and 18 `ExerciseNode` subclasses across
three types (Fill-in-Blanks, Picture, Word Connections). Each node carries the
metadata selection and rendering depend on: `cefr_range`, `difficulty`,
`learning_focus`, `estimated_minutes`, `combinable_with`, and the learner-facing
`display_name` / `short_instruction`. Edges (`feeds_vocabulary_to`,
`combines_with`, …) describe relationships. The graph is the single source of
truth for *what exists*.

### 3. Generation (`generate.py`)

Pure, deterministic generators turn a node + text into an `ExerciseInstance`.
They are strictly **data-driven** — no topic-specific constants. A shared
`MaterialLedger` records every sentence and word already used, so each generator
skips spent material.

### 4. Planning (`plan.py`)

`build_worksheet()` orders the chosen exercises (word-connection warm-ups →
gap-fills that walk the story in document order → picture/production tasks),
creates one `MaterialLedger`, and runs every generator through it. Result: a
sheet that develops as one story with **no overlapping content**.

### 5. Rendering (`render.py`)

A single design system (one type scale, one palette) lays out: a story page,
numbered exercise blocks (each `KeepTogether` so headers never orphan), a grammar
reference, a vocabulary table, and an answer key.

## Invariants

- **Determinism** — `(JSON, seed)` fully determines the PDF. No wall-clock, no
  unseeded randomness in generation.
- **No overlap** — within one worksheet, no sentence and no tested word is
  reused across exercises (enforced by the shared ledger).
- **No hard-coded content** — generators read facts from the `SourceText` only.
- **Graph is canonical** — titles, instructions, difficulty, CEFR ranges and
  focus all live on `ExerciseNode`, not scattered in the renderer.
- **E-paper / print friendly** — high contrast, restrained colour, A4.

## Adding an exercise subclass

1. Add an `ExerciseNode` in `graph.py` → `build_default_graph()` (id, type,
   difficulty, CEFR range, focus, `combinable_with`), and a `_LEARNER_META`
   entry for its title + rubric.
2. Add any edges relating it to existing nodes.
3. Implement generation in `generate.py` (read only from `SourceText`; reserve
   what you consume on the `MaterialLedger`).
4. The renderer dispatches by id prefix (`fib_*`, `pic_*`, `wc_*`); add a branch
   if the body layout is new.

See the Mermaid sources in this directory (`class_diagram.mermaid`,
`process_diagram.mermaid`) for visual versions; render them with
`python scripts/render_diagrams.py`.
