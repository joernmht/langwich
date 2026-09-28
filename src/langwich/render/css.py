"""Print CSS for the worksheet: editorial, calm, black ink, e-paper first.

Two bundled SIL OFL families carry every Latin glyph on the page:

* **Literata** (serif) — target-language text: title, story, items, words;
* **Atkinson Hyperlegible Next** (sans) — instructions, furniture, numbers.

Atkinson has no arrow (→), so Literata is the second font in the sans stack
rather than a host font. Margin boxes name their font explicitly; otherwise
WeasyPrint picks a host default and a third typeface sneaks into the PDF.
Hyphenation uses "-" (Atkinson has no U+2010).

Pagination: a task header never ends a page (it stays with the first two
items); tasks that must be seen whole (match, order, label, draw, word box
beside the items) move as a unit, the others break between items. A page
that starts inside a task names it in the running header (named strings,
see :func:`header_css`). ``break-after: avoid`` is never put on an element
that can be a last child: WeasyPrint carries it up to the task and would
glue the task to whatever follows.
"""

from __future__ import annotations

from pathlib import Path

FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"

#: (family, weight, style, file)
FONT_FILES: tuple[tuple[str, int, str, str], ...] = (
    ("Literata", 400, "normal", "Literata-400.ttf"),
    ("Literata", 400, "italic", "Literata-400i.ttf"),
    ("Literata", 600, "normal", "Literata-600.ttf"),
    ("Literata", 600, "italic", "Literata-600i.ttf"),
    ("Literata", 700, "normal", "Literata-700.ttf"),
    ("Atkinson Hyperlegible Next", 400, "normal", "AtkinsonHyperlegibleNext-400.ttf"),
    ("Atkinson Hyperlegible Next", 400, "italic", "AtkinsonHyperlegibleNext-400i.ttf"),
    ("Atkinson Hyperlegible Next", 600, "normal", "AtkinsonHyperlegibleNext-600.ttf"),
    ("Atkinson Hyperlegible Next", 700, "normal", "AtkinsonHyperlegibleNext-700.ttf"),
)

SANS = '"Atkinson Hyperlegible Next"'

#: Content box widths in mm.
A4_CONTENT_W = 178.0
EPAPER_CONTENT_W = 141.8
MAIN_W = 120.0
GAP_W = 6.0
SIDE_W = 52.0
GUTTER_W = 9.0


def font_face_css() -> str:
    """``@font-face`` rules with absolute ``file://`` URIs to the bundled TTFs."""
    rules = []
    for family, weight, style, name in FONT_FILES:
        uri = (FONTS_DIR / name).resolve().as_uri()
        rules.append(
            f'@font-face {{ font-family: "{family}"; font-weight: {weight}; '
            f"font-style: {style}; src: url({uri}); }}"
        )
    return "\n".join(rules) + "\n"


BASE_CSS = r"""
/* ---- tokens ------------------------------------------------------------ */
:root {
  --serif: "Literata", serif;
  --sans: "Atkinson Hyperlegible Next", "Literata", sans-serif;
  --ink-2: #333; --ink-3: #595959; --hair: #8c8c8c;
  --main: 120mm; --gap: 6mm; --side: 52mm; --gut: 9mm; --pitch: 9mm;
}

@page {
  size: A4;
  margin: 18mm 12mm 15mm 20mm;
  @top-center { content: element(pageheader); width: 100%; vertical-align: bottom;
                padding-bottom: 2.4mm; }
  @bottom-left { content: "langwich"; font-family: "Atkinson Hyperlegible Next";
                 font-weight: 600; font-size: 7.5pt; color: #595959;
                 vertical-align: top; padding-top: 4mm; }
  @bottom-right { content: counter(page) " / " counter(pages);
                  font-family: "Atkinson Hyperlegible Next"; font-weight: 600;
                  font-size: 8pt; color: #000; vertical-align: top; padding-top: 4mm; }
}
* { margin: 0; padding: 0; box-sizing: border-box; }
html { font-family: var(--sans); font-size: 11pt; line-height: 1.35; color: #000;
       overflow-wrap: break-word; hyphenate-character: "-"; }
body { background: #fff; }
.tl { font-family: var(--serif); }
b, strong { font-weight: 700; }
.tl b, b.tl { font-weight: 600; }

/* ---- running header ---------------------------------------------------- */
.pageheader { position: running(pageheader); width: 100%;
  display: flex; justify-content: space-between; align-items: baseline;
  border-bottom: .5pt solid #000; padding-bottom: 1.6mm;
  font: 600 8pt var(--sans); letter-spacing: .02em; }
.pageheader .t { font: italic 400 8.5pt var(--serif); letter-spacing: 0; white-space: nowrap; }
/* Running header text: the title, or "Task 12 · … (continued)" on a page that
   starts inside a task. Both come from named strings (see header_css()). */
.pageheader .t::before { content: string(hd, start); }
.pageheader .c { font: 600 8pt var(--sans); letter-spacing: 0; white-space: nowrap; }
.pageheader .c::before { content: string(cont, start); }
.pageheader .r { white-space: nowrap; padding-left: 4mm; }
.pageheader .hl { white-space: nowrap; }

/* ---- small furniture --------------------------------------------------- */
.cap { display: block; font: 700 7.5pt var(--sans); letter-spacing: .1em;
  text-transform: uppercase; margin-bottom: 1.4mm; }
.box { border: .75pt solid #000; padding: 2.4mm 3mm 2.6mm; }
.muted { color: var(--ink-3); }

/* ---- phase captions: the lesson arc ------------------------------------ */
.phase { font: 700 8pt var(--sans); letter-spacing: .1em; text-transform: uppercase;
  display: flex; align-items: center; margin: 0 0 3.2mm; break-after: avoid; break-inside: avoid; }
.phase .step { display: inline-block; width: 4.4mm; height: 4.4mm; border: .75pt solid #000;
  border-radius: 2.2mm; text-align: center; font-size: 7pt; line-height: 3.9mm;
  letter-spacing: 0; margin-right: 2.4mm; }
.phase .rule { flex: 1; border-top: .5pt solid var(--hair); margin-left: 2.6mm; }

/* ---- cover ------------------------------------------------------------- */
.cover { display: grid; grid-template-columns: var(--main) var(--gap) var(--side);
  margin: 1.5mm 0 1mm; }
.cover > .lead { grid-column: 1; grid-row: 1; }
.cover > aside { grid-column: 3; grid-row: 1; }
.kicker { font: 700 8pt var(--sans); letter-spacing: .1em; text-transform: uppercase;
  margin-bottom: 2.6mm; }
h1 { font: 600 25pt/1.08 var(--serif); letter-spacing: -.01em; margin: 0 0 3.4mm; }
.standfirst { font: 400 11pt/1.42 var(--sans); }
.cast { margin-top: 5mm; border-top: .5pt solid var(--hair); padding-top: 2.2mm; }
.cast .who-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; column-gap: 5mm;
  row-gap: 2.4mm; }
.cast .who b { display: block; font: 600 10pt/1.3 var(--serif); }
.cast .who span { display: block; font: 400 8.5pt/1.35 var(--sans); color: var(--ink-2); }
.previously { margin-top: 5mm; border-left: 2.5pt solid #000; padding: .4mm 0 .6mm 3mm; }
.previously p { font: italic 400 10pt/1.45 var(--serif); }
.route { border-left: .5pt solid var(--hair); padding: .6mm 0 .4mm 2.6mm;
  font: 400 8.5pt/1.5 var(--sans); }
.route ol { list-style: none; }
.route li { padding-left: 5mm; text-indent: -5mm; break-inside: avoid; }
.route li .rn { display: inline-block; width: 5mm; text-indent: 0; font-weight: 700; }
.route li.read { font-weight: 700; }
.route li.read .sub { font-weight: 400; color: var(--ink-3); }

/* ---- scenes: one measured column + side notes -------------------------- */
section.scene { margin-top: 7mm; }
section.scene.first { margin-top: 5mm; }
.sh { display: grid; grid-template-columns: var(--gut) calc(var(--main) - var(--gut)) var(--gap) var(--side);
  margin-bottom: 2.6mm; break-after: avoid; break-inside: avoid; }
.sh .kick { grid-column: 2; grid-row: 1; font: 700 7.5pt var(--sans); letter-spacing: .1em;
  text-transform: uppercase; color: var(--ink-3); }
.sh h2 { grid-column: 2 / span 3; grid-row: 2; font: 600 15pt/1.2 var(--serif); margin-top: .6mm; }
.sh .sn { grid-column: 1; grid-row: 2; justify-self: start; align-self: start; margin-top: .9mm;
  width: 6.5mm; height: 6.5mm; border: 1pt solid #000; font: 700 10pt/6.1mm var(--sans);
  text-align: center; }
.para { display: grid; grid-template-columns: var(--gut) calc(var(--main) - var(--gut)) var(--gap) var(--side);
  margin-bottom: 3.2mm; }
.para.keep { break-inside: avoid; }
.para > .txt { grid-column: 2; grid-row: 1; }
.para > .side { grid-column: 4; grid-row: 1; }
.txt p { font: 400 11pt/1.45 var(--serif); hyphens: manual; text-align: start;
  orphans: 3; widows: 3; }
.g { text-decoration: underline; text-decoration-thickness: .6pt; text-underline-offset: 1.6pt; }
.gls { border-left: .5pt solid var(--hair); padding: .9mm 0 .3mm 2.6mm;
  font: 400 9pt/1.45 var(--sans); }
.gls div { break-inside: avoid; }
.gls b { font: 600 9pt var(--serif); }
.side > * + * { margin-top: 4mm; }
.notes-band { columns: 3; column-gap: 6mm; margin: 1mm 0 0 var(--gut); }
.notes-band.n1 { columns: auto; width: calc(var(--main) - var(--gut)); }
.notes-band.n2 { columns: 2; }
.notes-band > * { break-inside: avoid; margin-bottom: 4mm; }
.notes-band, .notes-wide { break-before: avoid; }
.notes-wide { margin: 1mm 0 0 var(--gut); }
.notes-wide > * + * { margin-top: 4mm; }
.scene-fig { margin-top: 2mm; }

/* fact and grammar sidebars */
.fact { border-top: 1.2pt solid #000; padding-top: 1.6mm; break-inside: avoid; }
.fact .ft { font: 600 9.5pt/1.35 var(--serif); margin-bottom: .6mm; }
.fact p { font: 400 9.5pt/1.45 var(--serif); }
.fact .fsrc { font: 400 7.5pt/1.3 var(--sans); color: var(--ink-3); margin-top: 1.2mm; }
.snippet { border-left: 2.5pt solid #000; padding: .4mm 0 .6mm 3mm;
  font: 400 9pt/1.4 var(--sans); break-inside: avoid; }
.snippet .nm { font-weight: 700; }
.snippet .rule { font: 600 9pt/1.35 var(--serif); margin-top: 1.4mm; }
.snippet table { border-collapse: collapse; margin-top: 1.6mm; width: 100%; }
.snippet th { font: 700 7pt/1.3 var(--sans); letter-spacing: .04em; text-align: left;
  border-bottom: .5pt solid #000; padding: 0 1.2mm .5mm 0; vertical-align: bottom; }
.snippet td { font: 400 8.5pt/1.25 var(--serif); padding: .4mm 1.2mm .4mm 0;
  border-bottom: .3pt solid var(--hair); vertical-align: top; }
.snippet td.src { font-family: var(--sans); }
.snippet table.wide td { font-size: 7.8pt; }
.snippet td.nw, .nw { white-space: nowrap; }
/* a table wider than its column: equal columns, words may break (never clipped) */
.snippet table.fixed { table-layout: fixed; }
.snippet table.fixed td, .snippet table.fixed th { overflow-wrap: anywhere; }
/* a grammar box too wide for the side column spans the full width */
.snippet.full > .gtext { max-width: 120mm; }
.snippet.full table { width: auto; max-width: 100%; }
.snippet .ex { font: italic 400 9.5pt/1.45 var(--serif); margin-top: 1.4mm; }
.snippet .ex div + div { margin-top: .6mm; }
.aside-stack > * + * { margin-top: 5mm; }

/* ---- tasks --------------------------------------------------------------
   A task moves to the next page as a whole, unless it is a "flow" task
   (no side column, nothing that must stay in view): those break between
   items, but the header always stays with the first two items (and a
   dialogue's last line never stands alone). */
section.task { break-inside: avoid; margin-top: 7mm; }
section.task.flow { break-inside: auto; }
section.unit.first-in-phase { margin-top: 7mm; }
.pair { break-inside: avoid; }
.pair > section.task + section.task { margin-top: 7mm; }
.th { display: grid; grid-template-columns: var(--gut) 1fr auto; align-items: baseline;
  border-top: 1.2pt solid #000; padding-top: 2.4mm; margin-bottom: 4mm;
  break-inside: avoid; break-after: avoid; }
.tn { grid-column: 1; grid-row: 1 / span 2; justify-self: start; align-self: start;
  width: 6.5mm; height: 6.5mm; background: #000; color: #fff;
  font: 700 10pt/6.5mm var(--sans); text-align: center; }
.th h3 { grid-column: 2; grid-row: 1; font: 700 13pt/1.25 var(--sans); }
.th .src { grid-column: 3; grid-row: 1; font: 600 8pt var(--sans); color: var(--ink-3);
  letter-spacing: .06em; text-transform: uppercase; padding-left: 4mm; white-space: nowrap; }
.th .ins { grid-column: 2; grid-row: 2; font: 400 11pt/1.35 var(--sans);
  margin-top: .8mm; max-width: 150mm; }
.th .ins .len { white-space: nowrap; }
.body { display: grid; grid-template-columns: var(--main) var(--gap) var(--side); }
.body > .main { grid-column: 1; grid-row: 1; }
.body > aside { grid-column: 3; grid-row: 1; }
.body.full > .main { grid-column: 1 / span 3; }
.pre { margin-bottom: 4mm; break-after: avoid; }
/* grammar and word boxes read before the items (e-paper; wide grammar on A4) */
.before { margin: 0 0 4mm var(--gut); break-after: avoid; }
.before > * { break-inside: avoid; }
.before > * + * { margin-top: 3mm; }
.before .wordbox .words { display: flex; flex-wrap: wrap; }
.before .wordbox .words li { margin-right: 5mm; }
.body > aside .fig.mini { margin-bottom: 4mm; }
/* (never on a last child: WeasyPrint carries a last child's break-after to
   its task, which would glue the task to whatever follows) */
.items > .it:first-child:not(:last-child), .wb > .wbi:first-child:not(:last-child),
.dlg > .dl:first-child:not(:last-child), .dlg > .dl:nth-last-child(2) { break-after: avoid; }
/* chosen by the layout check when the page before would stay half empty */
section.task.loose .before, section.task.loose .items > .it:first-child { break-after: auto; }

/* numbered items with one hanging edge */
.items > .it { display: grid; grid-template-columns: var(--gut) 1fr; break-inside: avoid; }
.items > .it + .it { margin-top: 2.6mm; }
.it > .n { grid-column: 1; grid-row: 1; font: 700 11pt/1.45 var(--sans); }
.it > .c { grid-column: 2; grid-row: 1; font: 400 11pt/1.45 var(--serif); }
.it .q { font: 400 11pt/1.45 var(--serif); }
.gapped > .it > .n, .gapped > .it > .c { line-height: 7.6mm; }
.gapped > .it + .it { margin-top: .8mm; }
.blank { display: inline-block; border-bottom: .8pt solid #000; padding-top: 0;
  line-height: 1.12; vertical-align: baseline; margin: 0 .8mm; text-align: left; }
.blank .fl { font: 400 11pt var(--serif); padding-left: .8mm; }
.gap { white-space: nowrap; }
.gap.el .blank { margin-left: 0; }          /* after l', d', qu' … */
.gap.el .blank .fl { padding-left: 0; }
.gap.pu .blank { margin-right: 0; }         /* punctuation follows */
.gn { font: 700 7.5pt var(--sans); color: var(--ink-3); margin-left: .6mm; }
.hint { font: italic 400 9.5pt var(--sans); color: var(--ink-2); white-space: nowrap; }
.passage p { font: 400 11pt/8mm var(--serif); hyphens: manual; padding-left: var(--gut); }
.passage p + p { margin-top: 2mm; }

/* writing space: solid lines, handwriting pitch */
.lines > div { height: var(--pitch); border-bottom: .6pt solid var(--ink-3); break-inside: avoid; }
/* a writing space may continue on the next page, but never without its
   first lines here and never with fewer than three lines there */
.lines > div:nth-child(-n+3):not(:last-child),
.lines > div:nth-last-child(-n+3):not(:last-child) { break-after: avoid; }
.lines > div.starter { font: italic 400 11pt var(--serif); display: flex; align-items: flex-end;
  padding-bottom: 1.2mm; }
.it .lines { margin-top: -1mm; }
.wl { display: grid; grid-template-columns: auto 1fr; align-items: end; height: var(--pitch); }
.wl .cue { font: italic 400 9.5pt var(--sans); color: var(--ink-2); padding-right: 2.4mm;
  padding-bottom: 1mm; }
.wl .line, .fld .line { border-bottom: .6pt solid var(--ink-3); height: 6mm; }

/* word boxes */
.wordbox { break-inside: avoid; }
.wordbox .words { list-style: none; font: 400 11pt/6.2mm var(--serif); }
.wordbox .cnt { font: 700 8.5pt var(--sans); margin-left: 1mm; }
.wordbox.row .words { display: flex; flex-wrap: wrap; }
.wordbox.row .words li { margin-right: 6mm; }
.wordbox.row { display: flex; align-items: baseline; }
.wordbox.row .cap { margin: 0 4mm 0 0; white-space: nowrap; }
.usewords { margin: 0 0 3mm; font: 400 11pt/7mm var(--serif); break-inside: avoid; }
.usewords .cap { display: inline; margin: 0 3mm 0 0; }
.usewords span.w { margin-right: 5mm; white-space: nowrap; }
.usewords .tick { display: inline-block; width: 3.4mm; height: 3.4mm; border: .6pt solid #000;
  margin-right: 1.4mm; vertical-align: -.3mm; }
.prompt { font: 400 11pt/1.4 var(--sans); margin-bottom: 3mm; break-after: avoid; }
.usewords, .search { break-after: avoid; }
.writing, .k-draw .main, .k-label .main { padding-left: var(--gut); }

/* matching */
table.match { border-collapse: collapse; width: 100%; }
table.match td { height: 8.2mm; border-bottom: .5pt solid var(--hair); vertical-align: middle;
  padding-right: 2mm; }
table.match tr:first-child td { border-top: .5pt solid var(--hair); }
table.match td.n { width: var(--gut); font: 700 11pt var(--sans); }
table.match td.term { font: 400 11pt/1.3 var(--serif); }
table.match td.term.src { font-family: var(--sans); }
table.match td.bx { width: 14mm; }
table.match td.bx span { display: block; width: 8mm; height: 6.2mm; border: .75pt solid #000; }
table.match td.l { width: 7mm; font: 700 11pt var(--sans); }
table.match td.opt { font: 400 11pt/1.3 var(--sans); }
table.match td.opt.tl { font-family: var(--serif); }

/* true / false */
.tf > .it { grid-template-columns: var(--gut) 1fr auto; }
.tf .cks { grid-column: 3; grid-row: 1; padding-left: 5mm; white-space: nowrap;
  font: 400 9pt/1.45 var(--sans); padding-top: .5mm; }
.tf .ck { display: inline-block; margin-left: 3.5mm; }
.bxs { display: inline-block; width: 4.4mm; height: 4.4mm; border: .75pt solid #000;
  vertical-align: -1.1mm; margin-right: 1.4mm; }
.tf .corr { grid-column: 2 / span 2; grid-row: 2; height: 7.6mm;
  border-bottom: .6pt solid var(--ink-3); }

/* multiple choice */
.opts { margin-top: 1.4mm; }
.opts.row { display: grid; column-gap: 5mm; }
.opts.col > .op + .op { margin-top: 1.2mm; }
.op { padding-left: 10.4mm; text-indent: -10.4mm; font: 400 11pt/1.4 var(--serif); }
.op .bxs { text-indent: 0; margin-right: 1.6mm; }
.op .lt { display: inline-block; width: 4.4mm; text-indent: 0; font: 700 9.5pt var(--sans); }

/* order events */
.events > .ev { display: grid; grid-template-columns: 13mm 1fr; align-items: center;
  min-height: 8.2mm; border-bottom: .5pt solid var(--hair); break-inside: avoid; }
.events > .ev:first-child { border-top: .5pt solid var(--hair); }
.events .ev .bx { grid-column: 1; justify-self: start; width: 8mm; height: 6.2mm;
  border: .75pt solid #000; }
.events .ev .tl { grid-column: 2; padding: 1mm 0; font: 400 11pt/1.35 var(--serif); }

/* word building */
.wbi { display: grid; align-items: end; height: var(--pitch); break-inside: avoid; }
.wbi > span { grid-row: 1; padding-bottom: 1.3mm; white-space: nowrap; }
.wbi .n { font: 700 11pt var(--sans); }
.wbi .pt { font: 400 11pt var(--serif); }
.wbi .op { text-align: center; font: 400 11pt var(--sans); }
.wbi .ln { border-bottom: .8pt solid #000; height: 7mm; padding: 0; }

/* dialogue */
.dlg > .dl { display: grid; column-gap: 0; break-inside: avoid; }
.dl > .dn { grid-column: 1; grid-row: 1; font: 700 11pt/7.6mm var(--sans); }
.dl > .sp { grid-column: 2; grid-row: 1; font: 700 10pt/7.6mm var(--sans); padding-right: 3mm;
  overflow-wrap: normal; }
.dl > .dt { grid-column: 3; grid-row: 1; font: 400 11pt/7.6mm var(--serif); }
.dl > .dt .cue { font: italic 400 9.5pt/1.3 var(--sans); color: var(--ink-2); display: block;
  padding-top: 1.6mm; }
.dl > .dt .line { border-bottom: .6pt solid var(--ink-3); height: 7mm; }

/* media search */
.search { display: flex; align-items: baseline; border: .75pt solid #000;
  padding: 2.4mm 3.5mm; margin-bottom: 3.6mm; break-inside: avoid; }
.search .cap { margin: 0 4mm 0 0; white-space: nowrap; }
.search .q { font: 400 11pt/1.4 var(--serif); }
.search .q .sep { color: var(--ink-3); padding: 0 2.4mm; font-family: var(--sans); }
.ms .it .c { font-family: var(--sans); }
.ms .it .c .q { font: 400 11pt/1.45 var(--sans); }

/* draw */
.frame { border: .75pt solid #000; height: 90mm; }
.draw-words { margin-top: 3mm; }

/* ---- kind: scramble ---- */

/* ---- kind: classify ---- */

/* ---- kind: true_false+ ---- */

/* ---- kind: writing+ ---- */
/* who the text is for and its register; the text to answer, in a box as wide
   as the story column; the points to cover as a tick list; with "paragraphs",
   one numbered block of lines per point (the number in the gutter) */
.writing .wmeta { font: 400 10pt/1.4 var(--sans); margin: -1.2mm 0 3mm; break-after: avoid; }
.writing .wmeta .cap { display: inline; margin: 0 2mm 0 0; }
.writing .wmeta .reg { display: inline-block; margin-left: 3.5mm; padding: .3mm 1.4mm .2mm;
  border: .6pt solid #000; font: 700 7.5pt/1.3 var(--sans); letter-spacing: .1em;
  text-transform: uppercase; vertical-align: .3mm; }
.writing .wmeta .reg:first-child { margin-left: 0; }
.writing .input { max-width: calc(var(--main) - var(--gut)); margin: 0 0 3.6mm;
  break-inside: avoid; }
.writing .input p { font: 400 10.5pt/1.45 var(--serif); }
.writing .input.src p { font-family: var(--sans); }
.writing .input p + p { margin-top: 1.8mm; }
.writing .points { display: flex; align-items: baseline; margin: 0 0 3mm; break-inside: avoid;
  break-after: avoid; }
.writing .points .cap { margin: 0 3mm 0 0; white-space: nowrap; }
.writing .points ul { list-style: none; font: 400 11pt/1.45 var(--sans); }
.writing .points li { padding-left: 5mm; text-indent: -5mm; }
.writing .points li + li { margin-top: .6mm; }
.writing .points .tick { display: inline-block; width: 3.4mm; height: 3.4mm;
  border: .6pt solid #000; margin-right: 1.6mm; vertical-align: -.3mm; text-indent: 0; }
.writing .pn { font: 700 9pt var(--sans); color: var(--ink-3); text-indent: 0; }
.writing .points .pn { display: inline-block; min-width: 3.6mm; }
.writing .numbered + .numbered { margin-top: 3.6mm; }
.writing .numbered > div:first-child { position: relative; }
.writing .numbered .pn { position: absolute; left: calc(0mm - var(--gut)); bottom: 1.2mm; }
.writing .lines > div.starter.src { font-family: var(--sans); }
.solutions .sb .model.src { font-family: var(--sans); }
.solutions .sb .pts { list-style: none; margin-top: 1mm; }
.solutions .sb .pts li { padding-left: 3.6mm; text-indent: -3.6mm; }
.solutions .sb .pts li::before { content: "–"; display: inline-block; width: 3.6mm;
  text-indent: 0; }
.solutions .sb .pts li + li { margin-top: .5mm; }

/* ---- kind: cloze choice ---- */

/* ---- kind: table ---- */

/* ---- kind: gapped_text ---- */

/* ---- kind: find_in_text ---- */

/* ---- kind: proofread ---- */

/* ---- kind: transform+ ---- */

/* ---- kind: questions+ media_search+ ---- */

/* ---- kind: crossword ---- */

/* pictures */
.fig { break-inside: avoid; }
.pic { position: relative; border: 1pt solid #000; box-sizing: content-box;
  margin: 0 auto; }
.pic img { display: block; }
/* numbered markers: a white ring keeps them visible on dark parts of a photo */
.mk { position: absolute; width: 6mm; height: 6mm; border-radius: 50%; background: #000;
  border: .35mm solid #fff; box-sizing: content-box;
  color: #fff; font: 700 8.5pt/6mm var(--sans); text-align: center; }
.fig.mini .mk { width: 5mm; height: 5mm; font: 700 8.5pt/5mm var(--sans); }
.figcap { font: 400 7.5pt/1.35 var(--sans); color: var(--ink-3); margin: 1.4mm 0 0; }
.figcap .tl { font-style: italic; font-size: 8pt; color: #000; }
.name-grid { display: grid; grid-template-columns: 1fr 1fr 1fr; column-gap: 7mm; margin-top: 3mm; }
.fld { display: grid; grid-template-columns: var(--gut) 1fr; align-items: end;
  height: var(--pitch); font: 700 11pt var(--sans); }
.label-bank { margin-top: 3.4mm; }

/* series teaser */
.teaser { margin-top: 9mm; border: .75pt solid #000; padding: 3mm 3.6mm 3.4mm;
  break-inside: avoid; }
.teaser .ep { font: 600 8pt var(--sans); color: var(--ink-3); margin-bottom: 1mm; }
.teaser p { font: italic 400 11pt/1.45 var(--serif); }

/* ---- back matter -------------------------------------------------------- */
section.back { margin-top: 11mm; border-top: 1.2pt solid #000; padding-top: 3mm; }
section.back.newpage { break-before: page; margin-top: 0; border-top: 0; padding-top: 0; }
h2.big { font: 600 18pt/1.1 var(--serif); margin-bottom: 2.4mm; break-after: avoid; }
.lede { font: 400 9.5pt var(--sans); color: var(--ink-2); margin-bottom: 4.5mm; }
.vocab-list { columns: 2; column-gap: 10mm; }
.vocab-list h3 { font: 700 7.5pt var(--sans); letter-spacing: .1em; text-transform: uppercase;
  border-bottom: .5pt solid #000; padding-bottom: .8mm; margin: 0 0 1mm; break-after: avoid; }
.vocab-list h3.later { margin-top: 4mm; }
/* one row per word: term (+ gender, plural, forms) | translation (+ note) */
.vl { display: grid; grid-template-columns: 40mm 1fr; column-gap: 2mm; break-inside: avoid;
  padding: .8mm 0 .7mm; border-bottom: .4pt solid var(--hair); }
.vl .de { grid-column: 1; grid-row: 1; font: 400 9.5pt/1.35 var(--serif);
  hyphens: auto; hyphenate-limit-chars: 7 4 4; }
.vl .de.key { font-weight: 600; }
.vl .de i { font-style: normal; font-weight: 400; color: var(--ink-3); }
.vl .de .gd { font-style: italic; font-weight: 400; color: var(--ink-3); }
.vl .de .forms { display: block; font: italic 400 8pt/1.3 var(--serif); color: var(--ink-3); }
/* (padding-top: the sans face sits higher than Literata; aligns the baselines) */
.vl .en { grid-column: 2; grid-row: 1; font: 400 9pt/1.35 var(--sans); hyphens: auto;
  hyphenate-limit-chars: 7 4 4; padding-top: .52mm; }
.vocab-list.compact .vl { padding: .35mm 0 .3mm; }
.vocab-list.compact .vl .de { font-size: 9pt; line-height: 1.28; }
.vocab-list.compact .vl .en { font-size: 8.5pt; line-height: 1.28; padding-top: .49mm; }
.vocab-list.compact h3.later { margin-top: 2.6mm; }
.vocab-list.compact2 .vl { padding: .15mm 0 .1mm; }
.vocab-list.compact2 .vl .de, .vocab-list.compact2 .vl .en { font-size: 8.5pt; line-height: 1.2; }
.vocab-list.compact2 .vl .en { padding-top: .3mm; }
.vocab-list.compact2 .vl .de .forms { font-size: 8pt; line-height: 1.15; }
.vocab-list.compact2 h3.later { margin-top: 2mm; }
.ref-grammar { columns: 2; column-gap: 10mm; }
.ref-grammar .snippet { margin-bottom: 5mm; }
.ref-wide > .snippet + .snippet { margin-top: 5mm; }
.ref-grammar + .ref-wide { margin-top: 1mm; }
.loose-facts { columns: 2; column-gap: 10mm; }
.loose-facts .fact { margin-bottom: 4mm; }
.sol-head { border-top: 1.2pt solid #000; padding-top: 2.4mm; margin-bottom: 3mm;
  font: 700 13pt var(--sans); }
.solutions { columns: 3; column-gap: 7mm; font: 400 9pt/1.5 var(--sans); }
.solutions.cols { columns: auto; display: grid; grid-template-columns: repeat(3, 1fr);
  column-gap: 7mm; }
.solutions .sb { break-inside: avoid; margin-bottom: 3.4mm; }
.solutions .sb .st { display: block; font: 700 8.5pt/1.35 var(--sans); margin-bottom: .6mm; }
.solutions .sb .tn2 { display: inline-block; width: 4.2mm; height: 4.2mm; background: #000;
  color: #fff; text-align: center; font: 700 7.5pt/4.2mm var(--sans); margin-right: 1.6mm; }
.solutions .sb .k { font-family: var(--serif); }
.solutions .sb .kn { font-weight: 700; }
.solutions .sb .ke { white-space: nowrap; }
.solutions .sb .model { font: italic 400 9pt/1.45 var(--serif); }
.solutions .sb ol { list-style: none; }
.solutions .sb ol li { padding-left: 3.6mm; text-indent: -3.6mm; }
.solutions .sb ol li + li { margin-top: .5mm; }
.translations { columns: 2; column-gap: 10mm; }
.translations .tr { break-inside: avoid-column; margin-bottom: 4mm; }
.translations h4 { font: 600 9.5pt/1.3 var(--serif); margin-bottom: 1mm; break-after: avoid; }
.translations h4 .num { font: 700 8pt var(--sans); margin-right: 1.6mm; }
.translations p { font: 400 9pt/1.45 var(--sans); }
.translations p + p { margin-top: 1.6mm; }
.solhead { margin: 1.5mm 0 5mm; }
.solhead .standfirst i { font-family: var(--serif); }

/* ---- one task per page ------------------------------------------------- */
.otp section.unit { break-before: page; margin-top: 0; }
.otp section.back.words-sec { break-before: page; margin-top: 0; border-top: 0; padding-top: 0; }
"""


EPAPER_CSS = r"""
/* ---- e-paper: 157.8 x 210.4 mm (3:4), one column, notes below ---------- */
/* Readable on a 6"-10" screen: nothing below 8.5 pt, secondary text #444. */
:root { --main: 141.8mm; --side: 141.8mm; --gap: 0mm; --ink-3: #444; }
@page { size: 157.8mm 210.4mm; margin: 10mm 8mm 10mm 8mm; }
@page { @top-center { padding-bottom: 2mm; }
        @bottom-left { padding-top: 3mm; font-size: 8.5pt; color: #444; }
        @bottom-right { padding-top: 3mm; font-size: 8.5pt; } }
.pageheader { font-size: 8.5pt; }
.pageheader .t { font-size: 9pt; }
.pageheader .c { font-size: 8.5pt; }
.cap, .kicker, .sh .kick, .th .src, .vocab-list h3, .teaser .ep { font-size: 8.5pt; }
.phase { font-size: 8.5pt; }
.phase .step { width: 5.2mm; height: 5.2mm; border-radius: 2.6mm; font-size: 8.5pt;
  line-height: 4.7mm; }
.fact .fsrc, .figcap, .translations h4 .num { font-size: 8.5pt; }
.figcap .tl { font-size: 9pt; }
.snippet th { font-size: 8.5pt; }
.snippet td { font-size: 9pt; }
.gn { font-size: 8.5pt; color: #333; }
.vl .de i, .vl .de .gd { color: #333; }
.vl .de .forms, .vocab-list.compact2 .vl .de .forms { font-size: 8.5pt; color: #333; }
.solutions .sb .tn2 { width: 4.8mm; height: 4.8mm; font-size: 8.5pt; line-height: 4.8mm; }
.cover, .body { display: block; }
.cover > aside { margin-top: 5mm; }
.route { border: .75pt solid #000; padding: 2.4mm 3mm 2.4mm; }
.route ol { columns: 2; column-gap: 6mm; }
.cast .who-grid { grid-template-columns: 1fr 1fr; }
.sh { grid-template-columns: var(--gut) 1fr; }
.sh h2 { grid-column: 2; }
.para { display: block; margin-bottom: 3.6mm; }
.para > .txt { padding-left: var(--gut); }
.para > .side { margin: 1.6mm 0 0 var(--gut); break-before: avoid; }
.gls { border-left: 0; border-top: .5pt solid var(--hair); padding: 1mm 0 0; }
.gls div { display: inline-block; margin-right: 4mm; }
.side .fact, .side .snippet, .before .snippet, .before .fact, .notes-wide .snippet {
  border: .75pt solid #000; padding: 2.2mm 3mm 2.4mm; }
.before .fig.mini { margin-bottom: 1mm; }
.snippet.full > .gtext { max-width: none; }
.th .ins { max-width: none; }
.name-grid { grid-template-columns: 1fr 1fr; }
.frame { height: 80mm; }
.vocab-list { column-gap: 6mm; }
.vl { grid-template-columns: 34mm 1fr; }
.ref-grammar, .loose-facts, .translations { columns: 1; }
.solutions { columns: 2; column-gap: 6mm; }
.solutions.cols { grid-template-columns: repeat(2, 1fr); column-gap: 6mm; }

/* ---- kind: scramble ---- */

/* ---- kind: classify ---- */

/* ---- kind: true_false+ ---- */

/* ---- kind: writing+ ---- */
.writing .wmeta .reg { font-size: 8.5pt; }

/* ---- kind: cloze choice ---- */

/* ---- kind: table ---- */

/* ---- kind: gapped_text ---- */

/* ---- kind: find_in_text ---- */

/* ---- kind: proofread ---- */

/* ---- kind: transform+ ---- */

/* ---- kind: questions+ media_search+ ---- */

/* ---- kind: crossword ---- */

"""


def stylesheet(page: str) -> str:
    """The layout CSS (without ``@font-face``) for ``page`` = ``a4`` | ``epaper``."""
    return BASE_CSS + (EPAPER_CSS if page == "epaper" else "")


def css_string(text: str) -> str:
    """``text`` as a quoted CSS string (safe inside a ``<style>`` element)."""
    out = []
    for ch in text:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch in "\n\r\f" or ch == "<" or ord(ch) < 0x20:
            out.append(f"\\{ord(ch):x} ")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def header_css(title: str) -> str:
    """Named strings for the running header.

    Every element that starts something new on a page (cover, phase caption,
    task header, scene header, back-matter section) resets the header to the
    worksheet ``title``; the body of a task switches it to the task's
    "continued" label (``data-cont``). ``string(…, start)`` then shows the
    label only on pages that begin inside a task.
    """
    reset = f"string-set: hd {css_string(title)}, cont \"\";"
    return (
        f".cover, .solhead, .phase, .th, .sh, section.back, .teaser {{ {reset} }}\n"
        '.pre[data-cont], .before[data-cont], .body[data-cont] '
        '{ string-set: hd "", cont attr(data-cont); }\n'
    )
