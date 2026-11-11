"""The Claude skill people without a terminal upload: ``langwich-skill.zip``.

``scripts/build_skill.py`` packs ``skill/SKILL.md`` and an installable copy of
langwich; the Pages workflow publishes it next to the landing page. These tests
hold the zip to what the Claude apps expect and to what SKILL.md tells Claude
to do with it.
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "build_skill.py"

_spec = importlib.util.spec_from_file_location("build_skill", SCRIPT)
assert _spec and _spec.loader
build_skill = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build_skill)


@pytest.fixture(scope="module")
def skill_zip(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return build_skill.build(tmp_path_factory.mktemp("skill") / "langwich-skill.zip")


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must start with a --- frontmatter block"
    fields = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def test_the_frontmatter_is_what_the_claude_apps_accept() -> None:
    fields = _frontmatter((REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8"))
    assert set(fields) == {"name", "description"}
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    # claude.ai refuses longer descriptions (support article "How to create custom skills")
    assert 0 < len(fields["description"]) <= 200
    assert "<" not in fields["description"] and ">" not in fields["description"]


def test_the_zip_holds_one_skill_folder_with_an_installable_engine(skill_zip: Path) -> None:
    with zipfile.ZipFile(skill_zip) as zf:
        names = zf.namelist()
        pyproject = tomllib.loads(zf.read("langwich/engine/pyproject.toml").decode())
    assert {name.split("/")[0] for name in names} == {"langwich"}
    assert "langwich/SKILL.md" in names
    for name in build_skill.ENGINE_FILES:
        assert f"langwich/engine/{name}" in names
    # everything the wheel would ship: modules, fonts and their licences, the schema
    package = {
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "src" / "langwich").rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
    }
    assert {f"langwich/engine/{p}" for p in package} <= set(names)
    assert not [n for n in names if "__pycache__" in n or n.endswith(".pyc")]
    assert pyproject["project"]["scripts"]["langwich"] == "langwich.cli:main"


def test_the_zip_is_reproducible(skill_zip: Path, tmp_path: Path) -> None:
    again = build_skill.build(tmp_path / "again.zip")
    assert again.read_bytes() == skill_zip.read_bytes()


def test_the_bundled_engine_runs(skill_zip: Path, tmp_path: Path) -> None:
    with zipfile.ZipFile(skill_zip) as zf:
        zf.extractall(tmp_path)
    src = tmp_path / "langwich" / "engine" / "src"
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); "
         "from langwich.cli import main; sys.exit(main(['kinds']))", str(src)],
        capture_output=True, text=True, check=False, cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert "match" in result.stdout


def test_skill_md_names_the_engine_folder_it_ships_with() -> None:
    text = (REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "<skill-folder>/engine" in text
    assert "/mnt/user-data/outputs/" in text, "say where Claude apps pick up files to download"
