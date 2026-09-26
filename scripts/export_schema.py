#!/usr/bin/env python3
"""Regenerate ``src/langwich/schema/langwich-3.json`` from the pydantic model.

    python scripts/export_schema.py           # rewrite the file
    python scripts/export_schema.py --check   # exit 1 if the file is out of date (CI)

The model in ``src/langwich/model.py`` is the single source of truth; the
JSON file is a published copy for editors, other tools and LLMs.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "src" / "langwich" / "schema" / "langwich-3.json"


def schema_text() -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from langwich.model import json_schema

    return json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="do not write; exit 1 if the checked-in schema is stale")
    args = parser.parse_args(argv)
    text = schema_text()
    rel = SCHEMA_PATH.relative_to(ROOT)
    if args.check:
        current = SCHEMA_PATH.read_text(encoding="utf-8") if SCHEMA_PATH.exists() else ""
        if current != text:
            print(f"{rel} is out of date; run: python scripts/export_schema.py",
                  file=sys.stderr)
            return 1
        print(f"{rel} is up to date.")
        return 0
    SCHEMA_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCHEMA_PATH.write_text(text, encoding="utf-8")
    print(f"Wrote {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
