"""Remembered defaults: ``.langwich/profile.json``.

A tiny JSON file that any tool — the CLI, the ``/langwich`` slash command,
another LLM — can read and write, so the learner is not asked for their
languages and level every time::

    {
      "source_lang": "en",
      "target_lang": "de",
      "level": "B1",
      "frame": "episode",
      "color": false,
      "device": "epaper"
    }

:func:`load_profile` searches the start directory (default: the current
directory) and its parents, stopping at the filesystem root or at the first
directory that contains ``.git`` (the project root). :func:`save_profile`
always writes ``./.langwich/profile.json`` in the start directory.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

PROFILE_DIR = ".langwich"
PROFILE_FILE = "profile.json"

#: Keys langwich itself reads. Other keys are kept untouched.
KNOWN_KEYS: tuple[str, ...] = ("source_lang", "target_lang", "level", "frame", "color", "device")


def _start_dir(start: Path | None) -> Path:
    base = Path(start) if start is not None else Path.cwd()
    if base.is_file():
        base = base.parent
    return base


def find_profile(start: Path | None = None) -> Path | None:
    """The nearest ``.langwich/profile.json`` at or above ``start``, if any."""
    here = _start_dir(start).resolve()
    for folder in (here, *here.parents):
        candidate = folder / PROFILE_DIR / PROFILE_FILE
        if candidate.is_file():
            return candidate
        if (folder / ".git").exists():
            break
    return None


def load_profile(start: Path | None = None) -> dict[str, Any]:
    """Read the profile; ``{}`` when there is none or it is not a JSON object."""
    path = find_profile(start)
    if path is None:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_profile(data: dict[str, Any], start: Path | None = None) -> Path:
    """Write ``data`` to ``<start or cwd>/.langwich/profile.json`` and return the path."""
    folder = _start_dir(start) / PROFILE_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / PROFILE_FILE
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    tmp = path.with_name(f".{PROFILE_FILE}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path
