"""Gap markup used in cloze and dialogue texts.

A gap is written ``{{answer}}``. Accepted alternatives follow a ``|``,
a hint (base form, translation, …) follows ``::``::

    Die Bohnen {{werden}} in Wien {{geröstet::rösten}}.
    Sie trinkt ihren Kaffee {{schwarz|ohne Milch}}.

The first answer is the one printed in the answer key and used in word
banks; alternatives are also accepted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

GAP_RE = re.compile(r"\{\{(.+?)\}\}", re.DOTALL)


@dataclass(frozen=True)
class Gap:
    answer: str
    alternatives: tuple[str, ...] = field(default_factory=tuple)
    hint: str | None = None

    @property
    def accepted(self) -> tuple[str, ...]:
        return (self.answer, *self.alternatives)


def parse_gap(body: str) -> Gap:
    hint: str | None = None
    if "::" in body:
        body, hint = body.split("::", 1)
        hint = hint.strip() or None
    answers = [a.strip() for a in body.split("|") if a.strip()]
    if not answers:
        raise ValueError("empty gap {{}}")
    return Gap(answers[0], tuple(answers[1:]), hint)


def split(text: str) -> list[str | Gap]:
    """Split text into literal strings and :class:`Gap` objects, in order."""
    out: list[str | Gap] = []
    pos = 0
    for m in GAP_RE.finditer(text):
        if m.start() > pos:
            out.append(text[pos:m.start()])
        out.append(parse_gap(m.group(1)))
        pos = m.end()
    if pos < len(text):
        out.append(text[pos:])
    return out


def gaps(text: str) -> list[Gap]:
    return [p for p in split(text) if isinstance(p, Gap)]


def fill(text: str) -> str:
    """The text with every gap replaced by its first answer."""
    return "".join(p.answer if isinstance(p, Gap) else p for p in split(text))


def has_unbalanced_braces(text: str) -> bool:
    stripped = GAP_RE.sub("", text)
    return "{{" in stripped or "}}" in stripped
