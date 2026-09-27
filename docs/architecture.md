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
3. **A lesson arc.** Before you read → scene by scene (gist → detail → picture →
   form → practice) → your turn (production) → take it further. Picture tasks
   follow comprehension because they are about the scene just read; form and
   practice items move the story on.
4. **Deterministic.** The same JSON (and seed) always renders the same sheet;
   the task page and the answer key share every shuffle.
5. **E-paper first.** Monochrome, high contrast, bundled open-licence fonts,
   writing space sized for handwriting, an A4 and an e-paper page size.
6. **Any LLM.** `langwich prompt` prints a self-contained authoring prompt;
   `langwich validate --prompt` prints a repair prompt. Nothing depends on a
   particular vendor, so a local model works. Chatty replies are read
   leniently (see *Loading*), every repair reported as a warning.
7. **Offline.** No API, no key. The renderer fetches nothing: WeasyPrint may
   load only `data:` URIs and the bundled fonts, and SVG is sanitised. The
   only outside resource is a `picture.image` the JSON names.

## The contract (`langwich/3`)

Defined once in [`src/langwich/model.py`](../src/langwich/model.py) (pydantic);
`langwich schema` prints it as JSON Schema; the checked-in copy
`src/langwich/schema/langwich-3.json` (kept in sync by
`scripts/export_schema.py`) is published by the Pages workflow at the schema's
`$id`, `https://joernmht.github.io/langwich/schema/langwich-3.json`. Unknown
fields are errors (a worksheet has no `$schema` key). Top level:

| Field | Language | Purpose |
|---|---|---|
| `schema` | — | always `"langwich/3"` |
| `title`, `standfirst` | target / source | cover |
| `source_lang`, `target_lang`, `cefr_level`, `topic`, `frame` | — | metadata |
| `series` | mixed | episode number, "previously", teaser, review words |
| `story` | | `logline` (source), `setting`, `characters[]`, `scenes[]` |
| `story.scenes[]` | target | `id`, `heading`, `beat`, `text`, `translation` (source), `picture` |
| `picture` | | `image` (path relative to the JSON — `pictures/<file>` by convention — URL or `data:` URI) **or** `svg` (LLM line art), `labels[{n, term, x, y}]`, `caption`, `credit`, `prompt` (never printed) |
| `facts[]` | target | true, checkable facts shown as sidebars next to a scene |
| `vocabulary` | | `target[]` (5–15 key words; the brief narrows the range per level) + `items[]` (term, translation, pos, plural, forms) |
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
| `label` | name numbered objects in a scene picture | `scene`, `bank` (terms shown without articles) |
| `writing` | write a text | `prompt`, `starter`, `must_use[]`, `min_words`, `max_words`, `lines`, `model_answer` |
| `dialogue` | fill or write dialogue lines | `lines[{speaker, text \| cue, answer}]`, `bank`, `distractors[]` |
| `media_search` | search online in the target language | `media`, `queries[]`, `questions[]` |
| `draw` | draw and label | `prompt`, `labels[]` |

Stages, in lesson order: `warm_up`, `gist`, `detail`, `picture`, `form`,
`practice`, `production`, `epilogue`.

### Gap markup

`{{geröstet}}`, alternatives `{{schwarz|ohne Milch}}`, hint `{{geröstet::rösten}}`.
The first answer goes into the answer key and the word bank. See
[`markup.py`](../src/langwich/markup.py).

## Modules

| Module | Responsibility | Public interface |
|---|---|---|
| `model.py` | the contract, lenient loading with friendly errors | `Worksheet`, `load_worksheet(path, notes=None)`, `parse_worksheet(text) -> (Worksheet, [LoadNote])`, `normalize_quirks(data)`, `worksheet_from_dict(d)`, `ContractError`, `json_schema()`, `STAGES`, `TASK_KINDS` |
| `markup.py` | gap parsing | `split`, `gaps`, `fill`, `Gap` |
| `locale.py` | page furniture strings (en, de, fr, es, it, pt) | `t(key, lang, overrides, **fmt)`, `endonym(code)`, `missing_keys` |
| `plan.py` | lesson arc, glosses, sidebars, word boxes, seeded shuffles | `plan(ws, seed=None) -> Plan`, `PlannedTask`, `SceneBlock`, `strip_article`, `term_pattern` |
| `validate.py` | semantic checks beyond the schema | `validate(ws, base_dir) -> Report`, `check_file(path) -> Report`, `Issue`, `Report`, `CHECKS` (every check code), `ENVIRONMENT_CODES` |
| `answers.py` | renderer-neutral answer key | `answer_key(pt, ws) -> list[str]` |
| `images.py` | load / convert / sanitise / embed pictures, never crash | `prepare_picture(picture, base_dir, monochrome, warnings) -> PreparedPicture \| None`, `sanitize_svg(root)` |
| `render/` | HTML + CSS, fonts, PDF via WeasyPrint (offline URL fetcher) | `RenderOptions`, `RenderResult`, `render_worksheet(ws, out_pdf, options)`, `build_html(ws, options)`, `is_allowed_url(url)` |
| `prompt.py` | authoring and repair prompts for any LLM | `PromptOptions`, `resolve_options(opts)`, `build_prompt(opts)`, `repair_prompt(report, json_text)` (leaves out `ENVIRONMENT_CODES`; raises `ValueError` for a `no-picture-attached` file), `field_reference(values, terse=False)` |
| `series.py` | context for the next episode, file names | `continuation(prev_ws) -> Continuation`, `next_episode(prev_ws)`, `worksheet_filename(base, src, tgt, episode)`, `next_episode_filename(prev_path, …)` |
| `profile.py` | remembered defaults (`.langwich/profile.json`; `--save-profile` writes languages, level, colour, device — never `frame`) | `load_profile()`, `save_profile(data)`, `SAVED_KEYS` |
| `cli.py` | `render`, `validate`, `schema`, `prompt`, `kinds` (also `python -m langwich`) | `main(argv)` |

## The lesson arc (`plan.py`)

1. **Before you read** — all `warm_up` tasks, in JSON order.
2. **Scene by scene** — the scene text (with glosses in the side column and
   fact sidebars), then the tasks anchored to it: a task belongs to the *last*
   scene it references; tasks without a scene follow the last scene. Within a
   scene tasks are sorted by stage (`gist`, `detail`, `picture`, `form`,
   `practice`), then JSON order.
3. **Your turn** — all `production` tasks.
4. **Take it further** — all `epilogue` tasks.
5. **Back matter** — the series teaser, word list, unattached grammar,
   solutions, translations.

**Glosses** are vocabulary items found in a scene that no task tests (target
words, match pairs, labels, gap answers and word-building answers are never
glossed — a gloss there would be the answer).

**Grammar sidebars** sit beside the first task that references the grammar
point, else beside the first form/practice task of its scene, else beside its
scene, else in the back matter.

**Word boxes** are shuffled with the worksheet's seed: a `word_bank` cloze and
a dialogue with `bank` show the gap answers plus `distractors`; a label task
shows the label terms without their articles (`plan.strip_article`), so the
learner supplies the article — the answer key keeps the full term.

## Loading (`model.py`)

`load_worksheet` reads strict JSON first. When that fails it extracts a JSON
object from a Markdown code fence anywhere in the text or from surrounding
prose — only if the extracted text parses as a JSON object — and records a
`wrapped-json` note. Then `normalize_quirks` fixes known LLM slips and records
a `normalized` note for each: kind aliases (`multiple-choice`/`mcq` →
`multiple_choice`, `fill_in_the_blank(s)`/`gap_fill` → `cloze`,
`true_or_false` → `true_false`, `matching` → `match`, `ordering` →
`order_events`, `short_answer` → `questions`, `essay` → `writing`, `drawing`
→ `draw`, …), facts written as plain strings (→ `{"text": …}`), a lower-case
CEFR level. Nothing else is guessed — no trailing-comma repair; a JSON syntax
error names the position (with a trailing-comma hint only when the character
before it is `,`). `check_file` turns the notes into warnings. A file whose
whole text is the brief's `NO PICTURE ATTACHED` sentinel is the
`no-picture-attached` error.

## Validation (`validate.py`)

Errors block rendering; warnings are printed (and fail with `--strict`). Every
issue carries a stable code, a JSON-pointer location and a message written so
that an LLM can fix it — `langwich validate FILE --prompt` wraps them into a
repair prompt. The full list lives in `langwich.validate.CHECKS`.

**Environment issues** (`validate.ENVIRONMENT_CODES`: `image-not-found`,
`image-unreadable`) are problems no LLM can fix — a picture file that is
missing or cannot be decoded. The repair prompt leaves them out; `validate
--prompt` prints them for the user on stderr and exits 1 when nothing else is
left. `image-not-found`, `image-unreadable` and `svg-invalid` are errors when
the scene's picture has labels or a label or picture-stage task uses that
scene, otherwise warnings. `repair_prompt` refuses (`ValueError`) a
`no-picture-attached` file: the model never saw the photo, and a repair would
only make it invent one.

Errors: contract violations (`contract`, `legacy-format`,
`no-picture-attached`); duplicate ids;
unknown scene / grammar references; target words missing from
`vocabulary.items`; same source and target language; cloze items without gaps,
empty gaps, missing gap hints for `base_form`/`translation`, unbalanced
`{{ }}`, gap markup inside the story; label tasks on a scene without picture
labels, duplicate label numbers, labels without positions on a visual picture
(unless `numbers_in_image`); picture files and SVG that cannot be used where a
task needs them (see above); duplicate match partners; duplicate events;
dialogues with nothing to do; `min_words > max_words`.

Warnings: no production task; no gist/detail task; fewer than 2 or more than 7
scenes; story length outside the CEFR range; target set size outside 5–15,
duplicate target words; target words used in fewer than two tasks or absent
from the story; practice items that copy story sentences; cloze distractors
that are also answers; grammar boxes that show the answers of the task beside
them; no facts; no characters; unused series review words; missing
`previously` for episode ≥ 2; unknown `ui` keys; missing furniture strings for
a source language without built-in labels; nouns without article in languages
that have articles; picture files that cannot be used where no task needs
them; label tasks that fall back to "draw and label"; picture-stage tasks on a
scene without a picture; words drawn as `<text>` in label pictures; SVG with
external links or scripts (removed); dialogue word boxes without gaps; `{{…}}`
in fields that print braces literally; a file read leniently (`wrapped-json`,
`normalized`).

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
  accepted (`--allow-color`); SVG is embedded after `images.sanitize_svg` has
  removed `<script>`, `<foreignObject>` and every external `href`/`xlink:href`,
  `src`, `url()` and `@import`. Unreadable images produce a warning, never a
  crash; `render --strict` exits 1 when rendering produced warnings, which the
  CLI prints before its success line.
* Offline: WeasyPrint gets a URL fetcher (`render.make_url_fetcher`) that
  allows only `data:` URIs and the bundled font files; every picture is
  embedded as a `data:` URI first. `images.py` itself loads the one outside
  resource, a `picture.image` path or URL named in the JSON.
* Solutions: appended (default, always on a new page), a separate
  `<name>-solutions.pdf`, or none. The word list follows the series teaser
  without a forced page break.

## Why no heuristic fallback?

langwich 2 cut sentences out of a text and blanked words. The result tested
memory rather than language, drew the same sentences every time, gave answers
away and could not tell a story. Writing tasks is exactly what language models
are good at; checking and typesetting them is what code is good at.
