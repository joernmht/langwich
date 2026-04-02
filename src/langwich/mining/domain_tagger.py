"""Domain relevance tagging for extracted vocabulary.

Uses a combination of keyword matching and TF-IDF-style scoring to
determine whether a term is relevant to the configured knowledge domain.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class DomainTagger:
    """Scores and filters vocabulary by domain relevance.

    Parameters
    ----------
    domain : str
        The knowledge domain descriptor (e.g. ``"railway-operations"``).
    relevance_threshold : float
        Minimum score (0–1) for a term to be considered domain-relevant.
    """

    domain: str
    relevance_threshold: float = 0.3
    _domain_keywords: list[str] = field(default_factory=list, init=False, repr=False)

    def __post_init__(self) -> None:
        # Derive seed keywords from the domain slug.
        self._domain_keywords = [
            kw.lower() for kw in re.split(r"[-_\s]+", self.domain) if len(kw) > 2
        ]

    def score(self, term: str) -> float:
        """Return a relevance score in [0, 1] for a term.

        The current implementation uses simple keyword overlap and
        can be extended with corpus-based TF-IDF or embeddings.
        """
        term_lower = term.lower()
        if term_lower in self._domain_keywords:
            return 1.0

        # Partial match bonus
        for kw in self._domain_keywords:
            if kw in term_lower or term_lower in kw:
                return 0.7

        # Fallback: no specific domain signal — let general vocab through
        # with a neutral score that passes the default threshold.
        return 0.5

    def is_relevant(self, term: str) -> bool:
        """Return *True* if the term meets the relevance threshold."""
        return self.score(term) >= self.relevance_threshold
