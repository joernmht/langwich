"""OpenAlex source adapter — fetches works via the OpenAlex REST API."""

from __future__ import annotations

import logging

import httpx

from langwich.mining.sources.base import Source, SourceResult

logger = logging.getLogger(__name__)

_OPENALEX_API = "https://api.openalex.org"


class OpenAlexSource(Source):
    """Retrieves academic works from OpenAlex (open scholarly metadata)."""

    def __init__(self, email: str | None = None) -> None:
        self.email = email  # polite-pool access

    @property
    def name(self) -> str:
        return "OpenAlex"

    async def search(self, query: str, max_results: int = 10) -> list[SourceResult]:
        """Search OpenAlex for works matching *query*."""
        params: dict[str, str | int] = {
            "search": query,
            "per_page": max_results,
            "filter": "is_oa:true",
        }
        if self.email:
            params["mailto"] = self.email

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{_OPENALEX_API}/works", params=params)
            resp.raise_for_status()
            data = resp.json()

        results: list[SourceResult] = []
        for work in data.get("results", []):
            abstract_index = work.get("abstract_inverted_index")
            results.append(
                SourceResult(
                    url=work.get("doi") or work.get("id", ""),
                    title=work.get("title", "Untitled"),
                    language=work.get("language", "en"),
                    license=work.get("primary_location", {}).get("license") or "unknown",
                    metadata={
                        "openalex_id": work.get("id"),
                        "abstract_inverted_index": abstract_index,
                        "cited_by_count": work.get("cited_by_count", 0),
                    },
                )
            )
        return results

    async def extract_text(self, result: SourceResult) -> str:
        """Reconstruct abstract from the inverted index."""
        inv_index = result.metadata.get("abstract_inverted_index")
        if not inv_index:
            result.text = ""
            return ""

        # Rebuild the abstract from the inverted index format.
        word_positions: list[tuple[int, str]] = []
        for word, positions in inv_index.items():
            for pos in positions:
                word_positions.append((pos, word))
        word_positions.sort()
        text = " ".join(word for _, word in word_positions)
        result.text = text
        return text
