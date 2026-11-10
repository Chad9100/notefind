"""Resolving wiki links and relative Markdown links against a notes folder."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from .anchors import Anchors, collect_anchors, missing_markdown_anchor, missing_wiki_anchor
from .parse import Link, extract_links
from .resolve import NoteResolver
from .scan import Note, is_note
from .suggest import FileSuggester, suggest_markdown_fragment, suggest_wiki_fragment

# "http:", "mailto:", "obsidian:" ... anything with a URL scheme is external.
SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


@dataclass(frozen=True)
class BrokenLink:
    path: str
    line: int
    target: str
    kind: str
    # "no-file" when the target doesn't exist, "no-heading" / "no-block" when
    # the file exists but the #anchor doesn't; `detail` says which one.
    reason: str = "no-file"
    detail: str = ""
    # With suggest=True: the link target as it probably should be written.
    suggestion: str = ""
    # True when the suggestion is the only sensible one (no tie between
    # candidates, one file with that name): safe for `links --fix` to apply.
    unambiguous: bool = False


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


def split_fragment(link: Link) -> tuple[str, str]:
    """(target without the #fragment, fragment) for a link as written."""
    if link.kind == "wiki":
        name, _, fragment = link.target.partition("#")
        return name.strip(), fragment
    path, _, fragment = link.target.partition("#")
    return path.split("?", 1)[0], fragment


def is_self_anchor(link: Link) -> bool:
    """`[[#Heading]]`, `[[#^block]]` or `[text](#anchor)`: a link into the same note."""
    name, fragment = split_fragment(link)
    if link.kind == "markdown" and SCHEME_RE.match(link.target):
        return False
    return not name and bool(fragment.strip())


def find_broken_links(
    root: Path,
    notes: list[Note],
    files: list[str],
    check_anchors: bool = True,
    suggest: bool = False,
) -> tuple[list[BrokenLink], int]:
    """Return (broken links, number of links checked).

    With check_anchors, `#Heading` and `#^block` parts of links to notes
    (and links into the same note) are verified too; anchors on links to
    other files, such as `manual.pdf#page=3`, are not. With suggest, each
    broken link gets the closest existing note, file, heading or block as a
    `suggestion` when one is similar enough.
    """
    index = LinkIndex(files)
    resolver = NoteResolver(notes)
    texts = {note.rel: note.text for note in notes}
    cache: dict[str, Anchors] = {}
    suggesters = (FileSuggester(files), FileSuggester(files, unique=True)) if suggest else ()

    # Each suggestion is worked out twice, the second time insisting on a
    # unique answer; when both agree, the suggestion is unambiguous.
    def file_suggestion(source: str, link: Link) -> tuple[str, bool]:
        name, fragment = split_fragment(link)
        results = []
        for s in suggesters:
            fixed = s.wiki(name) if link.kind == "wiki" else s.markdown(source, name)
            if fixed is not None and fragment:
                fixed = f"{fixed}#{fragment}"
            results.append(fixed or "")
        if not results:
            return "", False
        return results[0], bool(results[0]) and results[0] == results[1]

    def anchor_suggestion(link: Link, target: str) -> tuple[str, bool]:
        if not suggest:
            return "", False
        name, fragment = split_fragment(link)
        suggest_fragment = (
            suggest_wiki_fragment if link.kind == "wiki" else suggest_markdown_fragment
        )
        written = link.target.partition("#")[0] if link.kind == "markdown" else name
        results = []
        for unique in (False, True):
            fixed = suggest_fragment(
                texts[target], fragment, anchors_of(target).blocks, unique=unique
            )
            results.append(f"{written}#{fixed}" if fixed is not None else "")
        return results[0], bool(results[0]) and results[0] == results[1]

    def anchors_of(rel: str) -> Anchors:
        if rel not in cache:
            cache[rel] = collect_anchors(texts[rel])
        return cache[rel]

    broken: list[BrokenLink] = []
    checked = 0
    for note in notes:
        for link in extract_links(note.text):
            self_anchor = check_anchors and is_self_anchor(link)
            if not (self_anchor or is_checkable(link)):
                continue
            checked += 1
            if self_anchor:
                targets = [note.rel]
            elif link.kind == "wiki":
                if not index.has_wiki_target(link.target):
                    broken.append(BrokenLink(
                        note.rel, link.line, link.target, link.kind, "no-file", "",
                        *file_suggestion(note.rel, link),
                    ))
                    continue
                targets = resolver.by_name(link.target)
            else:
                if not markdown_target_exists(root, note.rel, link.target):
                    broken.append(BrokenLink(
                        note.rel, link.line, link.target, link.kind, "no-file", "",
                        *file_suggestion(note.rel, link),
                    ))
                    continue
                targets = resolver.by_relative_path(note.rel, link.target)
            fragment = split_fragment(link)[1]
            if not check_anchors or not fragment.strip() or not targets:
                continue
            missing = missing_wiki_anchor if link.kind == "wiki" else missing_markdown_anchor
            # An ambiguous [[Name#Heading]] is fine if any note called Name has it.
            problems = [missing(anchors_of(t), fragment) for t in targets]
            if all(problems):
                detail = f"{problems[0]} in {targets[0]}"
                reason = "no-block" if problems[0].startswith("no block") else "no-heading"
                broken.append(BrokenLink(
                    note.rel, link.line, link.target, link.kind, reason, detail,
                    *anchor_suggestion(link, targets[0]),
                ))
    return broken, checked
