"""Walking a notes folder and reading notes from disk."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .ignore import is_ignored, load_rules

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


def walk_files(root: Path, use_ignore: bool = True) -> list[str]:
    """Return every visible file under root as a sorted list of "/"-separated paths.

    Hidden directories (.git, .obsidian, ...) and node_modules are skipped,
    as are hidden files. With use_ignore, files and folders matching a
    pattern in root/.notefindignore are skipped too.
    """
    root = Path(root)
    rules = load_rules(root) if use_ignore else []
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)

        def keep(name: str, is_dir: bool) -> bool:
            if name.startswith(".") or (is_dir and name in SKIP_DIRS):
                return False
            return not (rules and is_ignored(rules, (rel_dir / name).as_posix(), is_dir))

        dirnames[:] = sorted(d for d in dirnames if keep(d, True))
        found.extend((rel_dir / name).as_posix() for name in filenames if keep(name, False))
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
    root: Path,
    files: list[str] | None = None,
    jobs: int | None = None,
    use_ignore: bool = True,
) -> list[Note]:
    """Load every Markdown note under root, sorted by relative path.

    jobs is the number of reader threads. None picks one automatically:
    sequential for small folders, default_jobs() threads from
    PARALLEL_THRESHOLD notes up. 1 always reads sequentially. The result
    is the same in every case; unreadable files are skipped.
    """
    root = Path(root)
    if files is None:
        files = walk_files(root, use_ignore)
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
