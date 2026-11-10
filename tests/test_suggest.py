import json

from notefind.cli import main
from notefind.linkcheck import find_broken_links
from notefind.scan import load_notes, walk_files
from notefind.suggest import (
    FileSuggester, closest, suggest_markdown_fragment, suggest_wiki_fragment,
)


def suggestions(root):
    files = walk_files(root)
    result, _ = find_broken_links(root, load_notes(root, files), files, suggest=True)
    return [(b.target, b.suggestion) for b in result]


# --- closest() ------------------------------------------------------------

def test_closest_ignores_case_and_rejects_distant_words():
    assert closest("gardn plan", ["Garden Plan", "Compost"]) == "Garden Plan"
    assert closest("Zebra", ["Garden Plan", "Compost"]) is None
    assert closest("", ["a"]) is None


def test_closest_breaks_ties_by_sort_order():
    assert closest("cat", ["cap", "car"]) == "cap"


# --- file and note names --------------------------------------------------

def test_wiki_suggests_note_stem_and_attachment_names():
    s = FileSuggester(["Garden Plan.md", "img/diagram.png", "daily/Log.markdown"])
    assert s.wiki("Gardn Plan") == "Garden Plan"
    assert s.wiki("garden-plan.md") == "Garden Plan"
    assert s.wiki("diagrm.png") == "diagram.png"
    assert s.wiki("Lgo") == "Log"  # a .markdown note counts too
    assert s.wiki("Zebra") is None


def test_wiki_suggests_a_path_when_the_name_is_ambiguous_or_had_a_folder():
    s = FileSuggester(["a/Notes.md", "b/Notes.md", "x/Plan.md"])
    assert s.wiki("Note") == "a/Notes"
    assert s.wiki("y/Plan") == "x/Plan"


def test_markdown_suggests_a_path_relative_to_the_linking_note():
    s = FileSuggester(["archive/pruning guide.md", "top.md"])
    assert s.markdown("sub/a.md", "pruning%20guide.md") == "../archive/pruning%20guide.md"
    assert s.markdown("a.md", "tpo.md") == "top.md"
    assert s.markdown("sub/a.md", "/archive/pruning-guid.md") == "/archive/pruning%20guide.md"
    assert s.markdown("a.md", "zebra.txt") is None


def test_markdown_note_suffix_does_not_make_names_look_alike():
    s = FileSuggester(["projects/watering.md"])
    assert s.markdown("daily/a.md", "../projects/pruning.md") is None
    assert s.markdown("daily/a.md", "../projects/waterng.md") == "../projects/watering.md"


# --- anchors ---------------------------------------------------------------

def test_fragment_suggestions_for_headings_and_blocks():
    text = "# Intro\n## Tasks: urgent\n## Setup\nA line ^frost\n"
    blocks = {"frost"}
    assert suggest_wiki_fragment(text, "Task urgnt", blocks) == "Tasks: urgent"
    assert suggest_wiki_fragment(text, "Intro#Stup", blocks) == "Intro#Setup"
    assert suggest_wiki_fragment(text, "^frst", blocks) == "^frost"
    assert suggest_wiki_fragment(text, "Unrelated words here", blocks) is None
    assert suggest_markdown_fragment(text, "tasks-urgnt", blocks) == "tasks-urgent"
    assert suggest_markdown_fragment(text, "Stup", blocks) == "setup"
    assert suggest_markdown_fragment(text, "^frots", blocks) == "^frost"


# --- through the link checker ---------------------------------------------

def test_broken_links_get_suggestions_only_when_asked(make_vault):
    root = make_vault({
        "Garden Plan.md": "# Beds\nSoil. ^soil\n",
        "sub/a.md": (
            "[[Gardn Plan]] [[Garden Plan#Bed]] [[Garden Plan#^soli]] [[Zebra]]\n"
            "[up](../Garden%20Plan.md#bds) [moved](Garden%20Plan.md) [[#Intr]]\n"
            "# Intro\n"
        ),
    })
    assert suggestions(root) == [
        ("Gardn Plan", "Garden Plan"),
        ("Garden Plan#Bed", "Garden Plan#Beds"),
        ("Garden Plan#^soli", "Garden Plan#^soil"),
        ("Zebra", ""),
        ("#Intr", "#Intro"),  # wiki links come before Markdown ones on a line
        ("../Garden%20Plan.md#bds", "../Garden%20Plan.md#beds"),
        ("Garden%20Plan.md", "../Garden%20Plan.md"),
    ]
    files = walk_files(root)
    plain, _ = find_broken_links(root, load_notes(root, files), files)
    assert all(b.suggestion == "" for b in plain)


def test_cli_suggest_text_and_json(make_vault, capsys):
    root = make_vault({
        "Compost.md": "# Ratios\n",
        "a.md": "[[Compst]] [[Compost#Ratio]] [[Zebra]]\n",
    })
    code = main(["links", "-C", str(root), "--suggest"])
    out, err = capsys.readouterr()
    assert code == 1
    assert out.splitlines() == [
        'a.md:1: broken link -> Compst (did you mean "Compost"?)',
        'a.md:1: broken link -> Compost#Ratio '
        '(no heading "Ratio" in Compost.md; did you mean "Compost#Ratios"?)',
        "a.md:1: broken link -> Zebra",
    ]
    assert "3 broken" in err

    main(["links", "-C", str(root), "--suggest", "--json"])
    data = json.loads(capsys.readouterr().out)
    assert [b["suggestion"] for b in data["broken"]] == ["Compost", "Compost#Ratios", None]

    main(["links", "-C", str(root), "--json"])
    data = json.loads(capsys.readouterr().out)
    assert all("suggestion" not in b for b in data["broken"])
