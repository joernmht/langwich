"""arXiv source adapter — fetches papers via the arXiv Atom API."""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree

import httpx

from langwich.mining.sources.base import Source, SourceResult

logger = logging.getLogger(__name__)

_ARXIV_API = "http://export.arxiv.org/api/query"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"


class ArxivSource(Source):
    """Retrieves and extracts text from arXiv paper abstracts and metadata."""

    @property
    def name(self) -> str:
        return "arXiv"

    async def search(self, query: str, max_results: int = 10) -> list[SourceResult]:
        """Search arXiv for papers matching *query*."""
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(_ARXIV_API, params=params)
            resp.raise_for_status()

        root = ElementTree.fromstring(resp.text)
        results: list[SourceResult] = []
        for entry in root.findall(f"{_ATOM_NS}entry"):
            title = (entry.findtext(f"{_ATOM_NS}title") or "").strip()
            arxiv_id = (entry.findtext(f"{_ATOM_NS}id") or "").strip()
            summary = (entry.findtext(f"{_ATOM_NS}summary") or "").strip()

            # Extract clean arXiv ID from the URL
            match = re.search(r"(\d{4}\.\d{4,5})(v\d+)?$", arxiv_id)
            clean_id = match.group(0) if match else arxiv_id

            results.append(
                SourceResult(
                    url=arxiv_id,
                    title=title,
                    language="en",
                    license="arXiv-license",
                    metadata={"arxiv_id": clean_id, "abstract": summary},
                )
            )
        return results

    async def extract_text(self, result: SourceResult) -> str:
        """Return the paper abstract as plain text.

        Full-text extraction from PDFs could be added in a future version.
        """
        text = result.metadata.get("abstract", "")
        result.text = text
        return text
