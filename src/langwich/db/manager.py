"""Domain database manager — creates and operates per-domain SQLite databases.

Usage
─────
    db = DomainDatabase(domain="railway-operations", source_lang="en", target_lang="de")
    db.initialize()
    db.add_vocabulary(term="platform", lemma="platform", pos=PartOfSpeech.NOUN, level=CEFRLevel.A2)
    results = db.query_vocabulary(level=CEFRLevel.A2, limit=20)
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional, Sequence

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from langwich.db.models import (
    Base,
    CEFRLevel,
    ClassificationMethod,
    DomainMeta,
    PartOfSpeech,
    PhraseEntry,
    VocabularyEntry,
)

logger = logging.getLogger(__name__)


class DomainDatabase:
    """Manages a single per-domain SQLite vocabulary database.

    Parameters
    ----------
    domain : str
        The knowledge domain, e.g. ``"railway-operations"``.
    source_lang : str
        ISO 639-1 code for the language of the source texts.
    target_lang : str
        ISO 639-1 code for the learner's native language (translations).
    db_dir : Path | str
        Directory where ``.sqlite`` files are stored. Defaults to ``./data/``.
    """

    def __init__(
        self,
        domain: str,
        source_lang: str,
        target_lang: str,
        db_dir: Path | str = Path("./data"),
    ) -> None:
        self.domain = domain
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.db_dir = Path(db_dir)

        slug = f"{domain}_{source_lang}_{target_lang}".replace(" ", "-").lower()
        self.db_path = self.db_dir / f"{slug}.sqlite"

        self._engine: Engine | None = None
        self._session_factory: sessionmaker[Session] | None = None
        self._meta: DomainMeta | None = None

        # Optional grammar content (populated from JSON import)
        self.grammar_topic: str | None = None
        self.grammar_content: str | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create the database file and tables if they don't exist."""
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(f"sqlite:///{self.db_path}", echo=False)
        Base.metadata.create_all(self._engine)
        self._session_factory = sessionmaker(bind=self._engine)

        with self.session() as ses:
            existing = ses.execute(
                select(DomainMeta).where(DomainMeta.domain == self.domain)
            ).scalar_one_or_none()
            if existing is None:
                self._meta = DomainMeta(
                    domain=self.domain,
                    source_language=self.source_lang,
                    target_language=self.target_lang,
                )
                ses.add(self._meta)
                ses.commit()
                ses.refresh(self._meta)
            else:
                self._meta = existing

        logger.info("Database ready: %s", self.db_path)

    def session(self) -> Session:
        """Return a new SQLAlchemy session (use as context manager)."""
        if self._session_factory is None:
            raise RuntimeError("Call .initialize() before using the database.")
        return self._session_factory()

    @property
    def meta(self) -> DomainMeta:
        if self._meta is None:
            raise RuntimeError("Call .initialize() first.")
        return self._meta

    # ── Vocabulary CRUD ──────────────────────────────────────────────

    def add_vocabulary(
        self,
        term: str,
        lemma: str,
        pos: PartOfSpeech,
        level: CEFRLevel = CEFRLevel.UNKNOWN,
        method: ClassificationMethod = ClassificationMethod.FREQUENCY_LIST,
        frequency: float = 0.0,
        source_url: str | None = None,
        translations: list[str] | None = None,
    ) -> VocabularyEntry:
        """Insert or update a vocabulary entry. Returns the persisted object."""
        with self.session() as ses:
            existing = ses.execute(
                select(VocabularyEntry).where(
                    VocabularyEntry.term == term,
                    VocabularyEntry.domain_meta_id == self.meta.id,
                )
            ).scalar_one_or_none()

            if existing is not None:
                existing.cefr_level = level
                existing.frequency = max(existing.frequency, frequency)
                entry = existing
            else:
                entry = VocabularyEntry(
                    domain_meta_id=self.meta.id,
                    term=term,
                    lemma=lemma,
                    part_of_speech=pos,
                    cefr_level=level,
                    classification_method=method,
                    frequency=frequency,
                    source_url=source_url,
                    translations_json=json.dumps(translations) if translations else None,
                )
                ses.add(entry)
            ses.commit()
            ses.refresh(entry)
            return entry

    def add_phrase(
        self,
        text: str,
        level: CEFRLevel = CEFRLevel.UNKNOWN,
        translation: str | None = None,
        method: ClassificationMethod = ClassificationMethod.FREQUENCY_LIST,
        source_url: str | None = None,
        vocabulary_ids: Sequence[int] | None = None,
    ) -> PhraseEntry:
        """Insert a phrase and optionally link it to vocabulary entries."""
        with self.session() as ses:
            phrase = PhraseEntry(
                domain_meta_id=self.meta.id,
                text=text,
                translation=translation,
                cefr_level=level,
                classification_method=method,
                source_url=source_url,
            )
            if vocabulary_ids:
                vocabs = ses.execute(
                    select(VocabularyEntry).where(VocabularyEntry.id.in_(vocabulary_ids))
                ).scalars().all()
                phrase.vocabulary = list(vocabs)
            ses.add(phrase)
            ses.commit()
            ses.refresh(phrase)
            return phrase

    def query_vocabulary(
        self,
        level: CEFRLevel | None = None,
        pos: PartOfSpeech | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[VocabularyEntry]:
        """Query vocabulary entries with optional filters."""
        with self.session() as ses:
            stmt = select(VocabularyEntry).where(
                VocabularyEntry.domain_meta_id == self.meta.id
            )
            if level is not None:
                stmt = stmt.where(VocabularyEntry.cefr_level == level)
            if pos is not None:
                stmt = stmt.where(VocabularyEntry.part_of_speech == pos)
            stmt = stmt.order_by(VocabularyEntry.frequency.desc()).offset(offset).limit(limit)
            return list(ses.execute(stmt).scalars().all())

    def query_phrases(
        self,
        level: CEFRLevel | None = None,
        limit: int = 20,
    ) -> list[PhraseEntry]:
        """Query phrase entries with optional level filter."""
        with self.session() as ses:
            stmt = select(PhraseEntry).where(
                PhraseEntry.domain_meta_id == self.meta.id
            )
            if level is not None:
                stmt = stmt.where(PhraseEntry.cefr_level == level)
            stmt = stmt.limit(limit)
            return list(ses.execute(stmt).scalars().all())

    def count_vocabulary(self, level: Optional[CEFRLevel] = None) -> int:
        """Return the total number of vocabulary entries, optionally filtered by level."""
        with self.session() as ses:
            from sqlalchemy import func as sa_func

            stmt = select(sa_func.count(VocabularyEntry.id)).where(
                VocabularyEntry.domain_meta_id == self.meta.id
            )
            if level is not None:
                stmt = stmt.where(VocabularyEntry.cefr_level == level)
            return ses.execute(stmt).scalar_one()
