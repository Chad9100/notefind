"""Query parsing, matching, ranking and snippet highlighting."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from .parse import clean_tag, extract_tags, split_front_matter
from .scan import Note

TOKEN_RE = re.compile(r'(-?)(?:"([^"]*)"?|(\S+))')
HIGHLIGHT_ON = "\x1b[1;31m"
HIGHLIGHT_OFF = "\x1b[0m"
SNIPPET_WIDTH = 100
WORD_RE = re.compile(r"\w+")


@dataclass
class Query:
    terms: list[str] = field(default_factory=list)
    phrases: list[str] = field(default_factory=list)
    excludes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    exclude_tags: list[str] = field(default_factory=list)

    @property
    def positive(self) -> list[str]:
        return self.terms + self.phrases

    def is_empty(self) -> bool:
        return not (self.terms or self.phrases or self.tags)


@dataclass
class Hit:
    path: str
    line: int
    matches: int
    snippet: str
    # With fuzzy search: the words in the note that matched a term only
    # because they are within its typo budget (lowercased, sorted).
    fuzzy_words: list[str] = field(default_factory=list)


def _add(query: Query, text: str, negative: bool, quoted: bool) -> None:
    text = " ".join(text.split())
    if not text or text == "-":
        return
    if not quoted and text.lower().startswith("tag:"):
        name = clean_tag(text[4:])
        if name:
            (query.exclude_tags if negative else query.tags).append(name)
        return
    if negative:
        query.excludes.append(text)
    elif quoted or " " in text:
        query.phrases.append(text)
    else:
        query.terms.append(text)


def parse_query(parts: str | Sequence[str]) -> Query:
    """Parse search terms.

    - plain words are ANDed;
    - "quoted text" (or a single shell argument containing spaces) is a phrase;
    - -word / -"some phrase" excludes notes containing it;
    - tag:name keeps only notes with that tag, -tag:name drops them.
    """
    if isinstance(parts, str):
        parts = [parts]
    query = Query()
    for part in parts:
        s = part.strip()
        if not s:
            continue
        if '"' not in s and re.search(r"\s", s):
            # The shell already removed the quotes: treat the argument as a phrase.
            negative = s.startswith("-")
            _add(query, s[1:] if negative else s, negative, quoted=True)
            continue
        for m in TOKEN_RE.finditer(s):
            quoted = m.group(2) is not None
            _add(query, m.group(2) if quoted else m.group(3), m.group(1) == "-", quoted)
    return query


class QueryError(ValueError):
    """A search term that can't be used, such as an invalid --regex."""


def _whole_word(pattern: str) -> str:
    # Lookarounds instead of \b, so terms that start or end with a non-word
    # character (c++, #todo) still work: the match just can't touch a letter,
    # digit or underscore on either side.
    return rf"(?<!\w)(?:{pattern})(?!\w)"


def compile_pattern(text: str, whole_word: bool = False, regex: bool = False) -> re.Pattern[str]:
    """Case-insensitive pattern for a term, phrase or exclusion.

    By default the text is literal and whitespace inside a phrase matches any
    whitespace. With ``regex`` the text is a Python regular expression, with
    ``^`` and ``$`` matching at line boundaries. With ``whole_word`` the match
    can't be part of a longer word. Raises QueryError for an invalid regex or
    one that matches empty text.
    """
    if regex:
        pattern = text
        flags = re.IGNORECASE | re.MULTILINE
    else:
        pattern = r"\s+".join(re.escape(w) for w in text.split())
        flags = re.IGNORECASE
    if whole_word:
        pattern = _whole_word(pattern)
    try:
        compiled = re.compile(pattern, flags)
    except re.error as exc:
        raise QueryError(f"invalid regex {text!r}: {exc}") from None
    if regex and compiled.search("") is not None:
        raise QueryError(f"regex {text!r} matches empty text; it would match every note")
    return compiled


def typo_budget(term: str) -> int:
    """How many typos --fuzzy tolerates in a term: 0 up to 3 characters,
    1 for 4-7 characters, 2 from 8 characters on. Terms that aren't a single
    word (``c++``, ``2026-05-02``) are always matched exactly."""
    if not WORD_RE.fullmatch(term):
        return 0
    n = len(term)
    if n <= 3:
        return 0
    return 1 if n <= 7 else 2


def edit_distance(a: str, b: str, limit: int) -> int:
    """Optimal string alignment distance between a and b: insertions,
    deletions, substitutions and swaps of two neighbouring characters each
    cost 1. Returns ``limit + 1`` as soon as the distance must exceed limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > limit:
            return limit + 1
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= limit else limit + 1


class FuzzyTerm:
    """A search term that also matches whole words within its typo budget."""

    def __init__(self, term: str, budget: int | None = None, whole_word: bool = False) -> None:
        self.term = term
        self.lower = term.lower()
        self.budget = typo_budget(term) if budget is None else budget
        self.whole_word = whole_word
        self.exact = compile_pattern(term, whole_word=whole_word)
        self._close: dict[str, bool] = {}  # word -> within budget, across notes

    def is_close(self, word: str) -> bool:
        """True for a word that the exact pattern doesn't already match (one
        that doesn't contain the term, or with ``whole_word`` isn't the term)
        but is within budget."""
        known = self._close.get(word)
        if known is None:
            exact = word == self.lower if self.whole_word else self.lower in word
            known = (
                not exact
                and edit_distance(word, self.lower, self.budget) <= self.budget
            )
            self._close[word] = known
        return known

    def pattern_for(self, words: set[str]) -> tuple[re.Pattern[str], list[str]]:
        """Pattern matching the term or any close word in `words` (the note's
        lowercased vocabulary), plus the close words found."""
        if self.budget <= 0:
            return self.exact, []
        close = sorted(w for w in words if self.is_close(w))
        if not close:
            return self.exact, []
        return _term_or_words(self.exact.pattern, close), close


def _words_alternation(words: list[str]) -> str:
    # Longest first, so "tomatoes" wins over "tomato" at the same position.
    alternation = "|".join(re.escape(w) for w in sorted(words, key=lambda w: (-len(w), w)))
    return rf"\b(?:{alternation})\b"


def _term_or_words(term_pattern: str, words: list[str]) -> re.Pattern[str]:
    return re.compile(rf"{term_pattern}|{_words_alternation(words)}", re.IGNORECASE)


def words_pattern(words: list[str]) -> re.Pattern[str] | None:
    """Whole-word pattern for highlighting the fuzzy words of a hit."""
    if not words:
        return None
    return re.compile(_words_alternation(words), re.IGNORECASE)


def _has_tag(tags: set[str], wanted: str) -> bool:
    # tag:project also matches nested tags such as project/alpha.
    return wanted in tags or any(t.startswith(wanted + "/") for t in tags)


def make_snippet(line: str, patterns: list[re.Pattern[str]], width: int = SNIPPET_WIDTH) -> str:
    """The stripped line, cut to `width` characters around the first match."""
    s = line.strip()
    if len(s) <= width:
        return s
    starts = [m.start() for p in patterns if (m := p.search(s))]
    first = min(starts, default=0)
    start = max(0, min(first - 30, len(s) - width))
    end = start + width
    out = s[start:end]
    if start > 0:
        out = "..." + out
    if end < len(s):
        out += "..."
    return out


def highlight(text: str, patterns: list[re.Pattern[str]], color: bool) -> str:
    """Wrap every match in ANSI bold red when color is on."""
    if not color or not patterns:
        return text
    spans = sorted((m.start(), m.end()) for p in patterns for m in p.finditer(text) if m.end() > m.start())
    merged: list[list[int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, pos = [], 0
    for start, end in merged:
        out.append(text[pos:start])
        out.append(HIGHLIGHT_ON + text[start:end] + HIGHLIGHT_OFF)
        pos = end
    out.append(text[pos:])
    return "".join(out)


def _first_body_line(note: Note) -> int:
    _, body_start = split_front_matter(note.lines)
    for i in range(body_start, len(note.lines)):
        if note.lines[i].strip():
            return i + 1
    return 1


def search(
    notes: list[Note],
    query: Query,
    fuzzy: bool = False,
    whole_word: bool = False,
    regex: bool = False,
) -> list[Hit]:
    """Return matching notes, most matches first, ties broken by path.

    With ``fuzzy``, each plain term also matches whole words within its typo
    budget (see ``typo_budget``). Phrases, exclusions and tags stay exact.
    With ``whole_word``, terms, phrases and exclusions only match whole words.
    With ``regex``, they are regular expressions (see ``compile_pattern``);
    it can't be combined with ``fuzzy``. Raises QueryError for a bad regex.
    """
    if fuzzy and regex:
        raise QueryError("--fuzzy and --regex can't be combined")
    fuzzy_terms = [FuzzyTerm(t, whole_word=whole_word) for t in query.terms] if fuzzy else []
    fuzzy_terms = [f for f in fuzzy_terms if f.budget > 0]
    exact_terms = [t for t in query.terms if t not in {f.term for f in fuzzy_terms}]
    opts = {"whole_word": whole_word, "regex": regex}
    static = [compile_pattern(s, **opts) for s in exact_terms + query.phrases]
    negative = [compile_pattern(s, **opts) for s in query.excludes]
    hits: list[Hit] = []
    for note in notes:
        text = note.text
        if any(p.search(text) for p in negative):
            continue
        if query.tags or query.exclude_tags:
            tags = extract_tags(text)
            if not all(_has_tag(tags, t) for t in query.tags):
                continue
            if any(_has_tag(tags, t) for t in query.exclude_tags):
                continue
        positive = list(static)
        close_words: set[str] = set()
        if fuzzy_terms:
            vocab = set(WORD_RE.findall(text.lower()))
            for fterm in fuzzy_terms:
                pattern, close = fterm.pattern_for(vocab)
                positive.append(pattern)
                close_words.update(close)
        total = 0
        first: int | None = None
        for pattern in positive:
            # A regex can still match empty text in some places (lookarounds).
            found = [m.start() for m in pattern.finditer(text) if m.end() > m.start()]
            if not found:
                break
            total += len(found)
            first = found[0] if first is None else min(first, found[0])
        else:
            if first is None:
                line = _first_body_line(note)
            else:
                line = text.count("\n", 0, first) + 1
            snippet = make_snippet(note.lines[line - 1], positive)
            hits.append(Hit(note.rel, line, total, snippet, sorted(close_words)))
    hits.sort(key=lambda h: (-h.matches, h.path))
    return hits
