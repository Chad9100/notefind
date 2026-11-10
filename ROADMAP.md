# Roadmap

Estimates are rough working hours for one person, including tests and docs.

## v0.1 - first working version (done)

- [x] Folder scan that skips hidden directories and `node_modules`
- [x] UTF-8 with BOM stripping, replacement of bad bytes, CRLF handling
- [x] `search`: AND-ed terms, `"phrases"`, `-exclusions`, `tag:` / `-tag:` filters
- [x] Ranking by match count, ties by path; `path:line:` with a snippet
- [x] Match highlighting with `--color auto|always|never` and `NO_COLOR`
- [x] `tags`: front matter (three styles) plus inline `#tags`, ignoring code,
      headings, URLs, anchors and pure numbers
- [x] `links`: broken `[[wiki]]` (alias, heading, embeds, folder paths) and
      relative Markdown links, ignoring code and external URLs
- [x] `--json` for every command, meaningful exit codes
- [x] pytest suite, CI on Ubuntu and Windows with Python 3.10 / 3.12 / 3.13

## v0.2 - better link checking (about 7 h)

- [x] Verify `#Heading` and `#^block` anchors, not just target files (3 h)
- [x] `backlinks NOTE`: list notes linking to a note, with line numbers (2 h)
- [x] `orphans`: notes that nothing links to (1 h)
- [x] Reference-style Markdown links (`[text][ref]` + `[ref]: path`) (1 h)

## v0.3 - search quality (about 8 h)

- [x] Fuzzy matching (`--fuzzy`) with a typo tolerance based on edit distance (3 h)
- [x] Whole-word mode (`-w`) and regex mode (`--regex`) (2 h)
- [x] Field filters: `path:daily/`, `title:`, front matter keys (`status:done`) (2 h)
- [x] Show every matching line per note with `--all-lines` (1 h)

## v0.4 - big vaults (about 7 h)

- [ ] Optional cached index (`.notefind-cache`, keyed by mtime and size) so
      repeated runs on 10k+ notes only re-read changed files (4 h)
- [x] Parallel reading on cold runs, with `-j/--jobs N` (1 h)
- [ ] Benchmarks on a generated 20k-note vault in CI (2 h)

## v0.5 - maintenance commands (about 9 h)

- [x] `rename OLD NEW`: rename a note (in its folder) and rewrite every wiki
      and Markdown link to it; `--dry-run` lists the rewrites (3 h; split)
- [ ] `rename` across folders: also rewrite the moved note's own relative
      links, and show real unified diffs with `--dry-run` (2 h)
- [x] `links --suggest`: did-you-mean fixes for broken links (closest note,
      file, heading or block ID) (2 h)
- [x] `links --fix`: apply suggestions that are unambiguous, with `--dry-run`
      showing the changes first (2 h)

## v0.6 - reports and watching (about 6 h)

- [x] `report --html`: single-file HTML page with tags, broken links and
      orphans (3 h)
- [x] `watch`: re-run `links` (or any command) when notes change, polling only,
      no dependencies (3 h)

## v1.0 - release (about 4 h)

- [x] Extra ignore patterns in a `.notefindignore` file, with `--no-ignore`
      (1 h; split out of the config file item)
- [x] Config file (`.notefind.toml`) for command defaults such as `--limit`
      and `--color`; needs a small TOML fallback for Python 3.10 (1 h)
- [ ] Publish to PyPI with trusted publishing from a tagged release (1 h)
- [ ] Stable, documented JSON schema; changelog (1 h)

Total planned after v0.1: about 41 hours.
