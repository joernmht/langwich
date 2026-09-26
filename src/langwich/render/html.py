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
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from typing import Literal

from langwich import locale
from langwich.answers import answer_key
from langwich.images import PreparedPicture, prepare_picture
from langwich.model import (
    POS_VALUES,
    ClozeTask,
    Fact,
    GrammarPoint,
    LabelTask,
    OrderEventsTask,
    Scene,
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
    stylesheet,
)
from langwich.render.options import RenderOptions

Part = Literal["worksheet", "solutions", "all"]

#: Placeholder in the ``<style>`` element where the ``@font-face`` rules go.
FONT_MARKER = "/*@font-face*/"

#: Largest picture height in mm (so the numbered answer grid fits below it).
MAX_PICTURE_H = {"a4": 118.0, "epaper": 92.0}

#: How far (mm) the side column of a scene's last paragraph may outgrow the
#: text before further sidebars move into a band below the scene.
BAND_SLACK = 30.0

#: Paragraph rows (text + side notes) up to this height never split across pages.
KEEP_ROW_MM = 90.0

_TRANSLATE = str.maketrans({" ": " ", "‑": "-"})

#: Word-list group headings for the built-in languages (not in locale.py yet).


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------


def esc(text: str | None) -> str:
    """HTML-escape user text (quotes included). Characters the bundled fonts
    lack are mapped to close equivalents so no host font is pulled in."""
    return _html.escape((text or "").translate(_TRANSLATE), quote=True)


def esc_br(text: str | None) -> str:
    return esc(text).replace("\n", "<br>")


def comment_safe(text: str) -> str:
    """Text that can sit inside an HTML comment."""
    return text.replace("--", "–").replace("<", "‹").replace(">", "›")


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
    ):
        self.ws = ws
        self.opts = options or RenderOptions()
        self.plan = plan(ws, self.opts.seed)
        self.epaper = self.opts.page == "epaper"
        self.content_w = EPAPER_CONTENT_W if self.epaper else A4_CONTENT_W
        self.src = ws.source_lang
        self.tgt = ws.target_lang
        self.warnings: list[str] = []
        self.image_prompts: list[tuple[str, str]] = []
        #: per-render picture cache (scene id → prepared picture), may be shared
        self._pictures: dict[str, PreparedPicture | None] = {} if pictures is None else pictures
        self.scene_numbers = {b.scene.id: b.number for b in self.plan.scenes}
        self.picture_host = self._picture_hosts()
        self._vocab_terms = {strip_article(v.term, ws.target_lang).casefold() for v in ws.vocabulary.items}
        self._vocab_translations: set[str] = set()
        for v in ws.vocabulary.items:
            self._vocab_translations.add(v.translation.casefold())
            self._vocab_translations.update(
                p.strip().casefold() for p in re.split(r"[,;/]", v.translation) if p.strip()
            )

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
        return f' lang="{esc(self.tgt)}"'

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

    def main_width(self, with_aside: bool) -> float:
        if self.epaper:
            return self.content_w
        return MAIN_W if with_aside else self.content_w

    def blank_width(self, answers: list[str], with_aside: bool) -> float:
        widest = max((metrics.width_mm(a, "serif", 11.0) for a in answers), default=14.0)
        avail = self.main_width(with_aside) - GUTTER_W
        return round(min(max(widest + 7.0, 18.0), avail * 0.72), 1)

    def pos_name(self, pos: str) -> str:
        return self.t(f"pos.{pos}")

    # -- pictures ------------------------------------------------------------

    def _picture_hosts(self) -> dict[str, int]:
        """Scene id → number of the task that shows the scene's picture."""
        hosts: dict[str, int] = {}
        for pt in self.plan.tasks:
            if isinstance(pt.task, LabelTask) and pt.task.scene not in hosts:
                hosts[pt.task.scene] = pt.number
        for pt in self.plan.tasks:
            if pt.task.stage == "picture":
                for sid in pt.task.scene_ids:
                    hosts.setdefault(sid, pt.number)
        return hosts

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

    def figure_html(self, scene: Scene, prepared: PreparedPicture) -> str:
        pic = scene.picture
        assert pic is not None
        frame = 0.71  # two 1pt borders
        w = self.content_w - frame
        h = w * prepared.aspect
        max_h = MAX_PICTURE_H["epaper" if self.epaper else "a4"]
        if h > max_h:
            h = max_h
            w = h / prepared.aspect
        alt = pic.caption or scene.heading
        img = (f'<img src="{prepared.data_uri}" alt="{esc(alt)}" '
               f'style="width:{w:.2f}mm;height:{h:.2f}mm">')
        marks: list[str] = []
        if not pic.numbers_in_image:
            for lb in sorted(pic.labels, key=lambda lb: lb.n):
                if lb.x is None or lb.y is None:
                    self.warn(f"scene {scene.id!r}: label {lb.n} has no x/y position; "
                              "its marker is not drawn.")
                    continue
                cx = min(max(lb.x * w, 3.0), w - 3.0)
                cy = min(max(lb.y * h, 3.0), h - 3.0)
                marks.append(f'<span class="mk" style="left:{cx - 3:.2f}mm;top:{cy - 3:.2f}mm">'
                             f"{lb.n}</span>")
        caption = ""
        bits = []
        if pic.caption:
            bits.append(self.tl(pic.caption))
        if pic.credit:
            bits.append(esc(pic.credit))
        if bits:
            caption = f'<figcaption class="figcap">{" · ".join(bits)}</figcaption>'
        return (f'<figure class="fig"><div class="pic" style="width:{w:.2f}mm;height:{h:.2f}mm">'
                f'{img}{"".join(marks)}</div>{caption}</figure>')

    # -- small blocks --------------------------------------------------------

    def phase_html(self, step: int, label: str) -> str:
        return (f'<div class="phase"><span class="step">{step}</span>{esc(label)}'
                f'<span class="rule"></span></div>')

    def word_box(self, words: list[str], row: bool = False, cap: str | None = None) -> str:
        items = "".join(f"<li>{esc(w)}</li>" for w in words)
        klass = "box wordbox row" if row else "box wordbox"
        return (f'<div class="{klass}"><span class="cap">{esc(cap or self.t("word_box"))}</span>'
                f'<ul class="words tl"{self.lang_attr()}>{items}</ul></div>')

    def lines(self, count: int, starter: str | None = None) -> str:
        if count <= 0:
            return ""
        rows = []
        if starter:
            rows.append(f'<div class="starter tl"{self.lang_attr()}>{esc(starter)}</div>')
        rows.extend("<div></div>" for _ in range(count - len(rows)))
        return f'<div class="lines">{"".join(rows)}</div>'

    def grammar_html(self, gp: GrammarPoint, cap: bool = True) -> str:
        parts = [f'<span class="cap">{esc(self.t("grammar"))}</span>' if cap else "",
                 f'<div class="nm">{esc(gp.name)}</div>',
                 f"<div>{esc(gp.explanation)}</div>"]
        if gp.rule:
            parts.append(self.tl(gp.rule, "div", "rule"))
        if gp.table and gp.table.rows:
            head = ""
            if gp.table.head and any(h.strip() for h in gp.table.head):
                head = "<tr>" + "".join(f"<th>{esc(h)}</th>" for h in gp.table.head) + "</tr>"
            body = "".join(
                "<tr>" + "".join(f"<td>{esc(c)}</td>" for c in row) + "</tr>" for row in gp.table.rows
            )
            wide = max(len(r) for r in gp.table.rows) >= 3 and not self.epaper
            klass = ' class="wide"' if wide else ""
            parts.append(f"<table{klass}{self.lang_attr()}>{head}{body}</table>")
        if gp.examples:
            exs = "".join(f"<div>{esc(e)}</div>" for e in gp.examples)
            parts.append(f'<div class="ex tl"{self.lang_attr()}>{exs}</div>')
        return f'<div class="snippet">{"".join(parts)}</div>'

    def fact_html(self, fact: Fact) -> str:
        title = self.tl(fact.title, "div", "ft") if fact.title else ""
        source = (f'<div class="fsrc">{esc(self.t("source"))}: {esc(fact.source)}</div>'
                  if fact.source else "")
        return (f'<div class="fact"><span class="cap">{esc(self.t("did_you_know"))}</span>'
                f'{title}{self.tl(fact.text, "p")}{source}</div>')

    def sidebar_html(self, sb: Sidebar) -> str:
        if sb.grammar is not None:
            return self.grammar_html(sb.grammar)
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

    def task_instruction(self, pt: PlannedTask) -> str:
        task = pt.task
        if isinstance(task, LabelTask) and self.is_label_draw(pt):
            scene = self.ws.scene(task.scene)
            heading = scene.heading if scene else task.scene
            before, _, after = self.t("kind.label.draw", scene="\x00").partition("\x00")
            return esc(before) + self.tl(heading) + esc(after)
        if task.instruction:
            text = esc(task.instruction)
        elif isinstance(task, ClozeTask):
            text = esc(self.t(f"kind.cloze.{task.hint}"))
        else:
            text = esc(self.t(f"kind.{task.kind}.instruction"))
        if isinstance(task, WritingTask):
            length = None
            if task.min_words and task.max_words:
                length = self.t("kind.writing.length", min=task.min_words, max=task.max_words)
            elif task.max_words:
                length = f"≤ {task.max_words} {self.t('words')}"
            elif task.min_words:
                length = f"≥ {task.min_words} {self.t('words')}"
            if length:
                text += f' <span class="len">{esc(length)}</span>'
        return text

    def scene_ref(self, pt: PlannedTask) -> str:
        nums = [self.scene_numbers[s] for s in pt.task.scene_ids if s in self.scene_numbers]
        if not nums:
            return ""
        return f'<span class="src">{esc(self.t("scene"))} {number_ranges(nums)}</span>'

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
            side_parts.extend(self.sidebar_html(sb) for sb in sidebars_here)
            side = f'<div class="side">{"".join(side_parts)}</div>' if side_parts else ""
            keep = " keep" if max(para_h[i], side_h[i]) < KEEP_ROW_MM else ""
            para_html.append(
                f'<div class="para{keep}"><div class="txt"><p class="tl"{self.lang_attr()}>'
                f"{self._paragraph_html(text, s, e, spans)}</p></div>{side}</div>"
            )
        if band:
            para_html.append(f'<div class="notes-band n{min(len(band), 3)}">'
                             f'{"".join(self.sidebar_html(sb) for sb in band)}</div>')

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
        if not isinstance(task, LabelTask):
            for sid in task.scene_ids:
                scene = self.ws.scene(sid)
                if scene is not None and self.picture_host.get(sid) == pt.number:
                    prepared = self.picture(scene)
                    if prepared is not None:
                        pre = self.figure_html(scene, prepared) + pre
        aside = list(parts.aside) + [self.sidebar_html(sb) for sb in pt.sidebars]
        header = (
            f'<header class="th"><span class="tn">{pt.number}</span>'
            f"<h3>{esc(self.task_title(pt))}</h3>{self.scene_ref(pt)}"
            f'<p class="ins">{self.task_instruction(pt)}</p></header>'
        )
        if pre:
            pre = f'<div class="pre">{pre}</div>'
        if aside:
            body = (f'<div class="body"><div class="main">{parts.main}</div>'
                    f'<aside class="aside-stack">{"".join(aside)}</aside></div>')
        else:
            body = f'<div class="body full"><div class="main">{parts.main}</div></div>'
        keep = " keep" if parts.keep or pre else ""
        return (f'<section class="task unit k-{task.kind}{keep}" id="task-{pt.number}">'
                f"{phase}{header}{pre}{body}</section>")

    # -- the worksheet part ----------------------------------------------------

    def worksheet_html(self) -> str:
        p = self.plan
        out = [self.cover_html()]
        step = 0
        if p.before:
            step += 1
            cap = self.phase_html(step, self.t("phase.before"))
            out.extend(self.task_html(pt, cap if i == 0 else "") for i, pt in enumerate(p.before))
        step += 1
        read_cap = self.phase_html(step, self.t("read"))
        for i, block in enumerate(p.scenes):
            out.append(self.scene_html(block, read_cap if i == 0 else "", first=i == 0))
            out.extend(self.task_html(pt) for pt in block.tasks)
        for group, key in ((p.your_turn, "phase.your_turn"), (p.further, "phase.further")):
            if group:
                step += 1
                cap = self.phase_html(step, self.t(key))
                out.extend(self.task_html(pt, cap if i == 0 else "") for i, pt in enumerate(group))
        series = self.ws.series
        if series and series.next:
            out.append(
                f'<aside class="teaser"><span class="cap">{esc(self.t("next_episode"))}</span>'
                f'<p class="ep">{esc(series.title)} · {esc(self.t("episode"))} {series.episode + 1}</p>'
                f"<p>{esc_br(series.next)}</p></aside>"
            )
        return "".join(out)

    # -- back matter -----------------------------------------------------------

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
            for v in items:
                key = " key" if v.term.casefold() in targets else ""
                plural = plural_note(v, self.tgt)
                plural_html = f"<i>, {esc(plural)}</i>" if plural else ""
                forms = f'<span class="forms">{esc(v.forms)}</span>' if v.forms else ""
                note = f" <i>({esc(v.note)})</i>" if v.note else ""
                rows.append(
                    f'<div class="vl"><span class="de tl{key}"{self.lang_attr()}>{esc(v.term)}'
                    f'{plural_html}{forms}</span><span class="en">{esc(v.translation)}{note}</span></div>'
                )
            groups.append("".join(rows))
        return (f'<section class="back words-sec"><h2 class="big">{esc(self.t("word_list"))}</h2>'
                f'<div class="vocab-list">{"".join(groups)}</div></section>')

    def back_matter_html(self) -> str:
        out = [self.word_list_html()]
        if self.plan.reference_grammar:
            snippets = "".join(self.grammar_html(g, cap=False) for g in self.plan.reference_grammar)
            out.append(f'<section class="back"><h2 class="big">{esc(self.t("grammar"))}</h2>'
                       f'<div class="ref-grammar">{snippets}</div></section>')
        return "".join(out)

    # -- answers ---------------------------------------------------------------

    def key_for(self, pt: PlannedTask) -> list[str]:
        if self.is_label_draw(pt):
            return []
        return answer_key(pt, self.ws)

    def key_numbers(self, pt: PlannedTask, count: int) -> list[str] | None:
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
        key = self.key_for(pt)
        if key:
            numbers = self.key_numbers(pt, len(key))
            entries = []
            for i, k in enumerate(key):
                num = f'<span class="kn">{numbers[i]}</span> ' if numbers else ""
                entries.append(f'{num}<span class="k"{self.lang_attr()}>{esc(k)}</span>')
            if max(len(k) for k in key) > 32:
                content = "<ol>" + "".join(f"<li>{e}</li>" for e in entries) + "</ol>"
            else:
                content = " · ".join(entries)
        elif isinstance(task, WritingTask) and task.model_answer:
            content = (f'<i>{esc(self.t("model_answer"))}:</i> '
                       f'<span class="model"{self.lang_attr()}>{esc(task.model_answer)}</span>')
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
            paras = "".join(f"<p>{esc_br(p.strip())}</p>"
                            for p in scene.translation.split("\n\n") if p.strip())
            blocks.append(f'<div class="tr"><h4><span class="num">{block.number}</span>'
                          f'{self.tl(scene.heading)}</h4><div lang="{esc(self.src)}">{paras}</div></div>')
        return "".join(blocks)

    def answers_html(self, standalone: bool) -> str:
        out = []
        sols = "".join(self.solution_block(pt) for pt in self.plan.tasks)
        if standalone:
            out.append(
                f'<header class="solhead"><h1>{esc(self.t("solutions"))}</h1>'
                f'<p class="standfirst">{self.tl(self.ws.title, "i")}</p></header>'
                f'<section class="sol-sec"><div class="solutions">{sols}</div></section>'
            )
        else:
            out.append(f'<section class="back newpage sol-sec"><h2 class="big">'
                       f'{esc(self.t("solutions"))}</h2><div class="solutions">{sols}</div></section>')
        if self.opts.translations and any(b.scene.translation for b in self.plan.scenes):
            out.append(f'<section class="back trans-sec"><h2 class="big">{esc(self.t("translation"))}'
                       f'</h2><div class="translations">{self.translations_html()}</div></section>')
        return "".join(out)

    # -- document --------------------------------------------------------------

    def header_html(self) -> str:
        right = f"{locale.endonym(self.src)} → {locale.endonym(self.tgt)} · {self.ws.cefr_level}"
        room = self.content_w - metrics.width_mm(right, "sans-bold", 8.0) - 8.0
        title = self.ws.title
        if metrics.width_mm(title, "serif-italic", 8.5) > room:
            words = title.split()
            while len(words) > 1 and metrics.width_mm(" ".join(words) + " …", "serif-italic", 8.5) > room:
                words.pop()
            title = " ".join(words).rstrip(",;:–-") + " …"
        return (f'<div class="pageheader"><span class="t tl"{self.lang_attr()}>{esc(title)}'
                f'</span><span class="r">{esc(right)}</span></div>')

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
        return (
            "<!DOCTYPE html>\n"
            f'<html lang="{esc(self.src)}" class="{" ".join(classes)}">\n<head>\n'
            '<meta charset="utf-8">\n'
            '<meta name="generator" content="langwich 3">\n'
            f"<title>{esc(title)}</title>\n"
            + "".join(c + "\n" for c in comments)
            + f"<style>\n{FONT_MARKER}\n{stylesheet(self.opts.page)}</style>\n</head>\n"
            f'<body>\n{"".join(body)}\n</body>\n</html>\n'
        )
