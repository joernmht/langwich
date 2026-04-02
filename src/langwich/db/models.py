"""SQLAlchemy ORM models for the per-domain vocabulary database.

Each domain+language combination gets its own SQLite file so that databases
stay small, portable, and git-friendly.

Schema overview
───────────────
  domain_meta     1-to-many  vocabulary_entries
  domain_meta     1-to-many  phrase_entries
  vocabulary_entries  many-to-many  phrase_entries  (via vocab_phrase_link)
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── Enums ────────────────────────────────────────────────────────────

class CEFRLevel(str, enum.Enum):
    """Common European Framework of Reference levels."""
    A1 = "A1"
    A2 = "A2"
    B1 = "B1"
    B2 = "B2"
    C1 = "C1"
    C2 = "C2"
    UNKNOWN = "UNKNOWN"


class PartOfSpeech(str, enum.Enum):
    """Broad part-of-speech categories."""
    NOUN = "NOUN"
    VERB = "VERB"
    ADJECTIVE = "ADJ"
    ADVERB = "ADV"
    PREPOSITION = "PREP"
    CONJUNCTION = "CONJ"
    PRONOUN = "PRON"
    DETERMINER = "DET"
    INTERJECTION = "INTJ"
    NUMERAL = "NUM"
    PARTICLE = "PART"
    OTHER = "OTHER"


class ClassificationMethod(str, enum.Enum):
    """How the CEFR level was determined."""
    FREQUENCY_LIST = "frequency_list"
    LLM_FALLBACK = "llm_fallback"
    MANUAL = "manual"


# ── Base ─────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared declarative base for all langwich models."""
    pass


# ── Association table ────────────────────────────────────────────────

vocab_phrase_link = Table(
    "vocab_phrase_link",
    Base.metadata,
    Column("vocabulary_id", Integer, ForeignKey("vocabulary_entries.id"), primary_key=True),
    Column("phrase_id", Integer, ForeignKey("phrase_entries.id"), primary_key=True),
)


# ── Domain metadata ─────────────────────────────────────────────────

class DomainMeta(Base):
    """Metadata record for the domain this database covers."""

    __tablename__ = "domain_meta"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    source_language: Mapped[str] = mapped_column(String(10), nullable=False, doc="ISO 639-1 code")
    target_language: Mapped[str] = mapped_column(String(10), nullable=False, doc="ISO 639-1 code")
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    vocabulary_entries: Mapped[list[VocabularyEntry]] = relationship(
        back_populates="domain_meta", cascade="all, delete-orphan"
    )
    phrase_entries: Mapped[list[PhraseEntry]] = relationship(
        back_populates="domain_meta", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<DomainMeta(domain={self.domain!r}, "
            f"{self.source_language}→{self.target_language})>"
        )


# ── Vocabulary (single words / terms) ───────────────────────────────

class VocabularyEntry(Base):
    """A single vocabulary term with its CEFR level and metadata."""

    __tablename__ = "vocabulary_entries"
    __table_args__ = (
        UniqueConstraint("term", "domain_meta_id", name="uq_term_domain"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain_meta_id: Mapped[int] = mapped_column(ForeignKey("domain_meta.id"), nullable=False)

    term: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    lemma: Mapped[str] = mapped_column(String(300), nullable=False, index=True)
    part_of_speech: Mapped[PartOfSpeech] = mapped_column(Enum(PartOfSpeech), nullable=False)

    cefr_level: Mapped[CEFRLevel] = mapped_column(
        Enum(CEFRLevel), nullable=False, default=CEFRLevel.UNKNOWN
    )
    classification_method: Mapped[ClassificationMethod] = mapped_column(
        Enum(ClassificationMethod), nullable=False, default=ClassificationMethod.FREQUENCY_LIST
    )

    frequency: Mapped[float] = mapped_column(Float, default=0.0, doc="Normalised frequency score")
    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Translations stored as JSON-serialised list of strings (lightweight).
    translations_json: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, doc='JSON list, e.g. ["Bahnsteig", "Gleis"]'
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    domain_meta: Mapped[DomainMeta] = relationship(back_populates="vocabulary_entries")
    phrases: Mapped[list[PhraseEntry]] = relationship(
        secondary=vocab_phrase_link, back_populates="vocabulary"
    )

    def __repr__(self) -> str:
        return f"<VocabularyEntry({self.term!r} [{self.cefr_level.value}])>"


# ── Phrases ──────────────────────────────────────────────────────────

class PhraseEntry(Base):
    """A phrase or example sentence linked to one or more vocabulary entries."""

    __tablename__ = "phrase_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain_meta_id: Mapped[int] = mapped_column(ForeignKey("domain_meta.id"), nullable=False)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    translation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    cefr_level: Mapped[CEFRLevel] = mapped_column(
        Enum(CEFRLevel), nullable=False, default=CEFRLevel.UNKNOWN
    )
    classification_method: Mapped[ClassificationMethod] = mapped_column(
        Enum(ClassificationMethod), nullable=False, default=ClassificationMethod.FREQUENCY_LIST
    )

    source_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # Relationships
    domain_meta: Mapped[DomainMeta] = relationship(back_populates="phrase_entries")
    vocabulary: Mapped[list[VocabularyEntry]] = relationship(
        secondary=vocab_phrase_link, back_populates="phrases"
    )

    def __repr__(self) -> str:
        preview = self.text[:40] + "…" if len(self.text) > 40 else self.text
        return f"<PhraseEntry({preview!r} [{self.cefr_level.value}])>"
