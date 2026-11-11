"""The landing page's examples section must match the examples.

``docs/index.html`` lists every bundled example as a card and draws a map of
Europe: choosing a country filters the cards by the languages spoken there.
The cards, the map and the language table are written by hand (the map by
``scripts/build_europe_map.py``), so these tests hold them against the
examples and against each other:

1. every example has exactly one card, with the example's languages and level;
2. every card links to files that exist, and so does the rest of the page;
3. the language table knows every country on the map and every language of
   the cards, and names the languages as langwich does;
4. the map is in place, with one path per country and the projection the
   page's script needs to place the story locations.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

from langwich.locale import ENDONYMS
from langwich.model import CEFR_LEVELS, load_worksheet

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
INDEX = DOCS / "index.html"
EXAMPLES = sorted((REPO_ROOT / "examples").glob("*.json"))
GITHUB_BLOB = "https://github.com/joernmht/langwich/blob/main/"
#: Published by the Pages workflow, not checked in (the skill: scripts/build_skill.py).
DEPLOY_ONLY = ("schema/", "langwich-skill.zip")


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self.card_links: dict[str, list[str]] = {}
        self.card_images: dict[str, list[str]] = {}
        self.countries: list[str] = []
        self.svg: dict[str, str] = {}
        self.local: list[str] = []
        self.ids: set[str] = set()
        self.anchors: list[str] = []
        self.atlas_json = ""
        self._card: str | None = None
        self._depth = 0
        self._in_data = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        classes = a.get("class", "").split()
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "li" and "sheet-card" in classes:
            self.cards.append(a)
            self._card, self._depth = a.get("data-example", ""), 0
            self.card_links[self._card], self.card_images[self._card] = [], []
        elif tag == "li" and self._card is not None:
            self._depth += 1
        if tag == "path" and "country" in classes:
            self.countries.append(a.get("data-iso", ""))
        if tag == "svg" and "europe" in classes:
            self.svg = a
        if tag == "script" and a.get("id") == "atlas-data":
            self._in_data = True
        for key in ("href", "src"):
            value = a.get(key, "")
            if not value or value.startswith(("http:", "https:", "data:", "mailto:")):
                if self._card is not None and key == "href" and value:
                    self.card_links[self._card].append(value)
                continue
            if value.startswith("#"):
                self.anchors.append(value[1:])
                continue
            self.local.append(value)
            if self._card is not None:
                (self.card_links if key == "href" else self.card_images)[self._card].append(value)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_data = False
        if tag == "li" and self._card is not None:
            if self._depth == 0:
                self._card = None
            else:
                self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_data:
            self.atlas_json += data


@pytest.fixture(scope="module")
def page() -> _Page:
    parser = _Page()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    return parser


@pytest.fixture(scope="module")
def atlas(page: _Page) -> dict:
    return json.loads(page.atlas_json)


# -- the cards -------------------------------------------------------------------


def test_every_example_has_exactly_one_card(page: _Page) -> None:
    stems = [card.get("data-example", "") for card in page.cards]
    assert sorted(stems) == [p.stem for p in EXAMPLES], (
        "docs/index.html needs one <li class=\"sheet-card\" data-example=\"<file name>\"> per "
        "file in examples/"
    )


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_the_card_says_what_the_example_is(path: Path, page: _Page) -> None:
    ws = load_worksheet(path)
    card = next(c for c in page.cards if c.get("data-example") == path.stem)
    assert card["data-target"] == ws.target_lang
    assert card["data-source"] == ws.source_lang
    assert card["data-level"] == ws.cefr_level
    assert card.get("data-place"), "say where the story is set"
    # roughly Europe: the page projects these onto the map
    assert 34 <= float(card["data-lat"]) <= 62 and -12 <= float(card["data-lon"]) <= 32
    links = page.card_links[path.stem]
    assert f"examples/{path.stem}.pdf" in links
    assert f"{GITHUB_BLOB}examples/{path.name}" in links
    images = page.card_images[path.stem]
    assert len(images) == 1 and images[0].startswith("assets/") and images[0].endswith(".png")


def test_cards_use_known_levels(page: _Page) -> None:
    assert {card["data-level"] for card in page.cards} <= set(CEFR_LEVELS)


# -- links -----------------------------------------------------------------------


def test_local_links_images_and_fonts_exist(page: _Page) -> None:
    text = INDEX.read_text(encoding="utf-8")
    style = text[text.index("<style>"):text.index("</style>")]
    targets = set(page.local) | set(re.findall(r'url\("([^"]+)"\)', style))
    assert any(t.endswith(".woff2") for t in targets), "the page's fonts are gone"
    missing = sorted(
        t for t in targets
        if not t.startswith(DEPLOY_ONLY) and not (DOCS / t.split("#")[0]).is_file()
    )
    assert not missing, f"docs/index.html points to files that do not exist: {missing}"


def test_in_page_links_have_targets(page: _Page) -> None:
    assert not sorted(set(page.anchors) - page.ids)


def test_the_page_fetches_nothing_from_other_sites() -> None:
    """Fonts, pictures and scripts are local: the page works offline and tracks nobody."""
    text = INDEX.read_text(encoding="utf-8")
    assert not re.findall(r'<(?:script|link|img|iframe)[^>]+(?:src|href)="https?://[^"]+"', text)
    assert "@import" not in text and "fonts.googleapis" not in text


# -- the map and its language table --------------------------------------------------


def test_the_map_is_in_place(page: _Page) -> None:
    text = INDEX.read_text(encoding="utf-8")
    assert text.count("<!-- europe-map:start -->") == text.count("<!-- europe-map:end -->") == 1
    assert len(page.countries) >= 40 and len(set(page.countries)) == len(page.countries)
    assert {"DE", "FR", "NL", "BE", "LU", "CH", "AT", "CZ", "PL", "DK"} <= set(page.countries), (
        "Germany and its neighbours belong on the map"
    )
    # the constants the page's script projects the story locations with
    for key in ("data-lon0", "data-lat0", "data-radius", "data-west", "data-north", "data-scale"):
        assert float(page.svg[key]) or page.svg[key] == "0", key


def test_the_language_table_covers_the_map_and_the_cards(page: _Page, atlas: dict) -> None:
    languages, countries = atlas["languages"], atlas["countries"]
    assert set(countries) == set(page.countries), (
        sorted(set(countries) ^ set(page.countries))
    )
    used = {code for codes in countries.values() for code in codes}
    assert used <= set(languages), sorted(used - set(languages))
    assert all(codes for codes in countries.values())
    for card in page.cards:
        assert card["data-target"] in languages and card["data-source"] in languages
        assert card["data-country"] in countries, card["data-country"]
        # a language someone can learn here colours at least one country
        assert card["data-target"] in used, card["data-target"]


def test_languages_are_named_as_langwich_names_them(atlas: dict) -> None:
    for code, (english, endonym) in atlas["languages"].items():
        assert english and endonym, code
        if code in ENDONYMS:
            assert endonym == ENDONYMS[code], code


# -- the audience switch -------------------------------------------------------------


_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "source", "track", "wbr", "path"})


class _Views(HTMLParser):
    """Per top-level region (the hero and each <section>): which views it has content for."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.regions: dict[str, set[str]] = {}
        self.switches: list[tuple[dict[str, str], bool]] = []
        self._region: str | None = None
        self._stack: list[set[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        classes = a.get("class", "").split()
        if tag == "section" or (tag == "div" and "hero" in classes):
            self._region = a.get("id", "hero")
            self.regions.setdefault(self._region, set())
        if self._region is not None:
            for view in ("only-simple", "only-nerd"):
                if view in classes:
                    self.regions[self._region].add(view)
        if tag not in _VOID:
            self._stack.append(set(classes))
        if "data-view" in a:
            above = set().union(*self._stack)
            # hidden without JavaScript: inside the header control (hidden until the script
            # shows it) or inside .needs-js
            self.switches.append((a, bool(above & {"audience", "needs-js"})))

    def handle_endtag(self, tag: str) -> None:
        if tag not in _VOID and self._stack:
            self._stack.pop()


def test_both_views_cover_the_same_sections() -> None:
    """A region written for one view needs a version for the other: the switch hides the
    first, and nothing else would tell that the second is missing."""
    parser = _Views()
    parser.feed(INDEX.read_text(encoding="utf-8"))
    for region, views in parser.regions.items():
        assert views in (set(), {"only-simple", "only-nerd"}), (
            f"#{region} has {sorted(views)} only: give it the other version too"
        )
    assert {r for r, v in parser.regions.items() if v} >= {
        "hero", "how-it-works", "lesson", "examples", "your-ai", "get-started"
    }


def test_the_switch_works_and_fails_safe() -> None:
    """The head script picks a view; without it both versions show and the switches go."""
    text = INDEX.read_text(encoding="utf-8")
    assert '<html lang="en">' in text, "no view in the markup: without JavaScript show both"
    head = text[:text.index("<style>")]
    assert "localStorage.getItem('langwich-view')" in head and "get('view')" in head
    assert "dataset.audience" in head
    style = text[text.index("<style>"):text.index("</style>")]
    for rule in ('html[data-audience="simple"] .only-nerd',
                 'html[data-audience="nerd"] .only-simple',
                 "html:not([data-audience]) .needs-js"):
        assert rule in style, rule
    parser = _Views()
    parser.feed(text)
    assert parser.switches
    for attrs, hidden_without_js in parser.switches:
        assert attrs["data-view"] in ("simple", "nerd")
        assert hidden_without_js, f"this switch shows, dead, without JavaScript: {attrs}"
