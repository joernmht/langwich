"""Series continuation: what the next episode builds on."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from langwich.model import Worksheet, load_worksheet, worksheet_from_dict
from langwich.series import (
    MAX_REVIEW_WORDS,
    Continuation,
    continuation,
    file_slug,
    next_episode,
    next_episode_filename,
    scene_gist,
    sentences,
    slugify,
    worksheet_filename,
)

LENA = Path(__file__).resolve().parent.parent / "examples" / "lena_01_en_de.json"
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def _lena_dict() -> dict:
    return json.loads(LENA.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def lena() -> Worksheet:
    return load_worksheet(LENA)


def test_continuation_of_lena(lena: Worksheet):
    c = continuation(lena)
    assert isinstance(c, Continuation)
    assert (c.series_id, c.series_title, c.episode) == ("lena-in-wien", "Lena in Wien", 2)
    assert [ch.name for ch in c.characters] == ["Lena", "Frau Berger", "Herr Novak"]
    assert [ch.id for ch in c.characters] == ["lena", "berger", "novak"]
    assert c.setting == lena.story.setting
    assert c.teaser == lena.series.next
    assert "Triest" in c.teaser
    assert c.last_scene == lena.story.scenes[-1].text
    assert (c.source_lang, c.target_lang, c.cefr_level) == ("en", "de", "B1")


def test_story_so_far_has_logline_and_every_scene(lena: Worksheet):
    c = continuation(lena)
    assert lena.story.logline in c.story_so_far
    assert lena.title in c.story_so_far
    for scene in lena.story.scenes:
        assert scene.heading in c.story_so_far
    # one line per scene, after the logline line
    assert len(c.story_so_far.splitlines()) == 1 + len(lena.story.scenes)
    # the turn of the complication scene is in its gist
    assert "Lena ist enttäuscht." in c.story_so_far


def test_review_words_are_the_previous_target_words(lena: Worksheet):
    c = continuation(lena)
    assert c.review_words == lena.vocabulary.target


def test_review_words_are_deduplicated_and_capped():
    data = _lena_dict()
    data["series"]["review"] = [
        "die Bohne", "DIE BOHNE", "der Kellner", "die Tasse", "der Zucker", "die Milch",
        "das Wasser",
    ]
    ws = worksheet_from_dict(data)
    c = continuation(ws)
    assert len(c.review_words) == MAX_REVIEW_WORDS
    assert len({w.casefold() for w in c.review_words}) == len(c.review_words)
    assert c.review_words[:10] == ws.vocabulary.target
    assert c.review_words[10:] == ["der Kellner", "die Tasse"]


def test_previous_recap_and_episode_number_carry_over():
    data = _lena_dict()
    data["series"]["episode"] = 4
    data["series"]["previously"] = "Lena lernte in Wien, Kaffee zu rösten."
    c = continuation(worksheet_from_dict(data))
    assert c.episode == 5
    assert c.story_so_far.startswith("Before that: Lena lernte in Wien")
    assert "Episode 4" in c.story_so_far


def test_continuation_without_series_derives_id_and_title():
    data = _lena_dict()
    del data["series"]
    ws = worksheet_from_dict(data)
    c = continuation(ws)
    assert c.episode == 2
    assert c.series_title == ws.title
    assert c.series_id == "fuenf-tage-im-cafe-lindner"
    assert ID_PATTERN.match(c.series_id)
    assert c.teaser is None
    assert c.review_words == ws.vocabulary.target


def test_characters_are_copies(lena: Worksheet):
    c = continuation(lena)
    c.characters[0].role = "changed"
    assert lena.story.characters[0].role != "changed"


@pytest.mark.parametrize(("title", "slug"), [
    ("Fünf Tage im Café Lindner", "fuenf-tage-im-cafe-lindner"),
    ("Lena in Wien", "lena-in-wien"),
    ("Łódź – Straße!", "lodz-strasse"),
    ("¿Qué pasa, Señor?", "que-pasa-senor"),
    ("!!!", "series"),
    ("東京", "series"),
])
def test_slugify(title: str, slug: str):
    assert slugify(title) == slug
    assert ID_PATTERN.match(slugify(title))


def test_sentences_keep_closing_quotes():
    text = "„Am Freitag machst du den Test“, sagt sie. „Aber vorher lernst du.“ Lena nickt."
    assert sentences(text) == [
        "„Am Freitag machst du den Test“, sagt sie.",
        "„Aber vorher lernst du.“",
        "Lena nickt.",
    ]


def test_scene_gist():
    assert scene_gist("Eins zwei drei vier fünf sechs sieben acht.") == (
        "Eins zwei drei vier fünf sechs sieben acht."
    )
    # a very short first sentence takes the second along; the last one follows '…'
    text = "Es ist Montag. Lena steht hinter der Theke im Café. Sie ist nervös. Dann lacht sie."
    assert scene_gist(text) == (
        "Es ist Montag. Lena steht hinter der Theke im Café. … Dann lacht sie."
    )
    two = "Lena öffnet heute sehr früh am Morgen das Café. Es regnet."
    assert scene_gist(two) == two


@pytest.mark.parametrize(("prev", "expected"), [
    ("lena_01_en_de.json", "lena_02_en_de.json"),
    ("examples/lena_01_en_de.json", "examples/lena_02_en_de.json"),
    ("lena_09.json", "lena_10.json"),
    ("story_ep2.json", "story_ep3.json"),
    ("03_lena.json", "04_lena.json"),
    ("folge7.json", "folge8.json"),
    # no episode number: <series>_<nn>[_<src>_<tgt>]
    ("coffee.json", "coffee_02.json"),
    ("trip_2024.json", "trip_2024_02.json"),
])
def test_next_episode_filename(prev: str, expected: str):
    assert next_episode_filename(prev) == str(Path(expected))


@pytest.mark.parametrize(("prev", "target", "expected"), [
    ("lena_01_en_de.json", "de", "lena_02_en_de.json"),
    ("coffee_en_de.json", "de", "coffee_02_en_de.json"),   # documented <series>_<nn>_<src>_<tgt>
    ("data/mercado_valencia_en_es.json", "es", "data/mercado_valencia_02_en_es.json"),
    ("lena_b1_en_de.json", "de", "lena_b1_02_en_de.json"),
    ("coffee.json", "de", "coffee_02_en_de.json"),
    ("story_ep2.json", "de", "story_ep3.json"),
])
def test_next_episode_filename_follows_the_naming_convention(prev: str, target: str,
                                                             expected: str):
    name = next_episode_filename(prev, source_lang="en", target_lang=target)
    assert name == str(Path(expected))


def test_next_episode_filename_with_explicit_episode():
    assert next_episode_filename("lena_01_en_de.json", episode=5) == "lena_05_en_de.json"
    assert next_episode_filename("lena_01_en_de.json", episode=10) == "lena_10_en_de.json"
    assert next_episode_filename("coffee.json", episode=3) == "coffee_03.json"


def test_next_episode_filename_takes_the_new_languages():
    name = next_episode_filename("festival_lyon_de_fr.json", 2, source_lang="en",
                                 target_lang="fr", prev_langs=("de", "fr"))
    assert name == "festival_lyon_02_en_fr.json"


def test_next_episode_number_follows_the_series(lena: Worksheet):
    assert next_episode(lena) == lena.series.episode + 1 == continuation(lena).episode
    data = _lena_dict()
    data["series"]["episode"] = 5
    ws = worksheet_from_dict(data)
    assert next_episode(ws) == 6 == continuation(ws).episode
    # the file name agrees with series.episode, not with the old name's number
    assert next_episode_filename("lena_01_en_de.json", next_episode(ws)) == "lena_06_en_de.json"
    del data["series"]
    assert next_episode(worksheet_from_dict(data)) == 2


@pytest.mark.parametrize(("text", "slug"), [
    ("coffee", "coffee"),
    ("Sourdough & a night bakery", "sourdough_a_night_bakery"),
    ("Fünf Tage im Café Lindner", "fuenf_tage_im_cafe_lindner"),
    ("the history of the bicycle in the Netherlands and Denmark", "the_history_of_the_bicycle_in"),
    ("!!!", "story"),
])
def test_file_slug(text: str, slug: str):
    assert file_slug(text) == slug
    assert len(file_slug(text)) <= 32


def test_worksheet_filename():
    assert worksheet_filename("Night bakery", "en", "de") == "night_bakery_en_de.json"
    assert worksheet_filename("lena", "en", "de", 1) == "lena_01_en_de.json"
    assert worksheet_filename("coffee", "en", "de", variant=2) == "coffee-2_en_de.json"
