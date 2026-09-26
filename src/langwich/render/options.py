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


@dataclass
class RenderResult:
    html: Path
    pdf: Path | None               # None when html_only or WeasyPrint is unavailable
    solutions_pdf: Path | None
    pages: int | None
    warnings: list[str] = field(default_factory=list)
    image_prompts: list[tuple[str, str]] = field(default_factory=list)
    weasyprint_error: str | None = None
