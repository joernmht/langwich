"""Build the worksheet HTML from a ``langwich/3`` worksheet.

The builder walks the lesson arc from :func:`langwich.plan.plan` — cover,
"before you read", scene by scene with the tasks anchored to each scene,
"your turn", "take it further", the series teaser — and appends the back
matter (word list, reference grammar) and the answer section (solutions,
translations). Every random choice comes from the plan, so the task page and
the answer key always agree, and the same worksheet and seed give the same
HTML byte for byte.

Page furniture comes from :mod:`langwich.locale` in the learner's (source)
language, with the worksheet's ``ui`` overrides.

Layout decisions CSS cannot make are taken here, from text measurements
(:mod:`langwich.render.metrics`): whether a grammar table fits the 52 mm side
column (else it spans the page above the items), whether a label task and
the picture task after it fit on one page (else the later task gets a small
copy of the picture), how the answer key splits into balanced columns.
``render_worksheet`` checks these guesses on WeasyPrint's pages and builds
again with :class:`~langwich.render.options.LayoutHints` where they were wrong.
"""

from __future__ import annotations

import html as _html
import math
import re
import unicodedata
from typing import Literal

from langwich import locale
from langwich.answers import KeyRun, answer_key_runs, key_text, quoted_passage
from langwich.images import PreparedPicture, prepare_picture
from langwich.model import (
    POS_VALUES,
    ClozeTask,
    Fact,
    GrammarPoint,
    GrammarTable,
    LabelTask,
    MultipleChoiceTask,
    OrderEventsTask,
    QuestionsTask,
    Scene,
    TransformTask,
    TrueFalseTask,
    VocabItem,
    Worksheet,
    WritingTask,
)
from langwich.plan import Gloss, PlannedTask, SceneBlock, Sidebar, plan, strip_article, term_pattern
from langwich.render import metrics
from langwich.render.css import (
    A4_CONTENT_W,
    EPAPER_CONTENT_W,
    GUTTER_W,
    MAIN_W,
    SIDE_W,
    header_css,
    stylesheet,
)
from langwich.render.options import LayoutHints, RenderOptions

Part = Literal["worksheet", "solutions", "all"]

#: Placeholder in the ``<style>`` element where the ``@font-face`` rules go.
FONT_MARKER = "/*@font-face*/"

#: Largest picture height in mm (so the numbered answer grid fits below it).
MAX_PICTURE_H = {"a4": 118.0, "epaper": 92.0}
#: Largest height of a raster photo on A4 (line art may use MAX_PICTURE_H):
#: a 4:3 phone photo at full width would leave most of a page empty.
MAX_PHOTO_H = {"a4": 100.0, "epaper": 92.0}
#: Width of the small copy of a picture shown with a later picture task.
MINI_PICTURE_W = {"a4": SIDE_W, "epaper": 70.0}
MINI_PICTURE_H = 60.0

#: Height of the page content box in mm.
PAGE_CONTENT_H = {"a4": 297.0 - 18.0 - 15.0, "epaper": 210.4 - 20.0}

#: Marker radius and the width of its white ring, in mm.
MARK_R = 3.0
MINI_MARK_R = 2.5
MARK_RING = 0.35

#: How far (mm) the side column of a scene's last paragraph may outgrow the
#: text before further sidebars move into a band below the scene.
BAND_SLACK = 30.0

#: Paragraph rows (text + side notes) up to this height never split across pages.
KEEP_ROW_MM = 90.0

#: Grammar-table cells wrapped to more lines than this in the side column
#: move the grammar box to a full-width block.
MAX_CELL_LINES = 3

_TRANSLATE = str.maketrans({"\u202f": "\u00a0", "\u2011": "-"})

#: A gender note that belongs right after the headword: "m", "f.", "n", "m/f", "f pl" …
_GENDER_NOTE = re.compile(r"^[mfn]\.?(?:\s*/\s*[mfn]\.?)?(?:\s*pl\.?)?$", re.IGNORECASE)
#: A note that starts with a gender marker ("m.: le bénévole") describes the headword.
_GENDER_LEAD = re.compile(r"^[mfn]\.?\s*[:;]", re.IGNORECASE)

#: Tokens whose hyphen must not end a line: suffixes (-ie, -eur), open
#: compounds (Erasmus-) and hyphenated words (Croix-Rousse, tire-bouchon).
_HYPHEN_TOKEN = re.compile(r"(?<![\w-])(?:-\w+(?:-\w+)*|\w+(?:-\w+)+-?|\w+-)(?![\w-])")

#: Closing punctuation that belongs to the word (or blank) before it.
_TRAILING_PUNCT = re.compile(r"^(?:[.,;:!?…»”“\"'’)\]]+|\s[?!;:»](?:[.,;:!?…»”“\"'’)\]]*))")

_WORD = re.compile(r"\w+")

#: Letters (beyond a–z) that a language uses: a word with one of them that
#: the other language of the worksheet lacks is probably in this language.
_LETTERS = {
    "de": "äöüß", "fr": "àâæçéèêëîïôœùûÿ", "es": "áéíñóúü", "it": "àèéìíîòóù",
    "pt": "áâãàçéêíóôõú", "nl": "ëï", "pl": "ąćęłńóśźż", "cs": "áčďéěíňóřšťúůýž",
    "sv": "åäö", "da": "æøå", "no": "æøå", "fi": "äö", "tr": "çğıöşü", "ca": "àçèéíïòóúü",
}


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def esc(text: str | None) -> str:
    """HTML-escape user text (quotes included). Characters the bundled fonts
    lack are mapped to close equivalents so no host font is pulled in."""
    return _html.escape((text or "").translate(_TRANSLATE), quote=True)


def esc_br(text: str | None) -> str:
    return esc(text).replace("\n", "<br>")


def esc_nw(text: str | None) -> str:
    """:func:`esc`, with suffixes and hyphenated words kept on one line.

    The fonts have no non-breaking hyphen (U+2011), so a hyphenated token is
    wrapped in ``<span class="nw">`` instead: 'Nomen auf -ie' never breaks
    into 'Nomen auf -' / 'ie', 'Croix-Rousse' never into 'Croix-' / 'Rousse'.
    """
    text = text or ""
    out: list[str] = []
    pos = 0
    for m in _HYPHEN_TOKEN.finditer(text):
        out.append(esc(text[pos:m.start()]))
        out.append(f'<span class="nw">{esc(m.group(0))}</span>')
        pos = m.end()
    out.append(esc(text[pos:]))
    return "".join(out)


def trailing_punctuation(text: str) -> str:
    """The closing punctuation at the start of ``text`` (with a French space
    before ? ! ; : »), which belongs with the blank before it."""
    m = _TRAILING_PUNCT.match(text)
    return m.group(0) if m else ""


def comment_safe(text: str) -> str:
    """Text that can sit inside an HTML comment."""
    return text.replace("--", "–").replace("<", "‹").replace(">", "›")


def paragraphs(text: str) -> list[str]:
    """The paragraphs of ``text`` (split at blank lines), stripped, without
    empty ones."""
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Offsets of the paragraphs of ``text``, matching :attr:`Scene.paragraphs`."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for chunk in text.split("\n\n"):
        start, end = pos, pos + len(chunk)
        pos = end + 2
        lead = len(chunk) - len(chunk.lstrip())
        trail = len(chunk) - len(chunk.rstrip())
        if start + lead < end - trail:
            spans.append((start + lead, end - trail))
    return spans


def number_ranges(numbers: list[int]) -> str:
    """``[1, 2, 3, 5]`` → ``"1–3, 5"``."""
    nums = sorted(set(numbers))
    out: list[str] = []
    i = 0
    while i < len(nums):
        j = i
        while j + 1 < len(nums) and nums[j + 1] == nums[j] + 1:
            j += 1
        out.append(str(nums[i]) if j == i else f"{nums[i]}–{nums[j]}")
        i = j + 1
    return ", ".join(out)


def sort_key(term: str, lang: str | None = None) -> str:
    base = unicodedata.normalize("NFKD", strip_article(term, lang).casefold())
    return "".join(ch for ch in base if not unicodedata.combining(ch))


def with_article_nbsp(term: str, lang: str | None) -> str:
    """'die Espressomaschine' → 'die\u00a0Espressomaschine': a line may not
    break between an article and its noun (l' and un' are glued already)."""
    rest = strip_article(term, lang)
    if rest == term.strip() or not term.endswith(rest):
        return term
    article = term[: len(term) - len(rest)]
    if not article.endswith(" "):
        return term
    return article.rstrip() + "\u00a0" + rest


def balanced_split(heights: list[float], cols: int) -> list[tuple[int, int]]:
    """Split ``heights`` (in order) into ``cols`` runs with the smallest
    tallest run; returns ``(start, end)`` index pairs (runs may be empty)."""
    n = len(heights)
    prefix = [0.0]
    for h in heights:
        prefix.append(prefix[-1] + h)
    best: tuple[float, list[tuple[int, int]]] = (float("inf"), [])

    def search(start: int, left: int, runs: list[tuple[int, int]], tallest: float) -> None:
        nonlocal best
        if tallest >= best[0]:
            return
        if left == 1:
            total = max(tallest, prefix[n] - prefix[start])
            if total < best[0]:
                best = (total, runs + [(start, n)])
            return
        for end in range(n, start - 1, -1):  # (ties: fill the first columns)
            search(end, left - 1, runs + [(start, end)], max(tallest, prefix[end] - prefix[start]))

    search(0, max(cols, 1), [], 0.0)
    return best[1]


def is_gender_note(note: str | None) -> bool:
    return bool(note and _GENDER_NOTE.match(note.strip()))


_UMLAUT = {"a": "ä", "o": "ö", "u": "ü", "A": "Ä", "O": "Ö", "U": "Ü"}


def _umlauted(word: str) -> str | None:
    for i in range(len(word) - 1, -1, -1):
        ch = word[i]
        if ch in _UMLAUT:
            if ch in "uU" and i > 0 and word[i - 1] in "aA":  # Haus → Häus
                return word[: i - 1] + _UMLAUT[word[i - 1]] + word[i:]
            return word[:i] + _UMLAUT[ch] + word[i + 1:]
    return None


def plural_note(item: VocabItem, target_lang: str) -> str | None:
    """Dictionary-style plural: German ``-n``, ``¨-e``, ``-``; other
    languages print the plural as given."""
    if not item.plural:
        return None
    sing, plural = strip_article(item.term, target_lang), strip_article(item.plural, target_lang)
    if locale.base_lang(target_lang) != "de":
        regular = plural.casefold() in (sing.casefold() + "s", sing.casefold() + "es")
        return None if regular else item.plural
    if plural == sing:
        return "-"
    if plural.startswith(sing):
        return "-" + plural[len(sing):]
    uml = _umlauted(sing)
    if uml and plural == uml:
        return "¨"
    if uml and plural.startswith(uml):
        return "¨-" + plural[len(uml):]
    return item.plural


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


class Builder:
    """One HTML build: holds the plan, the options, collected warnings and
    the per-render picture cache."""

    def __init__(
        self,
        ws: Worksheet,
        options: RenderOptions | None = None,
        pictures: dict[str, PreparedPicture | None] | None = None,
        hints: LayoutHints | None = None,
    ):
        self.ws = ws
        self.opts = options or RenderOptions()
        self.hints = hints or LayoutHints()
        self.plan = plan(ws, self.opts.seed)
        self.epaper = self.opts.page == "epaper"
        self.page = "epaper" if self.epaper else "a4"
        self.content_w = EPAPER_CONTENT_W if self.epaper else A4_CONTENT_W
        self.src = ws.source_lang
        self.tgt = ws.target_lang
        self.src_dir = locale.direction(self.src)
        self.tgt_dir = locale.direction(self.tgt)
        self.warnings: list[str] = []
        self.image_prompts: list[tuple[str, str]] = []
        #: per-render picture cache (scene id → prepared picture), may be shared
        self._pictures: dict[str, PreparedPicture | None] = {} if pictures is None else pictures
        self.scene_numbers = {b.scene.id: b.number for b in self.plan.scenes}
        self._vocab_terms = {strip_article(v.term, ws.target_lang).casefold() for v in ws.vocabulary.items}
        self._vocab_translations: set[str] = set()
        for v in ws.vocabulary.items:
            self._vocab_translations.add(v.translation.casefold())
            self._vocab_translations.update(
                p.strip().casefold() for p in re.split(r"[,;/]", v.translation) if p.strip()
            )
        self._lex_tgt, self._lex_src = self._lexicons()
        self.picture_host = self._picture_hosts()
        #: label task number → number of the picture task kept on its page
        self.pairs: dict[int, int] = {}
        #: task number → scenes whose picture it shows as a small copy
        self.mini: dict[int, list[str]] = {}
        self._pair_pictures()

    # -- language ------------------------------------------------------------

    def t(self, key: str, **fmt: object) -> str:
        try:
            return locale.t(key, self.src, self.ws.ui, **fmt)
        except (KeyError, IndexError, ValueError):
            # a ui override with stray {braces}: fall back to the built-in string
            self.warn(f"ui string {key!r} could not be formatted; the built-in text is used.")
            return locale.t(key, self.src, None, **fmt)

    def warn(self, message: str) -> None:
        if message not in self.warnings:
            self.warnings.append(message)

    def lang_attr(self) -> str:
        """``lang`` (and ``dir`` when it differs from the page) for target text."""
        attr = f' lang="{esc(self.tgt)}"'
        if self.tgt_dir != self.src_dir:
            attr += f' dir="{self.tgt_dir}"'
        return attr

    def src_attr(self) -> str:
        """``lang`` (and ``dir``) for source-language text inside target blocks."""
        attr = f' lang="{esc(self.src)}"'
        if self.tgt_dir != self.src_dir:
            attr += f' dir="{self.src_dir}"'
        return attr

    def tl(self, text: str | None, tag: str = "span", cls: str = "") -> str:
        """Target-language text in the serif face."""
        klass = f"tl {cls}".strip()
        return f'<{tag} class="{klass}"{self.lang_attr()}>{esc(text)}</{tag}>'

    def column_is_target(self, values: list[str]) -> bool:
        """Heuristic for match columns: is this column in the target language?"""
        as_translation = sum(
            1 for v in values
            if v.casefold() in self._vocab_translations
            or strip_article(v, self.tgt).casefold() in self._vocab_translations
        )
        as_term = sum(1 for v in values if strip_article(v, self.tgt).casefold() in self._vocab_terms)
        return not (as_translation > as_term and as_translation * 2 >= len(values))

    def _lexicons(self) -> tuple[set[str], set[str]]:
        """Words seen only in target-language fields, and only in source-language
        fields (used to tell the language of a grammar-table cell)."""
        ws = self.ws
        tgt: list[str] = [ws.title]
        src: list[str] = [ws.standfirst or "", ws.story.logline, ws.story.setting or ""]
        for scene in ws.story.scenes:
            tgt += [scene.heading, scene.text]
            src.append(scene.translation or "")
        for v in ws.vocabulary.items:
            tgt += [v.term, v.plural or "", v.forms or ""]
            src.append(v.translation)
        for gp in ws.grammar:
            # (explanations quote target words and rules mix both languages,
            # so neither counts)
            tgt += list(gp.examples)
        for fact in ws.facts:
            tgt += [fact.title or "", fact.text]
        # (task titles and instructions quote target words: not counted)
        for c in ws.story.characters:
            src.append(c.role or "")
        src += list(ws.ui.values())

        def words(texts: list[str]) -> set[str]:
            return {w for text in texts for w in _WORD.findall(text.casefold())
                    if len(w) > 1 and not w.isdigit()}

        t_words, s_words = words(tgt), words(src)
        return t_words - s_words, s_words - t_words

    def cell_language(self, text: str) -> str | None:
        """``"tgt"``, ``"src"`` or ``None`` (cannot tell) for a table cell.

        Each word votes: by the worksheet's own target and source texts, else
        by letters only one of the two languages uses (ö, ß vs. é, ç …).
        """
        t_letters = _LETTERS.get(locale.base_lang(self.tgt), "")
        s_letters = _LETTERS.get(locale.base_lang(self.src), "")
        t_hits = s_hits = 0
        for w in _WORD.findall(text.casefold()):
            in_t = any(ch in t_letters and ch not in s_letters for ch in w)
            in_s = any(ch in s_letters and ch not in t_letters for ch in w)
            if in_t != in_s:
                t_hits += in_t
                s_hits += in_s
            elif w in self._lex_tgt:
                t_hits += 1
            elif w in self._lex_src:
                s_hits += 1
        if t_hits == s_hits:
            return None
        return "tgt" if t_hits > s_hits else "src"

    def main_width(self, with_aside: bool) -> float:
        if self.epaper:
            return self.content_w
        return MAIN_W if with_aside else self.content_w

    def blank_width(self, answers: list[str], with_aside: bool) -> float:
        widest = max((metrics.width_mm(a, "serif", 11.0) for a in answers), default=14.0)
        avail = self.main_width(with_aside) - GUTTER_W
        return round(min(max(widest + 7.0, 18.0), avail * 0.72), 1)

    def has_aside(self, pt: PlannedTask, boxes: bool) -> bool:
        """Does the task body get a side column (A4 only)? Word boxes, grammar
        that fits beside the items and small picture copies go there."""
        if self.epaper:
            return False
        if pt.number in self.mini:
            return True
        if pt.number in self.hints.flow:
            return False  # its boxes moved above the items (see task_html)
        if boxes:
            return True
        return any(sb.fact is not None or (sb.grammar is not None and self.grammar_fits_side(sb.grammar))
                   for sb in pt.sidebars)

    def pos_name(self, pos: str) -> str:
        return self.t(f"pos.{pos}")

    # -- pictures ------------------------------------------------------------

    def _picture_hosts(self) -> dict[str, int]:
        """Scene id → number of the task that shows the scene's picture.

        A label task needs the picture; otherwise the first picture-stage task
        of the scene's own block shows it. A picture task placed after a later
        scene does not take the picture away from its scene: the picture then
        follows the scene text, near the text that describes it.
        """
        hosts: dict[str, int] = {}
        for pt in self.plan.tasks:
            if isinstance(pt.task, LabelTask) and pt.task.scene not in hosts:
                hosts[pt.task.scene] = pt.number
        for pt in self.plan.tasks:
            if pt.task.stage == "picture":
                for sid in pt.task.scene_ids:
                    if pt.anchor == sid:
                        hosts.setdefault(sid, pt.number)
        return hosts

    def _pair_pictures(self) -> None:
        """Keep a label task and the picture task right after it on one page
        (when both fit); every other picture task whose picture is shown by
        another task gets a small copy of it."""
        sequences = [self.plan.before, *(b.tasks for b in self.plan.scenes),
                     self.plan.your_turn, self.plan.further]
        for seq in sequences:
            for i, pt in enumerate(seq):
                if pt.task.stage != "picture" or isinstance(pt.task, LabelTask):
                    continue
                for sid in pt.task.scene_ids:
                    host = self.picture_host.get(sid)
                    scene = self.ws.scene(sid)
                    if (host is None or host == pt.number or scene is None
                            or scene.picture is None or not scene.picture.has_visual
                            or self.picture(scene) is None):
                        continue
                    prev = seq[i - 1] if i else None
                    if (prev is not None and prev.number == host and isinstance(prev.task, LabelTask)
                            and prev.task.scene == sid and prev.number not in self.pairs
                            and not self.opts.one_task_per_page
                            and pt.number not in self.hints.unpair
                            and self._pair_fits(prev, pt, scene)):
                        self.pairs[prev.number] = pt.number
                    elif sid not in self.mini.get(pt.number, []):
                        self.mini.setdefault(pt.number, []).append(sid)

    def picture(self, scene: Scene) -> PreparedPicture | None:
        if scene.id not in self._pictures:
            pic = scene.picture
            self._pictures[scene.id] = (
                prepare_picture(pic, self.opts.base_dir, self.opts.monochrome, self.warnings,
                                what=f"scene {scene.id!r} picture")
                if pic is not None else None
            )
        return self._pictures[scene.id]

    def label_picture(self, task: LabelTask) -> PreparedPicture | None:
        scene = self.ws.scene(task.scene)
        if scene is None or scene.picture is None or not scene.picture.has_visual:
            return None
        return self.picture(scene)

    def figure_size(self, prepared: PreparedPicture, mini: bool = False,
                    max_h: float | None = None) -> tuple[float, float]:
        """Width and height (mm) of a picture inside its 1 pt frame."""
        frame = 0.71  # two 1pt borders
        if mini:
            w, cap = MINI_PICTURE_W[self.page] - frame, MINI_PICTURE_H
        else:
            w = self.content_w - frame
            cap = (MAX_PICTURE_H if prepared.is_vector else MAX_PHOTO_H)[self.page]
        max_h = min(cap, max_h) if max_h else cap
        h = w * prepared.aspect
        if h > max_h:
            h = max_h
            w = h / prepared.aspect
        return w, h

    def figure_html(self, scene: Scene, prepared: PreparedPicture, mini: bool = False,
                    max_h: float | None = None) -> str:
        pic = scene.picture
        assert pic is not None
        w, h = self.figure_size(prepared, mini, max_h)
        alt = pic.caption or scene.heading
        img = (f'<img src="{prepared.data_uri}" alt="{esc(alt)}" '
               f'style="width:{w:.2f}mm;height:{h:.2f}mm">')
        r = MINI_MARK_R if mini else MARK_R
        marks: list[str] = []
        if not pic.numbers_in_image:
            for lb in sorted(pic.labels, key=lambda lb: lb.n):
                if lb.x is None or lb.y is None:
                    self.warn(f"scene {scene.id!r}: label {lb.n} has no x/y position; "
                              "its marker is not drawn.")
                    continue
                cx = min(max(lb.x * w, r), w - r)
                cy = min(max(lb.y * h, r), h - r)
                off = r + MARK_RING  # the white ring sits outside the disc
                marks.append(f'<span class="mk" style="left:{cx - off:.2f}mm;top:{cy - off:.2f}mm">'
                             f"{lb.n}</span>")
        caption = ""
        bits = []
        if pic.caption and not mini:
            bits.append(self.tl(pic.caption))
        if pic.credit and not mini:
            bits.append(esc(pic.credit))
        if bits:
            caption = f'<figcaption class="figcap">{" · ".join(bits)}</figcaption>'
        klass = "fig mini" if mini else "fig"
        return (f'<figure class="{klass}" data-h="{h:.1f}"><div class="pic" '
                f'style="width:{w:.2f}mm;height:{h:.2f}mm">{img}{"".join(marks)}</div>'
                f"{caption}</figure>")

    def frame_height(self, pt: PlannedTask) -> float:
        normal = 80.0 if self.epaper else 90.0
        return min(normal, self.hints.shrink_for(pt.number) or normal)

    def frame_html(self, pt: PlannedTask) -> str:
        """The empty frame of a drawing task."""
        h = self.frame_height(pt)
        return f'<div class="frame" data-h="{h:.1f}" style="height:{h:.1f}mm"></div>'

    # -- height estimates (for keep-together decisions) -------------------------

    def _text_h(self, text: str, width: float, face: str = "sans", pt: float = 11.0,
                lead: float = 1.4) -> float:
        return metrics.line_count(text, width, face, pt) * pt * lead * metrics.PT_TO_MM

    def estimate_task_h(self, pt: PlannedTask) -> float:
        """A rough height (mm) of a task, erring on the tall side."""
        task = pt.task
        width = self.content_w - GUTTER_W
        h = 7.0 + 2.4 + 6.4 + 4.0  # margin, rule, title, gap to the body
        instruction = task.instruction or ""
        if instruction:
            h += self._text_h(instruction, min(width, 150.0))
        if isinstance(task, LabelTask):
            scene = self.ws.scene(task.scene)
            prepared = self.label_picture(task)
            if scene is None or prepared is None:
                return h + 100.0
            h += self.figure_size(prepared)[1] + 4.0 + (5.0 if scene.picture and scene.picture.caption else 0)
            per_row = 2 if self.epaper else 3
            n = len(scene.picture.labels) if scene.picture else 0
            h += math.ceil(n / per_row) * 9.0 + 3.0
            if task.bank:
                h += 12.0
            return h
        if isinstance(task, QuestionsTask):
            return h + sum(self._text_h(it.question, width - GUTTER_W, "serif", 11, 1.45)
                           + it.lines * 9.0 + 1.6 for it in task.items)
        if isinstance(task, TrueFalseTask):
            # three boxes: narrower statements under a row of column heads;
            # with "justify": one more line and more room per statement
            from langwich.render import tasks  # local import: tasks imports this module's helpers

            boxes, heads = 35.0, 0.0
            if task.not_given:
                boxes, heads = 3 * tasks.tf_column_width(self) + 5.0, 8.4
            per_item = 10.2 + (11.0 if task.justify else 0.0)
            return h + heads + sum(self._text_h(it.statement, width - boxes, "serif", 11, 1.45)
                                   + per_item for it in task.items)
        if isinstance(task, MultipleChoiceTask):
            return h + sum(self._text_h(it.question, width - GUTTER_W, "serif", 11, 1.45)
                           + 1.4 + len(it.options) * 6.6 + 2.6 for it in task.items)
        if isinstance(task, TransformTask):
            # the prompt (narrower beside a key word), then the → line, or the
            # frame on 7.6 mm lines beside its cue, with the task's blank (see
            # tasks.frame_blank_width) for its gap
            from langwich.render import tasks  # local import: tasks imports this module's helpers

            aside = self.has_aside(pt, False)
            avail = self.main_width(aside) - GUTTER_W
            blank_w = tasks.frame_blank_width(self, task, aside)
            for it in task.items:
                kw_w = (metrics.width_mm(it.keyword.upper(), "sans-bold", 10.0) + 4.0
                        if it.keyword else 0.0)
                h += self._text_h(it.prompt, avail - kw_w, "serif", 11, 1.45)
                if it.frame is None:
                    h += 11.6
                    continue
                width = avail - tasks.frame_cue_width(it.cue)
                h += tasks.frame_lines(it.frame, blank_w, width) * 7.6 + 3.4
            return h
        return h + 80.0

    def _pair_fits(self, label: PlannedTask, following: PlannedTask, scene: Scene) -> bool:
        total = self.estimate_task_h(label) + self.estimate_task_h(following)
        return total <= PAGE_CONTENT_H[self.page] * 0.96

    # -- small blocks --------------------------------------------------------

    def phase_html(self, step: int, label: str) -> str:
        return (f'<div class="phase"><span class="step">{step}</span>{esc(label)}'
                f'<span class="rule"></span></div>')

    def word_box(self, words: list[str], row: bool = False, cap: str | None = None,
                 counts: dict[str, int] | None = None) -> str:
        """A framed word box. ``counts`` (casefolded word → n) marks words that
        fill more than one gap ("2×") instead of listing them twice."""
        items = []
        for w in words:
            n = (counts or {}).get(w.casefold(), 1)
            mark = f'<span class="cnt">{n}×</span>' if n > 1 else ""
            items.append(f"<li>{esc(w)}{mark}</li>")
        klass = "box wordbox row" if row else "box wordbox"
        return (f'<div class="{klass}"><span class="cap">{esc(cap or self.t("word_box"))}</span>'
                f'<ul class="words tl"{self.lang_attr()}>{"".join(items)}</ul></div>')

    def lines(self, count: int, starter: str | None = None) -> str:
        if count <= 0:
            return ""
        rows = []
        if starter:
            rows.append(f'<div class="starter tl"{self.lang_attr()}>{esc(starter)}</div>')
        rows.extend("<div></div>" for _ in range(count - len(rows)))
        return f'<div class="lines">{"".join(rows)}</div>'

    # -- grammar ---------------------------------------------------------------

    def side_inner_w(self) -> float:
        """Text width inside a grammar box in the side column (bar + padding)."""
        return SIDE_W - 0.9 - 3.0

    def full_inner_w(self) -> float:
        """Text width inside a full-width grammar box."""
        if self.epaper:
            return self.content_w - GUTTER_W - 6.6  # framed box
        return self.content_w - GUTTER_W - 3.9

    def _table_cells(self, table: GrammarTable) -> list[tuple[int, str, bool, str | None]]:
        """(column, text, is_head, language) for every cell."""
        cells: list[tuple[int, str, bool, str | None]] = []
        if table.head and any(h.strip() for h in table.head):
            cells += [(c, h, True, self.cell_language(h)) for c, h in enumerate(table.head)]
        langs: dict[int, list[str | None]] = {}
        body = [(c, text, self.cell_language(text)) for row in table.rows for c, text in enumerate(row)]
        for c, _, lang in body:
            langs.setdefault(c, []).append(lang)
        for c, text, lang in body:
            if lang is None and len(_WORD.findall(text)) <= 2:
                # a short unknown cell ('werde', 'wirst') takes the language
                # all known cells of its column share
                known = [x for x in langs[c] if x]
                if known and known.count(known[0]) == len(known):
                    lang = known[0]
            cells.append((c, text, False, lang))
        return cells

    def table_layout(self, table: GrammarTable, avail: float, wide: bool) -> tuple[bool, bool, bool]:
        """``(fits, first_nowrap, overflows)`` for ``table`` in ``avail`` mm:
        does it fit with no cell wrapped to more than MAX_CELL_LINES lines,
        may its first column stay unbroken, and is even its narrowest layout
        (longest word per column) wider than ``avail``?"""
        pt_td = 7.8 if wide else (9.0 if self.epaper else 8.5)
        pt_th = 8.5 if self.epaper else 7.0
        cells = self._table_cells(table)
        ncols = max(c for c, *_ in cells) + 1
        pad = 1.2
        mins, maxs = [0.0] * ncols, [0.0] * ncols

        def face(head: bool, lang: str | None) -> tuple[str, float]:
            if head:
                return "sans-bold", pt_th
            return ("sans" if lang == "src" else "serif"), pt_td

        for c, text, head, lang in cells:
            f, size = face(head, lang)
            words = text.split()
            w_min = max((metrics.width_mm(w, f, size) for w in words), default=0.0)
            mins[c] = max(mins[c], w_min + pad)
            maxs[c] = max(maxs[c], metrics.width_mm(text, f, size) + pad)
        first_nowrap = ncols > 1 and maxs[0] <= 0.4 * avail
        if first_nowrap:
            mins[0] = maxs[0]
        if sum(maxs) <= avail:
            return True, first_nowrap, False
        if sum(mins) > avail:
            if first_nowrap:  # let the first column wrap before giving up
                return self._table_layout_wrapping(cells, mins, maxs, avail, face)
            return False, False, True
        extra, span = avail - sum(mins), sum(maxs) - sum(mins)
        widths = [mn + extra * (mx - mn) / span for mn, mx in zip(mins, maxs)]
        worst = max(metrics.line_count(text, widths[c] - pad, *face(head, lang))
                    for c, text, head, lang in cells)
        return worst <= MAX_CELL_LINES, first_nowrap, False

    @staticmethod
    def _table_layout_wrapping(cells, mins, maxs, avail, face) -> tuple[bool, bool, bool]:
        first_min = 0.0
        for c, text, head, lang in cells:
            if c == 0:
                f, size = face(head, lang)
                words = text.split()
                first_min = max(first_min, max((metrics.width_mm(w, f, size) for w in words),
                                               default=0.0) + 1.2)
        overflow = sum(mins) - mins[0] + first_min > avail
        return False, False, overflow

    def grammar_fits_side(self, gp: GrammarPoint) -> bool:
        """Can ``gp`` sit in the 52 mm side column (A4) without its table
        running past the column or wrapping every cell into a tower?"""
        if self.epaper or not gp.table or not gp.table.rows:
            return True
        wide = max(len(r) for r in gp.table.rows) >= 3
        return self.table_layout(gp.table, self.side_inner_w(), wide)[0]

    def grammar_fits(self, gp: GrammarPoint, avail: float) -> bool:
        """Does the table of ``gp`` fit a column ``avail`` mm wide?"""
        if not gp.table or not gp.table.rows:
            return True
        return self.table_layout(gp.table, avail, False)[0]

    def grammar_html(self, gp: GrammarPoint, cap: bool = True, full: bool = False,
                     avail: float | None = None) -> str:
        """A grammar box. ``full`` = a full-width block (else the side column
        or a column of the back matter, ``avail`` mm wide)."""
        text = [f'<div class="nm">{esc_nw(gp.name)}</div>', f"<div>{esc_nw(gp.explanation)}</div>"]
        if gp.rule:
            text.append(f'<div class="tl rule"{self.lang_attr()}>{esc_nw(gp.rule)}</div>')
        parts = [f'<span class="cap">{esc(self.t("grammar"))}</span>' if cap else ""]
        parts.append(f'<div class="gtext">{"".join(text)}</div>' if full else "".join(text))
        if gp.table and gp.table.rows:
            if avail is None:
                avail = self.full_inner_w() if (full or self.epaper) else self.side_inner_w()
            wide = max(len(r) for r in gp.table.rows) >= 3 and not full and not self.epaper
            _, first_nowrap, overflows = self.table_layout(gp.table, avail, wide)
            classes = [c for c, on in (("wide", wide), ("fixed", overflows)) if on]
            head_cells: list[str] = []
            rows: list[list[str]] = []
            for c, cell, head, lang in self._table_cells(gp.table):
                # (no hyphenation: in a narrow cell it breaks short forms like
                # 'va-mos'; a table that does not fit moves to full width instead)
                attrs, klass = "", []
                if lang == "tgt":
                    attrs = self.lang_attr()
                elif lang == "src":
                    attrs = self.src_attr()
                    if not head:
                        klass.append("src")
                if c == 0 and first_nowrap and not head:
                    klass.append("nw")
                cls = f' class="{" ".join(klass)}"' if klass else ""
                if head:
                    head_cells.append(f"<th{cls}{attrs}>{esc_nw(cell)}</th>")
                else:
                    if c == 0:
                        rows.append([])
                    rows[-1].append(f"<td{cls}{attrs}>{esc_nw(cell)}</td>")
            head_html = f"<tr>{''.join(head_cells)}</tr>" if head_cells else ""
            body = "".join(f"<tr>{''.join(r)}</tr>" for r in rows)
            table_class = f' class="{" ".join(classes)}"' if classes else ""
            parts.append(f"<table{table_class}>{head_html}{body}</table>")
        if gp.examples:
            exs = "".join(f"<div>{esc_nw(e)}</div>" for e in gp.examples)
            parts.append(f'<div class="ex tl"{self.lang_attr()}>{exs}</div>')
        box_class = "snippet full" if full else "snippet"
        return f'<div class="{box_class}">{"".join(parts)}</div>'

    def fact_html(self, fact: Fact) -> str:
        title = self.tl(fact.title, "div", "ft") if fact.title else ""
        source = (f'<div class="fsrc">{esc(self.t("source"))}: {esc(fact.source)}</div>'
                  if fact.source else "")
        return (f'<div class="fact"><span class="cap">{esc(self.t("did_you_know"))}</span>'
                f'{title}{self.tl(fact.text, "p")}{source}</div>')

    def sidebar_html(self, sb: Sidebar, full: bool = False) -> str:
        if sb.grammar is not None:
            return self.grammar_html(sb.grammar, full=full)
        if sb.fact is not None:
            return self.fact_html(sb.fact)
        return ""

    # -- task furniture --------------------------------------------------------

    def is_label_draw(self, pt: PlannedTask) -> bool:
        return isinstance(pt.task, LabelTask) and self.label_picture(pt.task) is None

    def task_title(self, pt: PlannedTask) -> str:
        task = pt.task
        if task.title:
            return task.title
        if self.is_label_draw(pt):
            return self.t("kind.draw.title")
        return self.t(f"kind.{task.kind}.title")

    @staticmethod
    def bank_is_exact(task: ClozeTask) -> bool:
        """True when the word box holds only the answers (no distractors)."""
        from langwich.answers import cloze_texts, safe_gaps

        answers = {g.answer.casefold() for text in cloze_texts(task) for g in safe_gaps(text)}
        return not ({d.casefold() for d in task.distractors} - answers)

    def task_instruction(self, pt: PlannedTask) -> str:
        task = pt.task
        if isinstance(task, LabelTask) and self.is_label_draw(pt):
            scene = self.ws.scene(task.scene)
            heading = scene.heading if scene else task.scene
            before, _, after = self.t("kind.label.draw", scene="\x00").partition("\x00")
            return esc(before) + self.tl(heading) + esc(after)
        from langwich.render import tasks  # local import: tasks imports this module's helpers

        default = None if task.instruction else tasks.default_instruction(self, pt)
        if task.instruction:
            text = esc(task.instruction)
        elif default is not None:
            text = esc(default)
        elif isinstance(task, ClozeTask):
            key = f"kind.cloze.{task.hint}"
            if task.hint == "word_bank" and self.bank_is_exact(task):
                key = "kind.cloze.word_bank_exact"
            text = esc(self.t(key))
        else:
            text = esc(self.t(f"kind.{task.kind}.instruction"))
        text += tasks.instruction_suffix(self, pt)
        if isinstance(task, WritingTask):
            length = None
            if task.min_words and task.max_words:
                length = self.t("kind.writing.length", min=task.min_words, max=task.max_words)
            elif task.max_words:
                length = f"≤ {task.max_words} {self.t('words')}"
            elif task.min_words:
                length = f"≥ {task.min_words} {self.t('words')}"
            numbers = [str(n) for n in (task.min_words, task.max_words) if n]
            said = task.instruction and all(
                re.search(rf"(?<!\d){n}(?!\d)", task.instruction) for n in numbers)
            if length and not said:
                text += f' <span class="len">{esc(length)}</span>'
        return text

    def scene_ref(self, pt: PlannedTask) -> str:
        nums = [self.scene_numbers[s] for s in pt.task.scene_ids if s in self.scene_numbers]
        if not nums:
            return ""
        return f'<span class="src">{esc(self.t("scene"))} {number_ranges(nums)}</span>'

    def header_room(self) -> float:
        right = f"{locale.endonym(self.src)} → {locale.endonym(self.tgt)} · {self.ws.cefr_level}"
        size = 8.5 if self.epaper else 8.0
        return self.content_w - metrics.width_mm(right, "sans-bold", size) - 8.0

    def fit_header(self, text: str, face: str, pt: float) -> str:
        """``text`` shortened with '…' to fit the running header."""
        room = self.header_room()
        if metrics.width_mm(text, face, pt) <= room:
            return text
        words = text.split()
        while len(words) > 1 and metrics.width_mm(" ".join(words) + " …", face, pt) > room:
            words.pop()
        return " ".join(words).rstrip(",;:–-") + " …"

    def continued_label(self, pt: PlannedTask) -> str:
        """Running-header text for a page that starts inside task ``pt``."""
        head = f"{self.t('task')} {pt.number} · "
        suffix = f" ({self.t('continued')})"
        title = self.task_title(pt)
        size = 8.5 if self.epaper else 8.0
        room = self.header_room()

        def width(text: str) -> float:
            return metrics.width_mm(text, "sans-bold", size)

        if width(head + title + suffix) <= room:
            return head + title + suffix
        words = title.split()
        while words and width(head + " ".join(words) + " …" + suffix) > room:
            words.pop()
        short = " ".join(words).rstrip(",;:–-") + " …" if words else "…"
        return head + short + suffix

    # -- cover ---------------------------------------------------------------

    def title_html(self) -> str:
        m = re.match(r"^(.+?[:：])\s+(\S.*)$", self.ws.title)
        if m:
            return f"{esc(m.group(1))}<br>{esc(m.group(2))}"
        return esc(self.ws.title)

    def route_html(self) -> str:
        items: list[str] = []

        def task_item(pt: PlannedTask) -> str:
            return f'<li><span class="rn">{pt.number}</span>{esc(self.task_title(pt))}</li>'

        items.extend(task_item(pt) for pt in self.plan.before)
        for block in self.plan.scenes:
            items.append(
                f'<li class="read"><span class="rn">¶</span>{esc(self.t("read"))}'
                f' <span class="sub">· {esc(self.t("scene"))} {block.number}</span></li>'
            )
            items.extend(task_item(pt) for pt in block.tasks)
        items.extend(task_item(pt) for pt in self.plan.your_turn + self.plan.further)
        return (f'<nav class="route"><span class="cap">{esc(self.t("route"))}</span>'
                f'<ol>{"".join(items)}</ol></nav>')

    def cover_html(self) -> str:
        ws = self.ws
        kicker = ""
        if ws.series:
            kicker = (f'<p class="kicker">{esc(ws.series.title)} · {esc(self.t("episode"))} '
                      f"{ws.series.episode}</p>")
        standfirst = ws.standfirst or ws.story.logline
        cast = ""
        if ws.story.characters:
            who = "".join(
                f'<div class="who"><b>{esc(c.name)}</b>'
                + (f"<span>{esc(c.role)}</span>" if c.role else "")
                + "</div>"
                for c in ws.story.characters
            )
            cast = (f'<div class="cast"><span class="cap">{esc(self.t("characters"))}</span>'
                    f'<div class="who-grid">{who}</div></div>')
        previously = ""
        if ws.series and ws.series.previously:
            previously = (f'<div class="previously"><span class="cap">{esc(self.t("previously"))}'
                          f"</span><p>{esc_br(ws.series.previously)}</p></div>")
        return (
            f'<header class="cover"><div class="lead">{kicker}'
            f'<h1 class="tl"{self.lang_attr()}>{self.title_html()}</h1>'
            f'<p class="standfirst">{esc(standfirst)}</p>{cast}{previously}</div>'
            f"<aside>{self.route_html()}</aside></header>"
        )

    # -- scenes --------------------------------------------------------------

    @staticmethod
    def _gloss_h(item: VocabItem) -> float:
        return metrics.line_count(f"{item.term} {item.translation}", SIDE_W - 2.8, "sans", 9.0) * 4.6

    @staticmethod
    def _sidebar_h(sb: Sidebar) -> float:
        col = SIDE_W - 3.5
        if sb.fact is not None:
            f = sb.fact
            h = 6.0 + metrics.line_count(f.text, col, "serif", 9.5) * 4.85
            if f.title:
                h += metrics.line_count(f.title, col, "serif-bold", 9.5) * 4.5
            if f.source:
                h += 4.5
            return h
        if sb.grammar is not None:
            g = sb.grammar
            h = 6.0 + metrics.line_count(g.name, col, "sans-bold", 9.0) * 4.45
            h += metrics.line_count(g.explanation, col, "sans", 9.0) * 4.45
            if g.rule:
                h += 1.4 + metrics.line_count(g.rule, col, "serif-bold", 9.0) * 4.3
            if g.table:
                h += 2.5 + (len(g.table.rows) + (1 if g.table.head else 0)) * 4.4
            for ex in g.examples:
                h += metrics.line_count(ex, col, "serif-italic", 9.5) * 4.85
            return h + 2.0
        return 0.0

    def _paragraph_html(self, text: str, start: int, end: int,
                        spans: list[tuple[int, int]]) -> str:
        out: list[str] = []
        pos = start
        for s, e in spans:
            if s < start or e > end:
                continue
            out.append(esc_br(text[pos:s]))
            out.append(f'<span class="g">{esc(text[s:e])}</span>')
            pos = e
        out.append(esc_br(text[pos:end]))
        return "".join(out)

    def scene_html(self, block: SceneBlock, phase: str = "", first: bool = False) -> str:
        scene = block.scene
        text = scene.text
        paras = paragraph_spans(text) or [(0, len(text))]

        # Where does each gloss sit? (paragraph of its first occurrence)
        spans: list[tuple[int, int]] = []
        anchored: list[tuple[int, Gloss]] = []
        for gloss in block.glosses:
            idx = len(paras) - 1
            if gloss.match:
                m = term_pattern(gloss.item, self.tgt).search(text)
                if m:
                    if not any(m.start() < e and s < m.end() for s, e in spans):
                        spans.append((m.start(), m.end()))
                    idx = next((i for i, (s, e) in enumerate(paras) if s <= m.start() < e), idx)
            anchored.append((idx, gloss))
        spans.sort()

        sidebars = list(block.sidebars)
        if block is self.plan.scenes[-1]:
            sidebars.extend(Sidebar(fact=f) for f in self.plan.loose_facts)
        # grammar whose table is too wide for the side column spans the page
        wide = [sb for sb in sidebars
                if sb.grammar is not None and not self.grammar_fits_side(sb.grammar)]
        sidebars = [sb for sb in sidebars if sb not in wide]

        def gloss_div(g: Gloss) -> str:
            return f"<div>{self.tl(g.item.term, 'b')} {esc(g.item.translation)}</div>"

        rows: list[tuple[list[Gloss], list[Sidebar]]] = [([], []) for _ in paras]
        para_h = [metrics.line_count(text[s:e], MAIN_W - GUTTER_W, "serif", 11.0) * 5.63
                  for s, e in paras]
        side_h = [0.0 for _ in paras]
        band: list[Sidebar] = []  # sidebars with no room beside the text
        if self.epaper:
            for idx, g in anchored:
                rows[idx][0].append(g)
            rows[-1][1].extend(sidebars)
        else:
            # Side notes flow: a gloss sits beside its paragraph if there is
            # room, else it moves down; sidebars fill the space left over and
            # whatever still does not fit goes into a band below the text.
            pending = list(anchored)
            side_queue = list(sidebars)
            last = len(paras) - 1
            for i in range(len(paras)):
                cap = para_h[i] + 2.0
                used = 0.0
                glosses_here, sidebars_here = rows[i]
                while pending and pending[0][0] <= i:
                    idx, g = pending[0]
                    h = self._gloss_h(g.item)
                    if used + h <= cap or (not glosses_here and idx == i) or i == last:
                        glosses_here.append(g)
                        used += h
                        pending.pop(0)
                    else:
                        break
                if glosses_here:
                    used += 2.0
                if not any(idx <= i for idx, _ in pending):
                    slack = BAND_SLACK if i == last else 0.0
                    while side_queue:
                        h = self._sidebar_h(side_queue[0]) + (4.0 if used else 0.0)
                        if used + h <= cap + slack:
                            sidebars_here.append(side_queue.pop(0))
                            used += h
                        else:
                            break
                side_h[i] = used
            for _, g in pending:  # cannot happen, but never drop a gloss
                rows[last][0].append(g)
            band = side_queue

        para_html = []
        for i, (s, e) in enumerate(paras):
            glosses_here, sidebars_here = rows[i]
            side_parts = []
            if glosses_here:
                side_parts.append(f'<div class="gls">{"".join(gloss_div(g) for g in glosses_here)}</div>')
            side_parts.extend(self.sidebar_html(sb, full=self.epaper) for sb in sidebars_here)
            side = f'<div class="side">{"".join(side_parts)}</div>' if side_parts else ""
            keep = " keep" if max(para_h[i], side_h[i]) < KEEP_ROW_MM else ""
            para_html.append(
                f'<div class="para{keep}"><div class="txt"><p class="tl"{self.lang_attr()}>'
                f"{self._paragraph_html(text, s, e, spans)}</p></div>{side}</div>"
            )
        if band:
            para_html.append(f'<div class="notes-band n{min(len(band), 3)}">'
                             f'{"".join(self.sidebar_html(sb) for sb in band)}</div>')
        if wide:
            para_html.append(f'<div class="notes-wide">'
                             f'{"".join(self.sidebar_html(sb, full=True) for sb in wide)}</div>')

        figure = ""
        if scene.picture is not None and scene.id not in self.picture_host:
            prepared = self.picture(scene)
            if prepared is not None:
                figure = f'<div class="scene-fig">{self.figure_html(scene, prepared)}</div>'

        heading = (f'<header class="sh"><span class="kick">{esc(self.t("scene"))} {block.number}'
                   f'</span><h2 class="tl"{self.lang_attr()}>{esc(scene.heading)}</h2></header>')
        klass = "scene unit first" if first else "scene unit"
        return (f'<section class="{klass}" id="scene-{esc(scene.id)}">{phase}{heading}'
                f'{"".join(para_html)}{figure}</section>')

    # -- tasks ---------------------------------------------------------------

    def task_html(self, pt: PlannedTask, phase: str = "") -> str:
        from langwich.render import tasks  # local import: tasks imports this module's helpers

        parts = tasks.render_task(self, pt)
        task = pt.task
        pre = parts.pre
        full_figure = bool(pre)
        if not isinstance(task, LabelTask):
            for sid in task.scene_ids:
                scene = self.ws.scene(sid)
                if scene is not None and self.picture_host.get(sid) == pt.number:
                    prepared = self.picture(scene)
                    if prepared is not None:
                        pre = self.figure_html(scene, prepared,
                                               max_h=self.hints.shrink_for(pt.number)) + pre
                        full_figure = True
        minis = []
        for sid in self.mini.get(pt.number, []):
            scene = self.ws.scene(sid)
            prepared = self.picture(scene) if scene is not None else None
            if scene is not None and prepared is not None:
                minis.append(self.figure_html(scene, prepared, mini=True))

        # Grammar and word boxes: beside the items on A4 (a grammar table too
        # wide for the side column spans the page above the items); before the
        # items on e-paper, where they can never trail onto a page of their own.
        before: list[str] = []
        aside: list[str] = []
        # A task that is kept whole only for convenience (its boxes beside the
        # items) may flow when the layout check asks for it.
        hard = parts.keep_hard or full_figure or bool(minis)
        loosened = not hard and pt.number in self.hints.flow
        if self.epaper or loosened:
            pre = "".join(minis) + pre
            before += [self.sidebar_html(sb, full=True) for sb in pt.sidebars]
            before += parts.aside
        else:
            aside += minis + list(parts.aside)
            for sb in pt.sidebars:
                if sb.grammar is not None and not self.grammar_fits_side(sb.grammar):
                    before.append(self.sidebar_html(sb, full=True))
                else:
                    aside.append(self.sidebar_html(sb))
        header = (
            f'<header class="th"><span class="tn">{pt.number}</span>'
            f"<h3>{esc(self.task_title(pt))}</h3>{self.scene_ref(pt)}"
            f'<p class="ins">{self.task_instruction(pt)}</p></header>'
        )
        # every block after the header names the task for a page that starts in it
        cont = f' data-cont="{esc(self.continued_label(pt))}"'
        pre_html = f'<div class="pre"{cont}>{pre}</div>' if pre else ""
        before_html = f'<div class="before"{cont}>{"".join(before)}</div>' if before else ""
        if aside:
            body = (f'<div class="body"{cont}><div class="main">{parts.main}</div>'
                    f'<aside class="aside-stack">{"".join(aside)}</aside></div>')
        else:
            body = f'<div class="body full"{cont}><div class="main">{parts.main}</div></div>'
        keep = hard or (parts.keep and not loosened)
        flow = not keep and not aside
        klass = f"task unit k-{task.kind}" + (" keep" if keep else "") + (" flow" if flow else "")
        if flow and pt.number in self.hints.loose:
            klass += " loose"
        data = ' data-soft="1"' if not flow and not hard else ""
        return (f'<section class="{klass}" id="task-{pt.number}"{data}>'
                f"{phase}{header}{pre_html}{before_html}{body}</section>")

    def tasks_html(self, planned: list[PlannedTask], phase: str = "") -> list[str]:
        """The tasks of one phase or scene, a label task and the picture task
        kept with it wrapped as one unit."""
        out: list[str] = []
        i = 0
        while i < len(planned):
            pt = planned[i]
            cap = phase if i == 0 else ""
            partner = self.pairs.get(pt.number)
            if partner is not None and i + 1 < len(planned) and planned[i + 1].number == partner:
                out.append(f'<div class="pair" data-pair="{partner}">{self.task_html(pt, cap)}'
                           f"{self.task_html(planned[i + 1])}</div>")
                i += 2
                continue
            out.append(self.task_html(pt, cap))
            i += 1
        return out

    # -- the worksheet part ----------------------------------------------------

    def worksheet_html(self) -> str:
        p = self.plan
        out = [self.cover_html()]
        step = 0
        if p.before:
            step += 1
            out.extend(self.tasks_html(p.before, self.phase_html(step, self.t("phase.before"))))
        step += 1
        read_cap = self.phase_html(step, self.t("read"))
        for i, block in enumerate(p.scenes):
            out.append(self.scene_html(block, read_cap if i == 0 else "", first=i == 0))
            out.extend(self.tasks_html(block.tasks))
        for group, key in ((p.your_turn, "phase.your_turn"), (p.further, "phase.further")):
            if group:
                step += 1
                out.extend(self.tasks_html(group, self.phase_html(step, self.t(key))))
        series = self.ws.series
        if series and series.next:
            out.append(
                f'<aside class="teaser"><span class="cap">{esc(self.t("next_episode"))}</span>'
                f'<p class="ep">{esc(series.title)} · {esc(self.t("episode"))} {series.episode + 1}</p>'
                f"<p>{esc_br(series.next)}</p></aside>"
            )
        return "".join(out)

    # -- back matter -----------------------------------------------------------

    def word_row_html(self, v: VocabItem, key: bool) -> str:
        term = esc(with_article_nbsp(v.term, self.tgt))
        gender = note_term = note_en = ""
        if v.note and is_gender_note(v.note):
            gender = f' <span class="gd">{esc(v.note.strip())}</span>'
        elif v.note and _GENDER_LEAD.match(v.note.strip()):
            note_term = v.note.strip()
        elif v.note:
            note_en = f" <i>({esc(v.note)})</i>"
        plural = plural_note(v, self.tgt)
        plural_html = ""
        if plural:
            if len(plural) <= 5 and plural[0] in "-¨":
                # a dictionary marker (-n, ¨-e) never starts a line of its own
                plural_html = f'<i class="nw">,\u00a0{esc(plural)}</i>'
            else:
                plural_html = f"<i>, {esc(plural)}</i>"
        forms = " · ".join(x for x in (v.forms, note_term) if x)
        forms_html = f'<span class="forms">{esc(forms)}</span>' if forms else ""
        klass = "de tl key" if key else "de tl"
        return (f'<div class="vl"><div class="{klass}"{self.lang_attr()}>{term}{gender}{plural_html}'
                f'{forms_html}</div><div class="en"{self.src_attr()}>{esc(v.translation)}{note_en}'
                f"</div></div>")

    def word_list_html(self) -> str:
        targets = {t.casefold() for t in self.ws.vocabulary.target}
        groups: list[str] = []
        for pos in POS_VALUES:
            items = sorted((v for v in self.ws.vocabulary.items if v.pos == pos),
                           key=lambda v: (sort_key(v.term, self.tgt), v.term))
            if not items:
                continue
            klass = ' class="later"' if groups else ""
            rows = [f"<h3{klass}>{esc(self.pos_name(pos))}</h3>"]
            rows.extend(self.word_row_html(v, v.term.casefold() in targets) for v in items)
            groups.append("".join(rows))
        compact = {0: "", 1: " compact", 2: " compact compact2"}[min(self.hints.compact_words, 2)]
        return (f'<section class="back words-sec"><h2 class="big">{esc(self.t("word_list"))}</h2>'
                f'<div class="vocab-list{compact}">{"".join(groups)}</div></section>')

    def back_matter_html(self) -> str:
        out = [self.word_list_html()]
        if self.plan.reference_grammar:
            col = self.full_inner_w() if self.epaper else (self.content_w - 10.0) / 2 - 3.9
            narrow = [g for g in self.plan.reference_grammar if self.grammar_fits(g, col)]
            wide = [g for g in self.plan.reference_grammar if g not in narrow]
            body = ""
            if narrow:
                snippets = "".join(self.grammar_html(g, cap=False, avail=col) for g in narrow)
                body += f'<div class="ref-grammar">{snippets}</div>'
            if wide:
                snippets = "".join(self.grammar_html(g, cap=False, full=True) for g in wide)
                body += f'<div class="ref-wide">{snippets}</div>'
            out.append(f'<section class="back"><h2 class="big">{esc(self.t("grammar"))}</h2>'
                       f"{body}</section>")
        return "".join(out)

    # -- answers ---------------------------------------------------------------

    def key_for(self, pt: PlannedTask) -> list[list[KeyRun]]:
        """The answer key of a task, each entry as its runs by language."""
        if self.is_label_draw(pt):
            return []
        return answer_key_runs(pt, self.ws)

    def key_html(self, runs: list[KeyRun]) -> str:
        """One answer-key entry, each run with its language's ``lang`` (and
        ``dir``): the answers the target's, a verdict or 'not in the text'
        the learner's. A short answer keeps its article on its line."""
        short = len(key_text(runs).split()) <= 3

        def shown(run: str, source: bool) -> str:
            return esc(with_article_nbsp(run, self.tgt) if short and not source else run)

        if len(runs) == 1:
            run, source = runs[0]
            attr = self.src_attr() if source else self.lang_attr()
            return f'<span class="k"{attr}>{shown(run, source)}</span>'
        inner = "".join(f"<span{self.src_attr() if source else self.lang_attr()}>"
                        f"{shown(run, source)}</span>" for run, source in runs)
        return f'<span class="k">{inner}</span>'

    def key_numbers(self, pt: PlannedTask, count: int) -> list[str] | None:
        from langwich.render import tasks  # local import: tasks imports this module's helpers

        own, labels = tasks.key_labels(self, pt, count)
        if own:
            return labels
        task = pt.task
        if isinstance(task, OrderEventsTask):
            return None
        if isinstance(task, LabelTask):
            scene = self.ws.scene(task.scene)
            if scene and scene.picture:
                nums = [str(lb.n) for lb in sorted(scene.picture.labels, key=lambda lb: lb.n)]
                if len(nums) == count:
                    return nums
        return [str(i) for i in range(1, count + 1)]

    def solution_block(self, pt: PlannedTask) -> str:
        task = pt.task
        runs = self.key_for(pt)
        key = [key_text(entry) for entry in runs]
        if key:
            numbers = self.key_numbers(pt, len(key))
            entries = []
            for i, k in enumerate(key):
                # a non-breaking space: "8 J" never splits into "8" / "J"
                num = f'<span class="kn">{numbers[i]}</span>\u00a0' if numbers else ""
                entry = num + self.key_html(runs[i])
                if len(k) <= 12:
                    entry = f'<span class="ke">{entry}</span>'
                entries.append(entry)
            if max(len(k) for k in key) > 32:
                content = "<ol>" + "".join(f"<li>{e}</li>" for e in entries) + "</ol>"
            else:
                content = " · ".join(entries)
        elif isinstance(task, WritingTask) and task.model_answer:
            # in the language the learner writes (paragraphs on new lines), then
            # each point with the words of the model answer that cover it
            source = task.output_lang == "source"
            attr = self.src_attr() if source else self.lang_attr()
            model = "<br>".join(esc_br(p) for p in paragraphs(task.model_answer))
            content = (f'<i>{esc(self.t("model_answer"))}:</i> '
                       f'<span class="model{" src" if source else ""}"{attr}>{model}</span>')
            points = ""
            for p in task.points:
                # (the words in the quote marks of their language, never twice)
                words = quoted_passage(p.covered_by or "", self.src if source else self.tgt)
                if words:
                    words = " — " + (esc(words) if source else self.tl(words))
                points += f"<li>{esc(p.point)}{words}</li>"
            if points:
                content += f'<ul class="pts">{points}</ul>'
        else:
            content = esc(self.t("open_answer"))
        return (f'<div class="sb"><span class="st"><span class="tn2">{pt.number}</span>'
                f"{esc(self.task_title(pt))}</span>{content}</div>")

    def translations_html(self) -> str:
        blocks = []
        for block in self.plan.scenes:
            scene = block.scene
            if not scene.translation:
                continue
            paras = "".join(f"<p>{esc_br(p)}</p>" for p in paragraphs(scene.translation))
            blocks.append(f'<div class="tr"><h4><span class="num">{block.number}</span>'
                          f'{self.tl(scene.heading)}</h4><div lang="{esc(self.src)}">{paras}</div></div>')
        return "".join(blocks)

    def solution_h(self, pt: PlannedTask, col_w: float) -> float:
        """Estimated height (mm) of a task's block in the answer key."""
        task = pt.task
        h = metrics.line_count(self.task_title(pt), col_w - 5.8, "sans-bold", 8.5) * 4.05 + 0.6
        key = [key_text(entry) for entry in self.key_for(pt)]
        if key:
            numbers = self.key_numbers(pt, len(key)) or [""] * len(key)
            entries = [f"{n} {k}".strip() for n, k in zip(numbers, key)]
            if max(len(k) for k in key) > 32:
                h += sum(metrics.line_count(e, col_w - 3.6, "serif", 9.0) * 4.76 + 0.5
                         for e in entries)
            else:
                h += metrics.line_count(" · ".join(entries), col_w, "serif", 9.0) * 4.76
        elif isinstance(task, WritingTask) and task.model_answer:
            model = "\n".join(paragraphs(task.model_answer))
            face = "sans" if task.output_lang == "source" else "serif-italic"
            h += metrics.line_count(f"{self.t('model_answer')}: {model}", col_w, face, 9.0) * 4.6
            lang = self.src if task.output_lang == "source" else self.tgt
            h += sum(metrics.line_count(f"– {p.point} — {quoted_passage(p.covered_by or '', lang)}",
                                        col_w - 3.6, "sans", 9.0) * 4.76 + 0.5 for p in task.points)
        else:
            h += 4.76
        return h + 3.4

    def solutions_html(self, available: float) -> str:
        """The answer key in columns. When it fits on one page it is split
        into explicit, balanced columns (CSS column balancing is slow and the
        key is atomic per task anyway); longer keys use CSS columns."""
        blocks = [self.solution_block(pt) for pt in self.plan.tasks]
        cols = 2 if self.epaper else 3
        gap = 6.0 if self.epaper else 7.0
        col_w = (self.content_w - gap * (cols - 1)) / cols
        heights = [self.solution_h(pt, col_w) for pt in self.plan.tasks]
        split = balanced_split(heights, cols)
        tallest = max((sum(heights[a:b]) for a, b in split), default=0.0)
        if not blocks or tallest > available * 0.88:
            return f'<div class="solutions">{"".join(blocks)}</div>'
        columns = "".join(f'<div class="col">{"".join(blocks[a:b])}</div>' for a, b in split)
        return f'<div class="solutions cols">{columns}</div>'

    def answers_html(self, standalone: bool) -> str:
        out = []
        page_h = PAGE_CONTENT_H[self.page]
        if standalone:
            sols = self.solutions_html(page_h - 32.0)
            out.append(
                f'<header class="solhead"><h1>{esc(self.t("solutions"))}</h1>'
                f'<p class="standfirst">{self.tl(self.ws.title, "i")}</p></header>'
                f'<section class="sol-sec">{sols}</section>'
            )
        else:
            sols = self.solutions_html(page_h - 12.0)
            out.append(f'<section class="back newpage sol-sec"><h2 class="big">'
                       f'{esc(self.t("solutions"))}</h2>{sols}</section>')
        if self.opts.translations and any(b.scene.translation for b in self.plan.scenes):
            out.append(f'<section class="back trans-sec"><h2 class="big">{esc(self.t("translation"))}'
                       f'</h2><div class="translations">{self.translations_html()}</div></section>')
        return "".join(out)

    # -- document --------------------------------------------------------------

    def header_title(self) -> str:
        return self.fit_header(self.ws.title, "serif-italic", 9.0 if self.epaper else 8.5)

    def header_html(self) -> str:
        right = f"{locale.endonym(self.src)} → {locale.endonym(self.tgt)} · {self.ws.cefr_level}"
        # the title (or a "continued" label) comes from the named strings in header_css()
        return (f'<div class="pageheader"><span class="hl"><span class="t tl"{self.lang_attr()}>'
                f'</span><span class="c"></span></span><span class="r">{esc(right)}</span></div>')

    def _collect_prompts(self) -> list[tuple[str, str]]:
        prompts = []
        for block in self.plan.scenes:
            pic = block.scene.picture
            if pic is not None and pic.prompt:
                if not pic.has_visual or self.picture(block.scene) is None:
                    prompts.append((block.scene.id, pic.prompt))
        return prompts

    def build(self, part: Part = "all") -> str:
        body: list[str] = [self.header_html()]
        if part in ("worksheet", "all"):
            body.append(self.worksheet_html())
            body.append(self.back_matter_html())
        if part == "solutions" or (part == "all" and self.opts.solutions != "none"):
            body.append(self.answers_html(standalone=part == "solutions"))
        self.image_prompts = self._collect_prompts()
        comments = []
        for block in self.plan.scenes:
            pic = block.scene.picture
            if pic is not None and pic.prompt:
                comments.append(f"<!-- image prompt · scene {comment_safe(block.scene.id)}: "
                                f"{comment_safe(pic.prompt)} -->")
        classes = [f"page-{self.opts.page}"]
        if self.opts.one_task_per_page:
            classes.append("otp")
        title = self.ws.title
        if part == "solutions":
            title = f"{self.t('solutions')} · {title}"
        direction = ' dir="rtl"' if self.src_dir == "rtl" else ""
        return (
            "<!DOCTYPE html>\n"
            f'<html lang="{esc(self.src)}"{direction} class="{" ".join(classes)}">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="generator" content="langwich 3">\n'
            f"<title>{esc(title)}</title>\n"
            + "".join(c + "\n" for c in comments)
            + f"<style>\n{FONT_MARKER}\n{stylesheet(self.opts.page)}"
            f"{header_css(self.header_title())}</style>\n</head>\n"
            f'<body>\n{"".join(body)}\n</body>\n</html>\n'
        )
