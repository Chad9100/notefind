"""Resolving wiki links and relative Markdown links against a notes folder."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from .parse import Link, extract_links
from .scan import Note, is_note

# "http:", "mailto:", "obsidian:" ... anything with a URL scheme is external.
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


@dataclass(frozen=True)
class BrokenLink:
    path: str
    line: int
    target: str
    kind: str


class LinkIndex:
    """Case-insensitive lookup of notes (by stem) and files (by name or path)."""

    def __init__(self, files: list[str]):
        self.stems: set[str] = set()
        self.names: set[str] = set()
        self.paths: set[str] = set()
        for rel in files:
            low = rel.lower()
            name = low.rsplit("/", 1)[-1]
            self.names.add(name)
            self.paths.add(low)
            if is_note(name):
                stem = name.rsplit(".", 1)[0]
                self.stems.add(stem)
                self.paths.add(low.rsplit(".", 1)[0])

    def has_wiki_target(self, target: str) -> bool:
        name = target.split("#", 1)[0].strip().replace("\\", "/").strip("/").lower()
        if not name:
            return True  # [[#Heading]] points into the same note
        if "/" in name:
            return any(p == name or p.endswith("/" + name) for p in self.paths)
        return name in self.stems or name in self.names


def is_checkable(link: Link) -> bool:
    """False for links we deliberately skip: external URLs and pure #anchors."""
    if link.kind == "wiki":
        return bool(link.target.split("#", 1)[0].strip())
    target = link.target
    if not target or target.startswith("#") or SCHEME_RE.match(target):
        return False
    return bool(target.split("#", 1)[0].split("?", 1)[0])


def markdown_target_exists(root: Path, note_rel: str, target: str) -> bool:
    path = unquote(target.split("#", 1)[0].split("?", 1)[0])
    if path.startswith("/"):
        base = Path(root)
    else:
        base = (Path(root) / note_rel).parent
    return (base / path.lstrip("/")).exists()


def find_broken_links(
    root: Path, notes: list[Note], files: list[str]
) -> tuple[list[BrokenLink], int]:
    """Return (broken links, number of links checked)."""
    index = LinkIndex(files)
    broken: list[BrokenLink] = []
    checked = 0
    for note in notes:
        for link in extract_links(note.text):
            if not is_checkable(link):
                continue
            checked += 1
            if link.kind == "wiki":
                ok = index.has_wiki_target(link.target)
            else:
                ok = markdown_target_exists(root, note.rel, link.target)
            if not ok:
                broken.append(BrokenLink(note.rel, link.line, link.target, link.kind))
    return broken, checked
