"""Which notes link to which: backlinks and orphan notes."""

from __future__ import annotations

from dataclasses import dataclass

from .linkcheck import is_checkable
from .parse import extract_links
from .resolve import NoteResolver, strip_note_suffix  # noqa: F401 (re-exported)
from .scan import Note


@dataclass(frozen=True)
class Edge:
    source: str  # relative path of the linking note
    line: int
    target: str  # relative path of the note linked to
    written: str  # the link target as written, e.g. "Garden Plan#Beds"
    kind: str  # "wiki" or "markdown"


def link_edges(notes: list[Note]) -> list[Edge]:
    """Every resolvable link between notes, in note and line order."""
    resolver = NoteResolver(notes)
    edges: list[Edge] = []
    for note in notes:
        for link in extract_links(note.text):
            if not is_checkable(link):
                continue
            if link.kind == "wiki":
                targets = resolver.by_name(link.target)
            else:
                targets = resolver.by_relative_path(note.rel, link.target)
            for target in targets:
                edges.append(Edge(note.rel, link.line, target, link.target, link.kind))
    return edges


def backlinks(edges: list[Edge], target: str) -> list[Edge]:
    """Links into `target` from other notes (a note linking to itself is skipped)."""
    return [e for e in edges if e.target == target and e.source != target]


def orphans(notes: list[Note], edges: list[Edge]) -> list[str]:
    """Notes no other note links to, sorted by path."""
    linked = {e.target for e in edges if e.source != e.target}
    return [n.rel for n in notes if n.rel not in linked]
