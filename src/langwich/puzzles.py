"""Puzzle construction algorithms for puzzle-type exercises.

Everything here is script-agnostic: filler letters for the word search and
the secret-code alphabet are derived from the input words themselves, so
Cyrillic, kana or Hangul vocabularies work just like Latin ones.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


def clean_word(term: str) -> str:
    """Reduce a term to its letters only (no articles, spaces, punctuation)."""
    for article in ("der ", "die ", "das ", "ein ", "eine ", "el ", "la ",
                    "los ", "las ", "le ", "la ", "les ", "l'", "un ", "une ",
                    "il ", "lo ", "gli ", "o ", "a ", "os ", "as ", "the "):
        if term.lower().startswith(article):
            term = term[len(article):]
            break
    return "".join(ch for ch in term if ch.isalpha())


# ---------------------------------------------------------------------------
# Word search
# ---------------------------------------------------------------------------

@dataclass
class WordSearch:
    grid: list[list[str]]
    placements: list[dict] = field(default_factory=list)
    # each placement: {"word": str, "start": (row, col), "end": (row, col)}


def build_word_search(
    words: list[str],
    size: int | None = None,
    allow_diagonal: bool = True,
    rng: random.Random | None = None,
) -> WordSearch | None:
    """Place uppercase words in a letter grid; fill gaps with letters drawn
    from the words themselves (keeps the grid in the same script)."""
    rng = rng or random.Random()
    cleaned = [clean_word(w).upper() for w in words]
    cleaned = [w for w in cleaned if 3 <= len(w) <= 14]
    if not cleaned:
        return None

    n = size or max(10, max(len(w) for w in cleaned) + 2)
    grid: list[list[str | None]] = [[None] * n for _ in range(n)]

    directions = [(0, 1), (1, 0)]
    if allow_diagonal:
        directions.append((1, 1))

    placements: list[dict] = []
    for word in cleaned:
        placed = False
        for _ in range(300):
            dr, dc = rng.choice(directions)
            max_r = n - 1 - dr * (len(word) - 1)
            max_c = n - 1 - dc * (len(word) - 1)
            if max_r < 0 or max_c < 0:
                break
            r0, c0 = rng.randint(0, max_r), rng.randint(0, max_c)
            cells = [(r0 + dr * i, c0 + dc * i) for i in range(len(word))]
            if all(grid[r][c] is None or grid[r][c] == word[i]
                   for i, (r, c) in enumerate(cells)):
                for i, (r, c) in enumerate(cells):
                    grid[r][c] = word[i]
                placements.append({
                    "word": word,
                    "start": cells[0],
                    "end": cells[-1],
                })
                placed = True
                break
        if not placed:
            continue  # word skipped; puzzle still works with the rest

    if not placements:
        return None

    alphabet = sorted({ch for w in cleaned for ch in w})
    filled = [[cell if cell is not None else rng.choice(alphabet)
               for cell in row] for row in grid]
    return WordSearch(grid=filled, placements=placements)


# ---------------------------------------------------------------------------
# Crossword
# ---------------------------------------------------------------------------

@dataclass
class Crossword:
    width: int
    height: int
    # letter at each occupied cell
    cells: dict[tuple[int, int], str]
    # clue number at word-start cells
    numbers: dict[tuple[int, int], int]
    across: list[dict] = field(default_factory=list)  # {"number", "clue", "answer"}
    down: list[dict] = field(default_factory=list)


def build_crossword(entries: list[tuple[str, str]]) -> Crossword | None:
    """Greedy crossword placement.

    ``entries`` is a list of (answer, clue).  The longest answer is placed
    horizontally; every following word must intersect an already placed one.
    Words that cannot be placed are skipped.
    """
    words = [(clean_word(a).upper(), c) for a, c in entries]
    words = [(a, c) for a, c in words if len(a) >= 3]
    if len(words) < 2:
        return None
    words.sort(key=lambda wc: -len(wc[0]))

    cells: dict[tuple[int, int], str] = {}
    # (word, clue, row, col, horizontal)
    placed: list[tuple[str, str, int, int, bool]] = []

    def can_place(word: str, r: int, c: int, horizontal: bool) -> bool:
        dr, dc = (0, 1) if horizontal else (1, 0)
        # cell before start and after end must be free
        if (r - dr, c - dc) in cells or \
           (r + dr * len(word), c + dc * len(word)) in cells:
            return False
        crosses = 0
        for i, ch in enumerate(word):
            rr, cc = r + dr * i, c + dc * i
            existing = cells.get((rr, cc))
            if existing is not None:
                if existing != ch:
                    return False
                crosses += 1
            else:
                # neighbours perpendicular to the word direction must be free
                pr, pc = (1, 0) if horizontal else (0, 1)
                if (rr + pr, cc + pc) in cells or (rr - pr, cc - pc) in cells:
                    return False
        return crosses > 0

    def place(word: str, clue: str, r: int, c: int, horizontal: bool) -> None:
        dr, dc = (0, 1) if horizontal else (1, 0)
        for i, ch in enumerate(word):
            cells[(r + dr * i, c + dc * i)] = ch
        placed.append((word, clue, r, c, horizontal))

    first_word, first_clue = words[0]
    place(first_word, first_clue, 0, 0, True)

    for word, clue in words[1:]:
        done = False
        for pword, _, pr, pc, phoriz in placed:
            pdr, pdc = (0, 1) if phoriz else (1, 0)
            for i, ch in enumerate(word):
                for j, pch in enumerate(pword):
                    if ch != pch:
                        continue
                    cr, cc = pr + pdr * j, pc + pdc * j
                    horizontal = not phoriz
                    dr, dc = (0, 1) if horizontal else (1, 0)
                    r0, c0 = cr - dr * i, cc - dc * i
                    if can_place(word, r0, c0, horizontal):
                        place(word, clue, r0, c0, horizontal)
                        done = True
                        break
                if done:
                    break
            if done:
                break
        # words that don't fit are silently skipped

    if len(placed) < 2:
        return None

    min_r = min(r for r, _ in cells)
    min_c = min(c for _, c in cells)
    shifted = {(r - min_r, c - min_c): ch for (r, c), ch in cells.items()}

    starts = sorted({(r - min_r, c - min_c) for _, _, r, c, _ in placed})
    numbers = {pos: i + 1 for i, pos in enumerate(starts)}

    across, down = [], []
    for word, clue, r, c, horizontal in placed:
        pos = (r - min_r, c - min_c)
        entry = {"number": numbers[pos], "clue": clue, "answer": word}
        (across if horizontal else down).append(entry)
    across.sort(key=lambda e: e["number"])
    down.sort(key=lambda e: e["number"])

    return Crossword(
        width=max(c for _, c in shifted) + 1,
        height=max(r for r, _ in shifted) + 1,
        cells=shifted,
        numbers=numbers,
        across=across,
        down=down,
    )


# ---------------------------------------------------------------------------
# Letter scramble
# ---------------------------------------------------------------------------

def scramble_word(term: str, rng: random.Random | None = None) -> str | None:
    """Shuffle the letters of a word, guaranteed different from the input."""
    rng = rng or random.Random()
    word = clean_word(term)
    if len(word) < 3 or len(set(word.lower())) < 2:
        return None
    letters = list(word.upper())
    for _ in range(20):
        rng.shuffle(letters)
        if "".join(letters) != word.upper():
            return " ".join(letters)
    return None


# ---------------------------------------------------------------------------
# Secret number code
# ---------------------------------------------------------------------------

@dataclass
class SecretCode:
    key: dict[str, int]  # letter -> number
    encoded: list[dict] = field(default_factory=list)
    # each: {"code": "3-1-7", "answer": "..." }


def build_secret_code(words: list[str]) -> SecretCode | None:
    """Assign a number to every letter used and encode the words."""
    cleaned = [clean_word(w).upper() for w in words]
    cleaned = [w for w in cleaned if len(w) >= 3]
    if not cleaned:
        return None
    alphabet = sorted({ch for w in cleaned for ch in w})
    key = {ch: i + 1 for i, ch in enumerate(alphabet)}
    encoded = [{"code": "-".join(str(key[ch]) for ch in w), "answer": w}
               for w in cleaned]
    return SecretCode(key=key, encoded=encoded)
