"""Orchestrates the end-to-end vocabulary mining process.

Pipeline stages
───────────────
  1. Source Discovery  — find relevant texts for the target domain
  2. Text Extraction   — pull clean text from each source
  3. NLP Processing    — tokenise, lemmatise, POS-tag
  4. Vocab Extraction  — identify unique terms and collocations
  5. CEFR Classification — rule-based first, LLM fallback for unknowns
  6. Domain Tagging    — score relevance to the target domain
  7. DB Storage        — persist everything to the per-domain SQLite
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Sequence

from langwich.config import AppConfig, settings
from langwich.db.manager import DomainDatabase
from langwich.db.models import CEFRLevel, ClassificationMethod, PartOfSpeech
from langwich.mining.domain_tagger import DomainTagger
from langwich.mining.nlp.cefr_classifier import CEFRClassifier
from langwich.mining.nlp.phrase_extractor import PhraseExtractor
from langwich.mining.nlp.tokenizer import Tokenizer
from langwich.mining.sources.base import Source, SourceResult

logger = logging.getLogger(__name__)


@dataclass
class ExtractedTerm:
    """Intermediate representation of a term found during mining."""

    term: str
    lemma: str
    pos: PartOfSpeech
    frequency: float = 0.0
    source_url: str | None = None
    context_sentences: list[str] = field(default_factory=list)


@dataclass
class MiningResult:
    """Summary returned after a mining run completes."""

    domain: str
    source_language: str
    target_language: str
    terms_added: int = 0
    phrases_added: int = 0
    sources_processed: int = 0
    errors: list[str] = field(default_factory=list)


class MiningPipeline:
    """Coordinates all stages of the vocabulary mining pipeline.

    Parameters
    ----------
    db : DomainDatabase
        An initialised per-domain database to store results in.
    sources : Sequence[Source]
        Ordered list of source adapters to query.
    config : AppConfig | None
        Application configuration; uses global ``settings`` if *None*.
    """

    def __init__(
        self,
        db: DomainDatabase,
        sources: Sequence[Source],
        config: AppConfig | None = None,
    ) -> None:
        self.db = db
        self.sources = list(sources)
        self.cfg = config or settings

        self.tokenizer = Tokenizer(spacy_model=self.cfg.spacy_model)
        self.phrase_extractor = PhraseExtractor()
        self.cefr_classifier = CEFRClassifier(scads_config=self.cfg.scads)
        self.domain_tagger = DomainTagger(domain=db.domain)

    # ── Public API ───────────────────────────────────────────────────

    async def run(self, query: str | None = None) -> MiningResult:
        """Execute the full pipeline for the configured domain.

        Parameters
        ----------
        query : str | None
            Optional search query to narrow source discovery.
            Defaults to the domain name.
        """
        query = query or self.db.domain
        result = MiningResult(
            domain=self.db.domain,
            source_language=self.db.source_lang,
            target_language=self.db.target_lang,
        )

        # Stage 1 + 2: Source discovery & text extraction
        all_source_results: list[SourceResult] = []
        for source in self.sources:
            try:
                results = await source.search(query, max_results=self.cfg.mining.max_sources)
                for sr in results:
                    sr.text = await source.extract_text(sr)
                all_source_results.extend(results)
                result.sources_processed += 1
            except Exception as exc:
                logger.warning("Source %s failed: %s", source.name, exc)
                result.errors.append(f"{source.name}: {exc}")

        # Stage 3 + 4: NLP processing & vocab extraction
        extracted_terms: dict[str, ExtractedTerm] = {}
        for sr in all_source_results:
            if not sr.text:
                continue
            tokens = self.tokenizer.process(sr.text)
            for tok in tokens:
                key = tok.lemma.lower()
                if key not in extracted_terms:
                    extracted_terms[key] = ExtractedTerm(
                        term=tok.text,
                        lemma=tok.lemma,
                        pos=tok.pos,
                        source_url=sr.url,
                    )
                extracted_terms[key].frequency += 1.0

        # Stage 5: CEFR classification
        for et in extracted_terms.values():
            level, method = self.cefr_classifier.classify(et.lemma)
            et_level = level  # store for later use

        # Stage 6: Domain tagging — filter out off-domain terms
        domain_terms = [
            et for et in extracted_terms.values()
            if self.domain_tagger.is_relevant(et.lemma)
        ]

        # Stage 7: Persist to DB
        for et in domain_terms:
            level, method = self.cefr_classifier.classify(et.lemma)
            self.db.add_vocabulary(
                term=et.term,
                lemma=et.lemma,
                pos=et.pos,
                level=level,
                method=method,
                frequency=et.frequency,
                source_url=et.source_url,
            )
            result.terms_added += 1

        # Extract and store phrases
        for sr in all_source_results:
            if not sr.text:
                continue
            phrases = self.phrase_extractor.extract(sr.text)
            for phrase_text in phrases:
                level, method = self.cefr_classifier.classify_phrase(phrase_text)
                self.db.add_phrase(
                    text=phrase_text,
                    level=level,
                    method=method,
                    source_url=sr.url,
                )
                result.phrases_added += 1

        logger.info(
            "Mining complete: %d terms, %d phrases from %d sources",
            result.terms_added,
            result.phrases_added,
            result.sources_processed,
        )
        return result
