"""Database layer — per-domain SQLite vocabulary databases."""

from langwich.db.models import VocabularyEntry, PhraseEntry, DomainMeta
from langwich.db.manager import DomainDatabase

__all__ = ["VocabularyEntry", "PhraseEntry", "DomainMeta", "DomainDatabase"]
