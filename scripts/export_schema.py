#!/usr/bin/env python3
"""Regenerate ``src/langwich/schema/langwich-3.json`` from the pydantic model.

    python scripts/export_schema.py           # rewrite the file
    python scripts/export_schema.py --check   # exit 1 if the file is out of date (CI)

The model in ``src/langwich/model.py`` is the single source of truth; the
JSON file is a published copy for editors, other tools and LLMs (the Pages
workflow also serves it at the schema's ``$id``).

``--check`` compares the *parsed* JSON with the model's schema, so a pydantic
release that only formats numbers differently (``1`` vs ``1.0``) does not
count as stale; such a formatting-only difference is reported as a note.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Literal

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "langwich" / "schema" / "langwich-3.json"

Status = Literal["same", "format", "stale"]


def current_schema() -> dict[str, Any]:
    sys.path.insert(0, str(ROOT / "src"))
    from langwich.model import json_schema

    return json_schema()


def schema_text(schema: dict[str, Any] | None = None) -> str:
    """The schema as the exporter writes it."""
    schema = current_schema() if schema is None else schema
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def compare(text: str, schema: dict[str, Any]) -> Status:
    """``'same'`` (byte-identical to the export), ``'format'`` (the same JSON,
    formatted differently) or ``'stale'`` (different content, or not JSON)."""
    if text == schema_text(schema):
        return "same"
    try:
        return "format" if json.loads(text) == schema else "stale"
    except ValueError:
        return "stale"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the checked-in schema is stale")
    args = parser.parse_args(argv)
    schema = current_schema()
    rel = SCHEMA_PATH.relative_to(ROOT)
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        status = compare(current, schema)
        if status == "stale":
            print(f"{rel} is out of date; run: python scripts/export_schema.py",
                  file=sys.stderr)
            return 1
        if status == "format":
            print(f"note: {rel} has the right content but is formatted differently from "
                  "this pydantic version's output; run 'python scripts/export_schema.py' to "
                  "reformat it (optional).", file=sys.stderr)
        print(f"{rel} is up to date.")
        return 0
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(schema_text(schema), encoding="utf-8")
    print(f"Wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
