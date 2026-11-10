"""Extra skip rules from a `.notefindignore` file in the notes folder."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

IGNORE_FILE = ".notefindignore"


@dataclass(frozen=True)
class Rule:
    pattern: str
    regex: re.Pattern[str]
    dir_only: bool
    anchored: bool


def _translate(glob: str) -> str:
    """Turn a glob into a regex: `*` and `?` stop at "/", `**` crosses folders."""
    out: list[str] = []
    i = 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


def parse_rules(text: str) -> list[Rule]:
    """Parse ignore-file text: one glob per line, blank lines and `#` comments skipped.

    A pattern ending in "/" only matches folders. A pattern containing "/"
    elsewhere is matched against the whole path from the notes folder;
    otherwise it matches a file or folder name at any depth.
    """
    rules: list[Rule] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        dir_only = line.endswith("/")
        body = line.rstrip("/")
        anchored = "/" in body
        body = body.lstrip("/")
        if not body:
            continue
        regex = re.compile(_translate(body) + r"\Z")
        rules.append(Rule(line, regex, dir_only, anchored))
    return rules


def load_rules(root: Path) -> list[Rule]:
    """Rules from root/.notefindignore, or none if the file is missing or unreadable."""
    try:
        text = (Path(root) / IGNORE_FILE).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    return parse_rules(text)


def is_ignored(rules: list[Rule], rel: str, is_dir: bool) -> bool:
    """True if the "/"-separated path rel matches any rule."""
    name = rel.rsplit("/", 1)[-1]
    for rule in rules:
        if rule.dir_only and not is_dir:
            continue
        if rule.regex.match(rel if rule.anchored else name):
            return True
    return False
