# langwich

**Graph-based language learning worksheet generator.**

langwich uses an exercise knowledge graph to generate PDF worksheets from any source text. The text is the gold mine — vocabulary, grammar, and exercises all derive from it. Twelve exercise families with **58 task subclasses** cover the whole spectrum from classic worksheet staples (fill-in-blanks, matching, crosswords, dictation) to new-media tasks: podcast listening, YouTube comprehension, music and film exploration, chat conversations, Instagram captions, micro posts, and 30-second video scripts.

Media tasks come with **QR codes**: a built-in [culture library](#culture-library) of curated podcasts, channels, artists, news sites, films and radio stations for 11 popular languages means learners scan and start — no searching.

---

## Quick Start

```bash
pip install -e .
```

Requires Python 3.11+ and one package: reportlab.

### Generate a worksheet

```bash
# Default showcase selection (text work, picture, puzzle, podcast QR, reflection)
langwich --from-json examples/coffee_en_de.json

# Pick specific exercises
langwich --from-json examples/coffee_en_de.json \
  --exercises fib_word_bank,pz_crossword,media_podcast,soc_chat,st_flashcards

# Everything the text supports (great for browsing the library)
langwich --from-json examples/coffee_en_de.json --exercises all

# List all available exercise types
langwich --list-exercises

# Browse the curated culture library (all languages, or one)
langwich --list-culture
langwich --list-culture de

# Custom output path
langwich --from-json examples/coffee_en_de.json -o my_worksheet.pdf
```

### Using with Claude Code

Run the `/langwich` slash command. Claude generates the source text and vocabulary JSON, then renders the worksheet.

---

## Exercise Knowledge Graph

The graph defines **what exercises exist**, their attributes, and how they connect. Both LLMs and deterministic systems can consume it.

### Node hierarchy

```
GraphNode (base)
├── ResourceNode
│   ├── VocabularyNode   — words with translation, pos, semantic type, synonym, antonym
│   └── GrammarNode      — grammar phenomena found in the text
└── ExerciseNode         — 58 subclasses across 12 families
```

### The task library (58 subclasses in 12 families)

**Fill-in-Blanks (`fib_*`)** — blank out words from the text with varying hints

| Diff | ID | Name |
|------|----|------|
| 2 | `fib_word_bank` | Word Bank |
| 2 | `fib_multiple_choice` | Multiple Choice |
| 3 | `fib_first_letter` | First Letter |
| 3 | `fib_translation_hint` | Translation Hint |
| 3 | `fib_full_translation` | Full Translation |
| 4 | `fib_base_form` | Base Form (conjugation) |
| 4 | `fib_no_hint` | No Hint |

**Picture Interaction (`pic_*`)** — tasks around a generated scene image

| Diff | ID | Name |
|------|----|------|
| 1 | `pic_color_query` | Color Query |
| 1 | `pic_element_marking` | Element Marking |
| 2 | `pic_object_naming` | Object Naming |
| 3 | `pic_position` | Position Description |
| 3 | `pic_fib` | Picture Fill-in-Blanks |
| 5 | `pic_scene_description` | Scene Description |

**Word Connections (`wc_*`)** — pairing and grouping vocabulary

| Diff | ID | Name |
|------|----|------|
| 1 | `wc_translation` | Translation Matching |
| 2 | `wc_category` | Category Grouping |
| 3 | `wc_synonym` | Synonyms |
| 3 | `wc_antonym` | Antonyms |
| 4 | `wc_compound` | Compounds (found in the text) |

**Puzzles (`pz_*`)** — script-agnostic word games built from the vocabulary

| Diff | ID | Name |
|------|----|------|
| 1 | `pz_word_search` | Word Search grid |
| 2 | `pz_word_scramble` | Word Scramble |
| 2 | `pz_odd_one_out` | Odd One Out |
| 2 | `pz_secret_code` | Secret Number Code |
| 3 | `pz_crossword` | Crossword (auto-generated grid) |

**Text Analysis (`ta_*`)** — working *on* the text

| Diff | ID | Name |
|------|----|------|
| 2 | `ta_word_marking` | Underline all nouns/verbs/adjectives |
| 3 | `ta_translation` | Sentence Translation |
| 4 | `ta_error_correction` | Spot & fix spelling errors |
| 5 | `ta_transformation` | Rewrite in another tense |

**Writing (`wr_*`)** — text production genres with scaffolds

| Diff | ID | Name |
|------|----|------|
| 2 | `wr_acrostic` | Acrostic Poem |
| 2 | `wr_postcard` | Postcard (with stamp box) |
| 3 | `wr_diary` | Diary Entry |
| 3 | `wr_headline` | News Headline + Lead |
| 4 | `wr_creative` | Creative Text |
| 4 | `wr_letter` | Structured Letter |
| 4 | `wr_review` | Review with star rating (+ QR pick) |
| 5 | `wr_opinion` | Opinion with pro/contra table |

**Dialogue (`dlg_*`)** — spoken-language scaffolds

| Diff | ID | Name |
|------|----|------|
| 2 | `dlg_comic` | Four-panel comic with speech bubbles |
| 3 | `dlg_roleplay` | Role Play with role cards |
| 3 | `dlg_interview` | Interview Questions (question-word bank) |

**Media (`media_*`)** — authentic media with QR codes from the culture library

| Diff | ID | Name |
|------|----|------|
| 2 | `media_video` | Video / YouTube comprehension |
| 2 | `media_music` | Music & Lyrics exploration |
| 3 | `media_podcast` | Podcast episode (pre/while/post listening) |
| 3 | `media_film` | Film & Series trailer task |
| 3 | `media_radio` | Live radio (word tally) |
| 4 | `media_news` | News article work |

**Social Media (`soc_*`)** — the formats learners actually use

| Diff | ID | Name |
|------|----|------|
| 2 | `soc_chat` | Chat conversation (speech-bubble layout) |
| 2 | `soc_caption` | Instagram photo captions + hashtags |
| 3 | `soc_comments` | Comment thread (agree / ask / share) |
| 3 | `soc_micro_post` | 280-character micro post + hashtags |
| 3 | `soc_storyboard` | Five-frame story storyboard |
| 4 | `soc_video_script` | 30-second video script (hook/main/CTA) |

**Real World (`rw_*`)** — practical text types

| Diff | ID | Name |
|------|----|------|
| 1 | `rw_shopping_list` | Shopping list with quantities & prices |
| 2 | `rw_week_planner` | Week planner (target-language weekdays) |
| 3 | `rw_how_to` | How-to guide (connector-word bank) |

**Numbers (`num_*`)** — numeracy in the target language

| Diff | ID | Name |
|------|----|------|
| 1 | `num_write_words` | Write numbers as words |
| 1 | `num_clock` | Drawn clock faces → time in words |

**Study Tools (`st_*`)** — meta-learning closers

| Diff | ID | Name |
|------|----|------|
| 1 | `st_flashcards` | Cut-out flashcards (dashed borders) |
| 1 | `st_reflection` | 3-2-1 reflection + AI-feedback tip |
| 2 | `st_dictation` | Dictation practice table |

### Graph connections (edges)

Exercises are connected by directed edges:

- **feeds_vocabulary_to** — blanked words from FIB feed into Word Connections vocabulary
- **combines_with** — exercises that work well together on a worksheet
- **provides_resource_to** — resource nodes (vocabulary, grammar) supply exercises
- **references_elements_of** — picture tasks reference elements that must be in the image

Example: `fib_word_bank` → *feeds_vocabulary_to* → `wc_translation` (blanked words become translation pairs).

---

## Culture Library

Media exercises should not send learners off to search the internet — the worksheet prints a **QR code** straight to a curated source. The culture library (`src/langwich/data/culture_library.json`) ships **175 hand-picked resources for 11 languages**:

| | Languages |
|---|---|
| 🇩🇪 🇫🇷 🇪🇸 🇮🇹 🇵🇹 🇬🇧 | German, French, Spanish, Italian, Portuguese, English |
| 🇯🇵 🇨🇳 🇰🇷 🇷🇺 🇸🇦 | Japanese, Mandarin, Korean, Russian, Arabic |

Seven categories per language:

- **podcast** — Slow German, InnerFrench, Nihongo con Teppei, Radio Ambulante, TTMIK, …
- **video** — Easy Languages channels, HugoDécrypte, Dreaming Spanish, Manual do Mundo, …
- **music** — artists whose lyrics reward study (Stromae, YOASOBI, Teresa Teng, Viktor Tsoi, Fairuz, …)
- **news** — including easy-language editions (Nachrichtenleicht, NHK News Web Easy, 1jour1actu, The Chairman's Bao, Breaking News English)
- **film_tv** — acclaimed films/series plus free public mediatheks (ARTE, RaiPlay, RTVE Play, TV5Monde)
- **radio** — live streams for immersion listening
- **social** — accounts posting short, daily target-language content

Every resource is tagged with **topics** (food, science, travel, sports, …) and a **CEFR entry level**. `pick_resource(language, category, topic, cefr_level)` chooses the best match for the worksheet — a cooking worksheet for Japanese learners gets *Midnight Diner*, a news task for German A2 learners gets *Nachrichtenleicht*. Worksheet topic slugs are mapped to library tags automatically (`coffee` → `food`, `ai` → `technology`, …).

For languages not (yet) in the library, media tasks fall back to a ready-made search URL, so the QR code always works.

```python
from langwich.culture import pick_resource

r = pick_resource("de", "podcast", topic="coffee", cefr_level="B1")
# → Slow German mit Annik Rubens, https://slowgerman.com
```

Extend it by editing the JSON (or passing `extra_path` to `load_culture_library`) — no code changes needed.

---

## The Text-First Approach

A source text drives everything:

1. **FIB** — blank out words from the text, produce hints (word bank, first letter, translation, base form, or nothing)
2. **Picture** — the text describes a scene; generate an image from it, then ask questions about colors, positions, objects
3. **Word Connections** — extract vocabulary from the text and pair it (translations, synonyms, antonyms, categories, compounds)
4. **Vocabulary & Grammar** — extracted as resource nodes, rendered as reference pages

The text can be written by hand, provided as input, or generated by an LLM. The exercise system is independent of text quality.

---

## JSON Format

The `--from-json` input uses this structure. See [`examples/coffee_en_de.json`](examples/coffee_en_de.json) for a complete working example.

```json
{
  "title": "Kaffee: Eine Reise um die Welt",
  "content": "Full text in the target language...",
  "translation": "Full text in the source language...",
  "source_lang": "en",
  "target_lang": "de",
  "cefr_level": "B1",
  "topic": "coffee",

  "picture_scene": {
    "description": "Image generation prompt describing the scene...",
    "elements": ["junge Frau", "weiße Tasse", "Cappuccino", "blauer Teller"],
    "paragraph_index": 2
  },

  "vocabulary": {
    "id": "vocab_coffee",
    "name": "Coffee Vocabulary",
    "items": [
      {
        "term": "der Kaffee",
        "translation": "coffee",
        "pos": "noun",
        "semantic_type": "drink",
        "synonym": null,
        "antonym": null
      }
    ]
  },

  "grammar": {
    "phenomena": [
      {
        "name": "present tense",
        "description": "Most of the text uses Präsens for general truths.",
        "examples": ["Die Kaffeepflanze wächst in tropischen Ländern."]
      }
    ]
  }
}
```

### Field reference

| Field | Required | Description |
|-------|----------|-------------|
| `title` | Yes | Title of the text |
| `content` | Yes | Full text in target language |
| `translation` | Yes | Full text in source language |
| `source_lang` | Yes | Learner's native language (ISO 639-1) |
| `target_lang` | Yes | Target language (ISO 639-1) |
| `cefr_level` | Yes | A1–C2 |
| `topic` | Yes | Topic slug (used in header and filename) |
| `picture_scene` | No | Scene description for image generation |
| `vocabulary` | No | Vocabulary list with items |
| `grammar` | No | Grammar phenomena list |

**Vocabulary item fields:** `term` (required), `translation` (required), `pos` (noun/verb/adjective/adverb/preposition), `semantic_type` (color/position/food/drink/clothing/furniture/...), `synonym` (optional), `antonym` (optional).

---

## Architecture

```
SourceText (JSON)
     │
     ├──→ VocabularyNode ──→ exercises (wc_translation, fib_word_bank, ...)
     ├──→ GrammarNode    ──→ grammar reference page
     ├──→ PictureScene   ──→ exercises (pic_color_query, pic_position, ...)
     │
     └──→ ExerciseGraph.generate_exercise(node, text)
              │
              └──→ ExerciseInstance (items + solutions)
                       │
                       └──→ render_worksheet() ──→ PDF
```

### Project structure

```
langwich/
├── src/langwich/
│   ├── __init__.py
│   ├── graph.py          # Exercise knowledge graph (58 nodes, edges, default graph)
│   ├── text.py           # SourceText model with PictureScene
│   ├── generate.py       # Exercise generation from text (all 12 families)
│   ├── puzzles.py        # Word search / crossword / scramble / code algorithms
│   ├── culture.py        # Culture library loader + resource picker
│   ├── i18n.py           # Localized instructions, question words, weekdays, ...
│   ├── render.py         # PDF rendering (ReportLab) incl. QR codes
│   ├── data/
│   │   └── culture_library.json  # 175 curated media resources, 11 languages
│   └── cli.py            # CLI entry point
├── examples/
│   ├── coffee_en_de.json # Complete coffee example (EN→DE, B1)
│   └── film_de_fr.json   # Legacy film example
├── tests/                # Graph, culture, puzzles, generation, render tests
├── archive/              # Previous implementation (preserved for reference)
├── data/                 # Generated PDFs
└── pyproject.toml
```

---

## Adding New Exercise Subclasses

To add a new exercise subclass:

1. **Define the node** in `graph.py` → `build_default_graph()`: add an `ExerciseNode` with id, type, difficulty, learning focus, example, and combinable_with (media tasks also set `media_category`)
2. **Add edges** connecting it to existing nodes (feeds_vocabulary_to, combines_with)
3. **Implement generation** in `generate.py`: add a handler in the family's `_generate_*` function. Emit items built from the generic render primitives — `task`/`lines`, `box`, `bank`, `table`, `grid`, `crossword`, `chat`, `frames`, `cards`, `clock`, `checkboxes`, `post`/`reply`, `role_card`, `stars`, `tip`, … — and rendering comes for free
4. **The renderer** in `render.py` picks the right renderer via the node-id prefix; unknown prefixes use the generic item-based renderer
5. **Localize the instruction** in `i18n.py` (de/fr/es; other source languages fall back to English)

## Adding Culture Resources

Append to `src/langwich/data/culture_library.json`:

```json
{"category": "podcast", "title": "…", "url": "https://…",
 "description": "…", "topics": ["food", "everyday"], "cefr": "B1+"}
```

Prefer stable URLs (official homepages, mediatheks) over deep links, and tag honestly — the picker matches on topics and level.

---

## License

MIT
