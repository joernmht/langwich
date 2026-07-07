"""Tests for the culture library."""

from langwich.culture import (
    CATEGORIES,
    fallback_resource,
    load_culture_library,
    normalize_topic,
    pick_resource,
    resources_for,
)

POPULAR_LANGUAGES = ["de", "fr", "es", "it", "pt", "en", "ja", "zh", "ko", "ru", "ar"]


def test_library_covers_popular_languages():
    lib = load_culture_library()
    for lang in POPULAR_LANGUAGES:
        assert lang in lib, lang
        assert len(lib[lang]) >= 8, lang


def test_every_resource_is_wellformed():
    lib = load_culture_library()
    for lang, resources in lib.items():
        for r in resources:
            assert r.category in CATEGORIES, r.title
            assert r.title, lang
            assert r.url.startswith("https://"), r.title
            assert r.topics, r.title
            assert r.cefr.rstrip("+") in ("A1", "A2", "B1", "B2", "C1", "C2"), r.title


def test_core_categories_present_per_language():
    lib = load_culture_library()
    for lang in POPULAR_LANGUAGES:
        categories = {r.category for r in lib[lang]}
        for required in ("podcast", "video", "music", "news", "film_tv"):
            assert required in categories, f"{lang} missing {required}"


def test_pick_resource_prefers_topic_match():
    lib = load_culture_library()
    r = pick_resource("ja", "film_tv", topic="cooking", cefr_level="B1", library=lib)
    assert r is not None
    assert "food" in r.topics  # Midnight Diner beats generic picks


def test_pick_resource_always_returns_something_for_known_language():
    lib = load_culture_library()
    for lang in POPULAR_LANGUAGES:
        for category in ("podcast", "video", "music", "news", "film_tv"):
            assert pick_resource(lang, category, topic="unknown-topic",
                                 library=lib) is not None


def test_fallback_resource_for_unknown_language():
    r = fallback_resource("nl", "video", "cooking")
    assert r.url.startswith("https://")
    assert "Dutch" in r.title


def test_topic_aliases():
    assert normalize_topic("coffee") == "food"
    assert normalize_topic("machine_learning") == "technology"
    assert normalize_topic("news") == "news"


def test_resources_for_filters():
    lib = load_culture_library()
    podcasts = resources_for("de", category="podcast", library=lib)
    assert podcasts and all(r.category == "podcast" for r in podcasts)
    news_topic = resources_for("de", topic="news", library=lib)
    assert news_topic and all("news" in r.topics for r in news_topic)
