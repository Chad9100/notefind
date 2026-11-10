"""Walking a notes folder and reading notes from disk."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

NOTE_SUFFIXES = (".md", ".markdown")
SKIP_DIRS = frozenset({"node_modules"})

# Below this many notes a thread pool costs more than it saves.
PARALLEL_THRESHOLD = 64
MAX_AUTO_JOBS = 8


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


def default_jobs() -> int:
    """Worker count used when none is given: the CPU count, capped at MAX_AUTO_JOBS."""
    return max(1, min(MAX_AUTO_JOBS, os.cpu_count() or 1))


def _read_note(root: Path, rel: str) -> Note | None:
    path = root / rel
    try:
        text = read_text(path)
    except OSError:
        return None
    return Note(rel=rel, path=path, text=text)


def load_notes(
    root: Path, files: list[str] | None = None, jobs: int | None = None
) -> list[Note]:
    """Load every Markdown note under root, sorted by relative path.

    jobs is the number of reader threads. None picks one automatically:
    sequential for small folders, default_jobs() threads from
    PARALLEL_THRESHOLD notes up. 1 always reads sequentially. The result
    is the same in every case; unreadable files are skipped.
    """
    root = Path(root)
    if files is None:
        files = walk_files(root)
    rels = [rel for rel in files if is_note(rel)]
    if jobs is None:
        jobs = default_jobs() if len(rels) >= PARALLEL_THRESHOLD else 1
    if jobs < 1:
        raise ValueError("jobs must be at least 1")
    jobs = min(jobs, len(rels)) or 1
    if jobs == 1:
        loaded = [_read_note(root, rel) for rel in rels]
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            loaded = list(pool.map(lambda rel: _read_note(root, rel), rels))
    return [note for note in loaded if note is not None]
