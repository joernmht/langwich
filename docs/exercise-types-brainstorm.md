# Exercise Types Brainstorm

> Design document for expanding langwich from 9 to 29 exercise types, plus
> structural worksheet changes.

---

## Current Exercise Types (9)

| # | Type | Size | Description |
|---|------|------|-------------|
| 1 | `vocab_matching` | HALF | Match terms to translations |
| 2 | `fill_blanks` | HALF | Complete sentences with missing words |
| 3 | `synonyms` | HALF | Write synonyms/antonyms for terms |
| 4 | `translation` | HALF | Translate sentences between languages |
| 5 | `reading_comprehension` | DOUBLE | Read passage, answer questions |
| 6 | `creative_writing` | FULL | Open-ended writing prompts |
| 7 | `text_summary` | FULL | Summarise a passage |
| 8 | `youtube_task` | FULL | Video comprehension with URL/QR |
| 9 | `drawing_task` | HALF | Visual sketch/diagram response |

---

## New Exercise Types (20)

### A — Text Production (formal/creative genres)

#### 10. `poetry_writing`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Write a poem in the target language. Prompt varies by level:
  - A2: acrostic poem using vocabulary words as first letters
  - B1: haiku or limerick on the domain topic
  - B2+: free verse or sonnet with required vocabulary
- **Config:** `form` (acrostic | haiku | limerick | free_verse), `num_vocab_required` (default 4)
- **Render:** Instructions + word bank + writing lines

#### 11. `news_headline`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Write newspaper headlines and short abstracts/lead paragraphs.
  Student receives a set of facts (who, what, where, when) and must compose:
  1. A punchy headline (max 10 words)
  2. A lead paragraph (2–3 sentences)
- **Config:** `num_articles` (default 2), `include_abstract` (default true)
- **Render:** Fact boxes → headline line → abstract writing lines
- **Variant:** Can also be used for **paper abstracts** (academic register) by
  setting `register: "academic"` — prompt changes to "Write a 3-sentence
  abstract for a research paper about…"

#### 12. `press_release`
- **Size:** FULL
- **CEFR:** B1+
- **Description:** Write a press release / official statement about a given
  event or announcement. Structured template with: headline, dateline,
  opening paragraph, quote, closing.
- **Config:** `include_template` (default true — shows the structural skeleton)
- **Render:** Template scaffold with labelled sections + writing lines

#### 13. `job_application`
- **Size:** FULL
- **CEFR:** B1+
- **Description:** Write a formal application letter (cover letter) responding
  to a job posting. The exercise provides a short job ad and the student must
  write the letter using formal register and domain vocabulary.
- **Config:** `include_job_ad` (default true), `line_count` (default 15)
- **Render:** Job ad info box → writing lines with structural hints
  (greeting, introduction, qualifications, closing)

#### 14. `blog_post`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Write a blog post entry on the topic. More informal register
  than press release. Student should include a title, an opening hook, body
  paragraphs, and a personal opinion/conclusion.
- **Config:** `word_count_target` (default 100), `num_vocab_required` (default 5)
- **Render:** Title line + writing lines + "Don't forget to include your
  personal opinion!" reminder

#### 15. `movie_review`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Write a review (movie, book, restaurant, product — configurable).
  Structured around: title, star rating, summary, pros/cons, recommendation.
- **Config:** `review_type` (movie | book | restaurant | product), `include_rating` (default true)
- **Render:** Star rating bubbles + structured writing sections (plot/summary,
  opinion, recommendation)

### B — Conversation & Dialogue

#### 16. `conversation`
- **Size:** FULL
- **CEFR:** A1+
- **Description:** Complete or write a dialogue between two or more people.
  Variants:
  - **Gap dialogue:** Some turns are given, student fills in the missing ones.
  - **Free dialogue:** Situation is described, student writes the entire exchange.
  - **Role-play cues:** Character cards with goals, student writes what each
    person would say.
- **Config:** `mode` (gap | free | roleplay), `num_turns` (default 6)
- **Render:** Speech-bubble-style layout with alternating speakers, blank lines
  for student responses

### C — Puzzle & Game Exercises

#### 17. `word_search`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Find vocabulary words hidden in a grid of random letters.
  Words can be placed horizontally, vertically, or diagonally. Grid size
  scales with level (A1: 10×10, B2+: 15×15).
- **Config:** `grid_size` (default auto by level), `num_words` (default 8),
  `allow_diagonal` (default true), `allow_reverse` (default false for A1)
- **Render:** Monospaced letter grid + word list to find below
- **Solution:** Grid with found words highlighted

#### 18. `crossword`
- **Size:** FULL
- **CEFR:** A1+
- **Description:** Crossword puzzle where clues are translations or definitions
  and answers are vocabulary terms. Uses the vocabulary list from the current
  worksheet.
- **Config:** `num_words` (default 10), `clue_type` (translation | definition | both)
- **Render:** Crossword grid (numbered cells) + Across/Down clue lists
- **Solution:** Filled grid
- **Note:** Grid generation uses a simple greedy placement algorithm —
  words are placed by finding intersecting letters.

#### 19. `word_stems`
- **Size:** HALF
- **CEFR:** A2+
- **Description:** Declination and conjugation exercises. Given a word stem,
  student must produce all required forms:
  - **Verbs:** conjugation table (I/you/he/we/they + tenses)
  - **Nouns:** singular/plural, cases (for German: Nom/Akk/Dat/Gen)
  - **Adjectives:** comparative/superlative, attributive forms
- **Config:** `pos_filter` (verb | noun | adj | all), `num_items` (default 4),
  `tenses` (list, default ["present"])
- **Render:** Morphology table with empty cells for student to fill in

### D — Opposites & Word Relationships

#### 20. `opposites`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Dedicated antonym/opposite exercise. Given a list of words,
  student must write the opposite. Can include:
  - Simple antonyms (hot → cold)
  - Negation forms (possible → impossible)
  - Contextual opposites from the domain
- **Config:** `num_items` (default 8), `include_hints` (default false),
  `word_bank` (default false — if true, provides a shuffled word bank)
- **Render:** Two-column layout: word → blank (or matching from word bank)

### E — Numbers, Time & Date

#### 21. `time_and_date`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Exercises around telling time and reading/writing dates.
  Variants by level:
  - **A1:** Read clock faces, write the time in words; write dates in full form
  - **A2:** Schedule reading (train timetable, appointment calendar)
  - **B1+:** Duration calculations, time zone conversions
- **Config:** `mode` (clock | calendar | schedule | mixed), `num_items` (default 6)
- **Render:** Clock face diagrams or timetable grids + answer lines

#### 22. `number_tasks`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Work with numbers in context:
  - Write numbers as words (cardinal and ordinal)
  - Read/write telephone numbers
  - Read/write years and historical dates
  - Technology specs (MHz, GB, km/h — reading numbers in context)
  - Prices and currencies
- **Config:** `category` (telephone | years | prices | technology | mixed),
  `num_items` (default 8)
- **Render:** Number → write-as-words lines, or context sentences with number blanks

#### 23. `calculation`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Math word problems in the target language. Student must:
  1. Read and understand the problem
  2. Perform the calculation
  3. Write the answer as a full sentence
  - A1: basic arithmetic (addition, subtraction, simple multiplication)
  - A2: percentages, unit conversions
  - B1+: multi-step problems, averages
- **Config:** `difficulty` (basic | intermediate | advanced), `num_problems` (default 4)
- **Render:** Word problem text + calculation space + answer line

#### 24. `statistics`
- **Size:** FULL
- **CEFR:** B1+
- **Description:** Read and interpret simple statistics. Important humanistic
  topic — understand data in media. Exercises include:
  - Read a bar chart / pie chart and answer questions
  - Calculate mean, median, percentage from a small data table
  - Write a 2–3 sentence summary interpreting the data
  - Compare two data sets and draw conclusions
- **Config:** `chart_type` (bar | pie | table | line), `num_questions` (default 4)
- **Render:** Simple chart/table (rendered as ReportLab drawing) + questions + writing lines

### F — Text Analysis & Marking

#### 25. `word_marking`
- **Size:** HALF
- **CEFR:** A2+
- **Description:** Given a text passage, mark/underline/circle all instances of
  a specific word category:
  - Attributive adjectives
  - Localization words (prepositions of place, directional words)
  - Temporal expressions
  - Modal verbs
  - Subjunctive forms (B2+)
- **Config:** `target_category` (attributive | localization | temporal | modal | subjunctive),
  `text_length` (short | medium | long)
- **Render:** Passage text with generous line spacing for marking + instruction
  box explaining what to find
- **Solution:** List of target words with positions

### G — Practical / Real-World Texts

#### 26. `recipe`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Read or write a recipe using domain vocabulary. Variants:
  - **Reading:** Given a complete recipe, answer comprehension questions
    (ingredients, quantities, steps)
  - **Writing:** Given ingredients list, write the preparation steps
  - **Reordering:** Given scrambled steps, put them in correct order
- **Config:** `mode` (read | write | reorder), `num_steps` (default 6)
- **Render:** Ingredients list in info box + numbered step lines or reorder items

#### 27. `walkthrough`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Write step-by-step instructions / how-to guide. Topics can
  include: how to use a device, how to get somewhere, how to complete a
  process. Tests imperative mood and sequential connectors
  (first, then, next, finally).
- **Config:** `num_steps` (default 6), `include_connector_bank` (default true)
- **Render:** Connector word bank + numbered step writing lines + tip box
  ("Use imperative forms!")

### H — Listening Comprehension (YouTube subtypes)

#### 28. `listening_steps`
- **Size:** FULL
- **CEFR:** A2+
- **Description:** Step-by-step listening comprehension for YouTube videos.
  Unlike the general `youtube_task`, this breaks the video into timed segments:
  1. Watch 0:00–1:30 → answer question 1
  2. Watch 1:30–3:00 → answer question 2
  3. etc.
  Also includes pre-listening vocabulary preview and post-listening reflection.
- **Config:** `video_url` (str), `segments` (list of {start, end, question}),
  `include_pre_listening` (default true), `include_post_listening` (default true)
- **Render:** Pre-listening word bank → segmented questions with timestamps →
  post-listening reflection lines

### I — Vocabulary at End + AI Recommendation

#### 29. `vocabulary_reference_end`
- **Size:** FULL (reference page, not a scored exercise)
- **CEFR:** all
- **Description:** A vocabulary reference list placed at the **end** of the
  worksheet (not the beginning). Includes:
  - Full vocabulary table grouped by part of speech
  - Recommendation box: *"Try to use these words in your exercises above.
    Also review the grammar rules from the grammar page!"*
  - This replaces the current front-placed vocab page when used in a path

---

## Structural Worksheet Changes

### Vocabulary List Position

Currently the vocabulary reference page is always prepended at the start.
New behaviour:

- **Default:** Vocabulary reference page moves to the **end** of the worksheet
- The vocab page includes a highlighted recommendation box:
  > **Tip:** Use the vocabulary from this list in your exercises.
  > Also apply the grammar rules from the grammar reference page!
- The `--vocab-position` CLI flag allows `start` or `end` (default: `end`)

### AI Upload Recommendation

Every worksheet should end with a footer section (after the last exercise,
before or on the vocabulary page):

> **Done?** Upload your completed worksheet to an AI assistant
> (e.g. ChatGPT, Claude, Gemini) to get instant feedback on your answers!

This is rendered as a styled info box on the last page.

---

## Exercise Categories Summary

| Category | Exercises | Typical CEFR |
|----------|-----------|--------------|
| **Text Production** | poetry, news_headline, press_release, job_application, blog_post, movie_review | A2–C1 |
| **Conversation** | conversation | A1–B2 |
| **Puzzles & Games** | word_search, crossword, word_stems | A1–B2 |
| **Word Relationships** | opposites (+ existing synonyms) | A1–B1 |
| **Numbers & Time** | time_and_date, number_tasks, calculation, statistics | A1–B2 |
| **Text Analysis** | word_marking | A2–C1 |
| **Real-World Texts** | recipe, walkthrough | A2–B2 |
| **Listening** | listening_steps (+ existing youtube_task) | A2–B2 |
| **Reference** | vocabulary_reference_end | all |

---

## Updated Learning Paths (examples)

### New Path: "Comprehensive"

A path that showcases many new exercise types:

```
vocab_matching (HALF) + opposites (HALF)
reading_comprehension (DOUBLE)
word_marking (HALF) + word_stems (HALF)
crossword (FULL)
news_headline (FULL)
conversation (FULL)
creative_writing (FULL)
→ vocabulary_reference_end (FULL)
→ AI upload recommendation
```

### New Path: "Real World"

Practical, real-life text types:

```
vocab_matching (HALF) + number_tasks (HALF)
recipe (FULL)
job_application (FULL)
blog_post (FULL)
time_and_date (HALF) + calculation (HALF)
conversation (FULL)
→ vocabulary_reference_end (FULL)
→ AI upload recommendation
```

### New Path: "Puzzle & Play"

Gamified / low-pressure exercises:

```
word_search (HALF) + opposites (HALF)
crossword (FULL)
word_stems (HALF) + time_and_date (HALF)
calculation (HALF) + number_tasks (HALF)
poetry_writing (FULL)
→ vocabulary_reference_end (FULL)
→ AI upload recommendation
```

---

## Bonus Exercise Ideas (Claude's additions)

These are additional exercise types that complement the above list well:

#### 30. `error_correction`
- **Size:** HALF
- **CEFR:** A2+
- **Description:** Find and correct mistakes in sentences or a short text.
  Each sentence contains 1–2 deliberate errors (grammar, spelling, word order,
  wrong preposition, etc.). Student must underline the error and write the
  corrected version. Great for grammar awareness without being a dry grammar
  drill.
- **Config:** `num_items` (default 6), `error_types` (grammar | spelling | word_order | mixed)
- **Render:** Numbered sentences with error + correction line below each

#### 31. `sentence_reorder`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Put scrambled words into the correct sentence order.
  Given a set of words in random order, student must arrange them into a
  grammatically correct sentence. Tests word order rules and syntax awareness.
- **Config:** `num_items` (default 6), `include_punctuation` (default true)
- **Render:** Jumbled word boxes → answer line

#### 32. `odd_one_out`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Identify which word doesn't belong in a group of 4–5 words.
  Student must circle the odd one out and explain why. Tests semantic
  categorisation and vocabulary depth.
- **Config:** `num_groups` (default 5), `group_size` (default 4),
  `require_explanation` (default true)
- **Render:** Numbered rows of words + "Why?" line

#### 33. `cloze_text`
- **Size:** FULL
- **CEFR:** B1+
- **Description:** A full passage with every nth word removed (classic cloze
  test). Unlike `fill_blanks` which targets specific vocabulary, cloze tests
  general language proficiency. Can be configured as open cloze (no word bank)
  or multiple-choice cloze.
- **Config:** `gap_frequency` (default 7 — every 7th word), `mode` (open | multiple_choice),
  `passage_length` (short | medium | long)
- **Render:** Continuous text with numbered blanks + optional MC options below

#### 34. `dictation_prep`
- **Size:** HALF
- **CEFR:** A1+
- **Description:** Prepares students for dictation practice. Provides a list
  of challenging words/phrases from the vocabulary to practice writing.
  Student writes each word/phrase 2–3 times, then self-tests by covering
  the original and writing from memory. Works well as homework before a
  classroom dictation.
- **Config:** `num_items` (default 8), `repetitions` (default 3)
- **Render:** Word column + practice columns (light grey ruled)

#### 35. `text_transformation`
- **Size:** FULL
- **CEFR:** B1+
- **Description:** Rewrite a text changing one dimension:
  - **Register shift:** informal → formal (or vice versa)
  - **Tense shift:** present → past (or future)
  - **Person shift:** first person → third person
  - **Active → passive** (or vice versa)
  Excellent for grammar practice in a meaningful context.
- **Config:** `transformation` (register | tense | person | voice),
  `source_register` (informal | formal), `target_tense` (past | present | future)
- **Render:** Source text in info box + transformation instruction + writing lines

---

## Implementation Priority

### Phase 1 — Quick wins (simple generate + render)
1. `opposites` — mirrors existing `synonyms`, straightforward
2. `word_search` — fun, visual, self-contained grid generation
3. `number_tasks` — simple templates, high value for A1/A2
4. `time_and_date` — high value for beginners
5. `conversation` — gap-fill variant reuses existing patterns

### Phase 2 — Text production genres
6. `news_headline` — structured prompts + writing lines
7. `blog_post` — informal variant of creative_writing
8. `movie_review` — structured review template
9. `poetry_writing` — creative, level-adaptive prompts
10. `press_release` — formal template scaffold
11. `job_application` — formal letter with job ad

### Phase 3 — Advanced / complex rendering
12. `crossword` — requires grid generation algorithm
13. `word_stems` — requires morphology table rendering
14. `word_marking` — requires inline text highlighting
15. `recipe` — structured format with ingredients + steps
16. `walkthrough` — step-by-step template
17. `calculation` — math word problem generation
18. `statistics` — chart rendering with ReportLab
19. `listening_steps` — segmented YouTube variant
20. `vocabulary_reference_end` — structural change + recommendation boxes
