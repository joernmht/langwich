"""CLI entry point for langwich.

Usage:
    langwich --from-json examples/coffee_en_de.json
    langwich --from-json examples/coffee_en_de.json --exercises fib_word_bank,pz_word_search,media_podcast
    langwich --from-json examples/coffee_en_de.json --exercises all
    langwich --list-exercises
    langwich --list-culture de
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from langwich.culture import load_culture_library
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
        help="Comma-separated list of exercise node IDs to generate, "
        "or 'all' for every type that works with the given text "
        "(default: a balanced showcase selection)",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output PDF path (default: data/<topic>.pdf)",
    )
    parser.add_argument(
        "--list-exercises", action="store_true",
        help="List all available exercise types and exit",
    )
    parser.add_argument(
        "--list-culture", type=str, nargs="?", const="all", default=None,
        metavar="LANG",
        help="List culture-library media resources (optionally for one "
        "language code, e.g. 'de') and exit",
    )

    args = parser.parse_args(argv)
    graph = build_default_graph()

    if args.list_exercises:
        _list_exercises(graph)
        return

    if args.list_culture:
        _list_culture(None if args.list_culture == "all" else args.list_culture)
        return

    if not args.from_json:
        parser.error("--from-json is required (unless using --list-exercises "
                     "or --list-culture)")

    # Load text
    with open(args.from_json) as f:
        data = json.load(f)
    text = SourceText.from_dict(data)

    # Pick exercises
    if args.exercises == "all":
        node_ids = [n.id for n in sorted(
            graph.exercises(), key=lambda n: (n.exercise_type.value, n.difficulty))]
    elif args.exercises:
        node_ids = [s.strip() for s in args.exercises.split(",")]
    else:
        node_ids = [
            "fib_word_bank",
            "pic_color_query",
            "wc_translation",
            "wc_compound",
            "pz_word_search",
            "media_podcast",
            "st_reflection",
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
    print(f"\n{'ID':<25} {'Type':<18} {'Diff':>4}  {'Name'}")
    print("-" * 75)
    for node in sorted(graph.exercises(), key=lambda n: (n.exercise_type.value, n.difficulty)):
        print(f"{node.id:<25} {node.exercise_type.value:<18} {node.difficulty:>4}  {node.name}")
    print(f"\n{len(graph.exercises())} exercise subclasses available.")


def _list_culture(lang: str | None) -> None:
    library = load_culture_library()
    languages = [lang] if lang else sorted(library)
    total = 0
    for code in languages:
        resources = library.get(code, [])
        if not resources:
            print(f"No culture resources for '{code}'. "
                  f"Available: {', '.join(sorted(library))}")
            continue
        print(f"\n═══ {code} ({len(resources)} resources) ═══")
        for r in sorted(resources, key=lambda r: r.category):
            topics = ", ".join(r.topics)
            print(f"  [{r.category:<8}] {r.title:<45} {r.cefr:<4} ({topics})")
            print(f"             {r.url}")
        total += len(resources)
    print(f"\n{total} resources total.")


if __name__ == "__main__":
    main()
