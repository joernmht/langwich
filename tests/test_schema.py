"""The published JSON Schema file must match the pydantic model."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from langwich.model import SCHEMA_ID, json_schema, worksheet_from_dict

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = REPO_ROOT / "src" / "langwich" / "schema" / "langwich-3.json"
EXPORT = REPO_ROOT / "scripts" / "export_schema.py"


def test_checked_in_schema_matches_the_model() -> None:
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == json_schema(), (
        "src/langwich/schema/langwich-3.json is stale; run: python scripts/export_schema.py"
    )


def test_schema_file_is_formatted_like_the_exporter() -> None:
    expected = json.dumps(json_schema(), indent=2, ensure_ascii=False) + "\n"
    assert SCHEMA_FILE.read_text(encoding="utf-8") == expected


def test_export_script_check_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(EXPORT), "--check"], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_schema_describes_the_contract() -> None:
    schema = json_schema()
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["schema"]["const"] == SCHEMA_ID
    assert {"schema", "title", "story", "vocabulary", "tasks"} <= set(schema["required"])


def test_examples_validate_against_the_model() -> None:
    for path in sorted((REPO_ROOT / "examples").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") == SCHEMA_ID:
            worksheet_from_dict(data)
