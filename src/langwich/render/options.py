"""Render options and results (shared by the HTML builder and the PDF writer)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class RenderOptions:
    page: Literal["a4", "epaper"] = "a4"
    one_task_per_page: bool = False
    solutions: Literal["append", "separate", "none"] = "append"
    translations: bool = True      # print scene translations in the answer section
    monochrome: bool = True        # False when the user passes --allow-color
    seed: int | None = None        # passed to plan(); None = derived from the JSON
    base_dir: Path | None = None   # folder of the JSON file; relative image paths resolve against it
    html_only: bool = False        # write the .html only, no PDF


@dataclass(frozen=True)
class LayoutHints:
    """Corrections from a first layout pass (see ``render_worksheet``).

    ``build_html`` estimates page breaks; after WeasyPrint has laid the pages
    out, the renderer may build once more with these hints.
    """

    #: numbers of picture tasks that must not share a keep-together unit with
    #: the label task before them (the pair did not fit on one page); they get
    #: a small copy of the picture instead
    unpair: frozenset[int] = frozenset()
    #: set the word list tighter (a few rows spilled onto an almost empty
    #: page): 0 = normal, 1 = tighter rows, 2 = also smaller type
    compact_words: int = 0
    #: tasks kept whole only for convenience (word box or grammar beside the
    #: items) that may break between items, so the page before them is not
    #: left almost empty; their boxes move above the items
    flow: frozenset[int] = frozenset()
    #: flowing tasks whose header may stay with just their grammar/word box
    #: (or first item) at the foot of a page that would otherwise stay half empty
    loose: frozenset[int] = frozenset()
    #: (task number, mm): a smaller picture, or a lower drawing frame, so the
    #: task fits the space left on the page before
    shrink: tuple[tuple[int, float], ...] = ()

    def shrink_for(self, number: int) -> float | None:
        return next((mm for n, mm in self.shrink if n == number), None)


@dataclass
class RenderResult:
    html: Path
    pdf: Path | None               # None when html_only or WeasyPrint is unavailable
    solutions_pdf: Path | None
    pages: int | None
    warnings: list[str] = field(default_factory=list)
    image_prompts: list[tuple[str, str]] = field(default_factory=list)
    weasyprint_error: str | None = None
