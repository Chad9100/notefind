"""Parsing helpers: code stripping, front matter, tags and links."""

from __future__ import annotations

import re
from dataclasses import dataclass

# An opening/closing code fence: up to 3 spaces, then ``` or ~~~ (3 or more).
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")
# Inline code: a run of backticks, content, and the same-length run again.
INLINE_CODE_RE = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")

TAG_KEY_RE = re.compile(r"^(tags?)\s*:\s*(.*?)\s*$", re.IGNORECASE)
LIST_ITEM_RE = re.compile(r"^\s*-\s*(.*?)\s*$")
# "#tag" not preceded by a word char, "#", "/", "&" or "\" (so URLs,
# anchors, HTML entities and "##" heading markers are not tags).
TAG_RE = re.compile(r"(?<![\w#/&\\])#(\w[\w/-]*)")
URL_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://\S+|www\.\S+")
WIKI_RE = re.compile(r"!?\[\[([^\[\]\n]+?)\]\]")
MD_LINK_RE = re.compile(
    r"\[[^\[\]\n]*\]\(\s*(<[^>\n]*>|[^()\s]*(?:\([^()\s]*\)[^()\s]*)*)"
    r"(?:\s+(?:\"[^\"\n]*\"|'[^'\n]*'))?\s*\)"
)


@dataclass(frozen=True)
class Link:
    line: int
    target: str
    kind: str  # "wiki" or "markdown"


def _blank(match: re.Match[str]) -> str:
    return " " * len(match.group(0))


def strip_code(lines: list[str]) -> list[str]:
    """Blank out fenced code blocks and inline code, keeping line numbers and columns."""
    out: list[str] = []
    fence: tuple[str, int] | None = None
    for line in lines:
        m = FENCE_RE.match(line)
        if fence is None:
            # A backtick fence's info string may not itself contain backticks.
            if m and not (m.group(1)[0] == "`" and "`" in m.group(2)):
                fence = (m.group(1)[0], len(m.group(1)))
                out.append("")
                continue
            out.append(INLINE_CODE_RE.sub(_blank, line))
        else:
            if (
                m
                and m.group(1)[0] == fence[0]
                and len(m.group(1)) >= fence[1]
                and not m.group(2).strip()
            ):
                fence = None
            out.append("")
    return out


def split_front_matter(lines: list[str]) -> tuple[list[str], int]:
    """Return (front matter lines, index of the first body line)."""
    if not lines or lines[0].strip() != "---":
        return [], 0
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            return lines[1:i], i + 1
    return [], 0


def clean_tag(raw: str) -> str:
    """Normalise a tag: drop quotes, a leading '#', stray separators; lowercase it."""
    tag = raw.strip().strip("\"'").strip().lstrip("#").strip("/-")
    return tag.lower()


def front_matter_tags(fm_lines: list[str]) -> list[str]:
    """Tags from `tags: [a, b]`, `tags: a, b` or a `tags:` block of `- a` lines."""
    tags: list[str] = []
    i = 0
    while i < len(fm_lines):
        m = TAG_KEY_RE.match(fm_lines[i])
        i += 1
        if not m:
            continue
        value = m.group(2)
        if value:
            if value.startswith("["):
                value = value.strip("[]")
            items = re.split(r"[,\s]+", value)
        else:
            items = []
            while i < len(fm_lines):
                line = fm_lines[i]
                item = LIST_ITEM_RE.match(line)
                if item:
                    items.append(item.group(1))
                elif line.strip():
                    break
                i += 1
        for item in items:
            tag = clean_tag(item)
            if tag:
                tags.append(tag)
    return tags


def inline_tags(lines: list[str]) -> list[str]:
    """Inline #tags in already code-stripped body lines."""
    tags: list[str] = []
    for line in lines:
        if "#" not in line:
            continue
        line = URL_RE.sub(_blank, line)
        line = WIKI_RE.sub(_blank, line)
        line = MD_LINK_RE.sub(_blank, line)
        for m in TAG_RE.finditer(line):
            tag = m.group(1).rstrip("/-")
            # Pure numbers ("#1", "#2024-05") are issue refs or dates, not tags.
            if tag and not tag.replace("/", "").replace("-", "").isdigit():
                tags.append(tag.lower())
    return tags


def extract_tags(text: str) -> set[str]:
    """All tags of a note: front matter tags plus inline #tags outside code."""
    lines = text.split("\n")
    fm, body_start = split_front_matter(lines)
    tags = set(front_matter_tags(fm))
    tags.update(inline_tags(strip_code(lines[body_start:])))
    return tags


def extract_links(text: str) -> list[Link]:
    """Wiki links and Markdown links outside code, with 1-based line numbers."""
    links: list[Link] = []
    for no, line in enumerate(strip_code(text.split("\n")), start=1):
        if "[" not in line:
            continue
        for m in WIKI_RE.finditer(line):
            # "[[Note\|alias]]" is how aliases are escaped inside tables.
            target = m.group(1).split("|", 1)[0].rstrip("\\").strip()
            links.append(Link(no, target, "wiki"))
        rest = WIKI_RE.sub(_blank, line)
        for m in MD_LINK_RE.finditer(rest):
            target = m.group(1).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1].strip()
            links.append(Link(no, target, "markdown"))
    return links
