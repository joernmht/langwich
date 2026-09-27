"""The published JSON Schema file must match the pydantic model."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

from langwich.model import SCHEMA_ID, json_schema, worksheet_from_dict

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_FILE = REPO_ROOT / "src" / "langwich" / "schema" / "langwich-3.json"
EXPORT = REPO_ROOT / "scripts" / "export_schema.py"
PAGES_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "pages.yml"
#: GitHub Pages serves docs/ at this address (see pages.yml).
PAGES_ROOT = "https://joernmht.github.io/langwich/"


def _export_module():
    spec = importlib.util.spec_from_file_location("export_schema", EXPORT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_checked_in_schema_matches_the_model() -> None:
    assert json.loads(SCHEMA_FILE.read_text(encoding="utf-8")) == json_schema(), (
        "src/langwich/schema/langwich-3.json is stale; run: python scripts/export_schema.py"
    )


def test_export_script_check_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(EXPORT), "--check"], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr


def test_check_compares_content_not_formatting() -> None:
    # A pydantic release that writes 1.0 instead of 1 must not make CI fail.
    export = _export_module()
    schema = {"type": "object", "properties": {"x": {"type": "number", "maximum": 1}}}
    exported = export.schema_text(schema)
    assert export.compare(exported, schema) == "same"
    assert export.compare(exported.replace('"maximum": 1', '"maximum": 1.0'), schema) == "format"
    assert export.compare(json.dumps(schema), schema) == "format"
    assert export.compare(exported.replace('"maximum": 1', '"maximum": 2'), schema) == "stale"
    assert export.compare("", schema) == "stale"
    assert export.compare("{not json", schema) == "stale"


def test_schema_describes_the_contract() -> None:
    schema = json_schema()
    assert schema["$schema"].startswith("https://json-schema.org/")
    assert schema["properties"]["schema"]["const"] == SCHEMA_ID
    assert {"schema", "title", "story", "vocabulary", "tasks"} <= set(schema["required"])


def test_schema_id_is_published_by_the_pages_workflow() -> None:
    # The $id must be a real address: pages.yml copies the checked-in file to
    # the matching place under docs/ before it uploads the site.
    schema_id = json_schema()["$id"]
    assert schema_id.startswith(PAGES_ROOT), schema_id
    published = "docs/" + schema_id.removeprefix(PAGES_ROOT)
    workflow = PAGES_WORKFLOW.read_text(encoding="utf-8")
    copy = f"cp {SCHEMA_FILE.relative_to(REPO_ROOT).as_posix()} {published}"
    assert copy in workflow, f"pages.yml must publish the schema: {copy}"
    assert workflow.index(copy) < workflow.index("upload-pages-artifact"), (
        "the schema must be copied before the site is uploaded"
    )
    assert urlparse(schema_id).path.endswith("/schema/langwich-3.json")


def test_examples_validate_against_the_model() -> None:
    for path in sorted((REPO_ROOT / "examples").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") == SCHEMA_ID:
            worksheet_from_dict(data)
