import json

import pytest

from notefind.cli import main
from notefind.graph import NoteResolver, backlinks, link_edges, orphans
from notefind.scan import load_notes

VAULT = {
    "Garden Plan.md": "# Plan\nSee [[Seed Order]] and [[compost|the heap]].\n",
    "Seed Order.md": "Back to [[Garden Plan#Beds]].\nAlso [[Seed Order]] (self).\n",
    "Compost.md": "Feeds the [plan](Garden%20Plan.md).\n",
    "projects/watering.md": "Schedule from [[Garden Plan]].\n[up](../Compost.md)\n",
    "daily/2026-05-02.md": "Nothing links here.\n```\n[[Garden Plan]] in code\n```\n",
    "notes.txt": "[[Garden Plan]] but not a note\n",
}


@pytest.fixture
def vault(make_vault):
    return make_vault(VAULT)


def edges_for(root):
    notes = load_notes(root)
    return notes, link_edges(notes)


def test_backlinks_wiki_and_markdown(vault):
    _, edges = edges_for(vault)
    found = [(e.source, e.line, e.kind) for e in backlinks(edges, "Garden Plan.md")]
    assert found == [
        ("Compost.md", 1, "markdown"),
        ("Seed Order.md", 1, "wiki"),
        ("projects/watering.md", 1, "wiki"),
    ]


def test_code_blocks_and_non_notes_do_not_count(vault):
    _, edges = edges_for(vault)
    sources = {e.source for e in backlinks(edges, "Garden Plan.md")}
    assert "daily/2026-05-02.md" not in sources
    assert "notes.txt" not in sources


def test_alias_and_case_insensitive_wiki_links(vault):
    _, edges = edges_for(vault)
    assert [e.source for e in backlinks(edges, "Compost.md")] == [
        "Garden Plan.md", "projects/watering.md"]


def test_self_links_are_not_backlinks(vault):
    _, edges = edges_for(vault)
    assert [e.source for e in backlinks(edges, "Seed Order.md")] == ["Garden Plan.md"]


def test_orphans(vault):
    notes, edges = edges_for(vault)
    # watering and the daily note are linked from nowhere; Seed Order only
    # links to itself besides being linked from Garden Plan, so it's not an orphan.
    assert orphans(notes, edges) == ["daily/2026-05-02.md", "projects/watering.md"]


def test_a_note_linking_only_to_itself_is_an_orphan(make_vault):
    root = make_vault({"Solo.md": "I mention [[Solo]] myself.\n"})
    notes, edges = edges_for(root)
    assert orphans(notes, edges) == ["Solo.md"]


def test_markdown_links_outside_the_folder_are_ignored(make_vault):
    root = make_vault({"a.md": "[x](../../etc/passwd)\n[y](/b.md)\n", "b.md": "hi\n"})
    _, edges = edges_for(root)
    assert [(e.source, e.target) for e in edges] == [("a.md", "b.md")]


@pytest.mark.parametrize("name, expected", [
    ("Garden Plan", ["Garden Plan.md"]),
    ("garden plan", ["Garden Plan.md"]),
    ("Garden Plan.md", ["Garden Plan.md"]),
    ("projects/watering", ["projects/watering.md"]),
    ("watering", ["projects/watering.md"]),
    ("Garden Plan#Beds", ["Garden Plan.md"]),
    ("nope", []),
    ("", []),
])
def test_resolver_by_name(vault, name, expected):
    assert NoteResolver(load_notes(vault)).by_name(name) == expected


def test_same_name_in_two_folders_is_ambiguous(make_vault):
    root = make_vault({"a/Todo.md": "x\n", "b/Todo.md": "y\n", "c.md": "[[a/Todo]]\n"})
    resolver = NoteResolver(load_notes(root))
    assert resolver.by_name("Todo") == ["a/Todo.md", "b/Todo.md"]
    assert resolver.by_name("a/Todo") == ["a/Todo.md"]


def test_cli_backlinks_text(vault, capsys):
    assert main(["backlinks", "garden plan", "-C", str(vault)]) == 0
    out, err = capsys.readouterr()
    assert "Compost.md:1: -> Garden%20Plan.md" in out
    assert "projects/watering.md:1: -> Garden Plan" in out
    assert "3 links from 3 notes to Garden Plan.md" in err


def test_cli_backlinks_json(vault, capsys):
    assert main(["backlinks", "Seed Order", "-C", str(vault), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {
        "note": "Seed Order.md",
        "backlinks": [{"path": "Garden Plan.md", "line": 2, "kind": "wiki",
                       "link": "Seed Order"}],
    }


def test_cli_backlinks_none_found_exits_1(vault, capsys):
    assert main(["backlinks", "watering", "-C", str(vault)]) == 1
    assert "nothing links to projects/watering.md" in capsys.readouterr().err


def test_cli_backlinks_unknown_or_ambiguous_note_exits_2(make_vault, capsys):
    root = make_vault({"a/Todo.md": "x\n", "b/Todo.md": "y\n"})
    assert main(["backlinks", "Missing", "-C", str(root)]) == 2
    assert main(["backlinks", "Todo", "-C", str(root)]) == 2
    err = capsys.readouterr().err
    assert "no note named 'Missing'" in err
    assert "matches 2 notes" in err and "a/Todo.md" in err and "b/Todo.md" in err


def test_cli_orphans(vault, capsys):
    assert main(["orphans", "-C", str(vault)]) == 0
    out, err = capsys.readouterr()
    assert out.split() == ["daily/2026-05-02.md", "projects/watering.md"]
    assert "2 of 5 notes have no links pointing to them" in err


def test_cli_orphans_json(vault, capsys):
    assert main(["orphans", "-C", str(vault), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "total_notes": 5, "orphans": ["daily/2026-05-02.md", "projects/watering.md"]}
