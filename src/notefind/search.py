"""Query parsing, matching, ranking and snippet highlighting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .parse import clean_tag, extract_tags, split_front_matter
from .scan import Note

TOKEN_RE = re.compile(r'(-?)(?:"([^"]*)"?|(\S+))')
HIGHLIGHT_ON = "\x1b[1;31m"
HIGHLIGHT_OFF = "\x1b[0m"
SNIPPET_WIDTH = 100


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)

    @property
    def positive(self) -> list[str]:
        return self.terms + self.phrases

    def is_empty(self) -> bool:
        return not (self.terms or self.phrases or self.tags)


@dataclass
class Hit:
    path: str
    line: int
    matches: int
    snippet: str


def _add(query: Query, text: str, negative: bool, quoted: bool) -> None:
    text = " ".join(text.split())
    if not text or text == "-":
        return
    if not quoted and text.lower().startswith("tag:"):
        name = clean_tag(text[4:])
        if name:
            (query.exclude_tags if negative else query.tags).append(name)
        return
    if negative:
        query.excludes.append(text)
    elif quoted or " " in text:
        query.phrases.append(text)
    else:
        query.terms.append(text)


def parse_query(parts: str | Sequence[str]) -> Query:
    """Parse search terms.

    - plain words are ANDed;
    - "quoted text" (or a single shell argument containing spaces) is a phrase;
    - -word / -"some phrase" excludes notes containing it;
    - tag:name keeps only notes with that tag, -tag:name drops them.
    """
    if isinstance(parts, str):
        parts = [parts]
    query = Query()
    for part in parts:
        s = part.strip()
        if not s:
            continue
        if '"' not in s and re.search(r"\s", s):
            # The shell already removed the quotes: treat the argument as a phrase.
            negative = s.startswith("-")
            _add(query, s[1:] if negative else s, negative, quoted=True)
            continue
        for m in TOKEN_RE.finditer(s):
            quoted = m.group(2) is not None
            _add(query, m.group(2) if quoted else m.group(3), m.group(1) == "-", quoted)
    return query


def compile_pattern(text: str) -> re.Pattern[str]:
    """Case-insensitive pattern; whitespace inside a phrase matches any whitespace."""
    return re.compile(r"\s+".join(re.escape(w) for w in text.split()), re.IGNORECASE)


def _has_tag(tags: set[str], wanted: str) -> bool:
    # tag:project also matches nested tags such as project/alpha.
    return wanted in tags or any(t.startswith(wanted + "/") for t in tags)


def make_snippet(line: str, patterns: list[re.Pattern[str]], width: int = SNIPPET_WIDTH) -> str:
    """The stripped line, cut to `width` characters around the first match."""
    s = line.strip()
    if len(s) <= width:
        return s
    starts = [m.start() for p in patterns if (m := p.search(s))]
    first = min(starts, default=0)
    start = max(0, min(first - 30, len(s) - width))
    end = start + width
    out = s[start:end]
    if start > 0:
        out = "..." + out
    if end < len(s):
        out += "..."
    return out


def highlight(text: str, patterns: list[re.Pattern[str]], color: bool) -> str:
    """Wrap every match in ANSI bold red when color is on."""
    if not color or not patterns:
        return text
    spans = sorted((m.start(), m.end()) for p in patterns for m in p.finditer(text) if m.end() > m.start())
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, pos = [], 0
    for start, end in merged:
        out.append(text[pos:start])
        out.append(HIGHLIGHT_ON + text[start:end] + HIGHLIGHT_OFF)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _first_body_line(note: Note) -> int:
    _, body_start = split_front_matter(note.lines)
    for i in range(body_start, len(note.lines)):
        if note.lines[i].strip():
            return i + 1
    return 1


def search(notes: list[Note], query: Query) -> list[Hit]:
    """Return matching notes, most matches first, ties broken by path."""
    positive = [compile_pattern(s) for s in query.positive]
    negative = [compile_pattern(s) for s in query.excludes]
    hits: list[Hit] = []
    for note in notes:
        text = note.text
        if any(p.search(text) for p in negative):
            continue
        if query.tags or query.exclude_tags:
            tags = extract_tags(text)
            if not all(_has_tag(tags, t) for t in query.tags):
                continue
            if any(_has_tag(tags, t) for t in query.exclude_tags):
                continue
        total = 0
        first: int | None = None
        for pattern in positive:
            found = [m.start() for m in pattern.finditer(text)]
            if not found:
                break
            total += len(found)
            first = found[0] if first is None else min(first, found[0])
        else:
            if first is None:
                line = _first_body_line(note)
            else:
                line = text.count("\n", 0, first) + 1
            snippet = make_snippet(note.lines[line - 1], positive)
            hits.append(Hit(note.rel, line, total, snippet))
    hits.sort(key=lambda h: (-h.matches, h.path))
    return hits
