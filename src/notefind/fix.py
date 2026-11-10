"""Rewriting broken links in place with their unambiguous suggestions (`links --fix`)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from pathlib import Path

from .linkcheck import BrokenLink
from .parse import MD_LINK_RE, REF_DEF_RE, WIKI_RE, _blank, _unbracket, strip_code

BOM = "﻿"
NEWLINE_RE = re.compile(r"(\r\n|\r|\n)")


@dataclass(frozen=True)
class Fix:
    path: str
    line: int  # the line actually rewritten (a reference definition's own line)
    kind: str
    old: str
    new: str


def _wiki_span(line: str, target: str) -> tuple[int, int] | None:
    """Columns of the target part of the first `[[target|alias]]` in line."""
    for m in WIKI_RE.finditer(line):
        inner = m.group(1).split("|", 1)[0]
        if inner.rstrip("\\").strip() == target:
            start = m.start(1) + inner.index(target)
            return start, start + len(target)
    return None


def _markdown_span(line: str, target: str) -> tuple[int, int] | None:
    """Columns of target inside the first inline `[text](target)` in line."""
    rest = WIKI_RE.sub(_blank, line)
    for m in MD_LINK_RE.finditer(rest):
        if _unbracket(m.group(1)) == target:
            start = m.start(1) + m.group(1).index(target)
            return start, start + len(target)
    return None


def _definition_span(line: str, target: str) -> tuple[int, int] | None:
    """Columns of target in a `[ref]: target` definition line."""
    m = REF_DEF_RE.match(line)
    if m and _unbracket(m.group(2)) == target:
        start = m.start(2) + m.group(2).index(target)
        return start, start + len(target)
    return None


def _decode(raw: bytes) -> str | None:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None  # rewriting would destroy the bytes we can't read


def fix_note(
    path: Path, rel: str, broken: list[BrokenLink], write: bool,
    diffs: list[str] | None = None, new_rel: str | None = None,
) -> list[Fix]:
    """Apply the unambiguous suggestions of one note's broken links.

    Only the link target changes: aliases, titles, `<...>` brackets, the
    note's line endings and a UTF-8 BOM are kept. Links are looked up in the
    code-stripped line, so a lookalike inside `code` is never touched. A
    reference-style link is fixed in its `[ref]: target` definition. Files
    that aren't valid UTF-8 are skipped. With write=False nothing is saved.
    """
    text = _decode(path.read_bytes())
    if text is None:
        return []
    bom = text.startswith(BOM)
    if bom:
        text = text[1:]
    original = text
    parts = NEWLINE_RE.split(text)
    lines, seps = parts[0::2], parts[1::2]
    fixes: list[Fix] = []
    for b in broken:
        if not (b.unambiguous and b.suggestion):
            continue
        stripped = strip_code(lines)
        i = b.line - 1
        find = _wiki_span if b.kind == "wiki" else _markdown_span
        span = find(stripped[i], b.target) if 0 <= i < len(lines) else None
        if span is None and b.kind == "markdown":
            for j, candidate in enumerate(stripped):
                span = _definition_span(candidate, b.target)
                if span:
                    i = j
                    break
        if span is None:
            continue  # e.g. a definition shared by two uses, already fixed
        start, end = span
        lines[i] = lines[i][:start] + b.suggestion + lines[i][end:]
        fixes.append(Fix(rel, i + 1, b.kind, b.target, b.suggestion))
    out = "".join(line + sep for line, sep in zip(lines, seps + [""]))
    if fixes and diffs is not None:
        diffs.extend(difflib.unified_diff(
            original.splitlines(keepends=True), out.splitlines(keepends=True),
            fromfile=f"a/{rel}", tofile=f"b/{new_rel or rel}",
        ))
    if fixes and write:
        path.write_bytes(((BOM if bom else "") + out).encode("utf-8"))
    return fixes


def fix_links(root: Path, broken: list[BrokenLink], write: bool = True) -> list[Fix]:
    """Fix every broken link that has an unambiguous suggestion, note by note."""
    by_note: dict[str, list[BrokenLink]] = {}
    for b in broken:
        by_note.setdefault(b.path, []).append(b)
    fixes: list[Fix] = []
    for rel, items in by_note.items():
        if any(b.unambiguous for b in items):
            fixes.extend(fix_note(Path(root) / rel, rel, items, write))
    return fixes
