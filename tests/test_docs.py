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
   ``src/langwich/…``, ``scripts/…``, ``tests/…``) exists.

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
from dataclasses import dataclass, field
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

import pytest

from langwich.cli import SUBCOMMANDS, build_parser
from langwich.model import TASK_KINDS, ContractError, worksheet_from_dict
from langwich.validate import check_file

REPO_ROOT = Path(__file__).resolve().parent.parent

DOC_FILES: tuple[str, ...] = (
    "README.md",
    "CLAUDE.md",
    ".claude/commands/langwich.md",
    "docs/index.html",
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
