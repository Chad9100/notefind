from notefind.anchors import (
    collect_anchors,
    github_slug,
    headings,
    loose_key,
    missing_markdown_anchor,
    missing_wiki_anchor,
)
from notefind.linkcheck import find_broken_links
from notefind.scan import load_notes, walk_files


def broken(root):
    files = walk_files(root)
    result, checked = find_broken_links(root, load_notes(root, files), files)
    return [(b.path, b.line, b.target, b.reason) for b in result], checked


# --- collecting headings and blocks -----------------------------------------

def test_headings_atx_setext_ignoring_front_matter_and_code():
    text = (
        "---\n# not: a heading (YAML comment)\n---\n"
        "# Title #\n"
        "#notatag-or-heading\n"
        "Setext One\n===\n"
        "Setext Two\n---\n"
        "- list item\n---\n"
        "```\n# in code\n```\n"
        "  ### [[Linked|Shown]] and [md](x.md) ###\n"
    )
    assert headings(text) == [
        "Title", "Setext One", "Setext Two", "Shown and md",
    ]


def test_github_slugs_and_loose_keys():
    assert github_slug("Tasks: Urgent (2026)!") == "tasks-urgent-2026"
    assert github_slug("C++ & Rust") == "c--rust"
    assert loose_key("Tasks: Urgent!") == loose_key("tasks-urgent") == "tasks urgent"
    assert loose_key("Café notes") == "café notes"


def test_repeated_headings_get_numbered_slugs():
    anchors = collect_anchors("# Notes\n## Notes\n## Notes\n")
    assert anchors.slugs == {"notes", "notes-1", "notes-2"}
    assert missing_markdown_anchor(anchors, "notes-2") is None
    assert missing_markdown_anchor(anchors, "notes-3") == 'no heading "notes-3"'


def test_block_ids_and_html_anchors():
    anchors = collect_anchors(
        "A paragraph. ^para-1\n^standalone\nnot^ablock\n"
        '<a id="custom"></a>\n```\nx ^incode\n```\n'
    )
    assert anchors.blocks == {"para-1", "standalone"}
    assert anchors.html_ids == {"custom"}
    assert missing_markdown_anchor(anchors, "custom") is None
    assert missing_wiki_anchor(anchors, "^PARA-1") is None
    assert missing_wiki_anchor(anchors, "^incode") == 'no block "^incode"'


def test_wiki_heading_paths_and_loose_matching():
    anchors = collect_anchors("# Plan\n## Beds: south fence\n")
    assert missing_wiki_anchor(anchors, "Beds south fence") is None
    assert missing_wiki_anchor(anchors, "Plan#Beds: South Fence") is None
    assert missing_wiki_anchor(anchors, "Plan#Paths") == 'no heading "Paths"'
    assert missing_wiki_anchor(anchors, "") is None


def test_markdown_fragment_accepts_slug_and_escaped_text():
    anchors = collect_anchors("## Watering schedule\n")
    assert missing_markdown_anchor(anchors, "watering-schedule") is None
    assert missing_markdown_anchor(anchors, "Watering%20schedule") is None
    assert missing_markdown_anchor(anchors, "watering") == 'no heading "watering"'


# --- in the link checker ------------------------------------------------------

def test_broken_anchors_in_other_notes(make_vault):
    root = make_vault({
        "index.md": (
            "[[Plan#Beds]] [[Plan#Paths]]\n"
            "[[Plan#^frost]] [[Plan#^thaw]]\n"
            "[p](./Plan.md#beds) [q](Plan.md#paths)\n"
        ),
        "Plan.md": "# Beds\nFrost warning tonight. ^frost\n",
    })
    assert broken(root) == ([
        ("index.md", 1, "Plan#Paths", "no-heading"),
        ("index.md", 2, "Plan#^thaw", "no-block"),
        ("index.md", 3, "Plan.md#paths", "no-heading"),
    ], 6)


def test_missing_file_is_reported_once_not_as_missing_anchor(make_vault):
    root = make_vault({"a.md": "[[Gone#Intro]] [x](gone.md#intro)\n"})
    assert broken(root) == ([
        ("a.md", 1, "Gone#Intro", "no-file"),
        ("a.md", 1, "gone.md#intro", "no-file"),
    ], 2)


def test_anchors_on_non_note_files_are_not_checked(make_vault):
    root = make_vault({
        "a.md": "[manual](manual.pdf#page=3) ![[diagram.png#x]]\n",
        "manual.pdf": b"%PDF",
        "diagram.png": b"png",
    })
    assert broken(root) == ([], 2)


def test_ambiguous_note_name_is_fine_if_any_match_has_the_heading(make_vault):
    root = make_vault({
        "a.md": "[[Todo#Garden]] [[Todo#Kitchen]]\n",
        "home/Todo.md": "# Kitchen\n",
        "garden/Todo.md": "# Garden\n",
    })
    assert broken(root) == ([], 2)


def test_headings_in_code_blocks_do_not_count(make_vault):
    root = make_vault({
        "a.md": "[[B#Real]] [[B#Fake]]\n",
        "B.md": "# Real\n```\n# Fake\n```\n",
    })
    assert broken(root) == ([("a.md", 1, "B#Fake", "no-heading")], 2)
