# langwich

**Graph-based language learning worksheet generator.**

**Website:** [joernmht.github.io/langwich](https://joernmht.github.io/langwich/) — why analogue material beats another app, and how to use langwich with Claude, ChatGPT, Gemini or any other AI.

langwich uses an exercise knowledge graph to generate PDF worksheets from any source text. The text is the gold mine — vocabulary, grammar, and exercises all derive from it. Four exercise families (Fill-in-Blanks, Picture Interaction, Word Connections, Media & Research) with 21 subclasses cover vocabulary, grammar, word manipulation, creativity, spatial language, listening, and research skills.

---

## Quick Start

```bash
pip install -e .
```

Requires Python 3.11+ and two packages: [WeasyPrint](https://weasyprint.org) (HTML→PDF, the default engine — needs the Pango system library, preinstalled on most Linux distros and available via `brew install pango` on macOS) and reportlab (automatic fallback when WeasyPrint's system libraries are missing).

### Generate a worksheet

```bash
# Default exercise selection
langwich --from-json examples/coffee_en_de.json

# Pick specific exercises
langwich --from-json examples/coffee_en_de.json \
  --exercises fib_word_bank,pic_object_naming,wc_translation,wc_compound

# Colour tasks (e.g. pic_color_query) must be accepted actively — many
# e-paper devices and printers are black-and-white only
langwich --from-json examples/coffee_en_de.json \
  --exercises pic_color_query --allow-color

# Embed an open-access image (local path or URL) as the worksheet picture
langwich --from-json examples/coffee_en_de.json \
  --image https://upload.wikimedia.org/.../cafe.jpg \
  --image-credit "Wikimedia Commons, CC BY-SA 4.0, Jane Doe"

# List all available exercise types
langwich --list-exercises

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
└── ExerciseNode         — 21 subclasses across 4 families
```

### Exercise types by difficulty

| Diff | ID | Type | Name | Learning Focus |
|------|----|------|------|----------------|
| 1 | `wc_translation` | WordConn | Translation Matching | vocabulary |
| 1 | `pic_color_query` | Picture | Color Query | vocabulary |
| 1 | `pic_element_marking` | Picture | Element Marking | vocabulary |
| 2 | `fib_word_bank` | FIB | Word Bank | vocabulary |
| 2 | `fib_multiple_choice` | FIB | Multiple Choice | vocabulary, grammar |
| 2 | `wc_category` | WordConn | Category Grouping | vocabulary |
| 2 | `pic_object_naming` | Picture | Object Naming | vocabulary |
| 2 | `media_video_search` | Media | Video Search | listening, vocabulary |
| 3 | `fib_first_letter` | FIB | First Letter | vocabulary, spelling |
| 3 | `fib_translation_hint` | FIB | Translation Hint | vocabulary |
| 3 | `fib_full_translation` | FIB | Full Translation | vocabulary, reading |
| 3 | `wc_synonym` | WordConn | Synonyms | vocabulary |
| 3 | `wc_antonym` | WordConn | Antonyms | vocabulary |
| 3 | `pic_position` | Picture | Position Description | spatial language |
| 3 | `pic_fib` | Picture | Picture Fill-in-Blanks | vocabulary, grammar |
| 3 | `media_article_search` | Media | Article Search | reading, research |
| 3 | `media_fact_hunt` | Media | Fact Hunt | research, vocabulary |
| 4 | `fib_base_form` | FIB | Base Form | word manipulation, grammar |
| 4 | `fib_no_hint` | FIB | No Hint | vocabulary, recall |
| 4 | `wc_compound` | WordConn | Compounds | morphology |
| 5 | `pic_scene_description` | Picture | Scene Description | creativity, grammar |

### Graph connections (edges)

Exercises are connected by directed edges:

- **feeds_vocabulary_to** — blanked words from FIB feed into Word Connections vocabulary
- **combines_with** — exercises that work well together on a worksheet
- **provides_resource_to** — resource nodes (vocabulary, grammar) supply exercises
- **references_elements_of** — picture tasks reference elements that must be in the image

Example: `fib_word_bank` → *feeds_vocabulary_to* → `wc_translation` (blanked words become translation pairs).

---

## The Text-First Approach

A source text drives everything:

1. **FIB** — blank out words from the text, produce hints (word bank, first letter, translation, base form, or nothing). Every variant on a worksheet draws *different* sentences and words from the text — a shared generation session tracks what has already been used.
2. **Picture** — the text describes a scene; generate an image from it, then ask questions about colors, positions, objects
3. **Word Connections** — extract vocabulary from the text and pair it (translations, synonyms, antonyms, categories, compounds)
4. **Media & Research** — search tasks around the topic: find a documentary, an article, a fact — in the target language. Deliberately link-free: URLs rot, and searching in the target language is part of the exercise. Suggested search terms are mined from the vocabulary.
5. **Vocabulary & Grammar** — extracted as resource nodes; grammar gets a reference page, vocabulary is repeated per page (see below)

The text can be written by hand, provided as input, or generated by an LLM. The exercise system is independent of text quality.

---

## Worksheet Design

Worksheets are built as an HTML document with print CSS and converted to PDF with WeasyPrint — the `.html` is written next to the `.pdf`, so you can open it in a browser, tweak the CSS, and re-convert. `--engine reportlab` forces the ReportLab renderer (also used automatically when WeasyPrint's system libraries are unavailable).

The layout is built for e-paper devices and black-and-white print, with narrow side margins so the content uses the full page:

- **An editorial look, not a form.** Two-column justified serif reading text with automatic hyphenation, a bold lead-in line, solid-black label chips, oversized task numerals, and a strong black title bar.

- **One task per page.** Every exercise starts on its own page and owns it — tasks never run across page breaks, so nothing jumps mid-exercise.
- **Vocabulary where you need it.** Instead of a reference table at the end, each page repeats the vocabulary that actually occurs on that page: small and grey along the bottom edge, as inline `term – translation` pairs separated by a middle dot.
- **Monochrome by default.** The design is high-contrast black/grey. Colour exercise types (like `pic_color_query`) are skipped unless colour output is actively accepted with `--allow-color` — the device or printer may well be black-and-white.
- **Full-page pictures.** The picture spans the full content width and takes all the height its task leaves free. Image-generation prompts automatically request high-contrast black-and-white artwork (bold outlines, solid blacks, no fine grey gradients); with `--allow-color` they ask for high-contrast colour instead.
- **Real images welcome.** Set `picture_scene.image` in the JSON (or pass `--image`) to a local path or URL — open-access sources like [Wikimedia Commons](https://commons.wikimedia.org) or [Openverse](https://openverse.org) work well. Images are converted to high-contrast grayscale for monochrome output (kept as-is with `--allow-color`). Use `picture_scene.image_credit` (or `--image-credit`) to print the attribution the licence requires.

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
    "paragraph_index": 2,
    "image": "https://upload.wikimedia.org/.../cafe.jpg",
    "image_credit": "Wikimedia Commons, CC BY-SA 4.0, Jane Doe"
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
| `picture_scene.image` | No | Local path or URL of an image to embed (open-access sources recommended) |
| `picture_scene.image_credit` | No | Attribution line printed under the embedded image |
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
     └──→ generate_exercise(node, text, session)
              │        (one GenerationSession per worksheet keeps variants fresh)
              └──→ ExerciseInstance (items + solutions)
                       │
                       └──→ HTML (html_render.py) ──→ WeasyPrint ──→ PDF
                            (ReportLab fallback: render.py)
```

### Project structure

```
langwich/
├── src/langwich/
│   ├── __init__.py
│   ├── graph.py          # Exercise knowledge graph (nodes, edges, default graph)
│   ├── text.py           # SourceText model with PictureScene
│   ├── generate.py       # Exercise generation from text
│   ├── html_render.py    # HTML worksheet + WeasyPrint PDF (default engine)
│   ├── render.py         # ReportLab PDF rendering (fallback engine)
│   └── cli.py            # CLI entry point
├── examples/
│   ├── coffee_en_de.json # Coffee example (EN→DE, B1)
│   ├── coffee_de_fr.json # Same topic for German speakers learning French (DE→FR, B1)
│   └── film_de_fr.json   # Cinema example (DE→FR, B1)
├── scripts/
│   └── update_page_stats.py  # syncs exercise/example counts into docs/index.html
├── archive/              # Previous implementation (preserved for reference)
├── data/                 # Generated PDFs
└── pyproject.toml
```

---

## Adding New Exercise Subclasses

To add a new exercise subclass:

1. **Define the node** in `graph.py` → `build_default_graph()`: add an `ExerciseNode` with id, type, difficulty, learning focus, example, and combinable_with
2. **Add edges** connecting it to existing nodes (feeds_vocabulary_to, combines_with)
3. **Implement generation** in `generate.py`: add a handler in the appropriate `_generate_*` function
4. **The renderer** in `render.py` picks it up automatically via the exercise type prefix (`fib_*`, `pic_*`, `wc_*`, `media_*`)

The landing page reads its exercise counts from the graph (`scripts/update_page_stats.py`, run automatically on deploy), so new subclasses show up there without touching the HTML.

---

## License

MIT
