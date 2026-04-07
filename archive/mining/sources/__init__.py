"""Source adapters for the mining pipeline."""

from langwich.mining.sources.base import Source, SourceResult
from langwich.mining.sources.wikipedia import WikipediaSource
from langwich.mining.sources.arxiv import ArxivSource
from langwich.mining.sources.openalex import OpenAlexSource
from langwich.mining.sources.youtube import YouTubeSource

__all__ = [
    "Source",
    "SourceResult",
    "WikipediaSource",
    "ArxivSource",
    "OpenAlexSource",
    "YouTubeSource",
]
