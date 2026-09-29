"""Lay out a crossword grid from the answers the LLM wrote.

The LLM writes every word and every clue of a ``crossword`` task; this
module only arranges the words in a grid — arrangement, like the planner's
shuffles, not content. The layout depends on the answers alone (no render
seed), so the validator sees the same grid as every render of the worksheet.

Letters are compared by ``.lower()`` and printed in upper case, one per
cell (a letter whose upper case is longer, such as ß, stays as it is; see
:func:`printed` for the capitals of Turkish, Azeri and Greek).
"""

from __future__ import annotations

import functools
import random
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass

from langwich.locale import base_lang


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
    """The grid: its size, the placed words (in clue order: across by number,
    then down by number) and the letter of every cell."""

    rows: int
    cols: int
    placed: tuple[Placed, ...]
    unplaced: tuple[int, ...]          # indices that could not be joined to the grid
    cells: Mapping[tuple[int, int], str]  # (row, col) -> letter in upper case (see printed)


#: Longest side of the grid in cells; fits e-paper (141.8 mm) at 7 mm per cell.
MAX_SIDE = 18

#: Shuffled word orders tried after the longest-first one (see :func:`layout`).
ORDERS = 40


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


def is_word(answer: str) -> bool:
    """One word of letters, as a grid needs it: no spaces, hyphens,
    apostrophes, digits or underscores (combining marks are fine)."""
    text = unicodedata.normalize("NFC", answer.strip())
    return bool(text) and text[0].isalpha() and all(
        ch.isalpha() or unicodedata.category(ch).startswith("M") for ch in text
    )


#: Languages whose i has a dotted capital, İ (and whose dotless ı has I):
#: the tailored case mappings of Unicode's SpecialCasing.
DOTTED_I_LANGS = frozenset({"tr", "az"})


def printed(word: str, lang: str = "") -> str:
    """``word`` in upper case as the answer key prints it, in the capitals
    of ``lang`` (the target language), character by character: a character
    whose upper case is longer (ß → SS) stays as it is, since each letter
    fills one cell. Turkish and Azeri write i as İ; Greek drops the accent
    (tonos) in capitals, but keeps the diaeresis (καφές → ΚΑΦΕΣ, ΐ → Ϊ)."""
    text = unicodedata.normalize("NFC", word)
    base = base_lang(lang)
    if base == "el":
        # (U+0301 is the tonos once decomposed; ΐ is ι, U+0308, U+0301)
        text = unicodedata.normalize(
            "NFC", unicodedata.normalize("NFD", text).replace("\u0301", ""))
    elif base in DOTTED_I_LANGS:  # (i with a combining dot, as 'İ'.lower() gives it, too)
        text = text.replace("i\u0307", "i").replace("i", "İ")
    return "".join(ch.upper() if len(ch.upper()) == 1 else ch for ch in text)


def layout(answers: list[str]) -> Layout:
    """The grid for ``answers`` (deterministic: the same answers always give
    the same grid). Words that cannot be joined to it are ``unplaced``.

    Each attempt places the words one by one in a given order: the first
    across, every next one where it crosses placed words at the same letters
    (by ``.lower()``) — the position with the most crossings, then the
    smallest grid, no side longer than :data:`MAX_SIDE`. The cells before
    and after a word stay empty, and a new letter has no letter on either
    side of it (above and below an across word), so every run of letters in
    the grid is exactly one answer. A word that fits nowhere yet is tried
    again at the end of the attempt, until no more fit. The longest-first
    order and :data:`ORDERS` shuffled ones (seeded by the answers) are
    tried; the best attempt places the most words, then has the most
    crossings, then the smallest area. A grid taller than wide is turned on
    its side (across words become down words): the page has more room
    across than down.
    """
    return _layout(tuple(answers))


def enclosed(grid: Layout) -> frozenset[tuple[int, int]]:
    """Blank cells that letter cells cut off from the edge of the grid."""
    rows, cols = grid.rows, grid.cols
    outside = {(r, c) for r in range(-1, rows + 1) for c in (-1, cols)}
    outside |= {(r, c) for r in (-1, rows) for c in range(cols)}
    todo = list(outside)
    while todo:
        r, c = todo.pop()
        for cell in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if (0 <= cell[0] < rows and 0 <= cell[1] < cols and cell not in outside
                    and cell not in grid.cells):
                outside.add(cell)
                todo.append(cell)
    return frozenset(
        (r, c) for r in range(rows) for c in range(cols)
        if (r, c) not in grid.cells and (r, c) not in outside
    )


def black_cells(grid: Layout) -> frozenset[tuple[int, int]]:
    """The blank cells the renderer fills in (the black squares of a printed
    crossword): the :func:`enclosed` holes only one cell wide (no 2 × 2
    block), which their neighbours' borders frame like letter boxes. A wider
    hole is open space and stays white, like the blank cells outside the
    words, instead of printing as a large black block."""
    holes = set(enclosed(grid))
    black: set[tuple[int, int]] = set()
    while holes:
        todo = [holes.pop()]
        hole = set(todo)
        while todo:
            r, c = todo.pop()
            for cell in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
                if cell in holes:
                    holes.remove(cell)
                    hole.add(cell)
                    todo.append(cell)
        if not any({(r + 1, c), (r, c + 1), (r + 1, c + 1)} <= hole for r, c in hole):
            black |= hole
    return frozenset(black)


_Cell = tuple[int, int]

# While placing, a cell is one int (row * _STRIDE + col, both shifted by
# _ORIGIN so they stay positive): one step across is +1, one step down is
# +_STRIDE. A grid never reaches further than MAX_SIDE cells from its first word.
_STRIDE = 4 * MAX_SIDE
_ORIGIN = 2 * MAX_SIDE


@dataclass
class _Attempt:
    """The words of one attempt, as (index, row, col, across) in the order
    they were placed."""

    words: list[tuple[int, int, int, bool]]
    unplaced: list[int]
    crossings: int
    rows: int
    cols: int

    def rank(self) -> tuple[int, int, int, int]:
        """Smaller is better: fewest unplaced words, most crossings, smallest
        area, then the shorter side (fewer rows once a tall grid is turned)."""
        return (len(self.unplaced), -self.crossings, self.rows * self.cols,
                min(self.rows, self.cols))


def _attempt(keys: list[list[str]], order: list[int]) -> _Attempt:
    """Place the words in ``order`` (see :func:`layout`)."""
    grid: dict[int, str] = {}
    across: set[int] = set()
    down: set[int] = set()
    by_letter: dict[str, list[int]] = {}
    words: list[tuple[int, int, bool]] = []  # (index, first cell, across)
    box = [0, 0, 0, 0]  # top, bottom, left, right (inclusive)
    crossings = 0

    def put(index: int, start: int, is_across: bool) -> None:
        step = 1 if is_across else _STRIDE
        own = across if is_across else down
        for p, ch in enumerate(keys[index]):
            cell = start + p * step
            if cell not in grid:
                grid[cell] = ch
                by_letter.setdefault(ch, []).append(cell)
            own.add(cell)
        row, col = divmod(start, _STRIDE)
        last_row, last_col = divmod(start + (len(keys[index]) - 1) * step, _STRIDE)
        if words:
            box[:] = [min(box[0], row), max(box[1], last_row),
                      min(box[2], col), max(box[3], last_col)]
        else:
            box[:] = [row, last_row, col, last_col]
        words.append((index, start, is_across))

    def best_spot(index: int) -> tuple[int, int, bool] | None:
        """(crossings, first cell, across) of the best position, or ``None``."""
        word = keys[index]
        n = len(word)
        best: tuple[int, int, bool] | None = None
        best_rank = (0, 0)
        tried: set[int] = set()
        top0, bottom0, left0, right0 = box
        for p, ch in enumerate(word):
            for hit in by_letter.get(ch, ()):
                if hit in across:
                    if hit in down:
                        continue  # already crossed: no third word through it
                    is_across, step, side = False, _STRIDE, 1
                else:
                    is_across, step, side = True, 1, _STRIDE
                start = hit - p * step
                if 2 * start + is_across in tried:
                    continue
                tried.add(2 * start + is_across)
                if start - step in grid or start + n * step in grid:
                    continue  # it would run on into another word
                row, col = divmod(start, _STRIDE)
                last_row, last_col = (row, col + n - 1) if is_across else (row + n - 1, col)
                top = row if row < top0 else top0
                bottom = last_row if last_row > bottom0 else bottom0
                left = col if col < left0 else left0
                right = last_col if last_col > right0 else right0
                if bottom - top >= MAX_SIDE or right - left >= MAX_SIDE:
                    continue
                own = across if is_across else down
                crosses = 0
                cell = start
                for letter in word:
                    have = grid.get(cell)
                    if have is None:
                        # a new letter: nothing beside it across the word
                        if cell + side in grid or cell - side in grid:
                            break
                    elif have != letter or cell in own:
                        break
                    else:
                        crosses += 1
                    cell += step
                else:
                    rank = (crosses, -(bottom - top + 1) * (right - left + 1))
                    if best is None or rank > best_rank:
                        best, best_rank = (crosses, start, is_across), rank
        return best

    unplaced: list[int] = []
    waiting: list[int] = []
    for index in order:
        if not 2 <= len(keys[index]) <= MAX_SIDE:
            unplaced.append(index)
            continue
        spot = best_spot(index) if words else (0, _ORIGIN * _STRIDE + _ORIGIN, True)
        if spot is None:
            waiting.append(index)
        else:
            crossings += spot[0]
            put(index, spot[1], spot[2])
    while waiting:  # a word placed later may have made room: try the rest again
        still = []
        for index in waiting:
            spot = best_spot(index)
            if spot is None:
                still.append(index)
            else:
                crossings += spot[0]
                put(index, spot[1], spot[2])
        if len(still) == len(waiting):
            break
        waiting = still
    placed = [(index, *divmod(start, _STRIDE), is_across) for index, start, is_across in words]
    return _Attempt(placed, sorted(unplaced + waiting), crossings,
                    box[1] - box[0] + 1 if words else 0, box[3] - box[2] + 1 if words else 0)


@functools.lru_cache(maxsize=64)
def _layout(answers: tuple[str, ...]) -> Layout:
    shapes = [letters(a) for a in answers]
    keys = [[ch.lower() for ch in word] for word in shapes]
    first = sorted(range(len(answers)), key=lambda i: (-len(keys[i]), i))
    rng = random.Random("crossword:" + "\x1f".join(answers))
    best = _attempt(keys, first)
    for _ in range(ORDERS):
        order = list(first)
        rng.shuffle(order)
        attempt = _attempt(keys, order)
        if attempt.rank() < best.rank():
            best = attempt
    return _finish(best, shapes)


def _finish(best: _Attempt, shapes: list[list[str]]) -> Layout:
    """Move the grid to (0, 0), turn a tall one on its side, number it."""
    if not best.words:
        return Layout(rows=0, cols=0, placed=(), unplaced=tuple(best.unplaced), cells={})
    top = min(row for _, row, _, _ in best.words)
    left = min(col for _, _, col, _ in best.words)
    words = [(i, row - top, col - left, across) for i, row, col, across in best.words]
    rows, cols = best.rows, best.cols
    if rows > cols:
        words = [(i, col, row, not across) for i, row, col, across in words]
        rows, cols = cols, rows
    cells: dict[_Cell, str] = {}
    for i, row, col, across in words:
        dr, dc = (0, 1) if across else (1, 0)
        for p, ch in enumerate(shapes[i]):
            cells.setdefault((row + dr * p, col + dc * p), printed(ch))
    starts = sorted({(row, col) for _, row, col, _ in words})
    numbers = {cell: n for n, cell in enumerate(starts, 1)}
    placed = sorted(
        (Placed(i, row, col, across, numbers[(row, col)]) for i, row, col, across in words),
        key=lambda p: (not p.across, p.number),
    )
    return Layout(rows=rows, cols=cols, placed=tuple(placed), unplaced=tuple(best.unplaced),
                  cells=cells)
