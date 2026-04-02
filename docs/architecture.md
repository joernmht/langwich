# langwich — Architecture Documentation

## Overview

langwich is a modular Python system that generates language learning worksheets as PDFs. It is designed around three independent subsystems connected by a per-domain SQLite database:

1. **Mining Pipeline** — discovers and extracts vocabulary from open-access sources
2. **Learning Paths** — defines configurable exercise sequences
3. **Worksheet Generator** — assembles exercises and renders styled PDFs

---

## Design Principles

- **Domain isolation**: Each domain+language combination gets its own SQLite file, keeping databases small, portable, and version-control-friendly.
- **Rule-first classification**: CEFR levels are assigned via frequency lists before falling back to LLM inference, minimising cost and latency.
- **Open-access bias**: The mining pipeline prioritises openly licensed scientific and educational content.
- **E-paper optimised**: The PDF renderer uses high-contrast, minimal-colour design suitable for e-ink displays.
- **Extensibility**: New sources, exercises, and learning paths can be added without modifying core code.

---

## Module Architecture

### Database Layer (`langwich.db`)

The database layer uses SQLAlchemy ORM with per-domain SQLite files.

**Key entities:**
- `DomainMeta` — one record per database, storing domain name, language pair, and timestamps
- `VocabularyEntry` — individual terms with CEFR level, POS tag, frequency score, and translations
- `PhraseEntry` — example sentences linked to vocabulary entries via a many-to-many association
- `DomainDatabase` — manager class that handles DB lifecycle, CRUD, and querying

**Schema relationships:**
- DomainMeta 1:N VocabularyEntry
- DomainMeta 1:N PhraseEntry
- VocabularyEntry M:N PhraseEntry (via `vocab_phrase_link`)

### Mining Pipeline (`langwich.mining`)

The pipeline runs in seven stages:

| Stage | Module | Description |
|-------|--------|-------------|
| 1. Source Discovery | `sources/*.py` | Query Wikipedia, arXiv, OpenAlex, YouTube for domain-relevant documents |
| 2. Text Extraction | `sources/*.py` | Fetch full text via source APIs, strip markup |
| 3. NLP Processing | `nlp/tokenizer.py` | SpaCy tokenisation, lemmatisation, POS tagging |
| 4. Vocab Extraction | `pipeline.py` | Collect unique lemmas, calculate frequency scores |
| 4b. Phrase Extraction | `nlp/phrase_extractor.py` | Select well-formed example sentences |
| 5. CEFR Classification | `nlp/cefr_classifier.py` | Rule-based lookup, then LLM fallback via scads.ai |
| 6. Domain Tagging | `domain_tagger.py` | Score and filter by domain relevance |
| 7. DB Storage | `pipeline.py` → `db/` | Upsert terms and phrases to SQLite |

**CEFR Classification Strategy:**
1. Look up lemma in bundled frequency lists (Oxford 5000, English Profile, Kelly list)
2. If found → assign level with method `FREQUENCY_LIST`
3. If not found → call scads.ai with a structured classification prompt
4. If LLM response is valid JSON → assign level with method `LLM_FALLBACK`
5. If all else fails → assign `UNKNOWN` for manual review

### Learning Paths (`langwich.paths`)

Paths are ordered lists of `PathStep` objects. Each step specifies an exercise type and optional configuration. A vocabulary page is always ensured as the first step.

**Built-in paths:**
- Vocabulary Focus — term-heavy (matching, synonyms, fill-blanks, translation)
- Reading First — comprehension-led (passage, then vocabulary consolidation)
- Balanced — mix of receptive and productive exercises
- Production — emphasises creative writing and summaries
- Multimedia — incorporates YouTube video tasks

Paths support serialisation to/from JSON for user customisation and curriculum design.

### Exercises (`langwich.exercises`)

Each exercise is a class that implements two methods:
- `generate(vocabulary, phrases, level)` → `ExerciseContent` (data model)
- `render(content)` → `list[Flowable]` (ReportLab PDF elements)

**Exercise types:**
- VocabMatching — match terms to translations
- FillBlanks — complete sentences with missing words
- Synonyms — identify words with similar meanings
- Translation — translate sentences between languages
- ReadingComprehension — read a passage and answer questions
- CreativeWriting — open-ended writing prompts
- TextSummary — summarise a passage
- YouTubeTask — video comprehension with QR code/URL
- DrawingTask — sketch/diagram response area

### Rendering (`langwich.rendering`)

The PDF engine uses ReportLab with a Cupertino-style design system:
- `styles.py` — typography (Helvetica family), colour palette, spacing scale
- `components.py` — reusable elements (info boxes, writing lines, drawing areas)
- `pdf_renderer.py` — assembles the full document with headers, footers, and page numbers

### Generator (`langwich.generator`)

`WorksheetGenerator` is the top-level orchestrator:
1. Loads vocabulary and phrases from the domain database
2. Iterates through the learning path steps
3. Instantiates the appropriate exercise class for each step
4. Generates content and renders flowables
5. Passes all flowables to `PDFRenderer` for final PDF assembly

---

## Configuration

All settings are managed via Pydantic Settings with `.env` file support:
- `ScadsConfig` — LLM API endpoint, model, temperature
- `MiningConfig` — rate limits, timeouts, max sources
- `PDFConfig` — page dimensions, margins, output directory
- `AppConfig` — aggregates all sub-configs

---

## Data Flow Summary

```
Open Sources → Mining Pipeline → SQLite DB → Worksheet Generator → PDF
```

The mining pipeline and worksheet generation are decoupled by the database. You can mine vocabulary once and generate many different worksheets from the same database using different paths and levels.
