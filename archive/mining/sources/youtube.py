"""YouTube transcript source adapter — fetches CC-licensed video transcripts."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from langwich.mining.sources.base import Source, SourceResult

logger = logging.getLogger(__name__)


class YouTubeSource(Source):
    """Extracts transcripts from CC-licensed YouTube videos.

    Uses the ``youtube-transcript-api`` library for transcript retrieval
    and the YouTube Data API v3 (or scraping) for video discovery.
    """

    def __init__(self, language: str = "en") -> None:
        self.language = language

    @property
    def name(self) -> str:
        return "YouTube Transcripts"

    async def search(self, query: str, max_results: int = 10) -> list[SourceResult]:
        """Search YouTube for CC-licensed videos matching *query*.

        Note: Full implementation requires a YouTube Data API key.
        This stub uses the ``videoLicense=creativeCommon`` filter.
        """
        # TODO: Implement via YouTube Data API v3 with creativeCommon filter
        logger.warning(
            "YouTubeSource.search() is a stub — implement with YouTube Data API key."
        )
        return []

    async def extract_text(self, result: SourceResult) -> str:
        """Fetch the transcript for a YouTube video.

        Uses ``youtube_transcript_api`` to retrieve captions.
        """
        video_id = result.metadata.get("video_id")
        if not video_id:
            result.text = ""
            return ""

        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript_list = YouTubeTranscriptApi.get_transcript(
                video_id, languages=[self.language]
            )
            text = " ".join(segment["text"] for segment in transcript_list)
            result.text = text
            return text
        except Exception as exc:
            logger.warning("Failed to fetch transcript for %s: %s", video_id, exc)
            result.text = ""
            return ""
