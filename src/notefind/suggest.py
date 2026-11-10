"""Did-you-mean suggestions for broken links: the closest note, file, heading or block."""

from __future__ import annotations

import posixpath
from difflib import SequenceMatcher
from typing import Iterable
from urllib.parse import unquote

from .anchors import github_slug, headings, loose_key
from .resolve import strip_note_suffix
from .scan import is_note

# How similar (difflib ratio, 0..1) a name must be to count as a likely typo.
CUTOFF = 0.6


def closest(word: str, candidates: Iterable[str], cutoff: float = CUTOFF) -> str | None:
    """The candidate most similar to word, ignoring case, or None if none is close.

    Ties go to the candidate that sorts first, so results are stable.
    """
    key = word.casefold().strip()
    if not key:
        return None
    best: str | None = None
    best_score = cutoff
    for cand in sorted(set(candidates)):
        score = SequenceMatcher(None, key, cand.casefold()).ratio()
        if score > best_score or (score == best_score and best is None):
            best, best_score = cand, score
    return best


class FileSuggester:
    """Closest existing note or file for a broken wiki or Markdown link."""

    def __init__(self, files: list[str]):
        self.files = list(files)
        self.stem_count: dict[str, int] = {}
        self.by_stem: dict[str, list[str]] = {}
        self.by_name: dict[str, list[str]] = {}
        for rel in files:
            name = rel.rsplit("/", 1)[-1]
            self.by_name.setdefault(name, []).append(rel)
            if is_note(name):
                stem = strip_note_suffix(name)
                self.by_stem.setdefault(stem, []).append(rel)
                low = stem.lower()
                self.stem_count[low] = self.stem_count.get(low, 0) + 1

    def wiki(self, name: str) -> str | None:
        """A wiki name ("Note", "folder/Note", "image.png") that probably was meant."""
        name = name.strip().replace("\\", "/").strip("/")
        base = name.rsplit("/", 1)[-1]
        if "." in base and not is_note(base):
            # An attachment such as diagram.png: match whole file names.
            match = closest(base, self.by_name)
            if match is None:
                return None
            rels = sorted(self.by_name[match])
            return match if len(rels) == 1 or "/" not in name else rels[0]
        match = closest(strip_note_suffix(base), self.by_stem)
        if match is None:
            return None
        rels = sorted(self.by_stem[match])
        if "/" in name or self.stem_count[match.lower()] > 1:
            return strip_note_suffix(rels[0])  # a path is needed to be unambiguous
        return match

    def markdown(self, source_rel: str, path: str) -> str | None:
        """A relative path, from source_rel's folder, to the closest file name."""
        clean = unquote(path).replace("\\", "/")
        base = clean.rstrip("/").rsplit("/", 1)[-1]
        # Compare notes without ".md", or the shared suffix makes "pruning.md"
        # look like "watering.md".
        keys: dict[str, list[str]] = {}
        for name, rels in self.by_name.items():
            keys.setdefault(strip_note_suffix(name), []).extend(rels)
        match = closest(strip_note_suffix(base), keys)
        if match is None:
            return None
        rels = sorted(keys[match])
        if clean.startswith("/"):
            return ("/" + rels[0]).replace(" ", "%20")
        start = posixpath.dirname(source_rel) or "."
        # Of several files with that name, prefer the one with the shortest path.
        best = min((posixpath.relpath(rel, start) for rel in rels), key=lambda p: (len(p), p))
        return best.replace(" ", "%20")


def suggest_wiki_fragment(text: str, fragment: str, blocks: Iterable[str]) -> str | None:
    """A corrected `#fragment` for a wiki link into a note with this text."""
    fragment = fragment.strip()
    if fragment.startswith("^"):
        match = closest(fragment[1:], blocks)
        return f"^{match}" if match else None
    by_key = _headings_by_key(text)
    parts = []
    changed = False
    for part in fragment.split("#"):
        key = loose_key(part)
        if not key or key in by_key:
            parts.append(part)
            continue
        match = closest(key, by_key)
        if match is None:
            return None
        parts.append(by_key[match])
        changed = True
    return "#".join(parts) if changed else None


def suggest_markdown_fragment(text: str, fragment: str, blocks: Iterable[str]) -> str | None:
    """A corrected `#fragment` (a GitHub-style slug) for a Markdown link."""
    fragment = unquote(fragment).strip()
    if fragment.startswith("^"):
        return suggest_wiki_fragment(text, fragment, blocks)
    by_key = _headings_by_key(text)
    match = closest(loose_key(fragment), by_key)
    return github_slug(by_key[match]) if match else None


def _headings_by_key(text: str) -> dict[str, str]:
    """Headings of a note keyed by loose_key(), first occurrence wins."""
    by_key: dict[str, str] = {}
    for name in headings(text):
        by_key.setdefault(loose_key(name), name)
    return by_key
