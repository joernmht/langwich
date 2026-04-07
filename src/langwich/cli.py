"""CLI entry point for langwich.

Usage:
    langwich --from-json examples/coffee_en_de.json
    langwich --from-json examples/coffee_en_de.json --exercises fib_word_bank,pic_color_query,wc_translation
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from langwich.generate import ExerciseInstance, generate_exercise
from langwich.graph import ExerciseGraph, build_default_graph
from langwich.render import render_worksheet
from langwich.text import SourceText


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="langwich",
        description="Graph-based language learning worksheet generator",
    )
    parser.add_argument(
        "--from-json", required=False, type=Path, default=None,
        help="Path to source text JSON file",
    )
    parser.add_argument(
        "--exercises", type=str, default=None,
        help="Comma-separated list of exercise node IDs to generate "
        "(default: one of each type)",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output PDF path (default: data/<topic>.pdf)",
    )
    parser.add_argument(
        "--list-exercises", action="store_true",
        help="List all available exercise types and exit",
    )

    args = parser.parse_args(argv)
    graph = build_default_graph()

    if args.list_exercises:
        _list_exercises(graph)
        return

    if not args.from_json:
        parser.error("--from-json is required (unless using --list-exercises)")

    # Load text
    with open(args.from_json) as f:
        data = json.load(f)
    text = SourceText.from_dict(data)

    # Pick exercises
    if args.exercises:
        node_ids = [s.strip() for s in args.exercises.split(",")]
    else:
        # Default: one per type, pick lowest difficulty
        node_ids = []
        for etype_nodes in [
            graph.get_by_type(et) for et in
            [e for e in graph.nodes.values()
             if hasattr(e, "exercise_type")].__class__.__mro__[0]  # type: ignore
        ]:
            pass
        # Simpler: just pick a representative set
        node_ids = [
            "fib_word_bank",
            "pic_color_query",
            "wc_translation",
            "wc_compound",
        ]

    exercises: list[ExerciseInstance] = []
    for nid in node_ids:
        if nid not in graph.nodes:
            print(f"Warning: unknown exercise '{nid}', skipping", file=sys.stderr)
            continue
        node = graph.nodes[nid]
        ex = generate_exercise(node, text)  # type: ignore[arg-type]
        if ex:
            exercises.append(ex)
        else:
            print(f"Warning: could not generate '{nid}' from text", file=sys.stderr)

    if not exercises:
        print("Error: no exercises generated", file=sys.stderr)
        sys.exit(1)

    # Render
    output = args.output or Path("data") / f"{text.topic}.pdf"
    result = render_worksheet(text, exercises, output)
    print(f"Worksheet generated: {result}")


def _list_exercises(graph: ExerciseGraph) -> None:
    from langwich.graph import ExerciseNode

    print(f"\n{'ID':<25} {'Type':<18} {'Diff':>4}  {'Name'}")
    print("-" * 75)
    for node in sorted(graph.exercises(), key=lambda n: (n.exercise_type.value, n.difficulty)):
        print(f"{node.id:<25} {node.exercise_type.value:<18} {node.difficulty:>4}  {node.name}")
    print(f"\n{len(graph.exercises())} exercise subclasses available.")


if __name__ == "__main__":
    main()
