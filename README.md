# langwich

**Graph-based language learning worksheet generator.**

langwich uses an exercise knowledge graph to generate PDF worksheets from any source text — including a newspaper article you paste in. The text is the gold mine: vocabulary, grammar, comprehension and exercises all derive from it. Four exercise families (Fill-in-Blanks, Picture Interaction, Word Connections, Reading & Comprehension) with 20 subclasses cover vocabulary, grammar, word manipulation, comprehension, creativity, and spatial language. A reworded **summary** drives the gap-fills, so the worksheet practises the material in fresh wording instead of re-printing the text.

---

## Quick Start

```bash
pip install -e .
```

Requires Python 3.11+ and one package: reportlab.

### Generate a worksheet

```bash
# Default: auto-selects exercises by CEFR level and combinability
langwich --from-json examples/coffee_en_de.json

# Prefer grammar-focused exercises
langwich --from-json examples/coffee_en_de.json --focus grammar

# Prefer vocabulary + morphology exercises
langwich --from-json examples/coffee_en_de.json --focus vocabulary,morphology

# Pick specific exercises
langwich --from-json examples/coffee_en_de.json \
  --exercises fib_word_bank,pic_color_query,wc_translation,wc_compound

# List all available exercise types (with CEFR range, estimated time, focus)
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
└── ExerciseNode         — 20 subclasses across 4 families
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
| 3 | `fib_first_letter` | FIB | First Letter | vocabulary, spelling |
| 3 | `fib_translation_hint` | FIB | Translation Hint | vocabulary |
| 3 | `fib_full_translation` | FIB | Full Translation | vocabulary, reading |
| 3 | `wc_synonym` | WordConn | Synonyms | vocabulary |
| 3 | `wc_antonym` | WordConn | Antonyms | vocabulary |
| 3 | `pic_position` | Picture | Position Description | spatial language |
| 3 | `pic_fib` | Picture | Picture Fill-in-Blanks | vocabulary, grammar |
| 3 | `comp_true_false` | Comprehension | True or False | reading comprehension |
| 4 | `comp_questions` | Comprehension | Open Questions | reading comprehension |
| 4 | `fib_base_form` | FIB | Base Form | word manipulation, grammar |
| 4 | `fib_no_hint` | FIB | No Hint | vocabulary, recall |
| 4 | `wc_compound` | WordConn | Compounds | morphology |
| 5 | `pic_scene_description` | Picture | Scene Description | creativity, grammar |

### Graph connections (edges)

Exercises are connected by directed edges:

- **feeds_vocabulary_to** — blanked words from FIB feed into Word Connections vocabulary
- **combines_with** — exercises that work well together on a worksheet (used by default selection to suggest pairings)
- **provides_resource_to** — resource nodes (vocabulary, grammar) supply exercises
- **references_elements_of** — picture tasks reference elements that must be in the image

Example: `fib_word_bank` → *feeds_vocabulary_to* → `wc_translation` (blanked words become translation pairs).

### How metadata drives exercise selection

When no `--exercises` flag is passed, the CLI uses `ExerciseNode` metadata to pick a suitable set:

1. **`cefr_range`** — filters exercises to those matching the text's CEFR level
2. **`learning_focus`** — when `--focus` is given, prefers exercises whose focus areas match
3. **`difficulty`** — picks the lowest-difficulty exercise per type for the given level
4. **`combinable_with`** — adds one complementary exercise per selected exercise
5. **`estimated_minutes`** — displayed in the worksheet header and CLI output

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
    "caption": "A Viennese café — the scene from paragraph 3.",
    "paragraph_index": 2,
    "elements": [
      {"name": "die Tasse", "color": "weiß", "position": "Die Tasse steht vor der Frau."},
      {"name": "das Fahrrad", "color": "rot"},
      {"name": "das Fenster"}
    ]
  },

  "vocabulary": {
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
  },

  "compounds": [
    {"left": "Milch", "right": "Schaum", "compound": "der Milchschaum", "translation": "milk foam"}
  ]
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
| `picture_scene` | No | Scene description + structured elements for picture tasks |
| `vocabulary` | No | Vocabulary list with items |
| `grammar` | No | Grammar phenomena list (the "grammatical twists" the text trains) |
| `compounds` | No | Compound words split into parts (drives the morphology exercise) |
| `summary` | Recommended | A short **reworded** recap; gap-fills target it so they don't repeat the text |
| `questions` | No | Comprehension questions `{prompt, answer, kind}` (native language) |
| `true_false` | No | True/false statements `{text, is_true}` about the text (target language) |
| `facts` | No | Real science/history/culture notes `{text, source}` in the **target language** → a "Facts & Culture" lead-in before the story |

**Vocabulary item fields:** `term` (required), `translation` (required), `pos` (noun/verb/adjective/adverb/preposition), `semantic_type` (color/position/food/drink/clothing/furniture/...), `synonym` (optional), `antonym` (optional).

**Scene element fields:** `name` (required, target-language noun phrase), `color` (optional, target language — used by colour and picture-gap tasks), `position` (optional, a full target-language sentence — used by the position task), `key` (optional bool, default true — whether the object is named/marked). Picture exercises only emit what the scene declares, so the system is fully topic-agnostic — nothing is hard-coded.

**Compound fields:** `left`, `right`, `compound` (required), `translation` (optional).

---

## Architecture

```
SourceText (JSON)
     │
     ├──→ VocabularyNode ──→ exercises (wc_translation, fib_word_bank, ...)
     ├──→ GrammarNode    ──→ grammar reference page
     ├──→ PictureScene   ──→ exercises (pic_color_query, pic_position, ...)
     │
     └──→ plan.build_worksheet(text, node_ids)   # one shared MaterialLedger
              │                                   # → no sentence/word reused
              └──→ [ExerciseInstance]  (items + solutions, in story order)
                       │
                       └──→ render_worksheet() ──→ PDF
```

### Project structure

```
langwich/
├── src/langwich/
│   ├── __init__.py
│   ├── graph.py          # Exercise knowledge graph (nodes, edges, metadata)
│   ├── text.py           # SourceText, PictureScene + SceneElement, Compound
│   ├── generate.py       # Data-driven generators + MaterialLedger (no overlap)
│   ├── plan.py           # Ordering + no-overlap worksheet orchestration
│   ├── render.py         # PDF design system (ReportLab)
│   └── cli.py            # CLI + CEFR/focus-aware auto-selection
├── examples/
│   ├── coffee_en_de.json # Complete example (EN→DE, B1, present tense + compounds)
│   └── cinema_de_fr.json # Complete example (DE→FR, B1, passé composé)
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
4. **The renderer** in `render.py` picks it up automatically via the exercise type prefix (`fib_*`, `pic_*`, `wc_*`)

---

## License

MIT
