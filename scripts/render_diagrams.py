#!/usr/bin/env python3
"""Render Mermaid diagrams to SVG/PNG for offline viewing.

This script provides multiple rendering strategies:

  1. **Mermaid CLI (mmdc)** — best quality, requires Node.js + @mermaid-js/mermaid-cli
  2. **mermaid.ink API** — zero-install, uses the free mermaid.ink web service
  3. **Kroki API** — alternative web service, supports many diagram types

Usage
─────
    # Render all .mermaid files in docs/ to SVG (auto-selects best method)
    python scripts/render_diagrams.py

    # Force a specific renderer
    python scripts/render_diagrams.py --renderer mmdc
    python scripts/render_diagrams.py --renderer mermaid-ink
    python scripts/render_diagrams.py --renderer kroki

    # Render to PNG instead of SVG
    python scripts/render_diagrams.py --format png

    # Render a single file
    python scripts/render_diagrams.py --input docs/class_diagram.mermaid

Prerequisites
─────────────
    For local rendering (mmdc):
        npm install -g @mermaid-js/mermaid-cli

    For web-based rendering:
        pip install httpx   (already a project dependency)
"""

from __future__ import annotations

import argparse
import base64
import logging
import shutil
import subprocess
import sys
import zlib
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
OUTPUT_DIR = DOCS_DIR / "rendered"


# ── Renderer: Mermaid CLI (mmdc) ────────────────────────────────────


def render_with_mmdc(
    mermaid_text: str,
    output_path: Path,
    fmt: str = "svg",
) -> bool:
    """Render using the Mermaid CLI (mmdc).

    Requires: npm install -g @mermaid-js/mermaid-cli
    """
    mmdc = shutil.which("mmdc")
    if mmdc is None:
        logger.warning("mmdc not found — install with: npm install -g @mermaid-js/mermaid-cli")
        return False

    # Write temp input
    tmp_input = output_path.with_suffix(".mmd")
    tmp_input.write_text(mermaid_text, encoding="utf-8")

    try:
        result = subprocess.run(
            [mmdc, "-i", str(tmp_input), "-o", str(output_path), "-f", fmt],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.error("mmdc failed: %s", result.stderr)
            return False
        logger.info("Rendered (mmdc): %s", output_path)
        return True
    except subprocess.TimeoutExpired:
        logger.error("mmdc timed out")
        return False
    finally:
        tmp_input.unlink(missing_ok=True)


# ── Renderer: mermaid.ink API ────────────────────────────────────────


def render_with_mermaid_ink(
    mermaid_text: str,
    output_path: Path,
    fmt: str = "svg",
) -> bool:
    """Render using the free mermaid.ink web API.

    No installation required — sends the diagram to mermaid.ink for rendering.
    """
    try:
        import httpx
    except ImportError:
        logger.error("httpx required — install with: pip install httpx")
        return False

    # mermaid.ink expects base64-encoded diagram in the URL
    encoded = base64.urlsafe_b64encode(mermaid_text.encode("utf-8")).decode("ascii")
    url = f"https://mermaid.ink/{fmt}/{encoded}"

    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        logger.info("Rendered (mermaid.ink): %s", output_path)
        return True
    except Exception as exc:
        logger.error("mermaid.ink request failed: %s", exc)
        return False


# ── Renderer: Kroki API ─────────────────────────────────────────────


def render_with_kroki(
    mermaid_text: str,
    output_path: Path,
    fmt: str = "svg",
) -> bool:
    """Render using the Kroki web API (https://kroki.io).

    Supports many diagram types; uses deflate compression for the payload.
    """
    try:
        import httpx
    except ImportError:
        logger.error("httpx required — install with: pip install httpx")
        return False

    compressed = zlib.compress(mermaid_text.encode("utf-8"), level=9)
    encoded = base64.urlsafe_b64encode(compressed).decode("ascii")
    url = f"https://kroki.io/mermaid/{fmt}/{encoded}"

    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        resp.raise_for_status()
        output_path.write_bytes(resp.content)
        logger.info("Rendered (kroki): %s", output_path)
        return True
    except Exception as exc:
        logger.error("Kroki request failed: %s", exc)
        return False


# ── Orchestrator ─────────────────────────────────────────────────────

RENDERERS = {
    "mmdc": render_with_mmdc,
    "mermaid-ink": render_with_mermaid_ink,
    "kroki": render_with_kroki,
}


def render_diagram(
    input_path: Path,
    output_dir: Path,
    fmt: str = "svg",
    renderer: str | None = None,
) -> Path | None:
    """Render a single .mermaid file to SVG or PNG.

    Tries renderers in order of preference unless a specific one is requested.
    """
    mermaid_text = input_path.read_text(encoding="utf-8")
    output_path = output_dir / f"{input_path.stem}.{fmt}"
    output_dir.mkdir(parents=True, exist_ok=True)

    if renderer:
        render_fn = RENDERERS.get(renderer)
        if render_fn is None:
            logger.error("Unknown renderer: %s (choose from %s)", renderer, list(RENDERERS))
            return None
        success = render_fn(mermaid_text, output_path, fmt)
        return output_path if success else None

    # Auto-select: try each renderer in order
    for name, render_fn in RENDERERS.items():
        logger.info("Trying renderer: %s", name)
        if render_fn(mermaid_text, output_path, fmt):
            return output_path

    logger.error("All renderers failed for %s", input_path)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render Mermaid diagrams to SVG or PNG",
    )
    parser.add_argument(
        "--input", "-i",
        type=Path,
        help="Path to a single .mermaid file (default: all files in docs/)",
    )
    parser.add_argument(
        "--output-dir", "-o",
        type=Path,
        default=OUTPUT_DIR,
        help=f"Output directory (default: {OUTPUT_DIR})",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["svg", "png"],
        default="svg",
        help="Output format (default: svg)",
    )
    parser.add_argument(
        "--renderer", "-r",
        choices=list(RENDERERS),
        help="Force a specific renderer (default: auto-select)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-8s %(message)s",
    )

    # Collect input files
    if args.input:
        files = [args.input]
    else:
        files = sorted(DOCS_DIR.glob("*.mermaid"))

    if not files:
        logger.error("No .mermaid files found in %s", DOCS_DIR)
        sys.exit(1)

    # Render each file
    success = 0
    for f in files:
        logger.info("Processing: %s", f.name)
        result = render_diagram(f, args.output_dir, args.format, args.renderer)
        if result:
            success += 1
            print(f"  OK  {result}")
        else:
            print(f"  FAIL  {f.name}")

    print(f"\nRendered {success}/{len(files)} diagrams to {args.output_dir}/")
    sys.exit(0 if success == len(files) else 1)


if __name__ == "__main__":
    main()
