import json

from notefind.cli import main
from notefind.fix import fix_links
from notefind.linkcheck import find_broken_links
from notefind.scan import load_notes, walk_files
from notefind.suggest import FileSuggester, closest


def broken_links(root):
    files = walk_files(root)
    return find_broken_links(root, load_notes(root, files), files, suggest=True)[0]


# --- what counts as unambiguous ---------------------------------------------

def test_closest_unique_refuses_ties():
    assert closest("cat", ["cap", "car"]) == "cap"
    assert closest("cat", ["cap", "car"], unique=True) is None
    assert closest("cat", ["cap", "dog"], unique=True) == "cap"


def test_unique_file_suggester_refuses_several_files_with_the_name():
    s = FileSuggester(["a/Notes.md", "b/Notes.md", "x/img.png", "y/img.png"], unique=True)
    assert s.wiki("Note") is None
    assert s.wiki("imgg.png") is None
    assert s.markdown("top.md", "Note.md") is None
    assert FileSuggester(["a/Notes.md"], unique=True).wiki("Note") == "Notes"


def test_broken_links_are_flagged_unambiguous_only_when_safe(make_vault):
    root = make_vault({
        "Compost.md": "# Ratios\n",
        "a/Plan.md": "", "b/Plan.md": "",
        "today.md": "[[Compst]] [[Pln]] [[Zebra]]\n",
    })
    got = [(b.target, b.suggestion, b.unambiguous) for b in broken_links(root)]
    assert got == [
        ("Compst", "Compost", True),
        ("Pln", "a/Plan", False),
        ("Zebra", "", False),
    ]


# --- rewriting ----------------------------------------------------------------

def test_fix_rewrites_only_the_target_and_keeps_everything_else(make_vault):
    root = make_vault({
        "Compost.md": "# Ratios\nA line ^mix\n",
        "sub/today.md": (
            "[[Compst|my heap]] ![[Compost#Ratio]] `[[Compst]]` [[Compost#^mx]]\n"
            "```\n[[Compst]]\n```\n"
            '[up](<../Compst.md> "title") [x](../Compost.md#ratio)\n'
        ),
    })
    fixes = fix_links(root, broken_links(root))
    assert [(f.line, f.old, f.new) for f in fixes] == [
        (1, "Compst", "Compost"),
        (1, "Compost#Ratio", "Compost#Ratios"),
        (1, "Compost#^mx", "Compost#^mix"),
        (5, "../Compst.md", "../Compost.md"),
        (5, "../Compost.md#ratio", "../Compost.md#ratios"),
    ]
    assert (root / "sub/today.md").read_text(encoding="utf-8") == (
        "[[Compost|my heap]] ![[Compost#Ratios]] `[[Compst]]` [[Compost#^mix]]\n"
        "```\n[[Compst]]\n```\n"
        '[up](<../Compost.md> "title") [x](../Compost.md#ratios)\n'
    )
    assert broken_links(root) == []


def test_fix_keeps_crlf_and_bom_and_fixes_reference_definitions(make_vault):
    root = make_vault({
        "Compost.md": "",
        "a.md": b"\xef\xbb\xbf[one][r] and [two][r]\r\n\r\n[r]: Compst.md 'heap'\r\n",
    })
    fixes = fix_links(root, broken_links(root))
    assert [(f.line, f.new) for f in fixes] == [(3, "Compost.md")]
    assert (root / "a.md").read_bytes() == (
        b"\xef\xbb\xbf[one][r] and [two][r]\r\n\r\n[r]: Compost.md 'heap'\r\n"
    )


def test_fix_skips_files_that_are_not_utf8(make_vault):
    raw = b"[[Compst]] caf\xe9\n"
    root = make_vault({"Compost.md": "", "a.md": raw})
    assert fix_links(root, broken_links(root)) == []
    assert (root / "a.md").read_bytes() == raw


def test_two_identical_broken_links_on_one_line_are_both_fixed(make_vault):
    root = make_vault({"Compost.md": "", "a.md": "[[Compst]] and [[Compst]]\n"})
    assert len(fix_links(root, broken_links(root))) == 2
    assert (root / "a.md").read_text(encoding="utf-8") == "[[Compost]] and [[Compost]]\n"


# --- command line ---------------------------------------------------------------

def vault_for_cli(make_vault):
    return make_vault({
        "Compost.md": "# Ratios\n",
        "a/Plan.md": "", "b/Plan.md": "",
        "today.md": "[[Compst]] [[Compost#Ratio]] [[Pln]] [[Zebra]]\n",
    })


def test_cli_dry_run_reports_without_writing(make_vault, capsys):
    root = vault_for_cli(make_vault)
    before = (root / "today.md").read_bytes()
    code = main(["links", "-C", str(root), "--fix", "--dry-run"])
    out, err = capsys.readouterr()
    assert code == 1
    assert out.splitlines() == [
        "today.md:1: would fix Compst -> Compost",
        "today.md:1: would fix Compost#Ratio -> Compost#Ratios",
        'today.md:1: broken link -> Pln (did you mean "a/Plan"?)',
        "today.md:1: broken link -> Zebra",
    ]
    assert "would fix 2 links in 1 note, 2 broken left" in err
    assert (root / "today.md").read_bytes() == before


def test_cli_fix_writes_and_exits_0_when_nothing_is_left(make_vault, capsys):
    root = make_vault({"Compost.md": "", "today.md": "[[Compst]]\n"})
    assert main(["links", "-C", str(root), "--fix"]) == 0
    out, err = capsys.readouterr()
    assert out.splitlines() == ["today.md:1: fixed Compst -> Compost"]
    assert "fixed 1 link in 1 note, no broken links left" in err
    assert (root / "today.md").read_text(encoding="utf-8") == "[[Compost]]\n"


def test_cli_fix_json(make_vault, capsys):
    root = vault_for_cli(make_vault)
    assert main(["links", "-C", str(root), "--fix", "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is False
    assert data["fixed"] == [
        {"path": "today.md", "line": 1, "kind": "wiki", "old": "Compst", "new": "Compost"},
        {"path": "today.md", "line": 1, "kind": "wiki",
         "old": "Compost#Ratio", "new": "Compost#Ratios"},
    ]
    assert [b["target"] for b in data["broken"]] == ["Pln", "Zebra"]


def test_cli_dry_run_needs_fix(make_vault, capsys):
    root = make_vault({"a.md": ""})
    assert main(["links", "-C", str(root), "--dry-run"]) == 2
    assert "--dry-run only works with --fix" in capsys.readouterr().err
