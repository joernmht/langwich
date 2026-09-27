"""Context for writing the next episode of a story series.

A worksheet can be one episode of a continuing story (``Worksheet.series``).
:func:`continuation` distils the previous episode into what an LLM needs to
write the next one — the cast, the story so far, how it ended, the teaser
it promised and the words worth recycling — and :mod:`langwich.prompt`
turns that into the "next episode" part of the authoring prompt.

Nothing here writes learner-facing text: the summaries are built from the
previous worksheet's own logline, headings and sentences.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from langwich.model import Character, Worksheet

#: At most this many earlier target words are offered for recycling.
MAX_REVIEW_WORDS = 12

#: A scene's gist is its first sentence, plus the next one when the first
#: has fewer words than this ("Es ist Montag." says little on its own).
_GIST_MIN_WORDS = 8

_SENTENCE_END_RE = re.compile(r"(?:(?<=[.!?…])|(?<=[.!?…][\"“”„»«’')]))\s+")
_TRANSLIT = str.maketrans({
    "ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss", "æ": "ae", "ø": "oe", "å": "aa",
    "œ": "oe", "ł": "l", "đ": "d", "þ": "th",
})


@dataclass
class Continuation:
    """What the next episode builds on (see :func:`continuation`)."""

    series_id: str
    series_title: str
    episode: int
    characters: list[Character]
    setting: str | None
    story_so_far: str
    last_scene: str
    teaser: str | None
    review_words: list[str] = field(default_factory=list)
    source_lang: str = "en"
    target_lang: str = "de"
    cefr_level: str = "B1"


def slugify(text: str, fallback: str = "series") -> str:
    """A series id from a title: ``"Fünf Tage im Café"`` → ``"fuenf-tage-im-cafe"``."""
    text = text.casefold().translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    slug = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:48].strip("-")
    return slug or fallback


def sentences(text: str) -> list[str]:
    """Split running text into sentences (closing quotes stay with their sentence)."""
    flat = " ".join(text.split())
    return [s.strip() for s in _SENTENCE_END_RE.split(flat) if s.strip()]


def scene_gist(text: str) -> str:
    """A one-line gist of a scene: its first sentence (two if the first is
    very short) and, when the scene is longer, ``…`` and its last sentence —
    scenes tend to open with the situation and close with the turn."""
    parts = sentences(text)
    if not parts:
        return " ".join(text.split())
    used = 1
    gist = parts[0]
    if len(gist.split()) < _GIST_MIN_WORDS and len(parts) > 2:
        gist, used = f"{gist} {parts[1]}", 2
    if len(parts) > used + 1:
        gist = f"{gist} … {parts[-1]}"
    elif len(parts) == used + 1:
        gist = f"{gist} {parts[-1]}"
    return gist


def _dedupe(words: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        word = word.strip()
        key = word.casefold()
        if not word or key in seen:
            continue
        seen.add(key)
        out.append(word)
        if len(out) == limit:
            break
    return out


def continuation(prev: Worksheet) -> Continuation:
    """Summarise ``prev`` for the author of the next episode.

    * ``story_so_far`` — the previous recap (if any), the logline, then each
      scene heading with a one-line gist (:func:`scene_gist`);
    * ``last_scene`` — the complete text of the final scene;
    * ``teaser`` — ``prev.series.next``, the hook the next episode must pick up;
    * ``review_words`` — the previous target words and review words,
      de-duplicated, at most :data:`MAX_REVIEW_WORDS`;
    * ``episode`` — the previous episode + 1 (2 when ``prev`` has no series;
      then the series id and title are derived from its title).
    """
    series = prev.series
    episode = next_episode(prev)
    if series is not None:
        series_id, series_title = series.id, series.title
        previously, teaser = series.previously, series.next
        earlier_review = list(series.review)
    else:
        series_id, series_title = slugify(prev.title), prev.title
        previously, teaser, earlier_review = None, None, []

    lines: list[str] = []
    if previously:
        lines.append(f"Before that: {previously}")
    label = f"Episode {episode - 1}" if series is not None else "The first story"
    lines.append(f"{label}, “{prev.title}”: {prev.story.logline}")
    for scene in prev.story.scenes:
        lines.append(f"- {scene.heading}: {scene_gist(scene.text)}")

    return Continuation(
        series_id=series_id,
        series_title=series_title,
        episode=episode,
        characters=[c.model_copy() for c in prev.story.characters],
        setting=prev.story.setting,
        story_so_far="\n".join(lines),
        last_scene=prev.story.scenes[-1].text,
        teaser=teaser,
        review_words=_dedupe(list(prev.vocabulary.target) + earlier_review, MAX_REVIEW_WORDS),
        source_lang=prev.source_lang,
        target_lang=prev.target_lang,
        cefr_level=prev.cefr_level,
    )


# An episode number is a 1–3 digit token between separators, optionally
# prefixed ('ep2', 'e02', 'folge3'): 'lena_01_en_de', 'story-ep2', '03_lena'.
# Level codes ('b1') and years ('2024') are not episode numbers.
_EPISODE_TOKEN_RE = re.compile(
    r"(?:^|(?<=[_\-. ]))(?P<prefix>(?:episode|folge|ep|e)?)(?P<num>\d{1,3})(?=$|[_\-. ])",
    re.IGNORECASE,
)

#: Longest slug in a suggested worksheet file name (cut at a word boundary).
_FILE_SLUG_MAX = 32


def next_episode(prev: Worksheet) -> int:
    """The episode number that follows ``prev``: ``series.episode + 1``, or 2
    when ``prev`` is a one-off story."""
    return prev.series.episode + 1 if prev.series is not None else 2


def file_slug(text: str, fallback: str = "story") -> str:
    """The ``<slug>`` of a worksheet file name: lower-case ASCII words joined
    by ``_``, at most 32 characters (``"Sourdough & a night bakery"`` →
    ``"sourdough_a_night_bakery"``)."""
    words = slugify(text, fallback="").split("-")
    slug = ""
    for word in (w for w in words if w):
        candidate = f"{slug}_{word}" if slug else word
        if len(candidate) > _FILE_SLUG_MAX:
            break
        slug = candidate
    return slug or (words[0][:_FILE_SLUG_MAX] if words and words[0] else fallback)


def worksheet_filename(
    base: str, source_lang: str, target_lang: str, episode: int | None = None,
    *, variant: int = 1,
) -> str:
    """A file name by the documented convention: ``<slug>_<src>_<tgt>.json``
    for a one-off story, ``<series>_<nn>_<src>_<tgt>.json`` for an episode
    (``worksheet_filename("lena", "en", "de", 1)`` → ``"lena_01_en_de.json"``).
    ``base`` is turned into a slug with :func:`file_slug`; ``variant`` > 1
    marks an alternative when the name is taken (``coffee-2_en_de.json``)."""
    slug = file_slug(base) + (f"-{variant}" if variant > 1 else "")
    number = f"_{episode:02d}" if episode is not None else ""
    return f"{slug}{number}_{source_lang}_{target_lang}.json"


def next_episode_filename(
    prev_path: str | Path,
    episode: int | None = None,
    *,
    source_lang: str | None = None,
    target_lang: str | None = None,
    prev_langs: tuple[str, str] | None = None,
) -> str:
    """The file name for the next episode, next to the previous one.

    ``episode`` is the new episode number — pass :func:`next_episode` of the
    previous worksheet, so the name agrees with ``series.episode``; without
    it the number in the old name + 1 (or 2) is used. ``source_lang`` and
    ``target_lang`` are the new episode's languages, ``prev_langs`` the
    previous episode's (default: the same); a name that ends with the
    previous language pair gets the new one.

    * A name with an episode number gets the new number, zero padding kept:
      ``lena_01_en_de.json`` → ``lena_02_en_de.json``, ``story_ep2.json`` →
      ``story_ep3.json``.
    * A name without one follows ``<series>_<nn>_<src>_<tgt>.json``: the
      number goes before the language pair (``coffee_en_de.json`` →
      ``coffee_02_en_de.json``); a name without the pair gets number and
      languages appended (``coffee.json`` → ``coffee_02_en_de.json``, or
      ``coffee_02.json`` when no languages are given).
    """
    path = Path(prev_path)
    stem, suffix = path.stem, path.suffix or ".json"
    new = (source_lang, target_lang) if source_lang and target_lang else None
    old = prev_langs or new
    langs = ""
    if old is not None:
        pair = f"_{old[0]}_{old[1]}"
        if stem.casefold().endswith(pair.casefold()) and len(stem) > len(pair):
            stem = stem[: len(stem) - len(pair)]
            langs = "_{}_{}".format(*(new or old))
    match = _EPISODE_TOKEN_RE.search(stem)
    if match:
        digits = match.group("num")
        number = str(episode if episode is not None else int(digits) + 1).zfill(len(digits))
        stem = stem[: match.start("num")] + number + stem[match.end("num"):]
    else:
        stem = f"{stem}_{episode if episode is not None else 2:02d}"
        if not langs and new is not None:
            langs = f"_{new[0]}_{new[1]}"
    return str(path.with_name(stem + langs + suffix))
