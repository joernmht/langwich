# langwich

Automated language learning worksheet generator for e-paper devices and print.

## Getting started

Install the project in development mode:

```bash
pip install -e .
```

Requires Python 3.11+ and one package: reportlab.

## Slash commands

- `/langwich` — Interactive worksheet generator. Walks the user through picking languages, topics, CEFR level, and exercises, then generates a source-text JSON and renders a PDF worksheet. This is the primary way to use the project with Claude Code.

## How it works

langwich is **text-first and graph-based**. An LLM (or a human) writes one source text JSON — title, text in the target language, translation, vocabulary list, grammar phenomena, picture scene. Everything else is deterministic Python: an exercise knowledge graph (`graph.py`) defines **58 task subclasses in 12 families**, `generate.py` derives concrete exercises from the text, and `render.py` produces the PDF.

**Read [`README.md`](README.md) before generating any JSON** — it documents the full JSON schema, the complete task library, and the culture library. [`examples/coffee_en_de.json`](examples/coffee_en_de.json) is a complete, working example.

### The 12 exercise families

| Prefix | Family | Examples |
|--------|--------|----------|
| `fib_` | Fill-in-Blanks | word bank, first letter, base form, no hint |
| `pic_` | Picture Interaction | color query, object naming, scene description |
| `wc_` | Word Connections | translation matching, synonyms, compounds |
| `pz_` | Puzzles | word search, crossword, scramble, secret code |
| `ta_` | Text Analysis | error correction, word marking, translation |
| `wr_` | Writing | letter, diary, review, headline, opinion, acrostic |
| `dlg_` | Dialogue | role play, interview questions, comic strip |
| `media_` | Media (QR codes) | podcast, video, music, film, news, radio |
| `soc_` | Social Media | chat, comments, micro post, captions, video script |
| `rw_` | Real World | how-to guide, shopping list, week planner |
| `num_` | Numbers | numbers as words, clock times |
| `st_` | Study Tools | flashcards, dictation, 3-2-1 reflection |

`langwich --list-exercises` prints all 58 with difficulty ratings.

### Culture library (QR codes to real media)

`src/langwich/data/culture_library.json` holds 175 curated resources (podcasts, YouTube channels, artists, news sites, films/series, radio, social accounts) for de, fr, es, it, pt, en, ja, zh, ko, ru, ar — tagged by topic and CEFR level. Media exercises pick a matching resource via `culture.pick_resource()` and the worksheet prints a QR code so learners scan instead of searching. Unknown languages fall back to search URLs. `langwich --list-culture [lang]` browses the library.

### Workflow

1. User runs `/langwich` (or an LLM generates JSON directly)
2. Claude guides through setup: native language, target language, topic, CEFR level, exercise selection
3. Claude generates a source-text JSON (README schema) at `./data/<topic>_<source>_<target>.json`
4. Claude runs `langwich --from-json <file> [--exercises id1,id2,... | all]` to render the PDF

## Project structure

- `src/langwich/` — main package
  - `graph.py` — exercise knowledge graph (58 nodes, edges)
  - `text.py` — SourceText model with PictureScene
  - `generate.py` — exercise generation for all 12 families
  - `puzzles.py` — word search / crossword / scramble / code algorithms
  - `culture.py` — culture library loader and resource picker
  - `i18n.py` — localized instructions (de/fr/es), question words, weekdays
  - `render.py` — ReportLab PDF renderer incl. QR codes
  - `data/culture_library.json` — curated media resources
  - `cli.py` — CLI entry point
- `examples/` — working example JSON files
- `tests/` — pytest suite (graph, culture, puzzles, generation, rendering)
- `archive/` — previous implementation, kept for reference only
- `data/` — generated PDF output directory

## CLI reference

```bash
# Generate from JSON (primary usage)
langwich --from-json examples/coffee_en_de.json

# Pick exercises explicitly, or render every type the text supports
langwich --from-json vocab.json --exercises fib_word_bank,pz_crossword,media_podcast
langwich --from-json vocab.json --exercises all

# Discovery
langwich --list-exercises          # all 58 task types
langwich --list-culture [lang]     # curated media resources

# Custom output path
langwich --from-json vocab.json -o my_worksheet.pdf
```

## Testing

```bash
pytest
```
