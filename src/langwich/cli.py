"""CLI entry point for langwich.

Examples
--------
    langwich --from-json examples/coffee_en_de.json
    langwich --from-json examples/coffee_en_de.json --focus grammar,morphology
    langwich --from-json examples/coffee_en_de.json \\
        --exercises wc_translation,fib_word_bank,pic_color_query
    langwich --list-exercises
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from langwich.graph import (
    CEFR_ORDER,
    ExerciseGraph,
    ExerciseType,
    LearningFocus,
    build_default_graph,
)
from langwich.plan import build_worksheet
from langwich.render import render_worksheet
from langwich.text import SourceText


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="langwich",
        description="Graph-based language-learning worksheet generator",
    )
    parser.add_argument("--from-json", type=Path, default=None,
                        help="Path to a source-text JSON file")
    parser.add_argument("--exercises", type=str, default=None,
                        help="Comma-separated exercise ids (overrides auto-selection)")
    parser.add_argument("--focus", type=str, default=None,
                        help="Comma-separated learning foci to prefer "
                             "(e.g. grammar,morphology,vocabulary)")
    parser.add_argument("--output", "-o", type=Path, default=None,
                        help="Output PDF path (default: data/<topic>.pdf)")
    parser.add_argument("--seed", type=int, default=0,
                        help="Random seed for reproducible worksheets")
    parser.add_argument("--list-exercises", action="store_true",
                        help="List every exercise type and exit")

    args = parser.parse_args(argv)
    graph = build_default_graph()

    if args.list_exercises:
        _list_exercises(graph)
        return

    if not args.from_json:
        parser.error("--from-json is required (unless using --list-exercises)")

    with open(args.from_json, encoding="utf-8") as f:
        data = json.load(f)
    text = SourceText.from_dict(data)

    if args.exercises:
        node_ids = [s.strip() for s in args.exercises.split(",") if s.strip()]
    else:
        focus = _parse_focus(args.focus)
        node_ids = select_exercises(graph, text, focus)

    exercises, skipped = build_worksheet(text, node_ids, graph, seed=args.seed)
    for nid in skipped:
        print(f"note: '{nid}' produced no content from this text — skipped",
              file=sys.stderr)

    if not exercises:
        print("error: no exercises could be generated from this text",
              file=sys.stderr)
        sys.exit(1)

    output = args.output or Path("data") / f"{text.topic}.pdf"
    result = render_worksheet(text, exercises, output)
    minutes = sum(ex.estimated_minutes for ex in exercises)
    print(f"Worksheet generated: {result}")
    print(f"  {len(exercises)} exercises · ~{minutes} min · level {text.cefr_level}")
    print("  " + " → ".join(ex.title.split(" · ")[-1] for ex in exercises))


# ---------------------------------------------------------------------------
# Automatic exercise selection (CEFR + focus + combinability)
# ---------------------------------------------------------------------------

def _parse_focus(raw: str | None) -> list[LearningFocus]:
    if not raw:
        return []
    out: list[LearningFocus] = []
    for token in raw.split(","):
        token = token.strip().lower().replace(" ", "_")
        try:
            out.append(LearningFocus(token))
        except ValueError:
            print(f"warning: unknown focus '{token}', ignoring", file=sys.stderr)
    return out


def _cefr_ok(node, level: str) -> bool:
    lo, hi = node.cefr_range
    return CEFR_ORDER.get(lo, 0) <= CEFR_ORDER.get(level, 2) <= CEFR_ORDER.get(hi, 5)


def select_exercises(
    graph: ExerciseGraph, text: SourceText, focus: list[LearningFocus],
) -> list[str]:
    """Pick a coherent set of exercises for this text.

    Strategy: keep only exercises within the text's CEFR band and whose material
    actually exists (a picture task needs a scene; compounds need compound data).
    Then take the best-fitting exercise of each *type* — preferring the requested
    focus, otherwise the gentlest difficulty — and round it out with one
    complementary partner via the graph's ``combinable_with`` edges.
    """
    level = text.cefr_level
    has_scene = text.picture_scene is not None
    has_compounds = bool(text.compounds)
    focus_set = set(focus)

    def usable(node) -> bool:
        if not _cefr_ok(node, level):
            return False
        if node.exercise_type == ExerciseType.PICTURE_INTERACTION and not has_scene:
            return False
        if node.id == "wc_compound" and not has_compounds:
            return False
        if node.id == "comp_questions" and not text.questions:
            return False
        if node.id == "comp_true_false" and not text.true_false:
            return False
        return True

    def score(node) -> tuple:
        focus_hit = len(focus_set.intersection(node.learning_focus))
        # Higher focus match first; then easier first (gentle ramp).
        return (-focus_hit, node.difficulty)

    chosen: list[str] = []
    for etype in (ExerciseType.WORD_CONNECTIONS,
                  ExerciseType.COMPREHENSION,
                  ExerciseType.FILL_IN_BLANKS,
                  ExerciseType.PICTURE_INTERACTION):
        candidates = [n for n in graph.get_by_type(etype) if usable(n)]
        if not candidates:
            continue
        # Comprehension is the demanding, non-repetitive core of the sheet —
        # include every subtype whose material exists, not just the best.
        if etype == ExerciseType.COMPREHENSION:
            chosen.extend(n.id for n in sorted(candidates, key=score))
            continue
        best = sorted(candidates, key=score)[0]
        chosen.append(best.id)
        # If a focus was requested, also add the next best distinct match.
        if focus_set:
            extras = [n for n in candidates
                      if n.id != best.id and focus_set.intersection(n.learning_focus)]
            if extras:
                chosen.append(sorted(extras, key=score)[0].id)

    # Add one complementary partner for the first chosen exercise, if usable.
    if chosen:
        for cid in graph.nodes[chosen[0]].combinable_with:  # type: ignore[attr-defined]
            node = graph.nodes.get(cid)
            if node and cid not in chosen and usable(node):
                chosen.append(cid)
                break

    return chosen


# ---------------------------------------------------------------------------
# --list-exercises
# ---------------------------------------------------------------------------

def _list_exercises(graph: ExerciseGraph) -> None:
    print(f"\n{'ID':<22}{'CEFR':<9}{'min':>4}  {'focus'}")
    print("-" * 78)
    last_type = None
    for node in sorted(graph.exercises(),
                       key=lambda n: (n.exercise_type.value, n.difficulty)):
        if node.exercise_type != last_type:
            print(f"\n  {node.type_label.upper()}")
            last_type = node.exercise_type
        cefr = f"{node.cefr_range[0]}–{node.cefr_range[1]}"
        print(f"{node.id:<22}{cefr:<9}{node.estimated_minutes:>4}  {node.focus_label}")
    print(f"\n{len(graph.exercises())} exercise subclasses available.\n")


if __name__ == "__main__":
    main()
