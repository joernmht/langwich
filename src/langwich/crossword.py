"""Lay out a crossword grid from the answers the LLM wrote.

The LLM writes every word and every clue of a ``crossword`` task; this
module only arranges the words in a grid — arrangement, like the planner's
shuffles, not content. The layout depends on the answers alone (no render
seed), so the validator sees the same grid as every render of the worksheet.

Letters are compared by ``.lower()`` and printed in upper case, one per
cell (a letter whose upper case is longer, such as ß, stays as it is).
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Placed:
    """One word in the grid."""

    index: int      # index into the answers
    row: int
    col: int
    across: bool
    number: int     # clue number printed in the first cell


@dataclass(frozen=True)
class Layout:
    """The grid: its size, the placed words and the letter of every cell."""

    rows: int
    cols: int
    placed: tuple[Placed, ...]
    unplaced: tuple[int, ...]          # indices that could not be joined to the grid
    cells: Mapping[tuple[int, int], str]  # (row, col) -> letter as printed in the key (upper case)


#: Longest side of the grid in cells; fits e-paper (141.8 mm) at 7 mm per cell.
MAX_SIDE = 18


def letters(word: str) -> list[str]:
    """The letters of ``word``, one entry per grid cell: the word in NFC with
    every combining mark kept on its letter ('é' typed as e + U+0301 is one
    cell). Compare entries with ``.lower()``."""
    out: list[str] = []
    for ch in unicodedata.normalize("NFC", word.strip()):
        if out and unicodedata.combining(ch):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def layout(answers: list[str]) -> Layout:
    """The grid for ``answers`` (deterministic: the same answers always give
    the same grid). Words that cannot be joined to it are ``unplaced``."""
    # (spine stub: the crossword implementation places the words)
    return Layout(rows=0, cols=0, placed=(), unplaced=tuple(range(len(answers))), cells={})
