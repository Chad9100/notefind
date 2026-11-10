import json

import pytest

from notefind.cli import main
from notefind.parse import front_matter_fields
from notefind.scan import Note
from notefind.search import FieldFilter, note_title, parse_query, search


def note(rel, text):
    return Note(rel=rel, path=None, text=text)


NOTES = [
    note("daily/2026-05-01.md", "---\nstatus: done\nmood: 'good'\n---\n# Friday\nWatered the tomatoes.\n"),
    note("daily/2026-05-02.md", "# Saturday\nPlanted tomatoes.\n"),
    note("projects/Garden Plan.md", "---\ntitle: Garden Plan 2026\nstatus: Active\n---\n# Beds\nTomatoes in the sunny bed.\n"),
    note("projects/beds.md", "---\nstatus:\n  - active\n  - \"in progress\"\nowner: [Ann, Bob]\n---\nSome text.\n"),
    note("misc.md", "```\n# not a title\n```\n# Misc notes\nTomato soup.\n"),
]


def paths(query):
    return sorted(h.path for h in search(NOTES, parse_query(query)))


# --- front matter ---------------------------------------------------------

def test_front_matter_fields_shapes():
    fm = [
        "Status: done",
        "title: \"Quoted: title\"",
        "aliases: [one, 'two', ]",
        "people:",
        "  - Ann",
        "  - Bob",
        "nested:",
        "  child: x",
        "summary: |",
        "  long text",
        "status: ignored second",
    ]
    assert front_matter_fields(fm) == {
        "status": ["done"],
        "title": ["Quoted: title"],
        "aliases": ["one", "two"],
        "people": ["Ann", "Bob"],
        "nested": [],
        "summary": [],
    }


def test_note_title_prefers_front_matter_then_h1_then_file_name():
    assert note_title(NOTES[2]) == "Garden Plan 2026"
    assert note_title(NOTES[1]) == "Saturday"
    # A "# line" inside a code block is not a heading.
    assert note_title(NOTES[4]) == "Misc notes"
    assert note_title(NOTES[3]) == "beds"
    assert note_title(note("a/[[x]].md", "## Only level two\n")) == "[[x]]"


# --- query parsing --------------------------------------------------------

def test_parse_field_filters():
    q = parse_query(["path:daily/", "-Status:done", "title:plan", "tomato"])
    assert q.fields == [FieldFilter("path", "daily/"), FieldFilter("title", "plan")]
    assert q.exclude_fields == [FieldFilter("status", "done")]
    assert q.terms == ["tomato"]


def test_parse_quoted_field_values():
    q = parse_query('status:"in progress" -owner:"Ann"')
    assert q.fields == [FieldFilter("status", "in progress")]
    assert q.exclude_fields == [FieldFilter("owner", "Ann")]
    # The shell already removed the quotes around the value.
    assert parse_query(["status:in progress"]).fields == [FieldFilter("status", "in progress")]


def test_things_that_are_not_field_filters():
    q = parse_query(['"status:done"', "https://example.com", "06:00", "todo:", "note: buy milk"])
    assert q.fields == [] and q.exclude_fields == []
    assert q.phrases == ["status:done", "note: buy milk"]
    assert q.terms == ["https://example.com", "06:00", "todo:"]


def test_tags_key_is_the_tag_filter_and_field_only_query_is_not_empty():
    assert parse_query(["tags:Garden"]).tags == ["garden"]
    assert not parse_query(["status:done"]).is_empty()
    assert parse_query(["-status:done"]).is_empty()


# --- matching -------------------------------------------------------------

def test_path_filter_is_a_case_insensitive_substring():
    assert paths(["path:DAILY/"]) == ["daily/2026-05-01.md", "daily/2026-05-02.md"]
    assert paths(["tomato", "-path:daily/"]) == ["misc.md", "projects/Garden Plan.md"]


def test_title_filter_uses_note_title():
    assert paths(["title:plan"]) == ["projects/Garden Plan.md"]
    # "Beds" is a heading in Garden Plan, but its title comes from front matter.
    assert paths(["title:beds"]) == ["projects/beds.md"]
    assert paths(["title:misc", "soup"]) == ["misc.md"]


def test_front_matter_filter_matches_whole_values_and_list_items():
    assert paths(["status:active"]) == ["projects/Garden Plan.md", "projects/beds.md"]
    assert paths(["status:act"]) == []
    assert paths(['status:"in progress"']) == ["projects/beds.md"]
    assert paths(["owner:bob"]) == ["projects/beds.md"]
    assert paths(["mood:good"]) == ["daily/2026-05-01.md"]


def test_excluding_a_field_keeps_notes_without_the_key():
    assert paths(["tomato", "-status:done"]) == [
        "daily/2026-05-02.md", "misc.md", "projects/Garden Plan.md",
    ]


def test_field_only_hit_points_at_first_body_line():
    [hit] = search(NOTES, parse_query(["status:done"]))
    assert (hit.path, hit.line, hit.matches, hit.snippet) == ("daily/2026-05-01.md", 5, 0, "# Friday")


def test_fields_combine_with_terms_tags_and_each_other():
    assert paths(["path:projects/", "status:active", "tomatoes"]) == ["projects/Garden Plan.md"]
    assert paths(["path:projects/", "status:done"]) == []


# --- CLI ------------------------------------------------------------------

@pytest.fixture
def vault(make_vault):
    return make_vault({
        "daily/2026-05-01.md": "---\nstatus: done\n---\nTomato day.\n",
        "projects/plan.md": "---\ntitle: Big Plan\nstatus: draft\n---\nTomato plan.\n",
    })


def test_cli_field_filters(vault, capsys):
    code = main(["search", "tomato", "-status:done", "-C", str(vault), "--color", "never"])
    out, err = capsys.readouterr()
    assert code == 0
    assert out.splitlines() == ["projects/plan.md:5: Tomato plan."]
    assert "1 note matched" in err


def test_cli_field_only_query_and_json(vault, capsys):
    code = main(["search", "title:big", "path:projects", "-C", str(vault), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert code == 0
    assert data["query"]["fields"] == ["title:big", "path:projects"]
    assert data["query"]["exclude_fields"] == []
    assert [r["path"] for r in data["results"]] == ["projects/plan.md"]


def test_cli_no_match_on_missing_key(vault, capsys):
    assert main(["search", "priority:high", "-C", str(vault)]) == 1
    assert "no notes matched" in capsys.readouterr().err
