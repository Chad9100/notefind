"""Re-running a command when files in the notes folder change (polling only)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, TextIO

from .scan import walk_files

# path -> (mtime in nanoseconds, size in bytes)
Snapshot = dict[str, tuple[int, int]]

CLEAR_SCREEN = "\x1b[2J\x1b[H"


def snapshot(root: Path) -> Snapshot:
    """Record mtime and size of every visible file under root.

    Uses the same rules as walk_files, so hidden folders such as .git and
    .obsidian don't trigger re-runs. Files that vanish mid-scan are left out.
    """
    root = Path(root)
    found: Snapshot = {}
    for rel in walk_files(root):
        try:
            st = os.stat(root / rel)
        except OSError:
            continue
        found[rel] = (st.st_mtime_ns, st.st_size)
    return found


def changed_files(old: Snapshot, new: Snapshot) -> list[str]:
    """Paths added, removed or modified between two snapshots, sorted."""
    return sorted(
        rel for rel in old.keys() | new.keys() if old.get(rel) != new.get(rel)
    )


def describe(changed: list[str], limit: int = 3) -> str:
    """Short human summary such as "2 files changed: a.md, b.md"."""
    noun = "file" if len(changed) == 1 else "files"
    names = ", ".join(changed[:limit])
    more = f" and {len(changed) - limit} more" if len(changed) > limit else ""
    return f"{len(changed)} {noun} changed: {names}{more}"


def watch(
    root: Path,
    run: Callable[[], int],
    interval: float = 1.0,
    *,
    clear: bool = False,
    out: TextIO,
    err: TextIO,
    sleep: Callable[[float], None] | None = None,
) -> int:
    """Run `run` now and again after every change under root, until Ctrl-C.

    The folder is snapshotted after each run, so files the command writes
    itself (links --fix) don't cause another run. Returns the exit code of
    the last run when interrupted.
    """
    if interval <= 0:
        raise ValueError("interval must be positive")
    if sleep is None:
        sleep = time.sleep
    code = 0
    try:
        if clear:
            out.write(CLEAR_SCREEN)
            out.flush()
        code = run()
        before = snapshot(root)
        while True:
            sleep(interval)
            now = snapshot(root)
            changed = changed_files(before, now)
            if not changed:
                continue
            if clear:
                out.write(CLEAR_SCREEN)
                out.flush()
            print(f"notefind: {describe(changed)}; running again", file=err)
            err.flush()
            code = run()
            before = snapshot(root)
    except KeyboardInterrupt:
        print("notefind: stopped watching", file=err)
    return code
