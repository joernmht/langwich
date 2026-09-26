# langwich 3 — Architecture

langwich turns a short **story** into a printable worksheet for e-paper and
black-and-white print. The story, the facts woven into it and every task item
are written by an LLM — Claude, ChatGPT, Gemini or a model running locally.
Python never invents learner-facing content: it **checks**, **orders**,
**lays out** and **renders**.

```
                ┌───────────────────┐
 learner's  ──▶ │ langwich prompt   │ ──▶ authoring prompt ──▶ any LLM (optionally
 wishes         └───────────────────┘                        with an attached photo)
                                                                   │
                                                                   ▼
                ┌───────────────────┐   issues  ┌──────────────────────────┐
                │ langwich validate │ ◀──────── │ worksheet.json (langwich/3)│
                └───────────────────┘ ────────▶ └──────────────────────────┘
                  repair prompt (--prompt)                 │
                                                           ▼
          plan.py (lesson arc, seeded shuffles) ──▶ render/ (HTML + print CSS) ──▶ WeasyPrint ──▶ PDF
```

## Principles

1. **The LLM writes, Python arranges.** No heuristic text slicing. If a task
   needs an item, the JSON contains it — with its answer.
2. **A story, not an essay.** Scenes with a protagonist, a goal, a complication
   and a resolution. True facts travel inside the story and in "Did you know?"
   sidebars.
3. **A lesson arc.** Before you read → scene by scene (gist → detail → form →
   practice → picture) → your turn (production) → take it further.
4. **Deterministic.** The same JSON (and seed) always renders the same sheet;
   the task page and the answer key share every shuffle.
5. **E-paper first.** Monochrome, high contrast, bundled open-licence fonts,
   writing space sized for handwriting, an A4 and an e-paper page size.
6. **Any LLM.** `langwich prompt` prints a self-contained authoring prompt;
   `langwich validate --prompt` prints a repair prompt. Nothing depends on a
   particular vendor, so a local model works.

## The contract (`langwich/3`)

Defined once in [`src/langwich/model.py`](../src/langwich/model.py) (pydantic);
`langwich schema` prints it as JSON Schema. Top level:

| Field | Language | Purpose |
|---|---|---|
| `schema` | — | always `"langwich/3"` |
| `title`, `standfirst` | target / source | cover |
| `source_lang`, `target_lang`, `cefr_level`, `topic`, `frame` | — | metadata |
| `series` | mixed | episode number, "previously", teaser, review words |
| `story` | | `logline` (source), `setting`, `characters[]`, `scenes[]` |
| `story.scenes[]` | target | `id`, `heading`, `beat`, `text`, `translation` (source), `picture` |
| `picture` | | `image` (path/URL) **or** `svg` (LLM line art), `labels[{n, term, x, y}]`, `prompt` (never printed) |
| `facts[]` | target | true, checkable facts shown as sidebars next to a scene |
| `vocabulary` | | `target[]` (6–15 key words) + `items[]` (term, translation, pos, plural, forms) |
| `grammar[]` | source + target | explanation, rule, table, examples; shown beside the task that practises it |
| `tasks[]` | source (titles, instructions) + target (items) | one of 13 kinds, each with a `stage` |
| `ui` | source | furniture strings for languages without built-in labels |

### Task kinds

| kind | learner does | key fields |
|---|---|---|
| `match` | match left to right (letters in boxes) | `pairs[{left,right}]`, `extra[]` |
| `true_false` | tick, correct false ones | `items[{statement, answer, correction}]` |
| `multiple_choice` | tick one option | `items[{question, options[], answer}]` |
| `order_events` | number events in story order | `events[]` (correct order) |
| `questions` | answer in writing | `items[{question, answer, lines}]` |
| `cloze` | fill gaps | `text` or `items[]` with `{{answer\|alt::hint}}`, `hint`, `distractors[]` |
| `transform` | rewrite sentences | `items[{prompt, cue, answer}]` |
| `word_building` | combine parts | `items[{parts[], answer}]` |
| `label` | name numbered objects in a scene picture | `scene`, `bank` |
| `writing` | write a text | `prompt`, `starter`, `must_use[]`, `min_words`, `max_words`, `lines`, `model_answer` |
| `dialogue` | fill or write dialogue lines | `lines[{speaker, text \| cue, answer}]`, `bank` |
| `media_search` | search online in the target language | `media`, `queries[]`, `questions[]` |
| `draw` | draw and label | `prompt`, `labels[]` |

Stages: `warm_up`, `gist`, `detail`, `form`, `practice`, `picture`,
`production`, `epilogue`.

### Gap markup

`{{geröstet}}`, alternatives `{{schwarz|ohne Milch}}`, hint `{{geröstet::rösten}}`.
The first answer goes into the answer key and the word bank. See
[`markup.py`](../src/langwich/markup.py).

## Modules

| Module | Responsibility | Public interface |
|---|---|---|
| `model.py` | the contract, loading with friendly errors | `Worksheet`, `load_worksheet(path)`, `worksheet_from_dict(d)`, `ContractError`, `json_schema()` |
| `markup.py` | gap parsing | `split`, `gaps`, `fill`, `Gap` |
| `locale.py` | page furniture strings (en, de, fr, es, it, pt) | `t(key, lang, overrides, **fmt)`, `endonym(code)`, `missing_keys` |
| `plan.py` | lesson arc, glosses, sidebars, seeded shuffles | `plan(ws, seed=None) -> Plan`, `PlannedTask`, `SceneBlock` |
| `validate.py` | semantic checks beyond the schema | `validate(ws, base_dir) -> Report`, `check_file(path) -> Report`, `Issue`, `Report`, `CHECKS` (every check code) |
| `answers.py` | renderer-neutral answer key | `answer_key(pt, ws) -> list[str]` |
| `images.py` | load / convert / embed pictures, never crash | `prepare_picture(picture, base_dir, monochrome, warnings) -> PreparedPicture \| None` |
| `render/` | HTML + CSS, fonts, PDF via WeasyPrint | `RenderOptions`, `RenderResult`, `render_worksheet(ws, out_pdf, options)`, `build_html(ws, options)` |
| `prompt.py` | authoring and repair prompts for any LLM | `PromptOptions`, `build_prompt(opts)`, `repair_prompt(report, json_text)`, `MINI_EXAMPLE`, `field_reference()` |
| `series.py` | context for the next episode | `continuation(prev_ws) -> Continuation`, `next_episode_filename(prev_path)` |
| `profile.py` | remembered defaults (`.langwich/profile.json`) | `load_profile()`, `save_profile()` |
| `cli.py` | `render`, `validate`, `schema`, `prompt`, `kinds` (also `python -m langwich`) | `main(argv)` |

## The lesson arc (`plan.py`)

1. **Before you read** — all `warm_up` tasks, in JSON order.
2. **Scene by scene** — the scene text (with glosses in the side column and
   fact sidebars), then the tasks anchored to it: a task belongs to the *last*
   scene it references; tasks without a scene follow the last scene. Within a
   scene tasks are sorted by stage (`gist`, `detail`, `form`, `practice`,
   `picture`), then JSON order.
3. **Your turn** — all `production` tasks.
4. **Take it further** — all `epilogue` tasks.
5. **Back matter** — word list, unattached grammar, solutions, translations,
   the series teaser.

**Glosses** are vocabulary items found in a scene that no task tests (target
words, match pairs, labels, gap answers and word-building answers are never
glossed — a gloss there would be the answer).

**Grammar sidebars** sit beside the first task that references the grammar
point, else beside the first form/practice task of its scene, else beside its
scene, else in the back matter.

## Validation (`validate.py`)

Errors block rendering; warnings are printed (and fail with `--strict`). Every
issue carries a stable code, a JSON-pointer location and a message written so
that an LLM can fix it — `langwich validate FILE --prompt` wraps them into a
repair prompt. The full list lives in `langwich.validate.CHECKS`.

Errors: contract violations (`contract`, `legacy-format`); duplicate ids;
unknown scene / grammar references; target words missing from
`vocabulary.items`; same source and target language; cloze items without gaps,
empty gaps, missing gap hints for `base_form`/`translation`, unbalanced
`{{ }}`, gap markup inside the story; label tasks on a scene without picture
labels, duplicate label numbers, labels without positions on a visual picture
(unless `numbers_in_image`); duplicate match partners; duplicate events;
dialogues with nothing to do; `min_words > max_words`.

Warnings: no production task; no gist/detail task; fewer than 2 or more than 7
scenes; story length outside the CEFR range; target set size outside 5–15,
duplicate target words; target words used in fewer than two tasks or absent
from the story; practice items that copy story sentences; cloze distractors
that are also answers; grammar boxes that show the answers of the task beside
them; no facts; no characters; unused series review words; missing
`previously` for episode ≥ 2; unknown `ui` keys; missing furniture strings for
a source language without built-in labels; nouns without article in languages
that have articles; image files that cannot be found; label tasks that fall
back to "draw and label"; dialogue word boxes without gaps; `{{…}}` in fields
that print braces literally; a file wrapped in a Markdown code fence (the fence
is stripped).

**Word matching** (`plan.term_pattern`) is language- and part-of-speech-aware:
nouns match with short endings, verbs by stem (plus regular German
participles), adjectives with agreement endings (accent-tolerant in French,
Spanish, Italian and Portuguese), phrases and function words exactly; plurals
and listed irregular forms are matched as written.

## Rendering (`render/`)

HTML with print CSS, converted by WeasyPrint. Fonts ship in
`src/langwich/fonts/` (SIL OFL): **Literata** for target-language text,
**Atkinson Hyperlegible Next** for instructions and furniture.

* A4 (`margin: 18mm 12mm 15mm 20mm`) or e-paper (`157.8 × 210.4 mm`, margins
  10/8/10/8 mm, single column, side notes flow as boxed notes below the text).
* Running header: target-language title (italic) · `English → Deutsch · B1`;
  footer: `langwich` · `n / N`.
* Flowing tasks (`break-inside: avoid`); on e-paper long tasks may break between
  items, except those that need everything in view (match, order events, label,
  draw, tasks with a word box). `--one-task-per-page` restores one task per page
  for annotation-heavy e-paper use.
* Scene: heading, paragraphs in a 120 mm column, glosses in a 52 mm side column
  beside the paragraph where the word first appears, glossed words underlined;
  fact and grammar sidebars in the side column — what does not fit beside the
  text moves into a band below the scene. Nothing is ever clipped.
* Tasks: solid numbered square, 13 pt title, 11 pt black instruction, hanging
  numbers, solid blanks sized to the longest answer (uniform per task), solid
  9 mm writing lines, framed word box.
* Pictures: 1 pt frame, full content width, 6 mm solid black numbered markers
  at the label positions; without image/svg a label task becomes "draw and
  label". The image prompt is never printed — it is returned to the CLI and
  written as an HTML comment.
* Raster images are converted to high-contrast greyscale unless colour is
  accepted (`--allow-color`); SVG is embedded as is. Unreadable images produce
  a warning, never a crash.
* Solutions: appended (default, always on a new page), a separate
  `<name>-solutions.pdf`, or none. The word list follows the series teaser
  without a forced page break.

## Why no heuristic fallback?

langwich 2 cut sentences out of a text and blanked words. The result tested
memory rather than language, drew the same sentences every time, gave answers
away and could not tell a story. Writing tasks is exactly what language models
are good at; checking and typesetting them is what code is good at.
