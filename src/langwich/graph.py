"""Exercise knowledge graph.

Defines the node hierarchy (resources + exercises), their attributes, and
connections.  This graph is the single source of truth for what exists and
how things relate.  Both LLMs and deterministic systems can consume it.

Node hierarchy
--------------
GraphNode (base)
├── ResourceNode
│   ├── VocabularyNode   — word + translation + optional synonym/antonym
│   └── GrammarNode      — grammar phenomenon found in a text
└── ExerciseNode
    ├── FIB subclasses   — fill-in-blank variations
    ├── Picture subclasses — picture-interaction variations
    └── WordConn subclasses — word-connection variations
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class NodeType(str, Enum):
    RESOURCE = "resource"
    EXERCISE = "exercise"


class ExerciseType(str, Enum):
    FILL_IN_BLANKS = "fib"
    PICTURE_INTERACTION = "picture"
    WORD_CONNECTIONS = "word_connections"
    PUZZLE = "puzzle"
    TEXT_ANALYSIS = "text_analysis"
    WRITING = "writing"
    DIALOGUE = "dialogue"
    MEDIA = "media"
    SOCIAL_MEDIA = "social_media"
    REAL_WORLD = "real_world"
    NUMBERS = "numbers"
    STUDY = "study"


class LearningFocus(str, Enum):
    VOCABULARY = "vocabulary"
    GRAMMAR = "grammar"
    WORD_MANIPULATION = "word_manipulation"
    CREATIVITY = "creativity"
    ERROR_CORRECTION = "error_correction"
    SPATIAL_LANGUAGE = "spatial_language"
    PHONETICS = "phonetics"
    MORPHOLOGY = "morphology"
    READING_COMPREHENSION = "reading_comprehension"
    SPELLING = "spelling"
    LISTENING = "listening"
    SPEAKING = "speaking"
    WRITING_PRODUCTION = "writing"
    CULTURE = "culture"
    NUMERACY = "numeracy"


class SemanticType(str, Enum):
    """Abstract semantic category for vocabulary items (used by tasks)."""
    COLOR = "color"
    POSITION = "position"
    CLOTHING = "clothing"
    FOOD = "food"
    DRINK = "drink"
    FURNITURE = "furniture"
    BODY = "body"
    ANIMAL = "animal"
    PROFESSION = "profession"
    EMOTION = "emotion"
    WEATHER = "weather"
    TIME = "time"
    OTHER = "other"


class EdgeType(str, Enum):
    FEEDS_VOCABULARY_TO = "feeds_vocabulary_to"
    REFERENCES_ELEMENTS_OF = "references_elements_of"
    COMBINES_WITH = "combines_with"
    REQUIRES_OUTPUT_OF = "requires_output_of"
    DERIVES_FROM_TEXT = "derives_from_text"
    PROVIDES_RESOURCE_TO = "provides_resource_to"


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    """Base class for all graph nodes."""
    id: str
    name: str
    node_type: NodeType = NodeType.RESOURCE

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "node_type": self.node_type.value}


# ── Resource nodes ────────────────────────────────────────────────────

@dataclass
class VocabularyItem:
    """Single vocabulary entry within a VocabularyNode."""
    term: str
    translation: str
    pos: str  # verb, noun, adjective, adverb, preposition, ...
    semantic_type: SemanticType = SemanticType.OTHER
    synonym: str | None = None
    antonym: str | None = None

    def to_dict(self) -> dict:
        d: dict = {
            "term": self.term,
            "translation": self.translation,
            "pos": self.pos,
            "semantic_type": self.semantic_type.value,
        }
        if self.synonym:
            d["synonym"] = self.synonym
        if self.antonym:
            d["antonym"] = self.antonym
        return d


@dataclass
class VocabularyNode(GraphNode):
    """A vocabulary list extracted from / associated with a text."""
    items: list[VocabularyItem] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.node_type = NodeType.RESOURCE

    def by_semantic_type(self, st: SemanticType) -> list[VocabularyItem]:
        return [i for i in self.items if i.semantic_type == st]

    def by_pos(self, pos: str) -> list[VocabularyItem]:
        return [i for i in self.items if i.pos == pos]

    def with_synonyms(self) -> list[VocabularyItem]:
        return [i for i in self.items if i.synonym]

    def with_antonyms(self) -> list[VocabularyItem]:
        return [i for i in self.items if i.antonym]

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["items"] = [i.to_dict() for i in self.items]
        return d


@dataclass
class GrammarPhenomenon:
    """A single grammar phenomenon found in a text."""
    name: str  # e.g. "present tense", "compound nouns", "subordinate clauses"
    description: str
    examples: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "examples": self.examples,
        }


@dataclass
class GrammarNode(GraphNode):
    """Grammar phenomena found in / relevant to a text."""
    phenomena: list[GrammarPhenomenon] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.node_type = NodeType.RESOURCE

    def has_phenomenon(self, name: str) -> bool:
        return any(p.name.lower() == name.lower() for p in self.phenomena)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["phenomena"] = [p.to_dict() for p in self.phenomena]
        return d


# ── Exercise nodes ────────────────────────────────────────────────────

@dataclass
class ExerciseNode(GraphNode):
    """One exercise subclass in the knowledge graph."""

    exercise_type: ExerciseType = ExerciseType.FILL_IN_BLANKS
    description: str = ""
    difficulty: int = 1  # 1-5
    cefr_range: tuple[str, str] = ("A1", "C2")
    learning_focus: list[LearningFocus] = field(default_factory=list)
    pre_knowledge: list[str] = field(default_factory=list)
    estimated_minutes: int = 5
    example: dict = field(default_factory=dict)

    # FIB-specific
    hint_type: str | None = None
    blank_target: str | None = None

    # Picture-specific
    required_elements: list[str] = field(default_factory=list)

    # WordConnections-specific
    connection_type: str | None = None

    # Media-specific: which culture-library category feeds this exercise
    # ("podcast", "video", "music", "news", "film_tv", "radio", "social")
    media_category: str | None = None

    combinable_with: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.node_type = NodeType.EXERCISE

    def to_dict(self) -> dict:
        d = super().to_dict()
        d.update({
            "exercise_type": self.exercise_type.value,
            "description": self.description,
            "difficulty": self.difficulty,
            "cefr_range": list(self.cefr_range),
            "learning_focus": [f.value for f in self.learning_focus],
            "pre_knowledge": self.pre_knowledge,
            "estimated_minutes": self.estimated_minutes,
            "hint_type": self.hint_type,
            "blank_target": self.blank_target,
            "required_elements": self.required_elements,
            "connection_type": self.connection_type,
            "media_category": self.media_category,
            "combinable_with": self.combinable_with,
            "example": self.example,
        })
        return d


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """Directed connection between two graph nodes."""
    source: str  # node id
    target: str  # node id
    edge_type: EdgeType
    label: str = ""

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type.value,
            "label": self.label,
        }


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------

class ExerciseGraph:
    """Knowledge graph of resources, exercise types, and their relationships."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.edges: list[Edge] = []

    def add_node(self, node: GraphNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    # -- Query helpers --

    def exercises(self) -> list[ExerciseNode]:
        return [n for n in self.nodes.values() if isinstance(n, ExerciseNode)]

    def resources(self) -> list[GraphNode]:
        return [n for n in self.nodes.values()
                if isinstance(n, (VocabularyNode, GrammarNode))]

    def get_by_type(self, exercise_type: ExerciseType) -> list[ExerciseNode]:
        return [n for n in self.exercises() if n.exercise_type == exercise_type]

    def get_combinable(self, node_id: str) -> list[ExerciseNode]:
        node = self.nodes[node_id]
        if not isinstance(node, ExerciseNode):
            return []
        return [self.nodes[cid] for cid in node.combinable_with  # type: ignore[misc]
                if cid in self.nodes and isinstance(self.nodes[cid], ExerciseNode)]

    def get_edges_from(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def get_edges_to(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def by_difficulty(self, max_difficulty: int) -> list[ExerciseNode]:
        return sorted(
            [n for n in self.exercises() if n.difficulty <= max_difficulty],
            key=lambda n: n.difficulty,
        )

    def to_dict(self) -> dict:
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
        }


# ---------------------------------------------------------------------------
# Default graph with all known exercise subclasses
# ---------------------------------------------------------------------------

def build_default_graph() -> ExerciseGraph:
    """Construct the complete exercise knowledge graph."""
    g = ExerciseGraph()

    # ── Fill-in-Blanks ────────────────────────────────────────────────
    fib_nodes = [
        ExerciseNode(
            id="fib_word_bank",
            name="FIB: Word Bank",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="Blanks with a shuffled word bank for the whole text. "
            "Learner picks from a shared pool.",
            difficulty=2,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["word recognition"],
            estimated_minutes=5,
            hint_type="word_bank",
            blank_target="content_words",
            combinable_with=["wc_translation", "wc_category"],
            example={
                "text": "Jeden Morgen beginnt der Tag mit einer Tasse ______.",
                "bank": ["Kaffee", "Milch", "Zucker", "Wasser"],
                "answer": "Kaffee",
            },
        ),
        ExerciseNode(
            id="fib_first_letter",
            name="FIB: First Letter",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="Only the first letter of the missing word is given. "
            "Tests spelling and recall.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.SPELLING],
            pre_knowledge=["basic vocabulary", "spelling patterns"],
            estimated_minutes=5,
            hint_type="first_letter",
            blank_target="content_words",
            combinable_with=["wc_translation"],
            example={
                "text": "Die Kaffeepflanze wächst in t______ Ländern.",
                "hint": "t",
                "answer": "tropischen",
            },
        ),
        ExerciseNode(
            id="fib_multiple_choice",
            name="FIB: Multiple Choice",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="Each blank has 2-4 options to choose from. "
            "Tests discrimination between similar words or forms.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.GRAMMAR],
            pre_knowledge=["word forms"],
            estimated_minutes=4,
            hint_type="multiple_choice",
            blank_target="content_words",
            combinable_with=["fib_word_bank", "wc_synonym"],
            example={
                "text": "Die Bauern ______ die Kaffeekirschen.",
                "choices": ["ernten", "erntet", "geerntet", "erntete"],
                "answer": "ernten",
            },
        ),
        ExerciseNode(
            id="fib_translation_hint",
            name="FIB: Translation Hint",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="The translation (or synonym/antonym) of the missing word is given. "
            "Bridges between languages.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["bilingual vocabulary"],
            estimated_minutes=5,
            hint_type="translation",
            blank_target="content_words",
            combinable_with=["wc_translation", "wc_synonym"],
            example={
                "text": "Die Röstung bestimmt den ______ (taste).",
                "hint": "taste",
                "answer": "Geschmack",
            },
        ),
        ExerciseNode(
            id="fib_base_form",
            name="FIB: Base Form",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="The dictionary/base form is given, learner must produce "
            "the correct inflected form. Tests conjugation and declension.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.WORD_MANIPULATION, LearningFocus.GRAMMAR],
            pre_knowledge=["conjugation rules", "declension patterns"],
            estimated_minutes=6,
            hint_type="base_form",
            blank_target="inflected_forms",
            combinable_with=["fib_word_bank"],
            example={
                "text": "Die Kaffeepflanze ______ (wachsen) in tropischen Ländern.",
                "hint": "wachsen",
                "answer": "wächst",
            },
        ),
        ExerciseNode(
            id="fib_no_hint",
            name="FIB: No Hint",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="No hints at all. Pure recall from context.",
            difficulty=4,
            cefr_range=("B1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.READING_COMPREHENSION],
            pre_knowledge=["strong vocabulary", "reading comprehension"],
            estimated_minutes=7,
            hint_type="none",
            blank_target="content_words",
            combinable_with=["wc_translation"],
            example={
                "text": "Kaffee ist mehr als ein ______ – er bringt Menschen zusammen.",
                "answer": "Getränk",
            },
        ),
        ExerciseNode(
            id="fib_full_translation",
            name="FIB: Full Translation",
            exercise_type=ExerciseType.FILL_IN_BLANKS,
            description="The complete translated text is provided. "
            "Learner fills blanks using the translation as reference.",
            difficulty=3,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.READING_COMPREHENSION],
            pre_knowledge=["reading ability in source language"],
            estimated_minutes=6,
            hint_type="full_translation",
            blank_target="content_words",
            combinable_with=["wc_translation"],
            example={
                "text": "Die ______ ernten die roten Kaffeekirschen von ______.",
                "translation": "The farmers harvest the red coffee cherries by hand.",
                "answers": ["Bauern", "Hand"],
            },
        ),
    ]

    # ── Picture Interaction ───────────────────────────────────────────
    pic_nodes = [
        ExerciseNode(
            id="pic_color_query",
            name="Picture: Color Query",
            exercise_type=ExerciseType.PICTURE_INTERACTION,
            description="Ask 'What color is [element]?' about objects in the picture. "
            "Tests color vocabulary and object identification.",
            difficulty=1,
            cefr_range=("A1", "A2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["colors", "basic nouns"],
            estimated_minutes=3,
            required_elements=["colored objects"],
            combinable_with=["pic_object_naming", "wc_category"],
            example={
                "question": "Welche Farbe hat die Tasse?",
                "answer": "Die Tasse ist weiß.",
                "picture_must_contain": ["white cup"],
            },
        ),
        ExerciseNode(
            id="pic_element_marking",
            name="Picture: Element Marking",
            exercise_type=ExerciseType.PICTURE_INTERACTION,
            description="'Mark [element] in the picture!' or 'Circle [element]'. "
            "Tests object identification and vocabulary.",
            difficulty=1,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["basic nouns"],
            estimated_minutes=3,
            required_elements=["named objects"],
            combinable_with=["pic_color_query", "pic_object_naming"],
            example={
                "instruction": "Kreise das Fahrrad im Bild ein!",
                "picture_must_contain": ["bicycle"],
            },
        ),
        ExerciseNode(
            id="pic_position",
            name="Picture: Position Description",
            exercise_type=ExerciseType.PICTURE_INTERACTION,
            description="'Describe the position of A relative to B.' "
            "Tests spatial prepositions and descriptive language.",
            difficulty=3,
            cefr_range=("A2", "B2"),
            learning_focus=[LearningFocus.SPATIAL_LANGUAGE, LearningFocus.GRAMMAR],
            pre_knowledge=["prepositions", "basic sentence structure"],
            estimated_minutes=5,
            required_elements=["multiple positioned objects"],
            combinable_with=["pic_scene_description"],
            example={
                "question": "Wo steht die Tasse im Verhältnis zum Teller?",
                "answer": "Die Tasse steht neben dem Teller.",
                "picture_must_contain": ["cup", "plate", "spatial relationship"],
            },
        ),
        ExerciseNode(
            id="pic_object_naming",
            name="Picture: Object Naming",
            exercise_type=ExerciseType.PICTURE_INTERACTION,
            description="Objects are circled or numbered in the picture. "
            "Learner writes the correct word for each.",
            difficulty=2,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["basic nouns"],
            estimated_minutes=4,
            required_elements=["numbered/circled objects"],
            combinable_with=["wc_translation", "pic_color_query"],
            example={
                "instruction": "Benenne die nummerierten Gegenstände im Bild.",
                "answers": {"1": "die Tasse", "2": "der Teller", "3": "das Fahrrad"},
            },
        ),
        ExerciseNode(
            id="pic_scene_description",
            name="Picture: Scene Description",
            exercise_type=ExerciseType.PICTURE_INTERACTION,
            description="'Describe what you see in the picture.' "
            "Open-ended writing task connected to a visual. Most complex picture task.",
            difficulty=5,
            cefr_range=("B1", "C2"),
            learning_focus=[LearningFocus.CREATIVITY, LearningFocus.GRAMMAR],
            pre_knowledge=["sentence construction", "descriptive vocabulary",
                           "spatial prepositions"],
            estimated_minutes=10,
            required_elements=["rich scene"],
            combinable_with=["fib_no_hint"],
            example={
                "instruction": "Beschreibe das Bild in 3-5 Sätzen.",
                "sample_answer": "Eine Frau sitzt in einem Café am Fenster. "
                "Vor ihr steht eine Tasse Cappuccino...",
            },
        ),
        ExerciseNode(
            id="pic_fib",
            name="Picture: Fill-in-Blanks",
            exercise_type=ExerciseType.PICTURE_INTERACTION,
            description="FIB exercise where blanks refer to elements visible in the picture. "
            "Combines visual and textual comprehension.",
            difficulty=3,
            cefr_range=("A2", "B2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.GRAMMAR],
            pre_knowledge=["nouns", "basic grammar"],
            estimated_minutes=5,
            required_elements=["named objects matching blanks"],
            combinable_with=["fib_word_bank", "pic_object_naming"],
            example={
                "text": "Im Bild sieht man eine ______ Tasse auf einem ______ Teller.",
                "answers": ["weiße", "blauen"],
                "picture_must_contain": ["white cup", "blue plate"],
            },
        ),
    ]

    # ── Word Connections ──────────────────────────────────────────────
    wc_nodes = [
        ExerciseNode(
            id="wc_translation",
            name="Word Connections: Translation",
            exercise_type=ExerciseType.WORD_CONNECTIONS,
            description="Connect words to their translations. "
            "Classic vocabulary matching exercise. Easiest exercise type.",
            difficulty=1,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["word recognition"],
            estimated_minutes=3,
            connection_type="translation",
            combinable_with=["fib_word_bank", "fib_translation_hint"],
            example={
                "pairs": [
                    {"source": "der Kaffee", "target": "coffee"},
                    {"source": "die Bohne", "target": "bean"},
                    {"source": "die Tasse", "target": "cup"},
                    {"source": "der Geschmack", "target": "taste"},
                ],
            },
        ),
        ExerciseNode(
            id="wc_synonym",
            name="Word Connections: Synonyms",
            exercise_type=ExerciseType.WORD_CONNECTIONS,
            description="Connect words to their synonyms within the target language. "
            "Deepens vocabulary breadth.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["vocabulary breadth in target language"],
            estimated_minutes=4,
            connection_type="synonym",
            combinable_with=["wc_antonym", "fib_translation_hint"],
            example={
                "pairs": [
                    {"source": "beginnen", "target": "anfangen"},
                    {"source": "beliebt", "target": "populär"},
                    {"source": "kräftig", "target": "stark"},
                ],
            },
        ),
        ExerciseNode(
            id="wc_antonym",
            name="Word Connections: Antonyms",
            exercise_type=ExerciseType.WORD_CONNECTIONS,
            description="Connect words to their antonyms. "
            "Tests understanding of opposite meanings.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["vocabulary breadth in target language"],
            estimated_minutes=4,
            connection_type="antonym",
            combinable_with=["wc_synonym"],
            example={
                "pairs": [
                    {"source": "hell", "target": "dunkel"},
                    {"source": "bitter", "target": "süß"},
                    {"source": "kräftig", "target": "mild"},
                ],
            },
        ),
        ExerciseNode(
            id="wc_category",
            name="Word Connections: Category Grouping",
            exercise_type=ExerciseType.WORD_CONNECTIONS,
            description="Group words into categories (e.g. 'coffee types', 'flavors'). "
            "Tests semantic organization.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["basic vocabulary"],
            estimated_minutes=4,
            connection_type="category",
            combinable_with=["wc_translation", "pic_object_naming"],
            example={
                "categories": {
                    "Geschmack": ["fruchtig", "bitter", "säuerlich"],
                    "Zubereitung": ["rösten", "mahlen", "brühen"],
                    "Gefäß": ["Tasse", "Kanne", "Becher"],
                },
            },
        ),
        ExerciseNode(
            id="wc_compound",
            name="Word Connections: Compounds",
            exercise_type=ExerciseType.WORD_CONNECTIONS,
            description="Connect word parts to form compound words. "
            "Tests morphological awareness (especially useful for German).",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.MORPHOLOGY, LearningFocus.VOCABULARY],
            pre_knowledge=["word building patterns"],
            estimated_minutes=5,
            connection_type="compound",
            combinable_with=["wc_translation"],
            example={
                "parts": [
                    {"left": "Kaffee", "right": "bohne", "compound": "Kaffeebohne"},
                    {"left": "Milch", "right": "schaum", "compound": "Milchschaum"},
                    {"left": "Apfel", "right": "strudel", "compound": "Apfelstrudel"},
                ],
            },
        ),
    ]

    # ── Puzzles ───────────────────────────────────────────────────────
    pz_nodes = [
        ExerciseNode(
            id="pz_word_search",
            name="Puzzle: Word Search",
            exercise_type=ExerciseType.PUZZLE,
            description="Vocabulary words hidden in a letter grid — horizontal, "
            "vertical, or diagonal. Filler letters come from the words themselves, "
            "so any script works.",
            difficulty=1,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.SPELLING],
            pre_knowledge=["word recognition"],
            estimated_minutes=6,
            combinable_with=["wc_translation", "pz_word_scramble"],
            example={"grid": "10x10 letters", "words": ["KAFFEE", "TASSE", "BOHNE"]},
        ),
        ExerciseNode(
            id="pz_word_scramble",
            name="Puzzle: Word Scramble",
            exercise_type=ExerciseType.PUZZLE,
            description="Unscramble shuffled letters back into vocabulary words. "
            "The translation is given as a hint.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.SPELLING, LearningFocus.VOCABULARY],
            pre_knowledge=["basic vocabulary"],
            estimated_minutes=5,
            combinable_with=["pz_word_search", "st_dictation"],
            example={"scramble": "S E T A S", "hint": "cup", "answer": "TASSE"},
        ),
        ExerciseNode(
            id="pz_crossword",
            name="Puzzle: Crossword",
            exercise_type=ExerciseType.PUZZLE,
            description="Crossword built from the vocabulary; clues are the "
            "translations. Grid is generated by greedy intersection placement.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.SPELLING],
            pre_knowledge=["solid vocabulary recall"],
            estimated_minutes=10,
            combinable_with=["wc_translation"],
            example={"across": [{"1": "coffee → KAFFEE"}], "down": [{"2": "cup → TASSE"}]},
        ),
        ExerciseNode(
            id="pz_odd_one_out",
            name="Puzzle: Odd One Out",
            exercise_type=ExerciseType.PUZZLE,
            description="Rows of four words — circle the one that doesn't belong "
            "and explain why. Tests semantic categorization.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["semantic categories"],
            estimated_minutes=4,
            combinable_with=["wc_category"],
            example={"row": ["Kaffee", "Tee", "Milch", "Teller"], "odd": "Teller"},
        ),
        ExerciseNode(
            id="pz_secret_code",
            name="Puzzle: Secret Code",
            exercise_type=ExerciseType.PUZZLE,
            description="Vocabulary words encoded as number sequences; a printed "
            "key maps numbers back to letters. Fun spelling reinforcement.",
            difficulty=2,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.SPELLING, LearningFocus.VOCABULARY],
            pre_knowledge=["alphabet"],
            estimated_minutes=5,
            combinable_with=["pz_word_scramble"],
            example={"code": "6-1-4-4-3-3", "key": "A=1 B=2 ...", "answer": "KAFFEE"},
        ),
    ]

    # ── Text analysis ─────────────────────────────────────────────────
    ta_nodes = [
        ExerciseNode(
            id="ta_error_correction",
            name="Text Analysis: Error Correction",
            exercise_type=ExerciseType.TEXT_ANALYSIS,
            description="Sentences from the text with one deliberately misspelled "
            "vocabulary word each. Underline the error, write the correction.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.ERROR_CORRECTION, LearningFocus.SPELLING],
            pre_knowledge=["spelling patterns"],
            estimated_minutes=6,
            combinable_with=["st_dictation"],
            example={"sentence": "Die Kaffeepflanze wähcst in tropischen Ländern.",
                     "error": "wähcst", "correction": "wächst"},
        ),
        ExerciseNode(
            id="ta_word_marking",
            name="Text Analysis: Word Marking",
            exercise_type=ExerciseType.TEXT_ANALYSIS,
            description="Underline every word of a given category (nouns, verbs, "
            "adjectives) in a passage. Builds grammatical awareness while reading.",
            difficulty=2,
            cefr_range=("A2", "C1"),
            learning_focus=[LearningFocus.GRAMMAR, LearningFocus.READING_COMPREHENSION],
            pre_knowledge=["parts of speech"],
            estimated_minutes=5,
            combinable_with=["ta_error_correction"],
            example={"instruction": "Underline all verbs in paragraph 1.",
                     "matches": ["beginnt", "kommt"]},
        ),
        ExerciseNode(
            id="ta_translation",
            name="Text Analysis: Sentence Translation",
            exercise_type=ExerciseType.TEXT_ANALYSIS,
            description="Translate selected sentences from the text into the "
            "native language. Classic mediation exercise.",
            difficulty=3,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.READING_COMPREHENSION, LearningFocus.VOCABULARY],
            pre_knowledge=["reading comprehension"],
            estimated_minutes=8,
            combinable_with=["wc_translation"],
            example={"source": "Kaffee bringt Menschen zusammen.",
                     "target": "Coffee brings people together."},
        ),
        ExerciseNode(
            id="ta_transformation",
            name="Text Analysis: Text Transformation",
            exercise_type=ExerciseType.TEXT_ANALYSIS,
            description="Rewrite the first paragraph in another tense or person. "
            "Grammar practice in meaningful context instead of drill tables.",
            difficulty=5,
            cefr_range=("B1", "C2"),
            learning_focus=[LearningFocus.GRAMMAR, LearningFocus.WORD_MANIPULATION],
            pre_knowledge=["tense system"],
            estimated_minutes=10,
            combinable_with=["fib_base_form"],
            example={"instruction": "Rewrite paragraph 1 in the past tense."},
        ),
    ]

    # ── Writing (text production genres) ──────────────────────────────
    wr_nodes = [
        ExerciseNode(
            id="wr_creative",
            name="Writing: Creative Text",
            exercise_type=ExerciseType.WRITING,
            description="Free writing prompt on the topic with a required-word "
            "bank drawn from the vocabulary.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.CREATIVITY, LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["sentence construction"],
            estimated_minutes=12,
            combinable_with=["wr_diary"],
            example={"prompt": "Write a short story set in a café.",
                     "required_words": ["Kaffee", "Fenster", "beginnen"]},
        ),
        ExerciseNode(
            id="wr_acrostic",
            name="Writing: Acrostic Poem",
            exercise_type=ExerciseType.WRITING,
            description="Poem where each line starts with a letter of a topic "
            "word, printed vertically. Low-pressure creative writing.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.CREATIVITY, LearningFocus.VOCABULARY],
            pre_knowledge=["basic vocabulary"],
            estimated_minutes=8,
            combinable_with=["wr_creative"],
            example={"word": "KAFFEE", "lines": ["K...", "A...", "F...", "F...", "E...", "E..."]},
        ),
        ExerciseNode(
            id="wr_letter",
            name="Writing: Letter",
            exercise_type=ExerciseType.WRITING,
            description="Write a letter about the topic following a labelled "
            "scaffold: greeting, introduction, main part, closing, signature.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["letter conventions"],
            estimated_minutes=15,
            combinable_with=["wr_postcard"],
            example={"sections": ["Greeting", "Introduction", "Main part", "Closing"]},
        ),
        ExerciseNode(
            id="wr_diary",
            name="Writing: Diary Entry",
            exercise_type=ExerciseType.WRITING,
            description="Personal diary entry about a day connected to the topic. "
            "Informal register, first person.",
            difficulty=3,
            cefr_range=("A2", "C1"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.CREATIVITY],
            pre_knowledge=["past tense helpful"],
            estimated_minutes=10,
            combinable_with=["wr_creative"],
            example={"prompt": "Dear diary, today I visited a coffee roastery..."},
        ),
        ExerciseNode(
            id="wr_headline",
            name="Writing: News Headline",
            exercise_type=ExerciseType.WRITING,
            description="Fact box from the text; learner writes a punchy headline "
            "and a 2-3 sentence lead paragraph. Journalistic register.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["summarizing"],
            estimated_minutes=8,
            combinable_with=["media_news", "soc_micro_post"],
            example={"facts": "Coffee grows near the equator...",
                     "headline": "________", "lead": "________"},
        ),
        ExerciseNode(
            id="wr_review",
            name="Writing: Review",
            exercise_type=ExerciseType.WRITING,
            description="Review a film/series or podcast picked from the culture "
            "library (QR code included): star rating, summary, opinion, "
            "recommendation.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.CULTURE],
            pre_knowledge=["opinion phrases"],
            estimated_minutes=12,
            media_category="film_tv",
            combinable_with=["media_film"],
            example={"rating": "4/5", "sections": ["Summary", "My opinion", "Recommendation"]},
        ),
        ExerciseNode(
            id="wr_postcard",
            name="Writing: Postcard",
            exercise_type=ExerciseType.WRITING,
            description="Classic postcard layout — message on the left, address "
            "lines and stamp box on the right. Short holiday text about the topic.",
            difficulty=2,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["greetings"],
            estimated_minutes=8,
            combinable_with=["wr_letter"],
            example={"layout": "message | address + stamp"},
        ),
        ExerciseNode(
            id="wr_opinion",
            name="Writing: Opinion",
            exercise_type=ExerciseType.WRITING,
            description="Statement about the topic; learner collects pro and "
            "contra arguments in a table, then writes their own opinion.",
            difficulty=5,
            cefr_range=("B1", "C2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.CREATIVITY],
            pre_knowledge=["argumentation phrases"],
            estimated_minutes=15,
            combinable_with=["soc_comments"],
            example={"statement": "Coffee plays a bigger role in our lives than ever.",
                     "table": ["Arguments for", "Arguments against"]},
        ),
    ]

    # ── Dialogue ──────────────────────────────────────────────────────
    dlg_nodes = [
        ExerciseNode(
            id="dlg_roleplay",
            name="Dialogue: Role Play",
            exercise_type=ExerciseType.DIALOGUE,
            description="Two role cards (curious person + expert on the topic); "
            "learner writes the dialogue on alternating A/B lines.",
            difficulty=3,
            cefr_range=("A2", "C1"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.SPEAKING],
            pre_knowledge=["question formation"],
            estimated_minutes=12,
            combinable_with=["dlg_interview"],
            example={"roles": ["curious visitor", "barista"], "turns": 8},
        ),
        ExerciseNode(
            id="dlg_interview",
            name="Dialogue: Interview Questions",
            exercise_type=ExerciseType.DIALOGUE,
            description="Write six interview questions for an expert on the topic. "
            "A question-word bank in the target language scaffolds the task.",
            difficulty=3,
            cefr_range=("A2", "B2"),
            learning_focus=[LearningFocus.GRAMMAR, LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["question words"],
            estimated_minutes=8,
            combinable_with=["dlg_roleplay", "media_podcast"],
            example={"question_words": ["Wer", "Was", "Wann", "Wo", "Warum", "Wie"]},
        ),
        ExerciseNode(
            id="dlg_comic",
            name="Dialogue: Comic Strip",
            exercise_type=ExerciseType.DIALOGUE,
            description="Four empty comic panels — draw the scene and fill the "
            "speech bubbles with dialogue about the topic.",
            difficulty=2,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.CREATIVITY, LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["basic phrases"],
            estimated_minutes=12,
            combinable_with=["soc_storyboard"],
            example={"panels": 4},
        ),
    ]

    # ── Media (with QR codes from the culture library) ────────────────
    media_nodes = [
        ExerciseNode(
            id="media_podcast",
            name="Media: Podcast Episode",
            exercise_type=ExerciseType.MEDIA,
            description="QR code to a curated podcast for the target language and "
            "topic. Pre-listening prediction, while-listening notes, "
            "post-listening summary.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.LISTENING, LearningFocus.CULTURE],
            pre_knowledge=["basic listening"],
            estimated_minutes=20,
            media_category="podcast",
            combinable_with=["st_dictation", "dlg_interview"],
            example={"resource": "Slow German", "tasks": ["predict", "note words", "summarize"]},
        ),
        ExerciseNode(
            id="media_video",
            name="Media: Video / YouTube",
            exercise_type=ExerciseType.MEDIA,
            description="QR code to a curated YouTube channel. Watch one video, "
            "tick heard vocabulary, summarize and give an opinion.",
            difficulty=2,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.LISTENING, LearningFocus.CULTURE],
            pre_knowledge=["basic listening"],
            estimated_minutes=15,
            media_category="video",
            combinable_with=["soc_video_script"],
            example={"resource": "Easy German", "tasks": ["tick words", "summary", "opinion"]},
        ),
        ExerciseNode(
            id="media_music",
            name="Media: Music & Lyrics",
            exercise_type=ExerciseType.MEDIA,
            description="QR code to a curated artist. Pick a song, note the title, "
            "describe what it is about, copy and translate a favourite line.",
            difficulty=2,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.LISTENING, LearningFocus.CULTURE],
            pre_knowledge=["none"],
            estimated_minutes=15,
            media_category="music",
            combinable_with=["wr_review"],
            example={"resource": "AnnenMayKantereit", "tasks": ["title", "meaning", "favourite line"]},
        ),
        ExerciseNode(
            id="media_film",
            name="Media: Film & Series",
            exercise_type=ExerciseType.MEDIA,
            description="QR code to a curated film/series. Watch a trailer or "
            "episode; note characters, setting, and whether to keep watching.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.LISTENING, LearningFocus.CULTURE],
            pre_knowledge=["basic listening"],
            estimated_minutes=20,
            media_category="film_tv",
            combinable_with=["wr_review"],
            example={"resource": "Dark (Netflix)", "tasks": ["characters", "setting", "opinion"]},
        ),
        ExerciseNode(
            id="media_news",
            name="Media: News Article",
            exercise_type=ExerciseType.MEDIA,
            description="QR code to a curated news site (learner-graded where "
            "available). Pick one article: reformulate the headline, collect new "
            "words, summarize.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.READING_COMPREHENSION, LearningFocus.CULTURE],
            pre_knowledge=["reading comprehension"],
            estimated_minutes=15,
            media_category="news",
            combinable_with=["wr_headline"],
            example={"resource": "Nachrichtenleicht", "tasks": ["headline", "new words", "summary"]},
        ),
        ExerciseNode(
            id="media_radio",
            name="Media: Live Radio",
            exercise_type=ExerciseType.MEDIA,
            description="QR code to a curated radio stream. Listen for five "
            "minutes, tally recognized vocabulary, identify the programme type.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.LISTENING, LearningFocus.CULTURE],
            pre_knowledge=["listening stamina"],
            estimated_minutes=10,
            media_category="radio",
            combinable_with=["media_podcast"],
            example={"resource": "Deutschlandfunk Nova", "tasks": ["tally words", "programme type"]},
        ),
    ]

    # ── Social media formats ──────────────────────────────────────────
    soc_nodes = [
        ExerciseNode(
            id="soc_chat",
            name="Social: Chat Conversation",
            exercise_type=ExerciseType.SOCIAL_MEDIA,
            description="Messenger-style layout with empty speech bubbles on both "
            "sides; learner writes a whole chat about the topic.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.CREATIVITY],
            pre_knowledge=["informal register"],
            estimated_minutes=10,
            combinable_with=["dlg_roleplay"],
            example={"situation": "Two friends plan a café visit", "bubbles": 8},
        ),
        ExerciseNode(
            id="soc_comments",
            name="Social: Comment Thread",
            exercise_type=ExerciseType.SOCIAL_MEDIA,
            description="The text's opening appears as a social media post; "
            "learner writes three replies: agree, ask, share experience.",
            difficulty=3,
            cefr_range=("A2", "C1"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["opinion phrases"],
            estimated_minutes=10,
            combinable_with=["wr_opinion"],
            example={"post": "Jeden Morgen beginnt der Tag mit ...",
                     "replies": ["agree", "question", "experience"]},
        ),
        ExerciseNode(
            id="soc_micro_post",
            name="Social: Micro Post",
            exercise_type=ExerciseType.SOCIAL_MEDIA,
            description="Summarize the whole text in one post of at most 280 "
            "characters, then add three hashtags built from the vocabulary.",
            difficulty=3,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.READING_COMPREHENSION],
            pre_knowledge=["summarizing"],
            estimated_minutes=8,
            combinable_with=["wr_headline"],
            example={"max_chars": 280, "hashtags": ["#Kaffee", "#Röstung"]},
        ),
        ExerciseNode(
            id="soc_caption",
            name="Social: Photo Captions",
            exercise_type=ExerciseType.SOCIAL_MEDIA,
            description="Three photo prompts (from the picture scene or "
            "vocabulary); learner writes an Instagram-style caption plus "
            "hashtags for each.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.CREATIVITY],
            pre_knowledge=["basic sentences"],
            estimated_minutes=8,
            combinable_with=["pic_scene_description"],
            example={"photo": "a white cup on a blue plate", "caption": "________"},
        ),
        ExerciseNode(
            id="soc_storyboard",
            name="Social: Story Storyboard",
            exercise_type=ExerciseType.SOCIAL_MEDIA,
            description="Plan a five-frame Instagram/TikTok story about the "
            "topic: sketch each frame and write its caption.",
            difficulty=3,
            cefr_range=("A2", "B2"),
            learning_focus=[LearningFocus.CREATIVITY, LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["basic sentences"],
            estimated_minutes=12,
            combinable_with=["dlg_comic", "soc_video_script"],
            example={"frames": 5},
        ),
        ExerciseNode(
            id="soc_video_script",
            name="Social: 30-Second Video Script",
            exercise_type=ExerciseType.SOCIAL_MEDIA,
            description="Script a 30-second reel about the topic with the classic "
            "structure: hook, main part, call to action.",
            difficulty=4,
            cefr_range=("B1", "C2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.CREATIVITY],
            pre_knowledge=["concise writing"],
            estimated_minutes=12,
            combinable_with=["media_video", "soc_storyboard"],
            example={"sections": ["Hook 0-5s", "Main 5-25s", "CTA 25-30s"]},
        ),
    ]

    # ── Real-world texts ──────────────────────────────────────────────
    rw_nodes = [
        ExerciseNode(
            id="rw_how_to",
            name="Real World: How-To Guide",
            exercise_type=ExerciseType.REAL_WORLD,
            description="Step-by-step instructions for something related to the "
            "topic. A connector-word bank (first, then, finally...) in the "
            "target language scaffolds sequencing.",
            difficulty=3,
            cefr_range=("A2", "B2"),
            learning_focus=[LearningFocus.WRITING_PRODUCTION, LearningFocus.GRAMMAR],
            pre_knowledge=["imperative forms"],
            estimated_minutes=10,
            combinable_with=["wr_creative"],
            example={"connectors": ["Zuerst", "Dann", "Zum Schluss"], "steps": 6},
        ),
        ExerciseNode(
            id="rw_shopping_list",
            name="Real World: Shopping List",
            exercise_type=ExerciseType.REAL_WORLD,
            description="Table of vocabulary items; learner adds quantities and "
            "prices, then two items of their own. Numbers practice in context.",
            difficulty=1,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.NUMERACY],
            pre_knowledge=["numbers"],
            estimated_minutes=6,
            combinable_with=["num_write_words"],
            example={"columns": ["Item", "Quantity", "Price"]},
        ),
        ExerciseNode(
            id="rw_week_planner",
            name="Real World: Week Planner",
            exercise_type=ExerciseType.REAL_WORLD,
            description="Weekly planner grid with day names in the target "
            "language; learner writes one topic-related activity per day.",
            difficulty=2,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.VOCABULARY, LearningFocus.WRITING_PRODUCTION],
            pre_knowledge=["weekdays"],
            estimated_minutes=8,
            combinable_with=["num_clock"],
            example={"days": ["Montag", "Dienstag", "..."]},
        ),
    ]

    # ── Numbers & time ────────────────────────────────────────────────
    num_nodes = [
        ExerciseNode(
            id="num_write_words",
            name="Numbers: Write as Words",
            exercise_type=ExerciseType.NUMBERS,
            description="Numbers taken from the text (plus standard ones) to be "
            "written out as words in the target language.",
            difficulty=1,
            cefr_range=("A1", "B1"),
            learning_focus=[LearningFocus.NUMERACY, LearningFocus.SPELLING],
            pre_knowledge=["number words"],
            estimated_minutes=5,
            combinable_with=["rw_shopping_list"],
            example={"number": 250, "answer": "zweihundertfünfzig"},
        ),
        ExerciseNode(
            id="num_clock",
            name="Numbers: Clock Times",
            exercise_type=ExerciseType.NUMBERS,
            description="Drawn analogue clock faces; learner writes each time in "
            "words in the target language.",
            difficulty=1,
            cefr_range=("A1", "A2"),
            learning_focus=[LearningFocus.NUMERACY, LearningFocus.VOCABULARY],
            pre_knowledge=["numbers to 60"],
            estimated_minutes=5,
            combinable_with=["rw_week_planner"],
            example={"clock": "07:15", "answer": "Viertel nach sieben"},
        ),
    ]

    # ── Study tools ───────────────────────────────────────────────────
    st_nodes = [
        ExerciseNode(
            id="st_flashcards",
            name="Study: Cut-Out Flashcards",
            exercise_type=ExerciseType.STUDY,
            description="Vocabulary printed as cut-out flashcards with dashed "
            "borders — term big, translation small at the card edge.",
            difficulty=1,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["none"],
            estimated_minutes=5,
            combinable_with=["st_dictation"],
            example={"card": {"front": "die Tasse", "back": "cup"}},
        ),
        ExerciseNode(
            id="st_dictation",
            name="Study: Dictation Practice",
            exercise_type=ExerciseType.STUDY,
            description="Copy each hard word twice, then cover the original and "
            "write it from memory. Classic pre-dictation drill.",
            difficulty=2,
            cefr_range=("A1", "B2"),
            learning_focus=[LearningFocus.SPELLING, LearningFocus.VOCABULARY],
            pre_knowledge=["handwriting"],
            estimated_minutes=8,
            combinable_with=["pz_word_scramble"],
            example={"columns": ["Word", "Practice 1", "Practice 2", "From memory"]},
        ),
        ExerciseNode(
            id="st_reflection",
            name="Study: 3-2-1 Reflection",
            exercise_type=ExerciseType.STUDY,
            description="Worksheet closer: three new words, two difficulties, one "
            "thing to review — plus a tip to upload the sheet to an AI assistant "
            "for feedback.",
            difficulty=1,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["none"],
            estimated_minutes=5,
            combinable_with=[],
            example={"prompts": ["3 new words", "2 difficulties", "1 review item"]},
        ),
    ]

    # Register all exercise nodes
    for node in (fib_nodes + pic_nodes + wc_nodes + pz_nodes + ta_nodes
                 + wr_nodes + dlg_nodes + media_nodes + soc_nodes + rw_nodes
                 + num_nodes + st_nodes):
        g.add_node(node)

    # ── Edges ─────────────────────────────────────────────────────────

    # FIB → WordConnections: blanked words become vocabulary for connections
    g.add_edge(Edge("fib_word_bank", "wc_translation", EdgeType.FEEDS_VOCABULARY_TO,
                     "blanked words become translation pairs"))
    g.add_edge(Edge("fib_word_bank", "wc_category", EdgeType.FEEDS_VOCABULARY_TO,
                     "blanked words can be grouped"))
    g.add_edge(Edge("fib_first_letter", "wc_translation", EdgeType.FEEDS_VOCABULARY_TO))
    g.add_edge(Edge("fib_translation_hint", "wc_synonym", EdgeType.FEEDS_VOCABULARY_TO))

    # Picture ↔ FIB: picture elements referenced in fill-in-blanks
    g.add_edge(Edge("pic_fib", "fib_word_bank", EdgeType.COMBINES_WITH,
                     "picture FIB can share word bank"))
    g.add_edge(Edge("pic_object_naming", "wc_translation", EdgeType.FEEDS_VOCABULARY_TO,
                     "named objects become translation pairs"))

    # WordConnections → FIB: vocabulary from connections feeds word banks
    g.add_edge(Edge("wc_translation", "fib_word_bank", EdgeType.FEEDS_VOCABULARY_TO,
                     "translation pairs provide word bank"))
    g.add_edge(Edge("wc_category", "fib_word_bank", EdgeType.FEEDS_VOCABULARY_TO,
                     "categorized words provide word bank"))

    # Combinations
    g.add_edge(Edge("pic_color_query", "pic_object_naming", EdgeType.COMBINES_WITH))
    g.add_edge(Edge("pic_element_marking", "pic_position", EdgeType.COMBINES_WITH))
    g.add_edge(Edge("wc_synonym", "wc_antonym", EdgeType.COMBINES_WITH,
                     "synonyms and antonyms pair naturally"))
    g.add_edge(Edge("fib_base_form", "fib_word_bank", EdgeType.COMBINES_WITH,
                     "base form + word bank scaffolds difficulty"))

    # Puzzles draw on the same vocabulary pool
    g.add_edge(Edge("wc_translation", "pz_crossword", EdgeType.FEEDS_VOCABULARY_TO,
                     "translation pairs become crossword clues"))
    g.add_edge(Edge("pz_word_search", "st_dictation", EdgeType.FEEDS_VOCABULARY_TO,
                     "found words become dictation practice"))
    g.add_edge(Edge("pz_word_scramble", "pz_secret_code", EdgeType.COMBINES_WITH,
                     "two light word puzzles pair well"))
    g.add_edge(Edge("wc_category", "pz_odd_one_out", EdgeType.FEEDS_VOCABULARY_TO,
                     "semantic categories supply odd-one-out rows"))

    # Text analysis derives from the text
    g.add_edge(Edge("ta_error_correction", "st_dictation", EdgeType.COMBINES_WITH,
                     "corrected words are dictation candidates"))
    g.add_edge(Edge("ta_word_marking", "fib_base_form", EdgeType.COMBINES_WITH,
                     "marked verbs feed conjugation practice"))
    g.add_edge(Edge("ta_translation", "wc_translation", EdgeType.COMBINES_WITH))

    # Media feeds production tasks
    g.add_edge(Edge("media_podcast", "st_dictation", EdgeType.FEEDS_VOCABULARY_TO,
                     "new words heard become practice words"))
    g.add_edge(Edge("media_news", "wr_headline", EdgeType.COMBINES_WITH,
                     "read real news, then write your own headline"))
    g.add_edge(Edge("media_film", "wr_review", EdgeType.REQUIRES_OUTPUT_OF,
                     "the review needs something watched"))
    g.add_edge(Edge("media_music", "wr_review", EdgeType.COMBINES_WITH))
    g.add_edge(Edge("media_video", "soc_video_script", EdgeType.COMBINES_WITH,
                     "watch a creator, then script your own reel"))
    g.add_edge(Edge("media_podcast", "dlg_interview", EdgeType.COMBINES_WITH,
                     "listen to interviews, then write interview questions"))

    # Social media production chain
    g.add_edge(Edge("soc_micro_post", "wr_headline", EdgeType.COMBINES_WITH,
                     "both condense the text"))
    g.add_edge(Edge("soc_storyboard", "soc_video_script", EdgeType.COMBINES_WITH,
                     "storyboard the frames, then script the audio"))
    g.add_edge(Edge("soc_comments", "wr_opinion", EdgeType.COMBINES_WITH,
                     "short replies scale up to full opinion pieces"))
    g.add_edge(Edge("pic_scene_description", "soc_caption", EdgeType.COMBINES_WITH,
                     "scene descriptions shrink into captions"))

    # Real world & numbers
    g.add_edge(Edge("rw_shopping_list", "num_write_words", EdgeType.COMBINES_WITH,
                     "prices practice number words"))
    g.add_edge(Edge("rw_week_planner", "num_clock", EdgeType.COMBINES_WITH,
                     "planning needs clock times"))

    # Study tools close the loop
    g.add_edge(Edge("wc_translation", "st_flashcards", EdgeType.FEEDS_VOCABULARY_TO,
                     "matched pairs become flashcards"))
    g.add_edge(Edge("fib_word_bank", "st_dictation", EdgeType.FEEDS_VOCABULARY_TO))

    return g
