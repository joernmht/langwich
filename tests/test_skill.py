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
import yaml

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
    """The frontmatter as Claude reads it: YAML (an unquoted ': ' would break it)."""
    match = re.match(r"---\n(.*?)\n---\n", text, re.S)
    assert match, "SKILL.md must start with a --- frontmatter block"
    fields = yaml.safe_load(match.group(1))
    assert isinstance(fields, dict) and all(isinstance(v, str) for v in fields.values())
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


#: Loaded at start-up (sitecustomize) by the Python that runs the offline fallback: it
#: cannot import WeasyPrint or fontTools, as SKILL.md promises the path needs only pydantic
#: and Pillow.
_NO_PDF_TOOLS = """
import sys
from importlib.abc import MetaPathFinder

class Blocked(MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("weasyprint", "fontTools"):
            raise ImportError(f"{name} is not installed in this sandbox")
        return None

sys.meta_path.insert(0, Blocked())
"""


def _skill_md() -> str:
    return (REPO_ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")


def test_the_offline_fallback_runs_the_engine_without_installing(
    skill_zip: Path, tmp_path: Path
) -> None:
    """SKILL.md's no-network path, exactly as written: ``PYTHONPATH=<engine>/src python3 -m
    langwich``, with no WeasyPrint and no fontTools. It checks a worksheet, and render writes
    the HTML, says "PDF not created" and exits 1 — which SKILL.md tells Claude to expect."""
    engine = _unpack(skill_zip, tmp_path)
    assert "PYTHONPATH=/tmp/langwich-engine/src python3 -m langwich kinds" in _skill_md()
    blocker = tmp_path / "blocker"
    blocker.mkdir()
    (blocker / "sitecustomize.py").write_text(_NO_PDF_TOOLS, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(engine / "src"), str(blocker)])}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "langwich", *args],
            capture_output=True, text=True, check=False, cwd=tmp_path, env=env,
        )

    where = subprocess.run(
        [sys.executable, "-c", "import langwich, weasyprint"],
        capture_output=True, text=True, check=False, cwd=tmp_path, env=env,
    )
    assert "not installed in this sandbox" in where.stderr, "the blocker is not loaded"
    kinds = run("kinds")
    assert kinds.returncode == 0, kinds.stderr
    assert "match" in kinds.stdout
    example = REPO_ROOT / "examples" / "krasnale_wroclaw_de_pl.json"
    checked = run("validate", str(example), "--quality")
    assert checked.returncode == 0, checked.stdout + checked.stderr
    assert "OK: no problems found." in checked.stdout
    out = tmp_path / "out"
    rendered = run("render", str(example), "-o", f"{out}/")
    assert rendered.returncode == 1, rendered.stdout + rendered.stderr
    assert "PDF not created: WeasyPrint could not be loaded" in rendered.stderr
    assert "PDF not created: WeasyPrint could not be loaded" in _skill_md()
    html = out / "krasnale_wroclaw_de_pl.html"
    assert html.is_file() and not html.with_suffix(".pdf").exists()


def test_the_handed_over_html_carries_its_fonts(tmp_path: Path) -> None:
    """The snippet in SKILL.md turns the sandbox's file:// font links into data: URIs, so the
    person's browser prints the HTML in langwich's fonts."""
    match = re.search(r"python3 - data/<file>\.html <<'EOF'\n(.*?)\nEOF\n", _skill_md(), re.S)
    assert match, "SKILL.md lost the font-embedding snippet"
    from langwich.cli import main

    example = REPO_ROOT / "examples" / "krasnale_wroclaw_de_pl.json"
    assert main(["render", str(example), "--html-only", "-o", f"{tmp_path}/"]) == 0
    html = tmp_path / "krasnale_wroclaw_de_pl.html"
    fonts = html.read_text(encoding="utf-8").count("file:")
    assert fonts, "the renderer no longer links fonts by file:// URI; check the snippet"
    done = subprocess.run(
        [sys.executable, "-", str(html)], input=match.group(1),
        capture_output=True, text=True, check=False,
    )
    assert done.returncode == 0, done.stderr
    text = html.read_text(encoding="utf-8")
    assert not re.search(r"url\(file:", text)
    assert text.count("data:font/ttf;base64,") >= 9


def test_the_bundled_engine_installs_with_pip(skill_zip: Path, tmp_path: Path) -> None:
    """The online path: ``pip install`` of the unpacked engine builds and runs.

    Without build isolation, so no download is needed: this checks the zip's
    pyproject.toml (readme, licence files, package data), not the network.
    """
    pytest.importorskip("pip")
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
