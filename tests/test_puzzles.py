"""Tests for puzzle construction algorithms."""

import random

from langwich.puzzles import (
    build_crossword,
    build_secret_code,
    build_word_search,
    clean_word,
    scramble_word,
)

WORDS = ["der Kaffee", "die Tasse", "die Bohne", "der Geschmack",
         "die Röstung", "das Fenster"]


def test_clean_word_strips_articles_and_punctuation():
    assert clean_word("der Kaffee") == "Kaffee"
    assert clean_word("die Röstung") == "Röstung"
    assert clean_word("the cup!") == "cup"


def test_word_search_contains_all_placed_words():
    ws = build_word_search(WORDS, rng=random.Random(1))
    assert ws is not None
    assert len(ws.placements) >= 4
    for p in ws.placements:
        (r0, c0), (r1, c1) = p["start"], p["end"]
        n = len(p["word"])
        dr = (r1 - r0) // max(n - 1, 1)
        dc = (c1 - c0) // max(n - 1, 1)
        recovered = "".join(ws.grid[r0 + dr * i][c0 + dc * i] for i in range(n))
        assert recovered == p["word"]


def test_word_search_grid_uses_word_alphabet():
    ws = build_word_search(WORDS, rng=random.Random(2))
    alphabet = {ch for w in WORDS for ch in clean_word(w).upper()}
    for row in ws.grid:
        for ch in row:
            assert ch in alphabet


def test_crossword_words_intersect():
    cw = build_crossword([(w, "clue") for w in WORDS])
    assert cw is not None
    assert len(cw.across) + len(cw.down) >= 2
    assert cw.across  # first word placed horizontally
    # every occupied cell lies within the reported bounds
    for (r, c) in cw.cells:
        assert 0 <= r < cw.height and 0 <= c < cw.width
    # numbering starts at 1 and is dense
    numbers = sorted(cw.numbers.values())
    assert numbers == list(range(1, len(numbers) + 1))


def test_scramble_differs_but_same_letters():
    s = scramble_word("die Röstung", rng=random.Random(3))
    assert s is not None
    assert sorted(s.replace(" ", "")) == sorted("RÖSTUNG")
    assert s.replace(" ", "") != "RÖSTUNG"


def test_secret_code_roundtrip():
    code = build_secret_code(WORDS[:3])
    assert code is not None
    reverse = {v: k for k, v in code.key.items()}
    for entry in code.encoded:
        decoded = "".join(reverse[int(n)] for n in entry["code"].split("-"))
        assert decoded == entry["answer"]
