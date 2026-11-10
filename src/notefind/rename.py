"""Renaming a note and rewriting every link that points to it (`rename`)."""

from __future__ import annotations

import os
import posixpath
import re
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote, unquote

from .fix import Fix, fix_note
from .graph import link_edges
from .linkcheck import BrokenLink, is_checkable
from .parse import extract_links
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


def new_note_path(old_rel: str, name: str) -> str:
    """The new relative path for `rename OLD NAME`.

    A bare name renames the note in its folder. A name with folders
    (`archive/2024/Plan`) moves it there, relative to the notes folder; a
    trailing `/` (`archive/`) moves it and keeps its file name.
    """
    raw = name.strip().replace("\\", "/")
    if "/" not in raw:
        return posixpath.join(posixpath.dirname(old_rel), new_filename(old_rel, raw))
    if raw.startswith("/"):
        raise RenameError("give the new folder relative to the notes folder, without a "
                          "leading /")
    folder, _, base = raw.rpartition("/")
    if any(p in ("", ".", "..") or p.startswith(".") for p in folder.split("/")):
        raise RenameError(f"not a usable folder: {folder!r}")
    filename = new_filename(old_rel, base) if base else old_rel.rsplit("/", 1)[-1]
    return folder + "/" + filename


def _relative_link(source_dir: str, target_rel: str, written: str) -> str:
    """A path from source_dir to target_rel in the style of the written link."""
    if written.startswith("/"):
        return "/" + target_rel
    path = posixpath.relpath(target_rel, source_dir or ".")
    if written.startswith("./") and not path.startswith("../"):
        path = "./" + path
    return path


def _moved_markdown_target(written: str, new_rel: str, source_dir: str) -> str:
    """Like _markdown_target, for a note that changed folder or links from one that did."""
    m = re.search(r"[#?]", written)
    path, rest = (written[: m.start()], written[m.start():]) if m else (written, "")
    target = new_rel
    if strip_note_suffix(path.rsplit("/", 1)[-1]) == path.rsplit("/", 1)[-1]:
        target = strip_note_suffix(new_rel)
    new_path = _relative_link(source_dir, target, written)
    if "%" in path:
        new_path = quote(new_path)
    return new_path + rest


def _own_relative_links(
    note: Note, old_rel: str, new_rel: str, resolver: NoteResolver
) -> list[BrokenLink]:
    """Relative links of the moved note that must change because its folder did."""
    old_dir, new_dir = posixpath.dirname(old_rel), posixpath.dirname(new_rel)
    out: list[BrokenLink] = []
    for link in extract_links(note.text):
        if link.kind != "markdown" or not is_checkable(link) or link.target.startswith("/"):
            continue
        m = re.search(r"[#?]", link.target)
        path, rest = (link.target[: m.start()], link.target[m.start():]) if m else (link.target, "")
        if resolver.by_relative_path(old_rel, link.target) == [old_rel]:
            continue  # a link to itself is rewritten with the other links to the note
        resolved = posixpath.normpath(posixpath.join(old_dir, unquote(path)))
        if resolved == ".." or resolved.startswith("../"):
            continue  # points outside the notes folder; can't be made relative
        new_path = _relative_link(new_dir, resolved, link.target)
        if "%" in path:
            new_path = quote(new_path)
        new = new_path + rest
        if new != link.target:
            out.append(BrokenLink(old_rel, link.line, link.target, "markdown",
                                  suggestion=new, unambiguous=True))
    return out


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
    new_rel = new_note_path(old_rel, name)
    moved = posixpath.dirname(new_rel) != posixpath.dirname(old_rel)
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
        elif moved:
            source_dir = posixpath.dirname(new_rel if e.source == old_rel else e.source)
            new = _moved_markdown_target(e.written, new_rel, source_dir)
        else:
            new = _markdown_target(e.written, new_rel)
        if new != e.written:
            changes.setdefault(e.source, []).append(
                BrokenLink(e.source, e.line, e.written, e.kind, suggestion=new, unambiguous=True)
            )
    if moved:
        note = next(n for n in notes if n.rel == old_rel)
        own = _own_relative_links(note, old_rel, new_rel, resolver)
        if own:
            changes.setdefault(old_rel, []).extend(own)
    return RenamePlan(old_rel, new_rel, changes, skipped)


def apply_rename(
    root: Path, plan: RenamePlan, write: bool = True, diffs: list[str] | None = None
) -> list[Fix]:
    """Rewrite the links, then rename the file. With write=False, nothing is saved.

    If `diffs` is a list, the unified diff of every rewritten note is appended
    to it (the renamed note itself is shown as old path -> new path).
    """
    fixes: list[Fix] = []
    for rel, items in plan.changes.items():
        fixes.extend(fix_note(Path(root) / rel, rel, items, write, diffs,
                              plan.new if rel == plan.old else None))
    if write:
        (Path(root) / plan.new).parent.mkdir(parents=True, exist_ok=True)
        os.replace(Path(root) / plan.old, Path(root) / plan.new)
    return [replace(f, path=plan.new) if f.path == plan.old else f for f in fixes]
