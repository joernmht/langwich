#!/usr/bin/env python3
"""Sync live counts from the exercise graph into the landing page.

The landing page (docs/index.html) shows numbers that depend on the code:
how many exercise subclasses exist, how many variants each family has, and
how many bundled examples ship with the repository. Instead of hardcoding
them, the page marks each number with ``data-count="<key>"`` and this
script fills in the real values derived from ``build_default_graph()`` and
``examples/*.json``.

Run it locally after adding exercise nodes or examples, or let CI run it —
the Pages workflow executes it before deploying, so the published page
always shows the current counts.

Usage:
    python3 scripts/update_page_stats.py           # rewrite docs/index.html
    python3 scripts/update_page_stats.py --check   # exit 1 if out of sync
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from langwich.graph import build_default_graph  # noqa: E402
from langwich.text import SourceText  # noqa: E402

INDEX_HTML = REPO_ROOT / "docs" / "index.html"
EXAMPLES_DIR = REPO_ROOT / "examples"


def count_examples() -> int:
    """Bundled examples that actually load with the current schema."""
    count = 0
    for path in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            SourceText.from_dict(json.loads(path.read_text(encoding="utf-8")))
            count += 1
        except Exception:
            print(f"  warning: {path.name} does not parse as a SourceText, "
                  "not counted", file=sys.stderr)
    return count


def compute_stats() -> dict[str, int]:
    graph = build_default_graph()
    exercises = graph.exercises()
    by_family: dict[str, int] = {}
    for node in exercises:
        by_family[node.exercise_type.value] = by_family.get(node.exercise_type.value, 0) + 1
    return {
        "exercise-types": len(exercises),
        "families": len(by_family),
        "fib-variants": by_family.get("fib", 0),
        "picture-variants": by_family.get("picture", 0),
        "wc-variants": by_family.get("word_connections", 0),
        "media-variants": by_family.get("media", 0),
        "examples": count_examples(),
    }


def apply_stats(html: str, stats: dict[str, int]) -> str:
    def replace(match: re.Match) -> str:
        key = match.group(2)
        if key not in stats:
            print(f"  warning: unknown data-count key '{key}' left as-is",
                  file=sys.stderr)
            return match.group(0)
        return f"{match.group(1)}{stats[key]}{match.group(3)}"

    return re.sub(
        r'(<span[^>]*\bdata-count="([\w-]+)"[^>]*>)[^<]*(</span>)',
        replace,
        html,
    )


def main(argv: list[str]) -> int:
    check_only = "--check" in argv

    stats = compute_stats()
    html = INDEX_HTML.read_text(encoding="utf-8")
    updated = apply_stats(html, stats)

    for key, value in stats.items():
        print(f"  {key}: {value}")

    if updated == html:
        print("docs/index.html is in sync.")
        return 0
    if check_only:
        print("docs/index.html is OUT OF SYNC — run "
              "'python3 scripts/update_page_stats.py' and commit.",
              file=sys.stderr)
        return 1
    INDEX_HTML.write_text(updated, encoding="utf-8")
    print("docs/index.html updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
