---
name: langwich
description: Make a printable worksheet for learning a language: a short story with true facts, tasks and answers, checked and typeset as a PDF. Use when someone asks for a language worksheet.
---

# langwich — a story worksheet, from a chat

The person you are talking to is learning a language and wants a worksheet to work through with a
pen: a short story in that language, told in scenes, with true facts woven in and tasks that lead
them through it. You write every word (story, facts, vocabulary, grammar, every task and its
answer) as a langwich/3 JSON file. The bundled `langwich` tool checks it, puts the tasks in lesson
order and typesets a calm black-and-white PDF for printing or an e-reader.

**Most people using this skill do not write code.** Never ask them to run a command, open a
terminal or edit a file. Do all of that yourself, quietly, and talk to them only about the story,
the settings and the result. No jargon: say "worksheet", "story", "level", "PDF" — not JSON,
schema, validate or render.

## 0. Set up the tool (once per conversation, silently)

This skill's folder holds the langwich engine in `engine/`. Copy it somewhere writable and install
it (the skill folder itself is read-only):

```bash
cp -r <skill-folder>/engine /tmp/langwich-engine
pip install --quiet /tmp/langwich-engine || pip install --quiet --break-system-packages /tmp/langwich-engine
langwich kinds
```

If the install fails because packages cannot be downloaded, install without them —
`pip install --quiet --no-deps --break-system-packages /tmp/langwich-engine` — and check that
`python3 -c "import pydantic, PIL"` works. langwich then still checks worksheets, and writes the
worksheet as an HTML page instead of a PDF (step 6 says what to tell the person).

Work in one folder for the whole conversation, and start every command there:

```bash
mkdir -p ~/langwich/data && cd ~/langwich && langwich kinds
```

## 1. Settings — one short message

Unless the person already said it, ask for four things in ONE friendly message with suggested
defaults they can accept with "ok". Take their language from how they write to you:

> Let's make your worksheet! Four quick settings — reply **ok** to keep them, or change any:
>
> 1. **Your language:** English
> 2. **You're learning:** German
> 3. **Level:** B1 — *A1* first words · *A2* everyday situations · *B1* stories on familiar
>    topics · *B2* longer texts · *C1* nuance and idiom · *C2* near-native
> 4. **For:** printing on paper — or an e-reader / e-paper tablet

Never assume colour; use it only when they ask for it.

## 2. The story idea — always theirs

Never pick a topic silently. Offer 3–4 concrete ideas, each with a named character, what they
want, and the real facts the story will carry; vary the areas (food, travel, nature, science,
history, a craft, a job). Then open the other doors: "Or tell me your own idea — or send me a
photo to build the story around — or paste a text you'd like to work with." Ask whether it should
be a one-off or episode 1 of a series.

- **A photo** they attached: in Claude apps uploads are in `/mnt/user-data/uploads/`. Look at it,
  say in one line what you see, and pass it with `--image` below. People in it become fictional
  characters; never guess who they are.
- **A pasted text:** save it as `~/langwich/source.txt` and pass `--from-text source.txt`.
- **The next episode** of a worksheet they made earlier: ask them to attach that worksheet's
  `.json` file (you hand it over with every PDF, step 6), save it in `data/` and pass
  `--continue data/<file>.json`.

## 3. Get the brief

```bash
cd ~/langwich && langwich prompt --source en --target de --level B1 --topic "sourdough and a night bakery" --device print -o prompt.md
```

Use their languages (codes such as `en`, `de`, `fr`, `es`, `pt-BR`), level and idea. Add what
applies: `--device epaper` for an e-reader, `--frame episode` for episode 1 of a series,
`--image <photo>`, `--from-text source.txt`, `--continue data/<file>.json`, `--notes "…"` for
anything else they told you ("make it funny", "set it in Graz"). Leave out `--compact`.

## 4. Write the worksheet

Read `prompt.md` completely and follow it to the letter — it is the single source of truth for
the format, the level, the story craft and the task rules. Plan as it says, then write exactly one
JSON object (no code fence, no comments) to the file name `langwich prompt` suggested at the end
of its output, in `data/`. With `--image`, write `picture.image` exactly as the brief says. Don't
paste the JSON or the brief into the chat; "Writing your story now…" is enough.

## 5. Check it — the tool first, then you

```bash
cd ~/langwich && langwich validate data/<file>.json --quality
```

Fix every error, every warning and every design finding (each message says where and how), and
check again until it prints `OK: no problems found.` and no findings. Then read the worksheet as a
strict native-speaker editor and an experienced teacher:

- **Language:** natural, right for the level; articles, genders, plurals and verb forms correct.
- **Facts:** every one true; no invented numbers, dates, records or quotes. When in doubt, cut it.
- **Tasks:** exactly one defensible answer per gap; distractors plausible but wrong; no answer
  given away elsewhere.
- **Story:** a named character who wants something, a complication, a payoff that turns on a true
  fact. Would they want to know how it ends?

Fix what you find and check again.

## 6. Make the PDF and hand it over

```bash
cd ~/langwich && langwich render data/<file>.json --page a4
```

`--page epaper` for an e-reader, `--page a4` for print; `--allow-color` only if they asked for
colour; `--solutions separate` if they want the answers in a second file. Warnings printed before
the `Rendered` line mean something is missing from the sheet: fix the cause and render again.

If the story has a photo or drawing with numbered labels, look at that page (for example with
`pip install pymupdf` and PyMuPDF's `page.get_pixmap()`): every number must sit on its object.
Fix `x`/`y` in the JSON and render again if not.

**Hand over the files.** In Claude apps, copy the PDF (and the solutions PDF, if any) **and the
`.json` file** to `/mnt/user-data/outputs/` so the person can download them; elsewhere, offer them
as downloads in whatever way this app allows. Tell them in plain words:

> Your worksheet is ready: *Die Nachtbäckerei*, 14 pages. Print it double-sided, or copy it to
> your e-reader. Keep the small .json file too: send it to me next time and I'll write episode 2.

If langwich could only write an HTML file (no PDF tools in this sandbox), hand over the `.html`
instead and say: "Open it in your browser and choose **Print → Save as PDF**."

End with one short line on what could come next: the next episode, the same story a level easier
or harder, another language, or a new story.

## Style

- One settings message, then one question at a time. At most four options, always with room for
  their own idea.
- Chat in their language; warm and plain, no hype, no technical words.
- From the first message to the PDF in two or three replies from them.
