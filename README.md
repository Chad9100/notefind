# notefind

Search and check a folder of Markdown notes from the command line.

`notefind` works on the kind of notes folder people keep in Obsidian, Logseq or
plain directories. It does these things:

- **search**: case-insensitive full-text search with AND-ed terms, `"phrases"`,
  `-exclusions` and `tag:` filters, ranked by number of matches, with the
  matching line shown and highlighted;
- **tags**: list every tag (front matter and inline `#tags`) with note counts;
- **links**: find broken `[[wiki links]]` and relative `[markdown](links.md)`;
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
it somewhere else. All commands accept `--json`.

The output below is real output from the made-up notes in
[`examples/notes/`](examples/notes), run from inside that folder.

### search

```
notefind search QUERY... [-C FOLDER] [--limit N] [--json] [--color auto|always|never]
```

| Query               | Meaning                                         |
|---------------------|-------------------------------------------------|
| `tomato basil`      | notes containing both words (AND)               |
| `"full sun"`        | the exact phrase (any whitespace between words) |
| `-blight`           | drop notes containing "blight"                  |
| `-"cream sauce"`    | drop notes containing the phrase               |
| `tag:garden`        | only notes tagged `garden` (or `garden/...`)    |
| `-tag:draft`        | drop notes tagged `draft`                       |

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
Seed Order.md:8: | Cherry tomato   | 2       |
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
5 notes matched
```

`Garden Plan.md` comes first because it mentions tomatoes twice.

```console
$ notefind search tomato basil -blight
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
Seed Order.md:8: | Cherry tomato   | 2       |
daily/2026-05-02.md:3: Planted the cherry tomatoes and basil today. Covered the lettuce
projects/watering.md:3: Water tomatoes deeply twice a week; basil likes lighter, more frequent
4 notes matched

$ notefind search "full sun"
Garden Plan.md:7: Raised beds go along the south fence. Tomatoes need full sun, so they get
1 note matched

$ notefind search tag:soil
Compost.md:6: # Compost
projects/Reading List.md:4: # Reading list
2 notes matched

$ notefind search zucchini
no notes matched
$ echo $?
1
```

Any argument that starts with a single `-` and isn't one of the options
(`-C`, `-h`) is an exclusion, so `notefind search pasta -tomato` just works.
Use `--` if a term would otherwise look like an option.

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
    "exclude_tags": []
  },
  "total": 1,
  "results": [
    {
      "path": "projects/Reading List.md",
      "line": 10,
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
projects/Reading List.md:10: broken link -> Pruning
projects/watering.md:6: broken link -> ../manuals/timer.md
3 broken (10 links checked in 6 notes)
$ echo $?
1
```

- `[[Wiki Link]]`, `[[Wiki Link|alias]]`, `[[Note#Heading]]` and `![[embeds]]`
  resolve by file name, case-insensitively, anywhere in the folder.
  `[[folder/Note]]` must match the end of a path. `[[#Heading]]` is a link
  into the same note and is not checked.
- `[text](other.md)`, `[text](sub/other.md#anchor)` and images resolve
  relative to the linking note (a leading `/` means the notes folder).
  `%20` escapes and `<angle brackets>` are handled.
- Reference-style links (`[text][ref]`, `[text][]` and `[text]`, with a
  `[ref]: path "optional title"` definition anywhere in the note) are checked
  like `[text](path)` and reported on the line where they are *used*. Labels
  match case-insensitively; the first definition wins. A reference with no
  definition is plain text (as in CommonMark), and `[^1]:` footnotes are not
  links.
- `http(s)://`, `mailto:` and other URLs, and pure `#anchors`, are skipped.
- Links inside code blocks and inline code are ignored.

Headings and anchors themselves are not verified yet, only the target file.
Exit code is 1 if any link is broken, 0 otherwise, so it can gate a CI job.

```console
$ notefind links --json
{
  "checked": 10,
  "broken": [
    {
      "path": "daily/2026-05-02.md",
      "line": 7,
      "kind": "markdown",
      "target": "../projects/pruning.md"
    },
    {
      "path": "projects/Reading List.md",
      "line": 10,
      "kind": "wiki",
      "target": "Pruning"
    },
    {
      "path": "projects/watering.md",
      "line": 6,
      "kind": "markdown",
      "target": "../manuals/timer.md"
    }
  ]
}
```

### backlinks

```console
$ notefind backlinks "Garden Plan"
Seed Order.md:12: -> Garden Plan
projects/Reading List.md:6: -> Garden Plan
2 links from 2 notes to Garden Plan.md
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
daily/2026-05-02.md
projects/Reading List.md
2 of 6 notes have no links pointing to them
```

Notes that no *other* note links to: useful for spotting forgotten notes. It
always exits with 0, since an orphan isn't an error (daily notes and index pages
are often orphans on purpose). `--json` prints `{"total_notes": 6, "orphans": [...]}`.

### Files

Notes are `*.md` and `*.markdown` files. They are read as UTF-8 (a BOM is
stripped, undecodable bytes become `?`-style replacement characters) and CRLF
line endings are handled, so line numbers are right for files written on
Windows. Paths are always printed with `/`.

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
  linkcheck.py  resolving wiki and Markdown links
  cli.py        argparse front end
tests/          pytest suite using throwaway tmp_path note folders
examples/notes  made-up notes used in this README
```

See [ROADMAP.md](ROADMAP.md) for what's planned next.

## License

MIT, see [LICENSE](LICENSE).
