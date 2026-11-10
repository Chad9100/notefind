import pytest

from notefind.cli import main

VAULT = {
    "Plan.md": "# Plan\n#garden #soil\nSee [[Compst]] and [[Compost]].\n",
    "Compost.md": "Back to [[Plan]]. #garden\n",
    "lonely.md": "Nobody links here <b>&</b>.\n",
}


@pytest.fixture
def vault(make_vault):
    return make_vault(VAULT)


def test_report_to_stdout(vault, capsys):
    assert main(["report", "--html", "-C", str(vault)]) == 0
    out = capsys.readouterr().out
    assert out.startswith("<!DOCTYPE html>")
    assert "3 notes, 2 tags, 3 links checked, 1 broken, 1 orphans" in out
    assert "Plan.md:3" in out and "Compst" in out
    assert "did you mean" in out
    assert "#garden" in out and "<td>2</td>" in out
    assert "lonely.md" in out
    assert "<script" not in out


def test_report_to_file(vault, tmp_path, capsys):
    target = tmp_path / "out.html"
    assert main(["report", "--html", "-C", str(vault), "-o", str(target)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "wrote" in captured.err
    assert "<h1>notefind report</h1>" in target.read_text(encoding="utf-8")


def test_report_escapes_html(make_vault, capsys):
    root = make_vault({"a.md": "[[<img src=x>]]\n"})
    assert main(["report", "--html", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert "<img" not in out
    assert "&lt;img src=x&gt;" in out


def test_report_clean_vault(make_vault, capsys):
    root = make_vault({"a.md": "[[b]]\n", "b.md": "[[a]]\n"})
    assert main(["report", "--html", "-C", str(root)]) == 0
    out = capsys.readouterr().out
    assert "No broken links." in out and "No tags." in out
    assert "Every note is linked" in out


def test_report_needs_html_flag(vault, capsys):
    assert main(["report", "-C", str(vault)]) == 2
    assert "needs --html" in capsys.readouterr().err


def test_report_unwritable_output(vault, tmp_path, capsys):
    bad = tmp_path / "missing-dir" / "x.html"
    assert main(["report", "--html", "-C", str(vault), "-o", str(bad)]) == 2
    assert "can't write" in capsys.readouterr().err
