"""The Claude skill people without a terminal upload: ``langwich-skill.zip``.

``scripts/build_skill.py`` packs ``skill/SKILL.md`` and an installable copy of
langwich; the Pages workflow publishes it next to the landing page. These tests
hold the zip to what the Claude apps expect and to what SKILL.md tells Claude
to do with it.
"""

from __future__ import annotations

import importlib.util
import os
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
    package = {f"langwich/engine/{p.relative_to(REPO_ROOT).as_posix()}"
               for p in build_skill.package_files()}
    assert {n for n in names if n.startswith("langwich/engine/src/")} == package
    assert any(n.endswith(".ttf") for n in names) and any(n.endswith(".json") for n in names)
    assert pyproject["project"]["scripts"]["langwich"] == "langwich.cli:main"


def test_the_zip_holds_what_git_tracks_and_nothing_else() -> None:
    """Patterns, not a directory listing: a stray local file never ships."""
    try:
        tracked = subprocess.run(
            ["git", "ls-files", "src/langwich"], cwd=REPO_ROOT,
            capture_output=True, text=True, check=True,
        ).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    packed = {p.relative_to(REPO_ROOT).as_posix() for p in build_skill.package_files()}
    assert packed == set(tracked)


def test_the_zip_is_reproducible(skill_zip: Path, tmp_path: Path) -> None:
    again = build_skill.build(tmp_path / "again.zip")
    assert again.read_bytes() == skill_zip.read_bytes()


def _unpack(skill_zip: Path, into: Path) -> Path:
    with zipfile.ZipFile(skill_zip) as zf:
        zf.extractall(into)
    return into / "langwich" / "engine"


#: Runs langwich's CLI as the offline fallback does, in a Python that cannot import
#: WeasyPrint or fontTools: SKILL.md promises this path needs only pydantic and Pillow.
_WITHOUT_PDF_TOOLS = """
import sys
from importlib.abc import MetaPathFinder

class Blocked(MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("weasyprint", "fontTools"):
            raise ImportError(f"{name} is not installed in this sandbox")
        return None

sys.meta_path.insert(0, Blocked())
import langwich
assert langwich.__file__.startswith(sys.argv[1]), langwich.__file__
from langwich.cli import main
sys.exit(main(sys.argv[2:]))
"""


def test_the_offline_fallback_runs_the_engine_without_installing(
    skill_zip: Path, tmp_path: Path
) -> None:
    """SKILL.md's no-network path: ``PYTHONPATH=<engine>/src python3 -m langwich``,
    with no WeasyPrint and no fontTools: it still checks a worksheet and writes the HTML."""
    engine = _unpack(skill_zip, tmp_path)
    text = (REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "PYTHONPATH=/tmp/langwich-engine/src python3 -m langwich kinds" in text
    src = engine / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", _WITHOUT_PDF_TOOLS, str(src), *args],
            capture_output=True, text=True, check=False, cwd=tmp_path, env=env,
        )

    kinds = run("kinds")
    assert kinds.returncode == 0, kinds.stderr
    assert "match" in kinds.stdout
    example = REPO_ROOT / "examples" / "krasnale_wroclaw_de_pl.json"
    checked = run("validate", str(example), "--quality")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "OK: no problems found." in checked.stdout
    out = tmp_path / "out"
    rendered = run("render", str(example), "-o", f"{out}/")
    assert (out / "krasnale_wroclaw_de_pl.html").is_file(), rendered.stdout + rendered.stderr
    assert not (out / "krasnale_wroclaw_de_pl.pdf").exists()
    assert "print it to PDF" in rendered.stdout + rendered.stderr


def test_the_bundled_engine_installs_with_pip(skill_zip: Path, tmp_path: Path) -> None:
    """The online path: ``pip install`` of the unpacked engine builds and runs.

    Without build isolation, so no download is needed: this checks the zip's
    pyproject.toml (readme, licence files, package data), not the network.
    """
    pytest.importorskip("setuptools", minversion="77")
    engine = _unpack(skill_zip, tmp_path / "unpacked")
    target = tmp_path / "site"
    pip = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--quiet", "--no-deps", "--no-build-isolation",
         "--no-index", "--target", str(target), str(engine)],
        capture_output=True, text=True, check=False, cwd=tmp_path,
    )
    assert pip.returncode == 0, pip.stderr
    assert (target / "langwich" / "fonts").is_dir() and (target / "langwich" / "schema").is_dir()
    result = subprocess.run(
        [sys.executable, "-m", "langwich", "kinds"],
        capture_output=True, text=True, check=False, cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(target)},
    )
    assert result.returncode == 0, result.stderr


def test_skill_md_names_the_engine_folder_it_ships_with() -> None:
    text = (REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert "<skill-folder>/engine" in text
    assert "/mnt/user-data/outputs/" in text, "say where Claude apps pick up files to download"
