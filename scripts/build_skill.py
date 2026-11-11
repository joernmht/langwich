"""Pack the langwich skill for the Claude apps: ``langwich-skill.zip``.

People who never open a terminal upload this file once in Claude (claude.ai or the
desktop app: Customize → Skills → + → Create skill → Upload a skill) and then simply
ask for a worksheet.
Claude reads ``langwich/SKILL.md`` and runs the bundled engine in its own sandbox.

The zip holds::

    langwich/SKILL.md            skill/SKILL.md from this repository
    langwich/engine/            an installable copy of langwich: pyproject.toml,
                                 README.md, LICENSE, NOTICE and the files of
                                 src/langwich/ the wheel ships (the modules and the
                                 package-data patterns in pyproject.toml)

The archive is reproducible (sorted entries, fixed timestamps), so the same
sources give the same bytes. The Pages workflow builds it into ``docs/``; it is
not checked in.

    python3 scripts/build_skill.py                 # -> dist/langwich-skill.zip
    python3 scripts/build_skill.py -o docs/langwich-skill.zip
"""

from __future__ import annotations

import argparse
import sys
import tomllib
import zipfile
from collections.abc import Iterator
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_MD = REPO_ROOT / "skill" / "SKILL.md"
DEFAULT_OUT = REPO_ROOT / "dist" / "langwich-skill.zip"
ENGINE_FILES = ("pyproject.toml", "README.md", "LICENSE", "NOTICE")
PACKAGE = REPO_ROOT / "src" / "langwich"
_EPOCH = (1980, 1, 1, 0, 0, 0)


def package_files() -> list[Path]:
    """What the wheel ships from src/langwich: every module and the package data.

    Patterns, not a directory listing, so that a stray file in a local checkout
    (an editor's swap file, a .DS_Store) never ends up in the zip.
    """
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = ["**/*.py", *pyproject["tool"]["setuptools"]["package-data"]["langwich"]]
    files = {path for pattern in patterns for path in PACKAGE.glob(pattern)}
    return sorted(p for p in files if p.is_file() and "__pycache__" not in p.parts)


def entries() -> Iterator[tuple[str, Path]]:
    """(name in the zip, source file), in a stable order."""
    yield "langwich/SKILL.md", SKILL_MD
    for name in ENGINE_FILES:
        yield f"langwich/engine/{name}", REPO_ROOT / name
    for path in package_files():
        yield f"langwich/engine/{path.relative_to(REPO_ROOT).as_posix()}", path


def build(out: Path) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name, path in entries():
            info = zipfile.ZipInfo(name, date_time=_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUT,
                        help=f"where to write the zip (default: {DEFAULT_OUT.relative_to(REPO_ROOT)})")
    args = parser.parse_args(argv)
    out = build(args.output)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
