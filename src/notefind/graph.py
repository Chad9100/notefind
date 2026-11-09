"""Which notes link to which: backlinks and orphan notes."""

from __future__ import annotations

import posixpath
from collections import defaultdict
from dataclasses import dataclass
from urllib.parse import unquote

from .linkcheck import is_checkable
from .parse import extract_links
from .scan import NOTE_SUFFIXES, Note


@dataclass(frozen=True)
class Edge:
    source: str  # relative path of the linking note
    line: int
    target: str  # relative path of the note linked to
    written: str  # the link target as written, e.g. "Garden Plan#Beds"
    kind: str  # "wiki" or "markdown"


def strip_note_suffix(path: str) -> str:
    low = path.lower()
    for suffix in NOTE_SUFFIXES:
        if low.endswith(suffix):
            return path[: -len(suffix)]
    return path


class NoteResolver:
    """Map link targets and user input to notes, case-insensitively."""

    def __init__(self, notes: list[Note]):
        self.by_stem: dict[str, list[str]] = defaultdict(list)
        self.by_path: dict[str, str] = {}
        for note in notes:
            low = note.rel.lower()
            self.by_stem[strip_note_suffix(low.rsplit("/", 1)[-1])].append(note.rel)
            self.by_path[low] = note.rel
            self.by_path[strip_note_suffix(low)] = note.rel

    def by_name(self, name: str) -> list[str]:
        """Notes a wiki-style name refers to: "Note", "Note.md" or "folder/Note".

        A bare name can match several notes in different folders; all of them
        are returned, sorted, and callers decide what that means.
        """
        key = name.split("#", 1)[0].strip().replace("\\", "/").strip("/").lower()
        if not key:
            return []
        if key in self.by_path:
            return [self.by_path[key]]
        if "/" in key:
            bare = strip_note_suffix(key)
            return sorted({rel for low, rel in self.by_path.items()
                           if strip_note_suffix(low).endswith("/" + bare)})
        return sorted(self.by_stem.get(strip_note_suffix(key), []))

    def by_relative_path(self, source_rel: str, target: str) -> list[str]:
        """The note a relative Markdown link from source_rel points to, if any."""
        path = unquote(target.split("#", 1)[0].split("?", 1)[0])
        if path.startswith("/"):
            joined = path.lstrip("/")
        else:
            joined = posixpath.join(posixpath.dirname(source_rel), path)
        norm = posixpath.normpath(joined)
        if norm.startswith("../") or norm == "..":
            return []  # points outside the notes folder
        rel = self.by_path.get(norm.lower())
        return [rel] if rel else []


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
