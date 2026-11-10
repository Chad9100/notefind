"""Renaming a note and rewriting every link that points to it (`rename`)."""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

from .fix import Fix, fix_note
from .graph import link_edges
from .linkcheck import BrokenLink
from .resolve import NoteResolver, strip_note_suffix
from .scan import Note


class RenameError(Exception):
    """The rename can't be done; the message says why."""


@dataclass(frozen=True)
class Skipped:
    """A link that points at the note only by a name other notes share."""

    path: str
    line: int
    link: str


@dataclass
class RenamePlan:
    old: str
    new: str
    # Per note (by its path before the rename): the links to rewrite.
    changes: dict[str, list[BrokenLink]]
    skipped: list[Skipped]


def new_filename(old_rel: str, name: str) -> str:
    """The file name for `rename OLD NAME`: a bare name keeps OLD's extension."""
    name = name.strip()
    if "/" in name or "\\" in name:
        raise RenameError("the new name can't contain a folder; renaming keeps the note "
                          "in its folder")
    stem = strip_note_suffix(name)
    if not stem.strip() or stem.startswith("."):
        raise RenameError(f"not a usable note name: {name!r}")
    if stem != name:
        return name
    return name + old_rel[len(strip_note_suffix(old_rel)):]


def _wiki_target(written: str, new_rel: str, shared_stem: bool) -> str:
    """A wiki link target for the renamed note, in the style of the old one."""
    name, sep, fragment = written.partition("#")
    name = name.strip().replace("\\", "/")
    keep_suffix = strip_note_suffix(name) != name
    new_path = new_rel if keep_suffix else strip_note_suffix(new_rel)
    depth = name.strip("/").count("/") + 1
    if "/" not in name.strip("/") and shared_stem:
        depth = new_path.count("/") + 1  # a bare name would now be ambiguous
    parts = new_path.split("/")
    target = "/".join(parts[-depth:])
    return target + sep + fragment


def _markdown_target(written: str, new_rel: str) -> str:
    """A relative-path link target for the renamed note, keeping `#...`, `?...`."""
    m = re.search(r"[#?]", written)
    path, rest = (written[: m.start()], written[m.start():]) if m else (written, "")
    folder, _, base = path.rpartition("/")
    new_base = new_rel.rsplit("/", 1)[-1]
    if strip_note_suffix(base) == base:
        new_base = strip_note_suffix(new_base)
    if "%" in base:
        new_base = quote(new_base)
    return (folder + "/" if "/" in path else "") + new_base + rest


def plan_rename(
    root: Path, notes: list[Note], files: list[str], old_rel: str, name: str
) -> RenamePlan:
    """Work out the new path and every link rewrite, without touching any file."""
    new_rel = posixpath.join(posixpath.dirname(old_rel), new_filename(old_rel, name))
    if new_rel == old_rel:
        raise RenameError(f"{old_rel} already has that name")
    clash = [f for f in files if f.lower() == new_rel.lower() and f != old_rel]
    on_disk = (Path(root) / new_rel).exists() and new_rel.lower() != old_rel.lower()
    if clash or on_disk:  # on_disk also catches files .notefindignore hides
        raise RenameError(f"{new_rel} already exists")
    resolver = NoteResolver(notes)
    new_stem = strip_note_suffix(new_rel.rsplit("/", 1)[-1]).lower()
    shared = bool([r for r in resolver.by_stem.get(new_stem, []) if r != old_rel])

    edges = link_edges(notes)
    reach: dict[tuple[str, int, str, str], set[str]] = {}
    for e in edges:
        reach.setdefault((e.source, e.line, e.written, e.kind), set()).add(e.target)
    changes: dict[str, list[BrokenLink]] = {}
    skipped: list[Skipped] = []
    seen: set[tuple[str, int, str, str]] = set()
    for e in edges:
        key = (e.source, e.line, e.written, e.kind)
        if e.target != old_rel or key in seen:
            continue
        seen.add(key)
        if len(reach[key]) > 1:
            skipped.append(Skipped(e.source, e.line, e.written))
            continue
        if e.kind == "wiki":
            new = _wiki_target(e.written, new_rel, shared)
        else:
            new = _markdown_target(e.written, new_rel)
        if new != e.written:
            changes.setdefault(e.source, []).append(
                BrokenLink(e.source, e.line, e.written, e.kind, suggestion=new, unambiguous=True)
            )
    return RenamePlan(old_rel, new_rel, changes, skipped)


def apply_rename(root: Path, plan: RenamePlan, write: bool = True) -> list[Fix]:
    """Rewrite the links, then rename the file. With write=False, nothing is saved."""
    fixes: list[Fix] = []
    for rel, items in plan.changes.items():
        fixes.extend(fix_note(Path(root) / rel, rel, items, write))
    if write:
        os.replace(Path(root) / plan.old, Path(root) / plan.new)
    return [replace(f, path=plan.new) if f.path == plan.old else f for f in fixes]
