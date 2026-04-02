"""SpaCy-based tokeniser with lemmatisation and POS tagging."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langwich.db.models import PartOfSpeech

logger = logging.getLogger(__name__)

# Mapping from SpaCy's universal POS tags to our enum.
_SPACY_POS_MAP: dict[str, PartOfSpeech] = {
    "NOUN": PartOfSpeech.NOUN,
    "VERB": PartOfSpeech.VERB,
    "ADJ": PartOfSpeech.ADJECTIVE,
    "ADV": PartOfSpeech.ADVERB,
    "ADP": PartOfSpeech.PREPOSITION,
    "CCONJ": PartOfSpeech.CONJUNCTION,
    "SCONJ": PartOfSpeech.CONJUNCTION,
    "PRON": PartOfSpeech.PRONOUN,
    "DET": PartOfSpeech.DETERMINER,
    "INTJ": PartOfSpeech.INTERJECTION,
    "NUM": PartOfSpeech.NUMERAL,
    "PART": PartOfSpeech.PARTICLE,
}


@dataclass(frozen=True)
class Token:
    """A processed token with its linguistic annotations."""

    text: str
    lemma: str
    pos: PartOfSpeech
    is_stop: bool
    is_alpha: bool


class Tokenizer:
    """Wraps a SpaCy pipeline for tokenisation, lemmatisation, and POS tagging.

    Parameters
    ----------
    spacy_model : str
        Name of the SpaCy model to load (e.g. ``"en_core_web_sm"``).
    min_token_length : int
        Discard tokens shorter than this.
    """

    def __init__(self, spacy_model: str = "en_core_web_sm", min_token_length: int = 2) -> None:
        self.min_token_length = min_token_length
        self._nlp = self._load_model(spacy_model)

    @staticmethod
    def _load_model(model_name: str):  # noqa: ANN205 — returns spacy.Language
        """Load a SpaCy model, downloading it if necessary."""
        try:
            import spacy

            return spacy.load(model_name)
        except OSError:
            logger.info("Downloading SpaCy model %s …", model_name)
            import spacy.cli

            spacy.cli.download(model_name)
            import spacy

            return spacy.load(model_name)

    def process(self, text: str) -> list[Token]:
        """Tokenise, lemmatise, and POS-tag *text*.

        Returns a list of ``Token`` objects filtered to meaningful
        content words (no punctuation, no whitespace, respects min length).
        """
        doc = self._nlp(text)
        tokens: list[Token] = []
        for tok in doc:
            if tok.is_punct or tok.is_space:
                continue
            if len(tok.text) < self.min_token_length:
                continue

            pos = _SPACY_POS_MAP.get(tok.pos_, PartOfSpeech.OTHER)
            tokens.append(
                Token(
                    text=tok.text,
                    lemma=tok.lemma_,
                    pos=pos,
                    is_stop=tok.is_stop,
                    is_alpha=tok.is_alpha,
                )
            )
        return tokens

    def sentences(self, text: str) -> list[str]:
        """Split *text* into sentences using SpaCy's sentence boundary detection."""
        doc = self._nlp(text)
        return [sent.text.strip() for sent in doc.sents]
