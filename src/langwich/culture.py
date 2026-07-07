"""Culture library: curated authentic media per target language.

Podcasts, YouTube channels, artists, news sites, films/series and radio
stations for the most popular target languages, tagged by topic and CEFR
entry level.  Media exercises pick a matching resource and the renderer
prints a QR code to its URL — the learner scans instead of searching.

The data lives in ``data/culture_library.json`` and can be extended without
touching code.  For languages not in the library, :func:`pick_resource`
falls back to a search URL so media exercises still work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources as importlib_resources
from pathlib import Path

CATEGORIES = ("podcast", "video", "music", "news", "film_tv", "radio", "social")

_CEFR_ORDER = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}

# Map free-form worksheet topic slugs to the library's standard topic tags.
_TOPIC_ALIASES: dict[str, str] = {
    "coffee": "food", "cooking": "food", "cuisine": "food", "recipes": "food",
    "gastronomy": "food", "restaurant": "food", "baking": "food",
    "football": "sports", "soccer": "sports", "fitness": "sports",
    "athletics": "sports", "gym": "sports",
    "ai": "technology", "machine-learning": "technology", "internet": "technology",
    "software": "technology", "computers": "technology", "robotics": "technology",
    "medicine": "health", "healthcare": "health", "anatomy": "health",
    "environment": "nature", "climate": "nature", "ecology": "nature",
    "sustainability": "nature", "animals": "nature", "gardening": "nature",
    "finance": "business", "economics": "business", "startups": "business",
    "marketing": "business", "accounting": "business",
    "archaeology": "history", "museums": "history",
    "painting": "art", "photography": "art", "design": "art", "fashion": "art",
    "law": "society", "politics": "politics", "school": "everyday",
    "family": "everyday", "shopping": "everyday", "hobbies": "everyday",
    "tourism": "travel", "transport": "travel", "vacation": "travel",
    "holidays": "travel", "geography": "travel",
    "movies": "film", "cinema": "film", "series": "film", "anime": "film",
    "books": "literature", "poetry": "literature", "reading": "literature",
    "physics": "science", "chemistry": "science", "biology": "science",
    "astronomy": "science", "research": "science",
    "songs": "music", "concerts": "music",
}


@dataclass
class CultureResource:
    """A single curated media resource."""
    language: str
    category: str  # one of CATEGORIES
    title: str
    url: str
    description: str = ""
    topics: list[str] = field(default_factory=list)
    cefr: str = "A1+"  # entry level, e.g. "B1+"

    @property
    def min_cefr_rank(self) -> int:
        return _CEFR_ORDER.get(self.cefr.rstrip("+"), 1)

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "category": self.category,
            "title": self.title,
            "url": self.url,
            "description": self.description,
            "topics": self.topics,
            "cefr": self.cefr,
        }


def _data_path() -> Path:
    return Path(str(importlib_resources.files("langwich"))) / "data" / "culture_library.json"


def load_culture_library(extra_path: str | Path | None = None) -> dict[str, list[CultureResource]]:
    """Load the bundled culture library, optionally merged with a user file.

    Returns a mapping of language code -> list of resources.  ``extra_path``
    may point to a JSON file with the same structure; its resources are
    appended (and take priority in :func:`pick_resource` scoring ties are
    resolved by list order, so bundled entries come first).
    """
    library: dict[str, list[CultureResource]] = {}

    def _ingest(raw: dict) -> None:
        for lang, entry in raw.get("languages", {}).items():
            bucket = library.setdefault(lang, [])
            for r in entry.get("resources", []):
                bucket.append(CultureResource(
                    language=lang,
                    category=r["category"],
                    title=r["title"],
                    url=r["url"],
                    description=r.get("description", ""),
                    topics=r.get("topics", []),
                    cefr=r.get("cefr", "A1+"),
                ))

    with open(_data_path(), encoding="utf-8") as f:
        _ingest(json.load(f))

    if extra_path is not None:
        p = Path(extra_path)
        if p.exists():
            with open(p, encoding="utf-8") as f:
                _ingest(json.load(f))

    return library


def normalize_topic(topic: str) -> str:
    """Map a worksheet topic slug to a standard library tag."""
    slug = topic.strip().lower().replace("_", "-")
    return _TOPIC_ALIASES.get(slug, slug)


def resources_for(
    language: str,
    category: str | None = None,
    topic: str | None = None,
    library: dict[str, list[CultureResource]] | None = None,
) -> list[CultureResource]:
    """All resources for a language, optionally filtered by category/topic."""
    lib = library if library is not None else load_culture_library()
    result = list(lib.get(language, []))
    if category:
        result = [r for r in result if r.category == category]
    if topic:
        tag = normalize_topic(topic)
        result = [r for r in result if tag in r.topics]
    return result


def pick_resource(
    language: str,
    category: str,
    topic: str | None = None,
    cefr_level: str | None = None,
    library: dict[str, list[CultureResource]] | None = None,
) -> CultureResource | None:
    """Pick the best resource for a worksheet.

    Scoring: topic match counts most, then a learner-friendly ``learning`` /
    ``everyday`` tag, then whether the resource's entry level is at or below
    the learner's CEFR level.  Returns ``None`` only when the language has
    no resources in that category at all — use :func:`fallback_resource`
    then.
    """
    lib = library if library is not None else load_culture_library()
    candidates = [r for r in lib.get(language, []) if r.category == category]
    if not candidates:
        return None

    tag = normalize_topic(topic) if topic else None
    learner_rank = _CEFR_ORDER.get((cefr_level or "").upper(), None)

    def score(r: CultureResource) -> int:
        s = 0
        if tag and tag in r.topics:
            s += 4
        if "learning" in r.topics or "everyday" in r.topics:
            s += 1
        if learner_rank is not None and r.min_cefr_rank <= learner_rank:
            s += 2
        return s

    return max(candidates, key=score)


def fallback_resource(language: str, category: str, topic: str | None = None) -> CultureResource:
    """Construct a search-URL resource for languages not in the library.

    Guarantees that media exercises always have a QR target.
    """
    from urllib.parse import quote_plus

    from langwich.i18n import LANG_NAMES

    lang_name = LANG_NAMES["en"].get(language, language)
    parts = [lang_name]
    if topic:
        parts.append(topic.replace("-", " ").replace("_", " "))

    if category in ("video", "music", "film_tv"):
        query = quote_plus(" ".join(parts + [{"video": "", "music": "music",
                                              "film_tv": "movie trailer"}[category]]).strip())
        url = f"https://www.youtube.com/results?search_query={query}"
        title = f"{lang_name} {category.replace('_tv', 's & TV')} search"
    elif category == "radio":
        url = f"https://tunein.com/search/?query={quote_plus(lang_name + ' radio')}"
        title = f"{lang_name} radio search"
    else:  # podcast, news, social
        kind = {"podcast": "podcast for learners", "news": "news",
                "social": "social media accounts"}[category]
        query = quote_plus(f"{lang_name} {kind} " + (topic or ""))
        url = f"https://duckduckgo.com/?q={query.strip()}"
        title = f"{lang_name} {kind} search"

    return CultureResource(
        language=language,
        category=category,
        title=title,
        url=url,
        description="No curated entry for this language yet — this QR code opens a ready-made search.",
        topics=[normalize_topic(topic)] if topic else [],
        cefr="A1+",
    )
