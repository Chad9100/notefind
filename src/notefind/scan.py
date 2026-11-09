"""Walking a notes folder and reading notes from disk."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

NOTE_SUFFIXES = (".md", ".markdown")
SKIP_DIRS = frozenset({"node_modules"})


@dataclass
class Note:
    """A Markdown note: its path relative to the root (always with "/") and its text."""

    rel: str
    path: Path
    text: str
    _lines: list[str] | None = field(default=None, repr=False, compare=False)

    @property
    def lines(self) -> list[str]:
        if self._lines is None:
            self._lines = self.text.split("\n")
        return self._lines


def is_note(name: str) -> bool:
    return name.lower().endswith(NOTE_SUFFIXES)


def walk_files(root: Path) -> list[str]:
    """Return every visible file under root as a sorted list of "/"-separated paths.

    Hidden directories (.git, .obsidian, ...) and node_modules are skipped,
    as are hidden files.
    """
    root = Path(root)
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames if not d.startswith(".") and d not in SKIP_DIRS
        )
        rel_dir = Path(dirpath).relative_to(root)
        for name in filenames:
            if name.startswith("."):
                continue
            found.append((rel_dir / name).as_posix())
    return sorted(found)


def read_text(path: Path) -> str:
    """Read a file as UTF-8, dropping a BOM, replacing bad bytes, normalising newlines."""
    with open(path, encoding="utf-8-sig", errors="replace", newline=None) as fh:
        return fh.read()


def load_notes(root: Path, files: list[str] | None = None) -> list[Note]:
    """Load every Markdown note under root, sorted by relative path."""
    root = Path(root)
    if files is None:
        files = walk_files(root)
    notes = []
    for rel in files:
        if not is_note(rel):
            continue
        path = root / rel
        try:
            text = read_text(path)
        except OSError:
            continue
        notes.append(Note(rel=rel, path=path, text=text))
    return notes
