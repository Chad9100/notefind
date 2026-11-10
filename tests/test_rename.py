import json

import pytest

from notefind.cli import main
from notefind.rename import RenameError, new_filename


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def read(root, rel):
    return (root / rel).read_bytes().decode("utf-8")


def test_new_filename_keeps_the_extension_and_refuses_folders():
    assert new_filename("a/Plan.md", "Schedule") == "Schedule.md"
    assert new_filename("a/Plan.markdown", "Schedule") == "Schedule.markdown"
    assert new_filename("a/Plan.md", "Schedule.markdown") == "Schedule.markdown"
    for bad in ("x/Schedule", "x\\Schedule", "  ", ".md", ".hidden"):
        with pytest.raises(RenameError):
            new_filename("a/Plan.md", bad)


def test_rename_rewrites_wiki_links_in_their_own_style(make_vault, capsys):
    root = make_vault({
        "Plan.md": "# Beds\nself [[Plan#Beds]]\n",
        "daily/today.md": (
            "[[Plan]] and [[plan|the plan]] and ![[Plan.md]]\n"
            "[[Plan#Beds]] [[Other]]\n"
        ),
        "Other.md": "x\n",
    })
    code, out, err = run(capsys, "rename", "Plan", "Schedule", "-C", str(root))
    assert code == 0
    assert not (root / "Plan.md").exists()
    assert read(root, "Schedule.md") == "# Beds\nself [[Schedule#Beds]]\n"
    assert read(root, "daily/today.md") == (
        "[[Schedule]] and [[Schedule|the plan]] and ![[Schedule.md]]\n"
        "[[Schedule#Beds]] [[Other]]\n"
    )
    assert "renamed Plan.md -> Schedule.md" in out
    assert "Schedule.md:2: Plan#Beds -> Schedule#Beds" in out
    assert "rewrote 5 links in 2 notes" in err


def test_rename_rewrites_markdown_links_and_keeps_line_endings(make_vault, capsys):
    root = make_vault({
        "garden/Plan.md": "x\n",
        "garden/see.md": "",
        "top.md": "",
    })
    (root / "garden/see.md").write_bytes(
        b"\xef\xbb\xbf[a](Plan.md) [b](./Plan.md#beds) [c](Plan)\r\n[d](<Plan.md>)\r\n"
    )
    (root / "top.md").write_bytes(b"[e](garden/Plan.md?x=1) [f](/garden/Plan.md)\n")
    code, out, err = run(capsys, "rename", "garden/Plan.md", "Garden Plan", "-C", str(root))
    assert code == 0
    assert (root / "garden/Garden Plan.md").exists()
    assert (root / "garden/see.md").read_bytes() == (
        b"\xef\xbb\xbf[a](Garden Plan.md) [b](./Garden Plan.md#beds) [c](Garden Plan)\r\n"
        b"[d](<Garden Plan.md>)\r\n"
    )
    assert (root / "top.md").read_bytes() == (
        b"[e](garden/Garden Plan.md?x=1) [f](/garden/Garden Plan.md)\n"
    )


def test_rename_keeps_percent_encoding(make_vault, capsys):
    root = make_vault({"Plan.md": "", "t.md": "[a](Plan.md) [b](My%20Plan.md)\n",
                       "My Plan.md": ""})
    code, *_ = run(capsys, "rename", "My Plan", "Big Plan", "-C", str(root))
    assert code == 0
    assert read(root, "t.md") == "[a](Plan.md) [b](Big%20Plan.md)\n"


def test_rename_leaves_code_and_other_notes_alone(make_vault, capsys):
    root = make_vault({
        "Plan.md": "",
        "Plan 2.md": "",
        "t.md": "`[[Plan]]` [[Plan 2]]\n```\n[[Plan]]\n```\n[[Plan]]\n",
    })
    code, *_ = run(capsys, "rename", "Plan", "Schedule", "-C", str(root))
    assert code == 0
    assert read(root, "t.md") == "`[[Plan]]` [[Plan 2]]\n```\n[[Plan]]\n```\n[[Schedule]]\n"


def test_rename_uses_a_path_when_the_new_name_is_shared(make_vault, capsys):
    root = make_vault({
        "a/Plan.md": "", "b/Notes.md": "",
        "t.md": "[[Plan]] [[a/Plan]] [[a/plan.md]]\n",
    })
    code, *_ = run(capsys, "rename", "a/Plan", "Notes", "-C", str(root))
    assert code == 0
    assert read(root, "t.md") == "[[a/Notes]] [[a/Notes]] [[a/Notes.md]]\n"


def test_rename_skips_links_that_were_ambiguous_before(make_vault, capsys):
    root = make_vault({
        "a/Plan.md": "", "b/Plan.md": "",
        "t.md": "[[Plan]] [[a/Plan]]\n",
    })
    code, out, err = run(capsys, "rename", "a/Plan", "Schedule", "-C", str(root))
    assert code == 0
    assert read(root, "t.md") == "[[Plan]] [[a/Schedule]]\n"
    assert "t.md:1: left alone, 'Plan' also matches other notes" in err


def test_rename_dry_run_writes_nothing(make_vault, capsys):
    root = make_vault({"Plan.md": "", "t.md": "[[Plan]]\n"})
    code, out, err = run(capsys, "rename", "Plan", "Schedule", "--dry-run", "-C", str(root))
    assert code == 0
    assert (root / "Plan.md").exists() and not (root / "Schedule.md").exists()
    assert read(root, "t.md") == "[[Plan]]\n"
    assert "would rename Plan.md -> Schedule.md" in out
    assert "t.md:1: Plan -> Schedule" in out
    assert "would rewrite 1 link in 1 note" in err


def test_rename_refuses_unknown_ambiguous_and_existing(make_vault, capsys):
    root = make_vault({"a/Plan.md": "", "b/Plan.md": "", "Other.md": "", "x.txt": ""})
    for argv, text in [
        (("Nope", "X"), "no note named"),
        (("Plan", "X"), "matches 2 notes"),
        (("a/Plan", "Plan"), "already has that name"),
        (("Other", "x/y"), "can't contain a folder"),
    ]:
        code, out, err = run(capsys, "rename", *argv, "-C", str(root))
        assert code == 2 and text in err
    make_vault({"Other.md": "", "Taken.md": ""})
    code, out, err = run(capsys, "rename", "Other", "taken", "-C", str(root))
    assert code == 2 and "already exists" in err
    assert (root / "Other.md").exists()


def test_rename_case_only_change(make_vault, capsys):
    root = make_vault({"plan.md": "", "t.md": "[[plan]]\n"})
    code, *_ = run(capsys, "rename", "plan", "Plan", "-C", str(root))
    assert code == 0
    assert "Plan.md" in {p.name for p in root.iterdir()}
    assert read(root, "t.md") == "[[Plan]]\n"


def test_rename_json(make_vault, capsys):
    root = make_vault({"Plan.md": "", "t.md": "[[Plan#Beds]]\n"})
    code, out, err = run(capsys, "rename", "Plan", "Schedule", "--json", "-C", str(root))
    assert code == 0
    assert json.loads(out) == {
        "dry_run": False,
        "renamed": {"from": "Plan.md", "to": "Schedule.md"},
        "rewritten": [{"path": "t.md", "line": 1, "kind": "wiki",
                       "old": "Plan#Beds", "new": "Schedule#Beds"}],
        "skipped": [],
    }


def test_dry_run_diff_shows_unified_diffs_and_writes_nothing(make_vault, capsys):
    root = make_vault({
        "Plan.md": "# Beds\nself [[Plan#Beds]]\n",
        "daily/today.md": "intro\n[[Plan]] here\nend\n",
    })
    code, out, err = run(capsys, "rename", "Plan", "Schedule", "--dry-run", "--diff",
                         "-C", str(root))
    assert code == 0
    assert "--- a/daily/today.md" in out
    assert "+++ b/daily/today.md" in out
    assert "-[[Plan]] here" in out
    assert "+[[Schedule]] here" in out
    assert "--- a/Plan.md" in out and "+++ b/Schedule.md" in out
    assert "would rewrite 2 links in 2 notes" in err
    assert (root / "Plan.md").exists()
    assert read(root, "daily/today.md") == "intro\n[[Plan]] here\nend\n"


def test_diff_requires_dry_run(make_vault, capsys):
    root = make_vault({"Plan.md": "x\n"})
    code, out, err = run(capsys, "rename", "Plan", "Schedule", "--diff", "-C", str(root))
    assert code == 2
    assert "--dry-run" in err
    assert (root / "Plan.md").exists()


def test_dry_run_diff_in_json(make_vault, capsys):
    root = make_vault({"Plan.md": "x\n", "a.md": "[[Plan]]\n"})
    code, out, err = run(capsys, "rename", "Plan", "Schedule", "--dry-run", "--diff",
                         "--json", "-C", str(root))
    assert code == 0
    assert "+[[Schedule]]" in json.loads(out)["diff"]
