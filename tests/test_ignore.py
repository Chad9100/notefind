""".notefindignore: parsing patterns, skipping files and --no-ignore."""

import json

import pytest

from notefind.cli import main
from notefind.ignore import is_ignored, load_rules, parse_rules
from notefind.scan import load_notes, walk_files
from notefind.watch import snapshot


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def vault(tmp_path):
    files = {
        "a.md": "tomato [[b]]",
        "b.md": "tomato",
        "templates/daily.md": "tomato [[{{date}}]]",
        "archive/2020/old.md": "tomato [[gone]]",
        "notes/archive/keep.md": "tomato",
        "drafts/x.draft.md": "tomato",
        "inbox/scratch.md": "tomato",
    }
    for rel, text in files.items():
        _write(tmp_path / rel, text)
    return tmp_path


def test_parse_rules_skips_blanks_and_comments():
    rules = parse_rules("\n# a comment\n  templates/  \n*.draft.md\n/\n")
    assert [r.pattern for r in rules] == ["templates/", "*.draft.md"]
    assert rules[0].dir_only and not rules[0].anchored
    assert not rules[1].dir_only


@pytest.mark.parametrize(
    "pattern, rel, is_dir, expected",
    [
        ("templates/", "templates", True, True),
        ("templates/", "notes/templates", True, True),
        ("templates/", "templates", False, False),
        ("*.draft.md", "drafts/x.draft.md", False, True),
        ("*.draft.md", "x.md", False, False),
        ("/archive", "archive", True, True),
        ("/archive", "notes/archive", True, False),
        ("archive/2020", "archive/2020", True, True),
        ("archive/*", "archive/2020/old.md", False, False),
        ("archive/**", "archive/2020/old.md", False, True),
        ("**/old.md", "archive/2020/old.md", False, True),
        ("**/old.md", "old.md", False, True),
        ("ol?.md", "old.md", False, True),
        ("ol?.md", "ol/.md", False, False),
        ("a+b.md", "a+b.md", False, True),
        ("a+b.md", "aab.md", False, False),
    ],
)
def test_is_ignored(pattern, rel, is_dir, expected):
    assert is_ignored(parse_rules(pattern), rel, is_dir) is expected


def test_missing_ignore_file_means_no_rules(tmp_path):
    assert load_rules(tmp_path) == []


def test_walk_files_applies_ignore_file(vault):
    _write(vault / ".notefindignore", "templates/\n/archive/\n*.draft.md\ninbox/scratch.md\n")
    assert walk_files(vault) == ["a.md", "b.md", "notes/archive/keep.md"]
    assert len(walk_files(vault, use_ignore=False)) == 7
    assert [n.rel for n in load_notes(vault)] == ["a.md", "b.md", "notes/archive/keep.md"]
    assert len(load_notes(vault, use_ignore=False)) == 7


def test_ignore_file_with_bom_and_crlf(vault):
    (vault / ".notefindignore").write_bytes(b"\xef\xbb\xbftemplates/\r\narchive/\r\n")
    assert "templates/daily.md" not in walk_files(vault)
    assert "notes/archive/keep.md" not in walk_files(vault)


def test_cli_search_and_no_ignore(vault, capsys):
    _write(vault / ".notefindignore", "templates/\narchive/\ndrafts/\ninbox/\n")
    assert main(["search", "tomato", "-C", str(vault), "--json"]) == 0
    paths = [r["path"] for r in json.loads(capsys.readouterr().out)["results"]]
    assert paths == ["a.md", "b.md"]
    assert main(["search", "tomato", "--no-ignore", "-C", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["total"] == 7


def test_cli_links_skips_ignored_templates(vault, capsys):
    assert main(["links", "-C", str(vault), "--json"]) == 1
    targets = {b["target"] for b in json.loads(capsys.readouterr().out)["broken"]}
    assert targets == {"{{date}}", "gone"}
    _write(vault / ".notefindignore", "templates/\narchive/\n")
    assert main(["links", "-C", str(vault)]) == 0
    assert "no broken links" in capsys.readouterr().err


def test_watch_snapshot_ignores_matched_files(vault):
    _write(vault / ".notefindignore", "templates/\n")
    assert "templates/daily.md" not in snapshot(vault)
    assert "templates/daily.md" in snapshot(vault, use_ignore=False)
