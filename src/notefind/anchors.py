"""Headings and block IDs inside a note, for checking `#Heading` and `#^block` links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import unquote

from .parse import split_front_matter, strip_code

# "## Heading text ##": 1-6 "#", a space, the text, an optional closing run.
ATX_RE = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$")
# Setext underlines ("Heading\n=====" or "Heading\n-----").
SETEXT_RE = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
# A line that cannot be the text of a setext heading: lists, quotes, tables...
NOT_PARAGRAPH_RE = re.compile(r"^\s*(?:[-*+>|#]|\d+[.)]\s|$)")
# An Obsidian block ID: "^id" at the end of a line, after a space (or alone).
BLOCK_RE = re.compile(r"(?:^|\s)\^([A-Za-z0-9-]+)[ \t]*$")
# HTML anchors that Markdown renderers link to: <a id="x"> / <a name="x">.
HTML_ANCHOR_RE = re.compile(r"<a\s[^>]*?\b(?:id|name)\s*=\s*[\"']([^\"']+)[\"']", re.IGNORECASE)
# Inline Markdown that renders as plain text inside a heading.
WIKI_IN_HEADING_RE = re.compile(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]")
MD_LINK_IN_HEADING_RE = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")


@dataclass(frozen=True)
class Anchors:
    """Everything in one note that a `#fragment` can point to."""

    headings: frozenset[str]  # loose keys, see loose_key()
    slugs: frozenset[str]  # GitHub-style slugs, with -1, -2 for repeats
    blocks: frozenset[str]  # block IDs, casefolded
    html_ids: frozenset[str]  # id/name of <a> tags, as written


def loose_key(text: str) -> str:
    """Compare headings ignoring case, punctuation and spacing.

    "Tasks: urgent!", "tasks urgent" and "tasks-urgent" all give "tasks urgent",
    so Obsidian links (which drop characters like ":" from heading links) and
    GitHub-style slugs both match.
    """
    return " ".join(re.sub(r"[\W_]+", " ", text.casefold()).split())


def heading_text(raw: str) -> str:
    """The visible text of a heading: links reduced to their labels."""
    text = WIKI_IN_HEADING_RE.sub(lambda m: m.group(1), raw)
    text = MD_LINK_IN_HEADING_RE.sub(lambda m: m.group(1), text)
    return text.strip()


def github_slug(text: str) -> str:
    """The anchor GitHub generates for a heading (before de-duplication)."""
    text = re.sub(r"[^\w\- ]", "", text.strip().lower())
    return text.replace(" ", "-")


def headings(text: str) -> list[str]:
    """Heading texts of a note in order, ignoring front matter and code blocks."""
    lines = text.split("\n")
    _, body_start = split_front_matter(lines)
    body = strip_code(lines[body_start:])
    found: list[str] = []
    prev = ""
    for line in body:
        atx = ATX_RE.match(line)
        if atx:
            if atx.group(2):
                found.append(heading_text(atx.group(2)))
            prev = ""
            continue
        if SETEXT_RE.match(line) and prev and not NOT_PARAGRAPH_RE.match(prev):
            found.append(heading_text(prev))
            prev = ""
            continue
        prev = line
    return found


def collect_anchors(text: str) -> Anchors:
    names = headings(text)
    slugs: set[str] = set()
    seen: dict[str, int] = {}
    for name in names:
        slug = github_slug(name)
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(slug if count == 0 else f"{slug}-{count}")
    body = strip_code(text.split("\n"))
    blocks = {m.group(1).casefold() for line in body if (m := BLOCK_RE.search(line))}
    html_ids = {m.group(1) for line in body for m in HTML_ANCHOR_RE.finditer(line)}
    return Anchors(
        headings=frozenset(loose_key(n) for n in names),
        slugs=frozenset(slugs),
        blocks=frozenset(blocks),
        html_ids=frozenset(html_ids),
    )


def missing_wiki_anchor(anchors: Anchors, fragment: str) -> str | None:
    """Why `[[Note#fragment]]` does not resolve inside the note, or None if it does.

    `#^id` is a block reference; `#A#B` is a heading path and every part of
    it must be a heading in the note.
    """
    fragment = fragment.strip()
    if fragment.startswith("^"):
        block = fragment[1:].strip()
        if block and block.casefold() not in anchors.blocks:
            return f'no block "^{block}"'
        return None
    for part in fragment.split("#"):
        key = loose_key(part)
        if key and key not in anchors.headings:
            return f'no heading "{part.strip()}"'
    return None


def missing_markdown_anchor(anchors: Anchors, fragment: str) -> str | None:
    """Why `[text](note.md#fragment)` does not resolve, or None if it does.

    Accepts GitHub-style slugs (`#my-heading`, `#notes-1` for a repeated
    heading), Obsidian-style text (`#My%20Heading`), `<a id>` anchors and
    `#^block` references.
    """
    fragment = unquote(fragment).strip()
    if not fragment:
        return None
    if fragment.startswith("^"):
        return missing_wiki_anchor(anchors, fragment)
    if (
        fragment in anchors.html_ids
        or fragment.lower() in anchors.slugs
        or loose_key(fragment) in anchors.headings
    ):
        return None
    return f'no heading "{fragment}"'
