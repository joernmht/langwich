"""Contract tests that keep the documentation honest.

The README, CLAUDE.md, the ``/langwich`` slash command and the landing page
show commands, flags and JSON that people — and LLMs — copy verbatim. These
tests fail as soon as the docs drift away from the code:

1. every ``langwich …`` command line in a code block parses with the real
   CLI parser (or is the deprecated ``langwich --from-json FILE`` form);
2. every ``--flag`` the docs mention exists in some ``langwich`` command (or
   is one of the few legacy flags the deprecated form still accepts); flags
   on the command lines of other programs (``python``, ``pip``, ``ollama`` …)
   are left alone;
3. every complete worksheet in a ``json`` code block — one that contains
   ``"schema": "langwich/3"`` — passes the contract. Fence a partial excerpt as
   ``jsonc`` instead (in HTML: ``<pre class="jsonc">``), or leave out the schema key;
4. every bundled example validates with no errors and no warnings;
5. the README mentions every task kind (in backticks);
6. every repository path the docs mention (``examples/…``, ``docs/…``,
   ``src/langwich/…``, ``scripts/…``, ``tests/…``) exists;
7. the README documents every option of every ``langwich`` command, and the
   ``--scenes`` range it states is the one the CLI accepts;
8. every stage sequence in the docs (``gist → detail → …`` or a backticked
   list) follows the lesson order in ``langwich.model.STAGES``;
9. install instructions use a virtual environment (PEP 668), and every Ollama
   recipe raises the context size;
10. packaging and CI agree with the docs: the Apache-2.0 licence file, the licence
    files in the wheel, one version source, the pinned ruff rule set, the
    Python versions, the system libraries and ``LANGWICH_REQUIRE_PDF`` in CI;
11. ``scripts/build_showcase.py --help`` (or a mistyped option) never renders.

"Code blocks" are Markdown fences and HTML ``<pre>`` elements. Placeholders in
commands (``<file>``, ``…``, ``FILE``) are replaced by a dummy value; a line
that still does not parse *because of* a placeholder is skipped.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import shlex
import subprocess
import sys
import tomllib
from dataclasses import dataclass, field
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

import pytest

import langwich
from langwich.cli import SUBCOMMANDS, build_parser
from langwich.model import STAGES, TASK_KINDS, ContractError, worksheet_from_dict
from langwich.validate import check_file

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC_FILES: tuple[str, ...] = (
    "README.md",
    "CLAUDE.md",
    ".claude/commands/langwich.md",
    "docs/index.html",
    "docs/architecture.md",
)

EXAMPLES = sorted((REPO_ROOT / "examples").glob("*.json"))

#: Flags only the deprecated ``langwich --from-json FILE`` form accepts
#: (``--exercises``, ``--image-credit`` and ``--engine`` are ignored with a note).
LEGACY_FLAGS: frozenset[str] = frozenset({
    "--from-json", "--list-exercises", "--output", "--allow-color",
    "--exercises", "--image", "--image-credit", "--engine",
})

#: Programs whose flags are not langwich's business.
OTHER_PROGRAMS: frozenset[str] = frozenset({
    "python", "python3", "py", "pip", "pip3", "pipx", "uv", "pytest", "ruff", "mypy",
    "git", "gh", "claude", "ollama", "lms", "llm", "llama-cli", "llama-server",
    "brew", "apt", "apt-get", "dnf", "pacman", "sudo", "choco", "winget", "scoop",
    "conda", "mamba", "cd", "cat", "echo", "curl", "wget", "open", "xdg-open", "start",
    "export", "source", "crontab", "npm", "npx", "docker", "weasyprint", "ls", "cp",
    "mv", "mkdir", "rm",
})

#: Code-block languages that never contain command lines.
_NON_SHELL_LANGS = frozenset({
    "json", "jsonc", "json5", "python", "py", "html", "css", "js", "javascript", "ts",
    "xml", "svg", "yaml", "yml", "toml", "ini", "diff",
})
#: Code-block languages whose every ``langwich …`` line is a command.
_SHELL_LANGS = frozenset({"", "bash", "sh", "shell", "console", "zsh", "fish", "powershell",
                          "ps1", "pwsh", "cmd", "bat", "shell-session"})

_FLAG_RE = re.compile(r"(?<![\w/-])--[a-z][a-z0-9]*(?:-[a-z0-9]+)*")
_SCHEMA_RE = re.compile(r'"schema"\s*:\s*"langwich/3"')
_ANGLE_PLACEHOLDER_RE = re.compile(r"<[^<>\s]+>")
_CAPS_PLACEHOLDER_RE = re.compile(r"^(?:[A-Z][A-Z_]+|N)$")
_ELLIPSES = frozenset({"…", "...", "[...]", "[…]"})
_PATH_RE = re.compile(
    r"(?<![\w./@-])((?:examples|docs|src/langwich|scripts|tests|\.github)/[\w.@/-]*\w)"
)
_OPERATORS = frozenset({"|", "||", "&&", ";", "&"})
_REDIRECTS = frozenset({">", ">>", "<", "<<", "&>", ">&", "2>", "2>>"})
_PLACEHOLDER = "placeholder"


# ---------------------------------------------------------------------------
# Reading the docs
# ---------------------------------------------------------------------------


@dataclass
class Block:
    """A code block: a Markdown fence or an HTML ``<pre>``."""

    lang: str
    text: str
    line: int


@dataclass
class Doc:
    name: str
    blocks: list[Block] = field(default_factory=list)
    inline_code: list[str] = field(default_factory=list)
    prose: str = ""


_FENCE_RE = re.compile(r"^\s*(?P<fence>`{3,}|~{3,})\s*(?P<info>[^`\s]*)[^`]*$")


def _parse_markdown(name: str, text: str) -> Doc:
    doc = Doc(name)
    prose: list[str] = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        m = _FENCE_RE.match(lines[i])
        if not m:
            prose.append(lines[i])
            i += 1
            continue
        fence = m.group("fence")
        lang = m.group("info").lower()
        start = i + 1
        body: list[str] = []
        i += 1
        while i < len(lines):
            stripped = lines[i].strip()
            if (stripped.startswith(fence[0] * len(fence))
                    and set(stripped) == {fence[0]}):
                break
            body.append(lines[i])
            i += 1
        i += 1  # skip the closing fence
        doc.blocks.append(Block(lang, "\n".join(body), start + 1))
    joined = "\n".join(prose)
    doc.inline_code = [m.group(2) for m in re.finditer(r"(`+)(.+?)\1", joined)]
    doc.prose = re.sub(r"(`+)(.+?)\1", " ", joined)
    return doc


class _HtmlDoc(HTMLParser):
    """Collects ``<pre>`` blocks, inline ``<code>`` and the visible text;
    ``<style>``, ``<script>`` and comments are dropped."""

    def __init__(self, doc: Doc):
        super().__init__(convert_charrefs=True)
        self.doc = doc
        self._skip = 0
        self._pre: list[str] | None = None
        self._pre_lang = ""
        self._pre_line = 0
        self._code: list[str] | None = None
        self._prose: list[str] = []

    @staticmethod
    def _lang(attrs: list[tuple[str, str | None]]) -> str:
        a = {k: v or "" for k, v in attrs}
        if a.get("data-lang"):
            return a["data-lang"].lower()
        for cls in a.get("class", "").split():
            cls = cls.lower().removeprefix("language-").removeprefix("lang-")
            if cls in ("json", "jsonc", "bash", "sh", "shell", "console", "text", "python"):
                return cls
        return ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "pre":
            self._pre, self._pre_lang, self._pre_line = [], self._lang(attrs), self.getpos()[0]
        elif tag == "code":
            if self._pre is not None:
                self._pre_lang = self._pre_lang or self._lang(attrs)
            else:
                self._code = []
        elif tag == "br" and self._pre is not None:
            self._pre.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag == "pre" and self._pre is not None:
            self.doc.blocks.append(Block(self._pre_lang, "".join(self._pre), self._pre_line))
            self._pre = None
        elif tag == "code" and self._code is not None:
            self.doc.inline_code.append("".join(self._code))
            self._code = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._pre is not None:
            self._pre.append(data)
        elif self._code is not None:
            self._code.append(data)
        else:
            self._prose.append(data)

    def close(self) -> None:
        super().close()
        self.doc.prose = " ".join(self._prose)


@cache
def load_doc(name: str) -> Doc:
    path = REPO_ROOT / name
    if not path.is_file():
        pytest.skip(f"{name} does not exist")
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".html":
        doc = Doc(name)
        parser = _HtmlDoc(doc)
        parser.feed(text)
        parser.close()
        return doc
    return _parse_markdown(name, text)


# ---------------------------------------------------------------------------
# Command lines
# ---------------------------------------------------------------------------


def _logical_lines(text: str) -> list[tuple[int, str]]:
    """Lines with backslash continuations joined: (offset of the first line, text)."""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    first = 0
    for n, line in enumerate(text.splitlines()):
        if not buf:
            first = n
        if line.rstrip().endswith("\\"):
            buf.append(line.rstrip()[:-1])
            continue
        buf.append(line)
        out.append((first, " ".join(buf)))
        buf = []
    if buf:
        out.append((first, " ".join(buf)))
    return out


def _tokens(line: str) -> list[str] | None:
    lex = shlex.shlex(line, posix=True, punctuation_chars=";&|<>")
    lex.whitespace_split = True
    lex.commenters = "#"
    try:
        return list(lex)
    except ValueError:  # unbalanced quotes: not a command line
        return None


def _commands(line: str) -> list[list[str]]:
    """Split a shell line into commands (at |, &&, ;) without redirections."""
    line = re.sub(r"^\s*(?:\$|%|PS[^>]*>)\s+", "", line)
    line = _ANGLE_PLACEHOLDER_RE.sub(_PLACEHOLDER, line)
    tokens = _tokens(line)
    if tokens is None:
        return []
    commands: list[list[str]] = [[]]
    skip_next = False
    for i, tok in enumerate(tokens):
        if skip_next:
            skip_next = False
            continue
        if tok in _OPERATORS:
            commands.append([])
        elif tok in _REDIRECTS:
            skip_next = True
        elif tok.isdigit() and i + 1 < len(tokens) and tokens[i + 1] in _REDIRECTS:
            continue
        else:
            commands[-1].append(tok)
    return [c for c in commands if c]


def _program(command: list[str]) -> tuple[str, list[str]]:
    """The program name and its arguments (``python -m langwich`` counts as langwich)."""
    rest = list(command)
    while rest and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", rest[0]):
        rest.pop(0)  # VAR=value prefixes
    if not rest:
        return "", []
    prog = Path(rest[0]).name.lower().removesuffix(".exe")
    if prog in ("python", "python3", "py") and rest[1:3] == ["-m", "langwich"]:
        return "langwich", rest[3:]
    return prog, rest[1:]


def _clean_args(args: list[str]) -> tuple[list[str], bool]:
    """Arguments with placeholders replaced; True when any placeholder was seen."""
    out: list[str] = []
    placeholder = False
    for arg in args:
        if arg in _ELLIPSES:
            placeholder = True
            continue
        if arg.startswith("[") or arg.endswith("]"):
            placeholder = True
            arg = arg.strip("[]")
            if not arg:
                continue
        if _PLACEHOLDER in arg or _CAPS_PLACEHOLDER_RE.match(arg) or "…" in arg:
            placeholder = True
        out.append(arg)
    return out, placeholder


@cache
def _parser() -> argparse.ArgumentParser:
    return build_parser()


def _legacy_parser() -> argparse.ArgumentParser:
    lp = argparse.ArgumentParser(prog="langwich", add_help=False)
    lp.add_argument("--from-json")
    lp.add_argument("-o", "--output")
    lp.add_argument("--allow-color", action="store_true")
    lp.add_argument("--list-exercises", action="store_true")
    for flag in ("--exercises", "--image", "--image-credit", "--engine"):
        lp.add_argument(flag)
    return lp


def _is_legacy(args: list[str]) -> bool:
    if args and args[0] in SUBCOMMANDS:
        return False
    return any(a == "--from-json" or a.startswith("--from-json=") or a == "--list-exercises"
               for a in args)


def parse_error(args: list[str]) -> str | None:
    """None when ``langwich ARGS`` parses, else argparse's complaint."""
    parser = _legacy_parser() if _is_legacy(args) else _parser()
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            parser.parse_args(args)
    except SystemExit as exc:
        if exc.code not in (0, None):
            lines = err.getvalue().strip().splitlines()
            return lines[-1] if lines else f"exit status {exc.code}"
    return None


def command_lines(doc: Doc) -> list[tuple[int, str, list[str], bool]]:
    """Every ``langwich …`` command in the doc's code blocks:
    (line number, original line, arguments, had a placeholder)."""
    found = []
    for block in doc.blocks:
        if block.lang in _NON_SHELL_LANGS:
            continue
        shell = block.lang in _SHELL_LANGS
        for offset, line in _logical_lines(block.text):
            for command in _commands(line):
                prog, args = _program(command)
                if prog != "langwich":
                    continue
                if not shell and not (args and (args[0] in SUBCOMMANDS or args[0].startswith("-"))):
                    continue  # prose (or a folder name) that starts with the word "langwich"
                args, placeholder = _clean_args(args)
                found.append((block.line + offset, line.strip(), args, placeholder))
    return found


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------


@cache
def langwich_flags() -> frozenset[str]:
    flags: set[str] = set()

    def walk(parser: argparse.ArgumentParser) -> None:
        for action in parser._actions:
            flags.update(s for s in action.option_strings if s.startswith("--"))
            if isinstance(action, argparse._SubParsersAction):
                for sub in action.choices.values():
                    walk(sub)

    walk(_parser())
    return frozenset(flags)


def _flags_in_code(text: str) -> set[str]:
    """Flags in code, except those on another program's command line."""
    flags: set[str] = set()
    for _, line in _logical_lines(text):
        commands = _commands(line)
        if not commands:  # not shell syntax (e.g. prose with an apostrophe)
            first = line.split()[0] if line.split() else ""
            if Path(first).name.lower() not in OTHER_PROGRAMS:
                flags.update(_FLAG_RE.findall(line))
            continue
        prog = ""
        for command in commands:
            prog, _ = _program(command)
            if prog in OTHER_PROGRAMS:
                continue
            # all tokens: a help-output line such as "--page {a4,epaper}" starts with a flag
            flags.update(f for tok in command for f in _FLAG_RE.findall(tok.split("=", 1)[0]))
        comment = re.search(r"(?:^|\s)#(.*)$", line)  # shlex drops comments; check them too
        if comment and prog not in OTHER_PROGRAMS:
            flags.update(_FLAG_RE.findall(comment.group(1)))
    return flags


def mentioned_flags(doc: Doc) -> set[str]:
    flags = set(_FLAG_RE.findall(doc.prose))
    for block in doc.blocks:
        if block.lang not in ("json", "jsonc", "json5", "css", "html", "svg", "xml"):
            flags |= _flags_in_code(block.text)
    for code in doc.inline_code:
        flags |= _flags_in_code(code)
    return flags


# ---------------------------------------------------------------------------
# 1. Commands parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", DOC_FILES)
def test_documented_commands_parse(name: str):
    doc = load_doc(name)
    problems = []
    for line_no, line, args, placeholder in command_lines(doc):
        error = parse_error(args)
        if error and not placeholder:
            problems.append(f"{name}:{line_no}: {line!r}: {error}")
    assert not problems, "documented commands that langwich rejects:\n" + "\n".join(problems)


def test_extraction_from_markdown_and_html():
    md = _parse_markdown("x.md", "Use `--page`.\n\n```jsonc\n{\"schema\": \"langwich/3\", …}\n"
                                 "```\n\n```bash\nlangwich kinds\n```\n")
    assert [b.lang for b in md.blocks] == ["jsonc", "bash"]
    assert mentioned_flags(md) == {"--page"}
    assert [c[2] for c in command_lines(md)] == [["kinds"]]

    html = Doc("x.html")
    parser = _HtmlDoc(html)
    parser.feed("<style>:root { --ink: #000 }</style><!-- --note -->"
                "<p>Try <code>langwich render x.json --page epaper</code>.</p>"
                "<pre class='jsonc'>{}</pre><pre>langwich render &lt;file&gt;.json</pre>")
    parser.close()
    assert [b.lang for b in html.blocks] == ["jsonc", ""]
    assert mentioned_flags(html) == {"--page"}
    assert [c[2] for c in command_lines(html)] == [["render", "placeholder.json"]]


def test_command_extraction_sees_the_readme_commands():
    # Guard against an extractor that silently finds nothing.
    commands = command_lines(load_doc("README.md"))
    subcommands = {args[0] for _, _, args, _ in commands if args}
    assert {"render", "validate", "prompt"} <= subcommands


def test_parse_error_detects_bad_commands():
    assert parse_error(["render", "x.json", "--page", "epaper"]) is None
    assert parse_error(["--from-json", "x.json", "-o", "x.pdf"]) is None
    assert parse_error(["render", "x.json", "--paper", "epaper"]) is not None
    assert parse_error(["prompt", "--level", "Z9"]) is not None
    assert parse_error(["draw", "x.json"]) is not None


# ---------------------------------------------------------------------------
# 2. Flags exist
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", DOC_FILES)
def test_documented_flags_exist(name: str):
    doc = load_doc(name)
    known = langwich_flags() | LEGACY_FLAGS
    unknown = sorted(mentioned_flags(doc) - known)
    assert not unknown, (
        f"{name} mentions flags that no langwich command has: {', '.join(unknown)}"
    )


def test_flag_extraction_ignores_other_programs():
    assert _flags_in_code("python scripts/export_schema.py --check") == set()
    assert _flags_in_code("langwich render x.json --page epaper | tee log") == {"--page"}
    assert _flags_in_code("langwich prompt --topic bread > p.txt && ollama run m --verbose") \
        == {"--topic"}
    assert _flags_in_code("  --page {a4,epaper}   page size") == {"--page"}
    assert _flags_in_code("LANGWICH_DEBUG=1 langwich render x.json --seed 3") == {"--seed"}
    assert _flags_in_code("langwich validate x.json   # add --strict") == {"--strict"}
    assert _flags_in_code("pip install -e .   # add --upgrade") == set()


# ---------------------------------------------------------------------------
# 3. Complete JSON worksheets in the docs pass the contract
# ---------------------------------------------------------------------------


def worksheet_problems(doc: Doc) -> list[str]:
    """Contract problems of the complete worksheets in the doc's json blocks."""
    problems = []
    for block in doc.blocks:
        if block.lang != "json" or not _SCHEMA_RE.search(block.text):
            continue  # excerpts: jsonc, or no "schema": "langwich/3"
        try:
            data = json.loads(block.text)
        except json.JSONDecodeError as exc:
            problems.append(f"{doc.name}:{block.line}: not valid JSON ({exc}); fence partial "
                            "excerpts as jsonc")
            continue
        try:
            worksheet_from_dict(data)
        except ContractError as exc:
            problems.append(f"{doc.name}:{block.line}: {exc}")
    return problems


@pytest.mark.parametrize("name", DOC_FILES)
def test_documented_worksheets_pass_the_contract(name: str):
    problems = worksheet_problems(load_doc(name))
    assert not problems, "\n".join(problems)


def test_worksheet_check_skips_excerpts_and_catches_broken_ones():
    excerpt = '{"schema": "langwich/3", "title": …}'
    broken = '{"schema": "langwich/3", "title": "x"}'
    doc = _parse_markdown("x.md", f"```jsonc\n{excerpt}\n```\n```json\n{{\"a\": 1}}\n```\n"
                                  f"```json\n{broken}\n```\n```json\n{excerpt}\n```\n")
    problems = worksheet_problems(doc)
    assert len(problems) == 2
    assert "x.md:8:" in problems[0] and "story" in problems[0]
    assert "not valid JSON" in problems[1]


# ---------------------------------------------------------------------------
# 4. The bundled examples are clean
# ---------------------------------------------------------------------------


def test_there_are_examples():
    assert EXAMPLES, "examples/*.json is empty"


@pytest.mark.parametrize("path", EXAMPLES, ids=lambda p: p.name)
def test_examples_validate_without_errors_or_warnings(path: Path):
    report = check_file(path)
    assert not report.errors, report.format_text()
    assert not report.warnings, report.format_text()


# ---------------------------------------------------------------------------
# 5. The README covers every task kind
# ---------------------------------------------------------------------------


def test_readme_mentions_every_task_kind():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = [k for k in TASK_KINDS if f"`{k}`" not in text]
    assert not missing, f"README.md does not mention these task kinds: {', '.join(missing)}"


# ---------------------------------------------------------------------------
# 6. Paths the docs mention exist
# ---------------------------------------------------------------------------


def _mentioned_paths(doc: Doc) -> set[str]:
    texts = [doc.prose, *doc.inline_code, *(b.text for b in doc.blocks if b.lang != "json")]
    return {m.group(1) for text in texts for m in _PATH_RE.finditer(text)}


@pytest.mark.parametrize("name", DOC_FILES)
def test_documented_paths_exist(name: str):
    doc = load_doc(name)
    missing = sorted(p for p in _mentioned_paths(doc) if not (REPO_ROOT / p).exists())
    assert not missing, f"{name} mentions paths that do not exist: {', '.join(missing)}"


# ---------------------------------------------------------------------------
# 7. The README documents every CLI option
# ---------------------------------------------------------------------------


def _subparsers() -> dict[str, argparse.ArgumentParser]:
    for action in _parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    return {}


def test_readme_documents_every_cli_option():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    missing = []
    for name, sub in _subparsers().items():
        for action in sub._actions:
            longs = [s for s in action.option_strings if s.startswith("--") and s != "--help"]
            if longs and not any(f"`{flag}" in text for flag in longs):
                missing.append(f"langwich {name} {longs[0]}")
    assert not missing, "README.md does not document: " + ", ".join(missing)


def _accepted_range(args: list[str], values: range) -> tuple[int, int]:
    ok = [n for n in values if parse_error([*args, str(n)]) is None]
    assert ok, f"no value in {values} is accepted by langwich {' '.join(args)}"
    return min(ok), max(ok)


def test_documented_scene_range_is_the_accepted_one():
    low, high = _accepted_range(["prompt", "--scenes"], range(0, 20))
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    row = next(line for line in readme.splitlines() if line.startswith("| `--scenes N`"))
    assert f"{low}–{high}" in row, f"README says {row!r}; the CLI accepts {low}–{high}"
    for name in ("CLAUDE.md", ".claude/commands/langwich.md"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8")
        for m in re.finditer(r"--scenes N`?\s*\((\d+)–(\d+)\)", text):
            assert (int(m.group(1)), int(m.group(2))) == (low, high), (name, m.group(0))


# ---------------------------------------------------------------------------
# 8. Stage sequences follow the lesson order
# ---------------------------------------------------------------------------

_STAGE = "|".join(sorted(STAGES, key=len, reverse=True))
#: gist → detail → picture, or a list of three or more stages separated by
#: commas (backticks optional in both)
_ONE = rf"`?\b(?:{_STAGE})\b`?"
_ARROW_RUN = re.compile(rf"{_ONE}(?:\s*(?:→|->)\s*{_ONE})+")
_LIST_RUN = re.compile(rf"{_ONE}(?:,\s*(?:and\s+|or\s+|then\s+)?{_ONE}){{2,}}")
_STAGE_WORD = re.compile(rf"\b({_STAGE})\b")
_ORDER_DOCS = (*DOC_FILES, "docs/assets/logo/README.md")


def stage_sequences(text: str) -> list[list[str]]:
    runs = [m.group(0) for m in _ARROW_RUN.finditer(text)]
    runs += [m.group(0) for m in _LIST_RUN.finditer(text)]
    return [_STAGE_WORD.findall(run) for run in runs]


def out_of_order(text: str) -> list[list[str]]:
    rank = {stage: i for i, stage in enumerate(STAGES)}
    return [seq for seq in stage_sequences(" ".join(text.split()))
            if [rank[s] for s in seq] != sorted(rank[s] for s in seq)]


def test_stage_sequence_extraction():
    assert stage_sequences("`gist` → `detail` → `picture`") == [["gist", "detail", "picture"]]
    assert stage_sequences("(gist → detail → form → practice)") == [
        ["gist", "detail", "form", "practice"]]
    assert stage_sequences("Stages: `warm_up`, `gist`, `detail`, and `form`.") == [
        ["warm_up", "gist", "detail", "form"]]
    assert stage_sequences("a picture of the form") == []
    assert stage_sequences("scene by scene: gist, detail, form, practice, picture →") == [
        ["gist", "detail", "form", "practice", "picture"]]
    assert stage_sequences("the picture, the form") == []
    assert out_of_order("gist → detail → form → practice → picture") == [
        ["gist", "detail", "form", "practice", "picture"]]
    assert out_of_order("`gist`, `detail`, `picture`, `form`, `practice`") == []


@pytest.mark.parametrize("name", _ORDER_DOCS)
def test_stage_sequences_follow_the_lesson_order(name: str):
    text = (REPO_ROOT / name).read_text(encoding="utf-8")
    wrong = out_of_order(text)
    assert not wrong, (f"{name} lists stages out of lesson order ({' → '.join(STAGES)}): "
                       + "; ".join(" → ".join(seq) for seq in wrong))


# ---------------------------------------------------------------------------
# 9. Install instructions use a venv; Ollama recipes raise the context
# ---------------------------------------------------------------------------

_BARE_PIP = re.compile(r"(?:^|[\s;&|])pip3?\s+install\s+(?:-e|--editable)\b")


@pytest.mark.parametrize("name", DOC_FILES)
def test_install_commands_use_a_virtual_environment(name: str):
    # PEP 668: Ubuntu, Debian and Homebrew refuse a bare pip install outside a venv.
    doc = load_doc(name)
    bare = [block.line for block in doc.blocks
            if _BARE_PIP.search(block.text) and "venv" not in block.text]
    # inline: the first install (`pip install -e .`); extras such as ".[heic]" go into a venv
    # that the surrounding text has already set up
    bare += [0 for code in doc.inline_code
             if re.search(r"(?:^|\s)pip3?\s+install\s+-e\s+\.(?:\s|$)", code)
             and "venv" not in code]
    assert not bare, (f"{name}: 'pip install -e' without a virtual environment "
                      f"(code blocks at lines {bare}; line 0 = inline code)")


@pytest.mark.parametrize("name", DOC_FILES)
def test_ollama_recipes_set_a_large_context(name: str):
    # Ollama's default context cuts a worksheet off in the middle.
    doc = load_doc(name)
    short = [block.line for block in doc.blocks
             if re.search(r"\bollama\s+run\b", block.text)
             and "num_ctx" not in block.text and "OLLAMA_CONTEXT_LENGTH" not in block.text]
    context = f"{doc.prose} {' '.join(doc.inline_code)} {' '.join(b.text for b in doc.blocks)}"
    if short and "num_ctx 32768" not in context:
        pytest.fail(f"{name}: 'ollama run' without a 32k context (blocks at lines {short})")


# ---------------------------------------------------------------------------
# 10. Packaging and CI agree with the docs
# ---------------------------------------------------------------------------


@cache
def _pyproject() -> dict:
    return tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def _ci() -> str:
    return (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


def test_license_file_matches_the_metadata():
    license_text = (REPO_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert license_text.lstrip().startswith("Apache License")
    notice_text = (REPO_ROOT / "NOTICE").read_text(encoding="utf-8")
    assert re.search(r"Copyright \d{4} \S", notice_text)
    project = _pyproject()["project"]
    assert project["license"] == "Apache-2.0"
    for pattern in project["license-files"]:
        assert list(REPO_ROOT.glob(pattern)), f"license-files entry matches nothing: {pattern}"
    assert "src/langwich/fonts/OFL-*.txt" in project["license-files"]
    assert "Apache-2.0" in (REPO_ROOT / "README.md").read_text(encoding="utf-8").split("## License")[-1]
    requires = " ".join(_pyproject()["build-system"]["requires"])
    assert re.search(r"setuptools>=(7[7-9]|[89]\d|\d{3})", requires), requires


def test_the_version_has_one_source():
    project = _pyproject()["project"]
    assert "version" not in project and "version" in project.get("dynamic", [])
    attr = _pyproject()["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "langwich.__version__"
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:\.?(?:a|b|rc|dev|post)\d+)?", langwich.__version__)


def test_the_ruff_rule_set_is_pinned():
    # ruff's default rules change between releases; an explicit set keeps CI stable.
    select = _pyproject()["tool"]["ruff"]["lint"]["select"]
    assert select and all(isinstance(rule, str) for rule in select)
    dev = " ".join(_pyproject()["project"]["optional-dependencies"]["dev"])
    assert re.search(r"ruff>=[\d.]+,<[\d.]+", dev), "cap ruff in the dev extra"
    assert re.search(r"mypy>=[\d.]+,<[\d.]+", dev), "cap mypy in the dev extra"


def test_ci_python_versions_match_the_classifiers():
    matrix = re.search(r"python-version:\s*\[([^\]]*)\]", _ci())
    assert matrix, "ci.yml has no python-version matrix"
    tested = set(re.findall(r"\"(3\.\d+)\"", matrix.group(1)))
    classified = {c.rsplit(" :: ", 1)[-1] for c in _pyproject()["project"]["classifiers"]
                  if re.fullmatch(r"Programming Language :: Python :: 3\.\d+", c)}
    assert tested == classified, (tested, classified)
    floor = _pyproject()["project"]["requires-python"].removeprefix(">=")
    assert floor in tested
    assert f"Python {floor}" in (REPO_ROOT / "README.md").read_text(encoding="utf-8")


def _apt_packages(text: str) -> set[str]:
    return {pkg for line in re.findall(r"apt(?:-get)? install ([^`\n]*)", text)
            for pkg in line.split() if not pkg.startswith("-")}


def test_system_libraries_agree_between_ci_and_docs():
    ci = _apt_packages(_ci())
    assert {"libpango-1.0-0", "libpangoft2-1.0-0", "libharfbuzz-subset0"} <= ci
    for name in ("README.md", "CLAUDE.md"):
        documented = _apt_packages((REPO_ROOT / name).read_text(encoding="utf-8"))
        assert documented == ci, f"{name} installs {sorted(documented)}, CI {sorted(ci)}"


def test_ci_requires_the_pdf_tests_and_runs_the_checks():
    ci = _ci()
    assert re.search(r"LANGWICH_REQUIRE_PDF:\s*\"?1\"?", ci)
    for step in ("ruff check src tests scripts", "mypy", "scripts/export_schema.py --check",
                 "pytest", "scripts/build_showcase.py --check"):
        assert step in ci, f"ci.yml does not run {step!r}"


# ---------------------------------------------------------------------------
# 11. build_showcase.py never renders by accident
# ---------------------------------------------------------------------------


def _showcase(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "build_showcase.py"), *args],
                          capture_output=True, text=True, timeout=60, check=False)


def test_build_showcase_help_does_not_render():
    result = _showcase("--help")
    assert result.returncode == 0, result.stderr
    assert "usage:" in result.stdout and "--check" in result.stdout
    assert "written" not in result.stdout and "unchanged" not in result.stdout


def test_build_showcase_rejects_unknown_options():
    result = _showcase("--chek")
    assert result.returncode == 2
    assert "unrecognized arguments" in result.stderr
    assert "written" not in result.stdout and "unchanged" not in result.stdout
