"""Source-text model — the single input that drives a whole worksheet.

The text is the gold mine: every exercise derives its content from it.

A ``SourceText`` carries four kinds of material, all optional except the text
itself:

* ``content`` / ``translation`` — the story, in the target and source language.
* ``vocabulary`` — the words the story teaches.
* ``grammar`` — the grammatical phenomena the story deliberately exhibits
  (the "grammatical twists" a worksheet is built around).
* ``picture_scene`` — a fully described scene that picture exercises query.

Everything is plain data so it can be produced by an LLM, written by hand, or
round-tripped through JSON without loss.  No exercise generator hard-codes any
content; if a fact is needed (a colour, a position, a compound) it lives here.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langwich.graph import (
    GrammarNode,
    GrammarPhenomenon,
    NodeType,
    SemanticType,
    VocabularyItem,
    VocabularyNode,
)


# ---------------------------------------------------------------------------
# Picture scene
# ---------------------------------------------------------------------------

@dataclass
class SceneElement:
    """One object that appears in the picture.

    Picture exercises read these structured facts instead of guessing, which is
    what makes them work for *any* topic.  ``color`` and ``position`` are written
    in the target language so they can be used verbatim as answers.
    """

    name: str  # target-language noun phrase, e.g. "die Tasse"
    color: str | None = None  # target-language colour, e.g. "weiß"
    position: str | None = None  # full target-language sentence: "Die Tasse steht neben dem Teller."
    key: bool = True  # a primary object (named / marked / counted)

    @classmethod
    def from_any(cls, value: object) -> SceneElement:
        """Accept either a plain string or a structured dict."""
        if isinstance(value, str):
            return cls(name=value)
        if isinstance(value, dict):
            return cls(
                name=value["name"],
                color=value.get("color"),
                position=value.get("position"),
                key=bool(value.get("key", True)),
            )
        raise TypeError(f"cannot build SceneElement from {value!r}")

    def to_dict(self) -> dict:
        d: dict = {"name": self.name, "key": self.key}
        if self.color:
            d["color"] = self.color
        if self.position:
            d["position"] = self.position
        return d


@dataclass
class PictureScene:
    """A scene the text describes, used to generate an image and query it."""

    description: str  # English image-generation prompt
    elements: list[SceneElement] = field(default_factory=list)
    paragraph_index: int = 0  # which paragraph of ``content`` describes the scene
    caption: str | None = None  # short caption printed under the picture box

    # -- queries used by picture exercises --
    def colored(self) -> list[SceneElement]:
        return [e for e in self.elements if e.color]

    def positioned(self) -> list[SceneElement]:
        return [e for e in self.elements if e.position]

    def key_elements(self) -> list[SceneElement]:
        return [e for e in self.elements if e.key]

    @property
    def element_names(self) -> list[str]:
        return [e.name for e in self.elements]

    def to_dict(self) -> dict:
        d: dict = {
            "description": self.description,
            "elements": [e.to_dict() for e in self.elements],
            "paragraph_index": self.paragraph_index,
        }
        if self.caption:
            d["caption"] = self.caption
        return d


# ---------------------------------------------------------------------------
# Compounds (optional structured material for the morphology exercise)
# ---------------------------------------------------------------------------

@dataclass
class Compound:
    """A compound word split into its parts (e.g. Kaffee + Bohne = Kaffeebohne)."""

    left: str
    right: str
    compound: str
    translation: str | None = None

    @classmethod
    def from_dict(cls, d: dict) -> Compound:
        return cls(
            left=d["left"],
            right=d["right"],
            compound=d["compound"],
            translation=d.get("translation"),
        )

    def to_dict(self) -> dict:
        d: dict = {"left": self.left, "right": self.right, "compound": self.compound}
        if self.translation:
            d["translation"] = self.translation
        return d


# ---------------------------------------------------------------------------
# Source text
# ---------------------------------------------------------------------------

@dataclass
class SourceText:
    """A text that drives exercise generation."""

    title: str
    content: str  # full story in the target language
    translation: str  # full story in the source language
    source_lang: str  # ISO 639-1
    target_lang: str  # ISO 639-1
    cefr_level: str  # A1-C2
    topic: str

    picture_scene: PictureScene | None = None
    vocabulary: VocabularyNode | None = None
    grammar: GrammarNode | None = None
    compounds: list[Compound] = field(default_factory=list)

    # -- derived views -----------------------------------------------------
    @property
    def paragraphs(self) -> list[str]:
        return [p.strip() for p in self.content.split("\n\n") if p.strip()]

    @property
    def translation_paragraphs(self) -> list[str]:
        return [p.strip() for p in self.translation.split("\n\n") if p.strip()]

    @property
    def picture_paragraph(self) -> str | None:
        if self.picture_scene is None:
            return None
        paras = self.paragraphs
        idx = self.picture_scene.paragraph_index
        return paras[idx] if 0 <= idx < len(paras) else None

    # -- serialisation -----------------------------------------------------
    def to_dict(self) -> dict:
        d: dict = {
            "title": self.title,
            "content": self.content,
            "translation": self.translation,
            "source_lang": self.source_lang,
            "target_lang": self.target_lang,
            "cefr_level": self.cefr_level,
            "topic": self.topic,
        }
        if self.picture_scene:
            d["picture_scene"] = self.picture_scene.to_dict()
        if self.vocabulary:
            d["vocabulary"] = self.vocabulary.to_dict()
        if self.grammar:
            d["grammar"] = self.grammar.to_dict()
        if self.compounds:
            d["compounds"] = [c.to_dict() for c in self.compounds]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> SourceText:
        return cls(
            title=data["title"],
            content=data["content"],
            translation=data["translation"],
            source_lang=data["source_lang"],
            target_lang=data["target_lang"],
            cefr_level=data["cefr_level"],
            topic=data["topic"],
            picture_scene=_scene_from_dict(data.get("picture_scene")),
            vocabulary=_vocab_from_dict(data.get("vocabulary")),
            grammar=_grammar_from_dict(data.get("grammar")),
            compounds=[Compound.from_dict(c) for c in data.get("compounds", [])],
        )


# ---------------------------------------------------------------------------
# Parsing helpers (tolerant of partial / LLM-authored JSON)
# ---------------------------------------------------------------------------

def _scene_from_dict(ps: dict | None) -> PictureScene | None:
    if not ps:
        return None
    return PictureScene(
        description=ps["description"],
        elements=[SceneElement.from_any(e) for e in ps.get("elements", [])],
        paragraph_index=ps.get("paragraph_index", 0),
        caption=ps.get("caption"),
    )


def _safe_semantic_type(value: object) -> SemanticType:
    if isinstance(value, str):
        try:
            return SemanticType(value)
        except ValueError:
            return SemanticType.OTHER
    return SemanticType.OTHER


def _vocab_from_dict(vd: dict | list | None) -> VocabularyNode | None:
    if not vd:
        return None
    raw_items = vd if isinstance(vd, list) else vd.get("items", [])
    items = [
        VocabularyItem(
            term=it["term"],
            translation=it["translation"],
            pos=it.get("pos", "noun"),
            semantic_type=_safe_semantic_type(it.get("semantic_type")),
            synonym=it.get("synonym"),
            antonym=it.get("antonym"),
        )
        for it in raw_items
    ]
    name = vd.get("name", "Vocabulary") if isinstance(vd, dict) else "Vocabulary"
    return VocabularyNode(id="vocab", name=name, node_type=NodeType.RESOURCE, items=items)


def _grammar_from_dict(gd: dict | list | None) -> GrammarNode | None:
    if not gd:
        return None
    raw = gd if isinstance(gd, list) else gd.get("phenomena", [])
    phenomena = [
        GrammarPhenomenon(
            name=p["name"],
            description=p["description"],
            examples=p.get("examples", []),
        )
        for p in raw
    ]
    return GrammarNode(
        id="grammar", name="Grammar", node_type=NodeType.RESOURCE, phenomena=phenomena
    )
