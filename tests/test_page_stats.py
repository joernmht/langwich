"""The landing page's data-count numbers must match the exercise graph."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_script():
    spec = importlib.util.spec_from_file_location(
        "update_page_stats", REPO_ROOT / "scripts" / "update_page_stats.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_index_html_counts_are_in_sync():
    script = _load_script()
    html = (REPO_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert script.apply_stats(html, script.compute_stats()) == html, (
        "docs/index.html counts are stale — run "
        "'python3 scripts/update_page_stats.py' and commit the result"
    )


def test_index_html_has_all_count_markers():
    html = (REPO_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    keys = set(re.findall(r'data-count="([\w-]+)"', html))
    script = _load_script()
    assert keys == set(script.compute_stats().keys())


def test_all_bundled_examples_are_counted():
    script = _load_script()
    assert script.compute_stats()["examples"] == 3
