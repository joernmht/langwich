"""Worksheet planning — turn a chosen set of exercises into a coherent sheet.

This is where the "one developing story" idea is enforced.  Two things matter:

1. **Order.**  Exercises are sequenced so the sheet eases the learner in and
   ramps up: receptive matching first, then guided gap-fills, then freer
   production, with picture work slotted by difficulty.  Within that order the
   gap-fill exercises consume sentences in document order, so the worksheet
   walks through the story from beginning to end.

2. **No overlap.**  A single :class:`MaterialLedger` is threaded through every
   generator, so no sentence is reused and no word is tested twice across the
   whole sheet.

The CLI's default selection (CEFR + focus aware) lives in :mod:`langwich.cli`;
this module takes an explicit ordered list of node ids and realises it.
"""

from __future__ import annotations

import random

from langwich.generate import ExerciseInstance, MaterialLedger, generate_exercise
from langwich.graph import ExerciseGraph, ExerciseNode, ExerciseType
from langwich.text import SourceText


# Order in which exercise *types* should appear on a finished sheet.  Within a
# type, difficulty (then the order requested) breaks ties.
_TYPE_ORDER = {
    ExerciseType.WORD_CONNECTIONS: 0,     # warm up: recognise vocabulary
    ExerciseType.COMPREHENSION: 1,        # engage with the text (read → think)
    ExerciseType.FILL_IN_BLANKS: 2,       # language focus, on a reworded recap
    ExerciseType.PICTURE_INTERACTION: 3,  # apply it to a scene / produce language
}


def order_node_ids(graph: ExerciseGraph, node_ids: list[str]) -> list[str]:
    """Sort exercises into a coherent learning progression."""
    def key(nid: str) -> tuple[int, int, int]:
        node = graph.nodes.get(nid)
        if not isinstance(node, ExerciseNode):
            return (99, 99, node_ids.index(nid))
        return (
            _TYPE_ORDER.get(node.exercise_type, 9),
            node.difficulty,
            node_ids.index(nid),
        )

    unique: list[str] = []
    for n in node_ids:
        if n not in unique:
            unique.append(n)
    return sorted(unique, key=key)


def build_worksheet(
    text: SourceText,
    node_ids: list[str],
    graph: ExerciseGraph,
    seed: int = 0,
) -> tuple[list[ExerciseInstance], list[str]]:
    """Generate all exercises for a worksheet, sharing one ledger.

    Returns ``(exercises, skipped)`` where ``skipped`` lists node ids that could
    not produce content from this text (e.g. a picture task with no scene).
    """
    rng = random.Random(seed)
    ledger = MaterialLedger()
    ordered = order_node_ids(graph, node_ids)

    exercises: list[ExerciseInstance] = []
    skipped: list[str] = []
    for nid in ordered:
        node = graph.nodes.get(nid)
        if not isinstance(node, ExerciseNode):
            skipped.append(nid)
            continue
        inst = generate_exercise(node, text, rng, ledger)
        if inst and inst.items:
            exercises.append(inst)
        else:
            skipped.append(nid)
    return exercises, skipped
