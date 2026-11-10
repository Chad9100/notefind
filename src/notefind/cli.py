"""Command-line interface: notefind search | tags | links | backlinks | orphans."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Sequence, TextIO

from . import __version__
from .graph import NoteResolver, backlinks, link_edges, orphans
from .linkcheck import find_broken_links
from .parse import extract_tags
from .scan import load_notes, walk_files
from .search import (
    QueryError, compile_pattern, highlight, parse_query, search, words_pattern,
)

PATH_COLOR = "\x1b[35m"
LINE_COLOR = "\x1b[32m"
RESET = "\x1b[0m"

# Options the search command understands. Any other argument starting with a
# single "-" is an exclusion term, so `notefind search pasta -tomato` works.
_SEARCH_VALUE_OPTS = {"-C", "--folder", "--limit", "--color"}
_SEARCH_SHORT_FLAGS = {"-h", "-w"}


def use_color(mode: str, stream: TextIO, environ: dict[str, str] | None = None) -> bool:
    """Decide whether to emit ANSI colour for --color auto|always|never."""
    if mode == "always":
        return True
    if mode == "never":
        return False
    env = os.environ if environ is None else environ
    if env.get("NO_COLOR"):
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _split_search_args(args: list[str]) -> tuple[list[str], list[str]]:
    opts: list[str] = []
    terms: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            terms.extend(args[i + 1 :])
            break
        if arg in _SEARCH_VALUE_OPTS:
            opts.extend(args[i : i + 2])
            i += 2
            continue
        if arg.startswith("--") or arg in _SEARCH_SHORT_FLAGS:
            opts.append(arg)
        else:
            terms.append(arg)
        i += 1
    return opts, terms


def _add_folder(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-C", "--folder", default=".", metavar="FOLDER",
        help="notes folder to scan (default: current directory)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="notefind",
        description="Search and check a folder of Markdown notes.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")
    sub.required = True

    p = sub.add_parser(
        "search",
        help="full-text search",
        description=(
            'Case-insensitive full-text search. Terms are ANDed; "a phrase" '
            "matches a phrase; -word excludes notes containing it; tag:name "
            "keeps notes with that tag (-tag:name drops them); path:text and "
            "title:text keep notes whose path or title contains text; "
            "key:value keeps notes whose front matter key has that value "
            "(-path:, -title:, -key: drop them)."
        ),
    )
    p.add_argument("query", nargs="*", metavar="QUERY", help="search terms")
    _add_folder(p)
    p.add_argument("--limit", type=int, default=20, metavar="N", help="max results (default 20)")
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument(
        "--fuzzy", action="store_true",
        help="let plain terms also match words with typos: 1 typo for 4-7 "
             "letters, 2 from 8 letters (phrases, exclusions and tags stay exact)",
    )
    p.add_argument(
        "-w", "--word", action="store_true",
        help="match whole words only: terms, phrases and exclusions can't be "
             "part of a longer word",
    )
    p.add_argument(
        "--regex", action="store_true",
        help="treat terms, phrases and exclusions as case-insensitive Python "
             "regular expressions (^ and $ match at line starts and ends)",
    )
    p.add_argument(
        "--color", choices=("auto", "always", "never"), default="auto",
        help="highlight matches (default: auto, only on a terminal without NO_COLOR)",
    )

    p = sub.add_parser("tags", help="list tags with note counts")
    _add_folder(p)
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser(
        "links",
        help="report broken wiki and Markdown links",
        description=(
            "Report links whose target note or file doesn't exist, and links "
            "whose #Heading or #^block anchor isn't in the target note."
        ),
    )
    _add_folder(p)
    p.add_argument("--json", action="store_true", help="print JSON")
    p.add_argument(
        "--no-anchors", action="store_true",
        help="only check that targets exist, not their #headings and #^blocks",
    )

    p = sub.add_parser(
        "backlinks",
        help="list notes that link to a note",
        description=(
            'Notes that link to NOTE, with line numbers. NOTE is a note name '
            '("Garden Plan"), a file name ("Garden Plan.md") or a path '
            '("projects/watering"), matched case-insensitively.'
        ),
    )
    p.add_argument("note", metavar="NOTE", help="the note to find links to")
    _add_folder(p)
    p.add_argument("--json", action="store_true", help="print JSON")

    p = sub.add_parser(
        "orphans",
        help="list notes that no other note links to",
        description="Notes that no other note links to. A link to itself doesn't count.",
    )
    _add_folder(p)
    p.add_argument("--json", action="store_true", help="print JSON")
    return parser


def _cmd_search(args: argparse.Namespace, root: Path) -> int:
    query = parse_query(args.query)
    if query.is_empty():
        print("notefind: search needs at least one term, phrase, tag: or field filter", file=sys.stderr)
        return 2
    opts = {"whole_word": args.word, "regex": args.regex}
    try:
        # Compile before reading the folder, so a bad regex fails fast.
        patterns = [compile_pattern(s, **opts) for s in query.positive + query.excludes]
        hits = search(load_notes(root), query, fuzzy=args.fuzzy, **opts)
    except QueryError as exc:
        print(f"notefind: {exc}", file=sys.stderr)
        return 2
    patterns = patterns[: len(query.positive)]
    shown = hits[: max(args.limit, 0)]
    if args.json:
        payload = {
            "query": {
                "terms": query.terms,
                "phrases": query.phrases,
                "exclude": query.excludes,
                "tags": query.tags,
                "exclude_tags": query.exclude_tags,
                "fields": [str(f) for f in query.fields],
                "exclude_fields": [str(f) for f in query.exclude_fields],
                **({"fuzzy": True} if args.fuzzy else {}),
                **({"whole_word": True} if args.word else {}),
                **({"regex": True} if args.regex else {}),
            },
            "total": len(hits),
            "results": [
                {"path": h.path, "line": h.line, "matches": h.matches, "snippet": h.snippet,
                 **({"fuzzy_words": h.fuzzy_words} if args.fuzzy else {})}
                for h in shown
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        color = use_color(args.color, sys.stdout)
        for h in shown:
            loc = f"{h.path}:{h.line}"
            if color:
                loc = f"{PATH_COLOR}{h.path}{RESET}:{LINE_COLOR}{h.line}{RESET}"
            extra = words_pattern(h.fuzzy_words)
            line_patterns = patterns + [extra] if extra else patterns
            print(f"{loc}: {highlight(h.snippet, line_patterns, color)}")
        sys.stdout.flush()  # keep the summary after the results when 2>&1
        if hits:
            note = "note" if len(hits) == 1 else "notes"
            extra = f", showing {len(shown)}" if len(shown) < len(hits) else ""
            print(f"{len(hits)} {note} matched{extra}", file=sys.stderr)
        else:
            print("no notes matched", file=sys.stderr)
    return 0 if hits else 1


def _cmd_tags(args: argparse.Namespace, root: Path) -> int:
    counts: Counter[str] = Counter()
    for note in load_notes(root):
        counts.update(extract_tags(note.text))
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if args.json:
        print(json.dumps([{"tag": t, "count": c} for t, c in rows], indent=2, ensure_ascii=False))
    else:
        width = max((len(str(c)) for _, c in rows), default=1)
        for tag, count in rows:
            print(f"{count:>{width}}  #{tag}")
    return 0


def _cmd_links(args: argparse.Namespace, root: Path) -> int:
    files = walk_files(root)
    notes = load_notes(root, files)
    broken, checked = find_broken_links(root, notes, files, check_anchors=not args.no_anchors)
    if args.json:
        payload = {
            "checked": checked,
            "broken": [
                {"path": b.path, "line": b.line, "kind": b.kind, "target": b.target,
                 "reason": b.reason, **({"detail": b.detail} if b.detail else {})}
                for b in broken
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for b in broken:
            detail = f" ({b.detail})" if b.detail else ""
            print(f"{b.path}:{b.line}: broken link -> {b.target}{detail}")
        sys.stdout.flush()
        summary = f"{len(broken)} broken" if broken else "no broken links"
        print(f"{summary} ({checked} links checked in {len(notes)} notes)", file=sys.stderr)
    return 1 if broken else 0


def _cmd_backlinks(args: argparse.Namespace, root: Path) -> int:
    notes = load_notes(root)
    matches = NoteResolver(notes).by_name(args.note)
    if not matches:
        print(f"notefind: no note named {args.note!r}", file=sys.stderr)
        return 2
    if len(matches) > 1:
        print(f"notefind: {args.note!r} matches {len(matches)} notes; "
              "give its path instead:", file=sys.stderr)
        for rel in matches:
            print(f"  {rel}", file=sys.stderr)
        return 2
    [target] = matches
    found = backlinks(link_edges(notes), target)
    if args.json:
        payload = {
            "note": target,
            "backlinks": [
                {"path": e.source, "line": e.line, "kind": e.kind, "link": e.written}
                for e in found
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        for e in found:
            print(f"{e.source}:{e.line}: -> {e.written}")
        sys.stdout.flush()
        sources = len({e.source for e in found})
        if found:
            links = "link" if len(found) == 1 else "links"
            note = "note" if sources == 1 else "notes"
            print(f"{len(found)} {links} from {sources} {note} to {target}", file=sys.stderr)
        else:
            print(f"nothing links to {target}", file=sys.stderr)
    return 0 if found else 1


def _cmd_orphans(args: argparse.Namespace, root: Path) -> int:
    notes = load_notes(root)
    lonely = orphans(notes, link_edges(notes))
    if args.json:
        print(json.dumps({"total_notes": len(notes), "orphans": lonely},
                         indent=2, ensure_ascii=False))
    else:
        for rel in lonely:
            print(rel)
        sys.stdout.flush()
        print(f"{len(lonely)} of {len(notes)} notes have no links pointing to them",
              file=sys.stderr)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "search":
        opts, terms = _split_search_args(argv[1:])
        argv = ["search", *opts, "--", *terms]
    args = build_parser().parse_args(argv)
    root = Path(args.folder)
    if not root.is_dir():
        print(f"notefind: not a folder: {args.folder}", file=sys.stderr)
        return 2
    if args.command == "search":
        return _cmd_search(args, root)
    if args.command == "tags":
        return _cmd_tags(args, root)
    if args.command == "backlinks":
        return _cmd_backlinks(args, root)
    if args.command == "orphans":
        return _cmd_orphans(args, root)
    return _cmd_links(args, root)
