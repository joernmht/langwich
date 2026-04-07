"""Exercise knowledge graph.

Defines exercise types, subclasses, their attributes, and connections.
This graph is the single source of truth for what exercises exist and how
they relate to each other. Both LLMs and deterministic systems can consume it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ExerciseType(str, Enum):
    FILL_IN_BLANKS = "fib"
    PICTURE_INTERACTION = "picture"
    WORD_CONNECTIONS = "word_connections"


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


class EdgeType(str, Enum):
    FEEDS_VOCABULARY_TO = "feeds_vocabulary_to"
    REFERENCES_ELEMENTS_OF = "references_elements_of"
    COMBINES_WITH = "combines_with"
    REQUIRES_OUTPUT_OF = "requires_output_of"
    DERIVES_FROM_TEXT = "derives_from_text"


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------

@dataclass
class ExerciseNode:
    """One exercise subclass in the knowledge graph."""

    id: str
    name: str
    exercise_type: ExerciseType
    description: str
    difficulty: int  # 1-5
    cefr_range: tuple[str, str]  # e.g. ("A1", "C2")
    learning_focus: list[LearningFocus]
    pre_knowledge: list[str]
    estimated_minutes: int
    example: dict = field(default_factory=dict)

    # type-specific attributes (optional, filled per type)
    hint_type: str | None = None        # FIB: what hint is given
    blank_target: str | None = None     # FIB: what is blanked
    required_elements: list[str] = field(default_factory=list)  # Picture
    connection_type: str | None = None  # WordConnections
    combinable_with: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
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
            "combinable_with": self.combinable_with,
            "example": self.example,
        }


@dataclass
class Edge:
    """Directed connection between two exercise nodes."""

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
    """Knowledge graph of exercise types, subclasses, and their relationships."""

    def __init__(self) -> None:
        self.nodes: dict[str, ExerciseNode] = {}
        self.edges: list[Edge] = []

    def add_node(self, node: ExerciseNode) -> None:
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def get_by_type(self, exercise_type: ExerciseType) -> list[ExerciseNode]:
        return [n for n in self.nodes.values() if n.exercise_type == exercise_type]

    def get_combinable(self, node_id: str) -> list[ExerciseNode]:
        node = self.nodes[node_id]
        return [self.nodes[cid] for cid in node.combinable_with if cid in self.nodes]

    def get_edges_from(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.source == node_id]

    def get_edges_to(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]

    def by_difficulty(self, max_difficulty: int) -> list[ExerciseNode]:
        return sorted(
            [n for n in self.nodes.values() if n.difficulty <= max_difficulty],
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
            description="No hints at all. Pure recall from context. "
            "Hardest FIB variant.",
            difficulty=5,
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
            "Open-ended writing task connected to a visual.",
            difficulty=4,
            cefr_range=("A2", "C2"),
            learning_focus=[LearningFocus.CREATIVITY, LearningFocus.GRAMMAR],
            pre_knowledge=["sentence construction", "descriptive vocabulary"],
            estimated_minutes=8,
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
            "Classic vocabulary matching exercise.",
            difficulty=2,
            cefr_range=("A1", "C2"),
            learning_focus=[LearningFocus.VOCABULARY],
            pre_knowledge=["bilingual vocabulary"],
            estimated_minutes=4,
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

    # Register all nodes
    for node in fib_nodes + pic_nodes + wc_nodes:
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

    return g
