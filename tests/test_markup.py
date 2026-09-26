"""Gap markup: {{answer|alternative::hint}}."""

from __future__ import annotations

import pytest

from langwich import markup


def test_split_and_fill():
    parts = markup.split("Die Bohnen {{werden}} {{geröstet::rösten}}.")
    assert parts[0] == "Die Bohnen "
    assert parts[1] == markup.Gap("werden")
    assert parts[3] == markup.Gap("geröstet", (), "rösten")
    assert markup.fill("Die Bohnen {{werden}} {{geröstet::rösten}}.") == "Die Bohnen werden geröstet."


def test_alternatives_and_hint():
    gap = markup.gaps("Sie trinkt ihn {{schwarz | ohne Milch :: black}}.")[0]
    assert gap.answer == "schwarz"
    assert gap.alternatives == ("ohne Milch",)
    assert gap.hint == "black"
    assert gap.accepted == ("schwarz", "ohne Milch")


def test_text_without_gaps():
    assert markup.gaps("Kein Loch hier.") == []
    assert markup.split("Kein Loch hier.") == ["Kein Loch hier."]


def test_empty_gap_is_an_error():
    with pytest.raises(ValueError):
        markup.gaps("Ein {{ | }} Fehler.")


def test_unbalanced_braces():
    assert markup.has_unbalanced_braces("Ein {{Test} hier.")
    assert markup.has_unbalanced_braces("Ein Test}} hier.")
    assert not markup.has_unbalanced_braces("Ein {{Test}} hier.")
