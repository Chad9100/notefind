# notefind

Search and check a folder of Markdown notes from the command line.

`notefind` works on the kind of notes folder people keep in Obsidian, Logseq or
plain directories. It does these things:

- **search**: case-insensitive full-text search with AND-ed terms, `"phrases"`,
  `-exclusions`, `tag:` filters and `path:` / `title:` / front matter field
  filters (`status:done`), optional typo tolerance (`--fuzzy`),
  whole-word (`-w`) and regular expression (`--regex`) modes, ranked by
  number of matches, with the first (or with `--all-lines` every) matching
  line shown and highlighted;
- **tags**: list every tag (front matter and inline `#tags`) with note counts;
- **links**: find broken `[[wiki links]]` and relative `[markdown](links.md)`,
  including `#Heading` and `#^block` anchors that don't exist, with
  did-you-mean suggestions and `--fix` to apply the unambiguous ones;
- **backlinks**: list the notes that link to a given note;
- **orphans**: list notes that nothing links to.

There is no index and no database. Every run scans the folder, skipping hidden
directories (`.git`, `.obsidian`, `.trash`, ...) and `node_modules`.

## Who it's for

People with a folder of Markdown notes who want a quick terminal answer to
"where did I write about X?", "which tags do I actually use?" and "which links
did I break when I renamed that note?", without opening an editor or
installing a plugin. It is also handy in CI for a docs folder or a published
vault: `notefind links` exits with 1 when something is broken.

## Built with

- Python 3.10+, standard library only (`argparse`, `re`, `os`, `json`, `pathlib`)
- [pytest](https://pytest.org) for the test suite
- GitHub Actions, testing on Ubuntu and Windows with Python 3.10, 3.12 and 3.13

## Install

```bash
git clone https://github.com/Chad9100/notefind.git
cd notefind
python -m pip install .
```

That puts a `notefind` command on your PATH. `python -m notefind` works too.

## Usage

Every command scans the current directory by default; use `-C FOLDER` to point
it somewhere else. All commands accept `--json`, and `-j N` to choose how many
threads read the notes (see [Files](#files)).

The output below is real output from the made-up notes in
[`examples/notes/`](examples/notes), run from inside that folder.

### search

```
notefind search QUERY... [-C FOLDER] [--limit N] [--json] [--fuzzy] [-w] [--regex]
                [--all-lines] [--color auto|always|never]
```

| Query               | Meaning                                         |
|---------------------|-------------------------------------------------|
| `tomato basil`      | notes containing both words (AND)               |
| `"full sun"`        | the exact phrase (any whitespace between words) |
| `-blight`           | drop notes containing "blight"                  |
| `-"cream sauce"`    | drop notes containing the phrase               |
| `tag:garden`        | only notes tagged `garden` (or `garden/...`)    |
| `-tag:draft`        | drop notes tagged `draft`                       |
| `path:daily/`       | only notes whose path contains `daily/`         |
| `title:plan`        | only notes whose title contains "plan"          |
| `status:done`       | only notes with `status: done` in front matter  |
| `-status:done`      | drop notes with `status: done`                  |

Matching is case-insensitive substring matching. Results are ranked by the
total number of matches, ties broken by path, and show `path:line:` plus the
first matching line. Matches are highlighted in colour only when stdout is a
terminal and `NO_COLOR` is not set (override with `--color always|never`).
The default limit is 20 results. Exit code is 0 when something matched, 1 when
nothing did.

```console
$ notefind search tomato
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
Compost.md:13: Tomato vines go in the green pile, but not if they had blight.
Seed Order.md:9: | Cherry tomato   | 2       |
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
5 notes matched
```

`Garden Plan.md` comes first because it mentions tomatoes twice.

```console
$ notefind search tomato basil -blight
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
Seed Order.md:9: | Cherry tomato   | 2       |
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
4 notes matched

$ notefind search "full sun"
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
1 note matched

$ notefind search tag:soil
Compost.md:6: # Compost
projects/Reading List.md:5: # Reading list
2 notes matched

$ notefind search zucchini
no notes matched
$ echo $?
1
```

#### Field filters: `path:`, `title:` and front matter keys

A `key:value` word filters notes instead of searching their text:

- `path:text` keeps notes whose path (relative to the notes folder, with `/`)
  contains `text`, so `path:daily/` means "in the daily folder";
- `title:text` keeps notes whose title contains `text`. The title is the
  front matter `title:`, else the first `# Heading`, else the file name;
- any other key, such as `status:done`, keeps notes whose front matter has
  that key set to exactly that value, or to a list that contains it
  (`status: [active, review]` or a `- review` block list). Use
  `status:"in progress"` for values with spaces.

All of them ignore case, combine with terms, tags and each other, and a
leading `-` drops matching notes instead (`-status:done` keeps notes that have
no `status` at all). They stay exact with `--fuzzy`, `-w` and `--regex`.
`tag:` / `tags:` are the tag filter described above. A word with a key that
doesn't start with a letter (`06:00`), an empty value (`todo:`) or a value
starting with `/` (`https://...`) is a normal search term; quote the whole
word (`'"status:done"'`) to search for it as text.

In `examples/notes`, `Seed Order.md` has `status: done` and
`projects/Reading List.md` has `status: draft`:

```console
$ notefind search status:done
Seed Order.md:5: # Seed Order
1 note matched

$ notefind search basil -status:done
Garden Plan.md:8: the bed nearest the shed. Basil goes next to the tomatoes. #companion-planting
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
3 notes matched

$ notefind search tomato path:projects/
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
1 note matched

$ notefind search title:list
projects/Reading List.md:5: # Reading list
1 note matched
```

A filter-only search shows each note's first line. In `--json` output the
query lists them as `"fields": ["status:done"]` and `"exclude_fields"`.

#### Typos: `--fuzzy`

With `--fuzzy`, each plain term also matches whole words that are a few typos
away from it. A typo is one inserted, deleted or changed character, or two
neighbouring characters swapped (`tomaot` -> `tomato`). The allowance grows
with the term's length:

| Term length    | Typos allowed |
|----------------|---------------|
| 1-3 characters | 0 (exact)     |
| 4-7 characters | 1             |
| 8 or more      | 2             |

Exact substring matches still count, so `--fuzzy` only ever adds results.
Phrases, `-exclusions`, `tag:` and field filters and terms that aren't a single word
(`c++`, `2026-05-02`) stay exact. Typo matches count towards the ranking like
exact ones and are highlighted too.

```console
$ notefind search tomatos
no notes matched

$ notefind search tomatos --fuzzy
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
Compost.md:13: Tomato vines go in the green pile, but not if they had blight.
Seed Order.md:9: | Cherry tomato   | 2       |
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
5 notes matched

$ notefind search compst ratio --fuzzy
Garden Plan.md:11: - Compost notes live in [[Compost#Ratios|the compost note]]
Compost.md:6: # Compost
2 notes matched
```

In `--json` output the query gets `"fuzzy": true` and every result lists the
words that matched only thanks to the typo allowance:

```console
$ notefind search wartering --fuzzy --limit 1 --json
{
  "query": {
    "terms": [
      "wartering"
    ],
    "phrases": [],
    "exclude": [],
    "tags": [],
    "exclude_tags": [],
    "fields": [],
    "exclude_fields": [],
    "fuzzy": true
  },
  "total": 3,
  "results": [
    {
      "path": "Garden Plan.md",
      "line": 12,
      "matches": 4,
      "snippet": "- Watering schedule: [watering](projects/watering.md#watering-schedule)",
      "fuzzy_words": [
        "watering"
      ]
    }
  ]
}
```

#### Whole words: `-w` and regular expressions: `--regex`

With `-w` (`--word`), terms, phrases and `-exclusions` only match whole words:
the match can't have a letter, digit or underscore right before or after it.
Plain `tomato` also finds "Tomatoes"; `-w tomato` doesn't:

```console
$ notefind search tomato -w
Compost.md:13: Tomato vines go in the green pile, but not if they had blight.
Seed Order.md:9: | Cherry tomato   | 2       |
2 notes matched
```

This works for terms with symbols at the edges too: `-w c++` doesn't match
"c++11", and `-w "#todo"` doesn't match "#todos".

With `--regex`, terms, phrases and `-exclusions` are Python regular
expressions, still case-insensitive. `^` and `$` match at the start and end of
each line. `tag:` filters stay as they are. Quote patterns so the shell leaves
them alone; leading and trailing spaces are dropped, so use `\s` for those.
List items that contain a wiki link:

```console
$ notefind search --regex '^- .*\[\['
Garden Plan.md:10: - Order seeds by March (see [[Seed Order]])
projects/Reading List.md:7: - "The Well-Tended Perennial Garden" - recommended in [[Garden Plan]]
2 notes matched
```

Wiki links with a `#heading` or `#^block` anchor:

```console
$ notefind search --regex '\[\[[^]|]+#'
projects/watering.md:7: Bed layout: [[Garden Plan#Beds]]. Last frost: [[2026-05-02#^frost]].
Garden Plan.md:11: - Compost notes live in [[Compost#Ratios|the compost note]]
2 notes matched
```

The two combine: `--regex -w 'beds?'` finds "bed" and "beds" but not
"embedded". An invalid pattern, or one that matches empty text (such as `x*`,
which would match every note), is an error with exit code 2. `--regex` can't
be combined with `--fuzzy`.

```console
$ notefind search --regex 'tomato('
notefind: invalid regex 'tomato(': missing ), unterminated subpattern at position 6
$ echo $?
2
```

In `--json` output the query gets `"whole_word": true` and `"regex": true`
when those modes are on.

#### Every matching line: `--all-lines`

Normally each note shows only its first matching line. With `--all-lines`
every line where a term or phrase matches is printed as its own `path:line:`
row, in line order, each line once even if it matches several times. A phrase
that wraps onto the next line counts on the line where it starts. `--limit`
still counts notes, and the summary adds the number of lines printed:

```console
$ notefind search tomato --all-lines
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
Garden Plan.md:8: the bed nearest the shed. Basil goes next to the tomatoes. #companion-planting
Compost.md:13: Tomato vines go in the green pile, but not if they had blight.
Seed Order.md:9: | Cherry tomato   | 2       |
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
5 notes matched (6 lines)
```

A filter-only search (`tag:soil --all-lines`) still shows one line per note.
It works with `--fuzzy`, `-w` and `--regex`. In `--json` output the query gets
`"all_lines": true` and each result a `"lines"` list (`line` and `snippet`
for each matching line); `line` and `snippet` keep pointing at the first one:

```console
$ notefind search "full sun" basil --all-lines --json
{
  "query": {
    "terms": [
      "basil"
    ],
    "phrases": [
      "full sun"
    ],
    "exclude": [],
    "tags": [],
    "exclude_tags": [],
    "fields": [],
    "exclude_fields": [],
    "all_lines": true
  },
  "total": 1,
  "results": [
    {
      "path": "Garden Plan.md",
      "line": 7,
      "matches": 2,
      "snippet": "Raised beds go along the south fence. Tomatoes need full sun, so they get",
      "lines": [
        {
          "line": 7,
          "snippet": "Raised beds go along the south fence. Tomatoes need full sun, so they get"
        },
        {
          "line": 8,
          "snippet": "the bed nearest the shed. Basil goes next to the tomatoes. #companion-planting"
        }
      ]
    }
  ]
}
```

#### Options and exclusions

Any argument that starts with a single `-` and isn't one of the options
(`-C`, `-h`, `-w`) is an exclusion, so `notefind search pasta -tomato` just works.
Use `--` if a term would otherwise look like an option, or `-"w"` to exclude
the word "w".

JSON output:

```console
$ notefind search pruning tag:reading --json
{
  "query": {
    "terms": [
      "pruning"
    ],
    "phrases": [],
    "exclude": [],
    "tags": [
      "reading"
    ],
    "exclude_tags": [],
    "fields": [],
    "exclude_fields": []
  },
  "total": 1,
  "results": [
    {
      "path": "projects/Reading List.md",
      "line": 11,
      "matches": 1,
      "snippet": "- Notes on [[Pruning]] still to write. #todo"
    }
  ]
}
```

### tags

```console
$ notefind tags
4  #garden
2  #soil
2  #todo
1  #companion-planting
1  #log
1  #planning
1  #reading
1  #shopping
```

Counts are numbers of notes. Tags are lowercased. They come from:

- front matter: `tags: [a, b]`, `tags: a, b`, or a `tags:` key followed by
  `- a` lines (`tag:` works too);
- inline `#tags` in the body, including nested ones like `#project/alpha`.

Not counted as tags: `# Headings`, anything inside fenced code blocks or
`inline code`, URL fragments such as `https://example.com/#gardening`, link
anchors like `[[Note#Heading]]`, and pure numbers such as `#1` or `#2024-05`.
`examples/notes/projects/Reading List.md` and `watering.md` contain all of
these, and none show up above.

`notefind tags --json` prints `[{"tag": "garden", "count": 4}, ...]`.

### links

```console
$ notefind links
daily/2026-05-02.md:7: broken link -> ../projects/pruning.md
projects/Reading List.md:11: broken link -> Pruning
projects/watering.md:6: broken link -> ../manuals/timer.md
projects/watering.md:7: broken link -> Garden Plan#Beds (no heading "Beds" in Garden Plan.md)
4 broken (12 links checked in 6 notes)
$ echo $?
1
```

- `[[Wiki Link]]`, `[[Wiki Link|alias]]`, `[[Note#Heading]]` and `![[embeds]]`
  resolve by file name, case-insensitively, anywhere in the folder.
  `[[folder/Note]]` must match the end of a path.
- `[text](other.md)`, `[text](sub/other.md#anchor)` and images resolve
  relative to the linking note (a leading `/` means the notes folder).
  `%20` escapes and `<angle brackets>` are handled.
- Reference-style links (`[text][ref]`, `[text][]` and `[text]`, with a
  `[ref]: path "optional title"` definition anywhere in the note) are checked
  like `[text](path)` and reported on the line where they are *used*. Labels
  match case-insensitively; the first definition wins. A reference with no
  definition is plain text (as in CommonMark), and `[^1]:` footnotes are not
  links.
- `http(s)://`, `mailto:` and other URLs are skipped.
- Links inside code blocks and inline code are ignored.

Anchors are checked too, when the link points to a note:

- `[[Note#Heading]]` needs a heading with that text in `Note`, compared
  ignoring case, punctuation and spacing (so `[[Plan#Tasks urgent]]` matches
  `## Tasks: urgent!`). `[[Note#Parent#Child]]` needs both headings.
- `[[Note#^block-id]]` needs a line ending in `^block-id` in `Note`.
- `[text](note.md#some-heading)` accepts GitHub-style slugs (`#notes-1` for
  the second `## Notes`), Obsidian-style `#Some%20Heading`, `#^block-id` and
  `<a id="...">` anchors.
- `[[#Heading]]` and `[text](#heading)` are checked against the note they are
  in.
- ATX (`# Heading`) and setext (`Heading` + `===`) headings count; headings
  in code blocks and front matter don't.
- Anchors on other files, such as `manual.pdf#page=3`, are not checked.

`examples/notes` has one of each kind that works (`[[Compost#Ratios]]`,
`[[2026-05-02#^frost]]`, `projects/watering.md#watering-schedule`) and one
that doesn't (`[[Garden Plan#Beds]]`). Use `--no-anchors` to check only that
targets exist:

```console
$ notefind links --no-anchors
daily/2026-05-02.md:7: broken link -> ../projects/pruning.md
projects/Reading List.md:11: broken link -> Pruning
projects/watering.md:6: broken link -> ../manuals/timer.md
3 broken (12 links checked in 6 notes)
```

Exit code is 1 if any link is broken, 0 otherwise, so it can gate a CI job.

Add `--suggest` to get a "did you mean" for each broken link: the closest
existing note name, file name, heading or block ID, compared ignoring case
(at least 60% similar, by `difflib`). It catches typos (`[[Gardn Plan]]`),
renamed headings (`[[Compost#Ratio]]`) and files linked from the wrong folder,
for which it gives the path relative to the linking note. For example, with
`[[Compst]] [[Compost#Ratio]] [up](pruning.md)` in `daily/today.md`:

```console
$ notefind links --suggest
daily/today.md:1: broken link -> Compst (did you mean "Compost"?)
daily/today.md:1: broken link -> Compost#Ratio (no heading "Ratio" in Compost.md; did you mean "Compost#Ratios"?)
daily/today.md:1: broken link -> pruning.md (did you mean "../projects/pruning.md"?)
```

Links with nothing close enough (like all four in `examples/notes`) get
no suggestion. A wiki suggestion uses the bare note name unless several notes
share it, then a path; file suggestions keep the link's `#anchor`, and
heading suggestions for Markdown links are GitHub-style slugs. `--suggest`
only reports; nothing is rewritten.

#### Fixing links: `--fix`

`--fix` rewrites broken links in place with their suggestion, but only when
the suggestion is unambiguous: no other name, heading or block ID is just as
close, and only one file in the folder has the chosen name. Everything else is
reported as usual, with its suggestion, for you to decide. Start with
`--dry-run` to see what would change without touching any file:

```console
$ notefind links --fix --dry-run
daily/today.md:1: would fix Compst -> Compost
daily/today.md:1: would fix Compost#Ratio -> Compost#Ratios
daily/today.md:1: broken link -> Pln (did you mean "a/Plan"?)
would fix 2 links in 1 note, 1 broken left (3 links checked in 4 notes)
$ notefind links --fix
daily/today.md:1: fixed Compst -> Compost
daily/today.md:1: fixed Compost#Ratio -> Compost#Ratios
daily/today.md:1: broken link -> Pln (did you mean "a/Plan"?)
fixed 2 links in 1 note, 1 broken left (3 links checked in 4 notes)
```

(`Pln` is left alone because both `a/Plan.md` and `b/Plan.md` exist.)

Only the link target changes: aliases (`[[Compst|my heap]]`), embeds, link
titles, `<angle brackets>`, the note's line endings and a UTF-8 BOM are kept,
and lookalikes inside code are never touched. A reference-style link is fixed
in its `[ref]: path` definition. Notes that aren't valid UTF-8 are skipped so
their bytes stay intact. The exit code is 1 if broken links remain after the
fixes (or would remain, with `--dry-run`), 0 otherwise.

```console
$ notefind links --json
{
  "checked": 12,
  "broken": [
    {
      "path": "daily/2026-05-02.md",
      "line": 7,
      "kind": "markdown",
      "target": "../projects/pruning.md",
      "reason": "no-file"
    },
    {
      "path": "projects/Reading List.md",
      "line": 11,
      "kind": "wiki",
      "target": "Pruning",
      "reason": "no-file"
    },
    {
      "path": "projects/watering.md",
      "line": 6,
      "kind": "markdown",
      "target": "../manuals/timer.md",
      "reason": "no-file"
    },
    {
      "path": "projects/watering.md",
      "line": 7,
      "kind": "wiki",
      "target": "Garden Plan#Beds",
      "reason": "no-heading",
      "detail": "no heading \"Beds\" in Garden Plan.md"
    }
  ]
}
```

`reason` is `no-file`, `no-heading` or `no-block`; `detail` is only there for
missing anchors. With `--suggest`, every entry also has a `suggestion`: the
corrected target as a string, or `null` when nothing is close. With `--fix`,
the payload also has `dry_run` and `fixed`, a list of
`{"path", "line", "kind", "old", "new"}` (for a reference-style link, `line`
is the definition's line), and `broken` lists only the links still broken.

### backlinks

```console
$ notefind backlinks "Garden Plan"
Seed Order.md:13: -> Garden Plan
projects/Reading List.md:7: -> Garden Plan
projects/watering.md:7: -> Garden Plan#Beds
3 links from 3 notes to Garden Plan.md
```

`NOTE` can be a note name (`"Garden Plan"`), a file name (`"Garden Plan.md"`) or
a path (`projects/watering`), matched case-insensitively. Both wiki links
(including aliases and `#heading` links) and relative Markdown links, inline or
reference-style, count; a note linking to itself does not. If a name matches
notes in several folders, `backlinks` lists them and asks for a path instead
(exit code 2). It exits with 1 when nothing links to the note. `--json` prints
`{"note": ..., "backlinks": [{"path", "line", "kind", "link"}, ...]}`.

### orphans

```console
$ notefind orphans
projects/Reading List.md
1 of 6 notes have no links pointing to them
```

Notes that no *other* note links to: useful for spotting forgotten notes. It
always exits with 0, since an orphan isn't an error (daily notes and index pages
are often orphans on purpose). `--json` prints `{"total_notes": 6, "orphans": [...]}`.

### Files

Notes are `*.md` and `*.markdown` files. They are read as UTF-8 (a BOM is
stripped, undecodable bytes become `?`-style replacement characters) and CRLF
line endings are handled, so line numbers are right for files written on
Windows. Paths are always printed with `/`.

Folders with 64 or more notes are read by a small thread pool (one thread per
CPU, at most 8), which helps most on network drives and cold disk caches.
`-j N` / `--jobs N` sets the thread count for any command; `-j 1` reads one
file at a time. Output is identical either way: notes are always processed in
path order.

## Development

```bash
git clone https://github.com/Chad9100/notefind.git
cd notefind
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
```

Layout:

```
src/notefind/
  scan.py       walk the folder, read notes (BOM/CRLF handling)
  parse.py      code stripping, front matter, tags, link extraction
  search.py     query parsing, matching, ranking, snippets, highlighting
  resolve.py    mapping link targets and note names to notes
  anchors.py    headings, slugs and block IDs for #anchor checks
  linkcheck.py  resolving wiki and Markdown links and their anchors
  suggest.py    closest note, file or heading for links --suggest
  graph.py      backlinks and orphans
  cli.py        argparse front end
tests/          pytest suite using throwaway tmp_path note folders
examples/notes  made-up notes used in this README
```

See [ROADMAP.md](ROADMAP.md) for what's planned next.

## License

MIT, see [LICENSE](LICENSE).
