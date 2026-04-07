"""Wikipedia source adapter — fetches articles via the MediaWiki API."""

from __future__ import annotations

import logging

import httpx

from langwich.mining.sources.base import Source, SourceResult

logger = logging.getLogger(__name__)

_API_BASE = "https://{lang}.wikipedia.org/w/api.php"


class WikipediaSource(Source):
    """Retrieves and extracts text from Wikipedia articles.

    Parameters
    ----------
    language : str
        Wikipedia language edition (ISO 639-1 code, default ``"en"``).
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language
        self._api_url = _API_BASE.format(lang=language)

    @property
    def name(self) -> str:
        return f"Wikipedia ({self.language})"

    async def search(self, query: str, max_results: int = 10) -> list[SourceResult]:
        """Search Wikipedia for articles matching *query*."""
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": max_results,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._api_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[SourceResult] = []
        for item in data.get("query", {}).get("search", []):
            page_title = item["title"]
            url = f"https://{self.language}.wikipedia.org/wiki/{page_title.replace(' ', '_')}"
            results.append(
                SourceResult(
                    url=url,
                    title=page_title,
                    language=self.language,
                    license="CC-BY-SA-3.0",
                    metadata={"pageid": item.get("pageid")},
                )
            )
        return results

    async def extract_text(self, result: SourceResult) -> str:
        """Fetch the plain-text extract of a Wikipedia page."""
        pageid = result.metadata.get("pageid")
        params = {
            "action": "query",
            "prop": "extracts",
            "explaintext": True,
            "exsectionformat": "plain",
            "pageids": pageid,
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(self._api_url, params=params)
            resp.raise_for_status()
            data = resp.json()

        pages = data.get("query", {}).get("pages", {})
        text = pages.get(str(pageid), {}).get("extract", "")
        result.text = text
        return text
