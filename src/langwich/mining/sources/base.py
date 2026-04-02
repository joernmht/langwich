"""Abstract base class for all source adapters."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class SourceResult:
    """A single document or page retrieved from a source.

    Attributes
    ----------
    url : str
        Canonical URL of the source document.
    title : str
        Human-readable title.
    text : str | None
        Extracted plain text; populated after ``extract_text()`` is called.
    language : str
        ISO 639-1 language code of the document.
    license : str | None
        SPDX-style license identifier (e.g. ``"CC-BY-4.0"``).
    retrieved_at : datetime
        Timestamp when the document was fetched.
    metadata : dict
        Source-specific extra fields (DOI, video ID, etc.).
    """

    url: str
    title: str
    text: str | None = None
    language: str = "en"
    license: str | None = None
    retrieved_at: datetime = field(default_factory=datetime.utcnow)
    metadata: dict = field(default_factory=dict)


class Source(abc.ABC):
    """Abstract interface every source adapter must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Human-readable source name (e.g. ``'Wikipedia'``)."""
        ...

    @abc.abstractmethod
    async def search(self, query: str, max_results: int = 10) -> list[SourceResult]:
        """Discover documents matching *query*.

        Returns at most *max_results* lightweight ``SourceResult`` objects
        with ``text`` still set to *None*.
        """
        ...

    @abc.abstractmethod
    async def extract_text(self, result: SourceResult) -> str:
        """Download and extract clean plain text from a ``SourceResult``.

        The extracted text is also stored on ``result.text`` as a side-effect.
        """
        ...
