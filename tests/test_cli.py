import io
import json
import subprocess
import sys

import pytest

from notefind.cli import main, use_color
from notefind.search import HIGHLIGHT_ON


@pytest.fixture
def vault(make_vault):
    return make_vault({
        "pasta.md": "---\ntags: [recipe]\n---\n# Pasta\nPasta with tomato and basil. Pasta!\n",
        "bread.md": "---\ntags:\n  - recipe\n  - baking\n---\nRye bread, no tomato.\n",
        "ideas/todo.md": "Plan #project/alpha and #recipe ideas.\nSee [[Pasta]] and [[Soup]].\n",
        "ideas/links.md": "[ok](todo.md) [bad](../missing.md)\n",
        ".obsidian/hidden.md": "pasta tomato",
    })


def run(capsys, *args):
    code = main(list(args))
    out, err = capsys.readouterr()
    return code, out, err


# --- search ---------------------------------------------------------------

def test_search_prints_path_line_snippet(vault, capsys):
    code, out, err = run(capsys, "search", "tomato", "-C", str(vault), "--color", "never")
    assert code == 0
    assert out.splitlines() == [
        "bread.md:6: Rye bread, no tomato.",
        "pasta.md:5: Pasta with tomato and basil. Pasta!",
    ]
    assert "2 notes matched" in err


def test_search_exclusion_passed_as_cli_argument(vault, capsys):
    code, out, _ = run(capsys, "search", "-C", str(vault), "tomato", "-rye", "--color=never")
    assert code == 0
    assert out.startswith("pasta.md:5:")
    assert "bread.md" not in out


def test_search_no_results_exit_1(vault, capsys):
    code, out, err = run(capsys, "search", "zucchini", "-C", str(vault))
    assert code == 1 and out == "" and "no notes matched" in err


def test_search_empty_query_exit_2(vault, capsys):
    code, _, err = run(capsys, "search", "-nothing", "-C", str(vault))
    assert code == 2 and "at least one term" in err


def test_search_limit(vault, capsys):
    code, out, err = run(capsys, "search", "tag:recipe", "-C", str(vault), "--limit", "1")
    assert code == 0
    assert len(out.splitlines()) == 1
    assert "3 notes matched, showing 1" in err


def test_search_json_shape(vault, capsys):
    code, out, _ = run(capsys, "search", "pasta", "tag:recipe", "-C", str(vault), "--json")
    data = json.loads(out)
    assert code == 0
    assert set(data) == {"query", "total", "results"}
    assert data["query"]["terms"] == ["pasta"] and data["query"]["tags"] == ["recipe"]
    assert data["total"] == 2
    assert data["results"] == [
        {"path": "pasta.md", "line": 4, "matches": 3, "snippet": "# Pasta"},
        {"path": "ideas/todo.md", "line": 2, "matches": 1, "snippet": "See [[Pasta]] and [[Soup]]."},
    ]


def test_search_fuzzy_finds_typos(vault, capsys):
    code, out, err = run(capsys, "search", "tomatoe", "-C", str(vault), "--color", "never")
    assert code == 1 and out == ""
    code, out, err = run(capsys, "search", "tomatoe", "basl", "--fuzzy", "-C", str(vault),
                         "--color", "never")
    assert code == 0
    assert out.splitlines() == ["pasta.md:5: Pasta with tomato and basil. Pasta!"]
    assert "1 note matched" in err


def test_search_fuzzy_json_and_highlight(vault, capsys):
    _, out, _ = run(capsys, "search", "--fuzzy", "breed", "-C", str(vault), "--json")
    data = json.loads(out)
    assert data["query"]["fuzzy"] is True
    assert data["results"] == [
        {"path": "bread.md", "line": 6, "matches": 1, "snippet": "Rye bread, no tomato.",
         "fuzzy_words": ["bread"]},
    ]
    _, colored, _ = run(capsys, "search", "--fuzzy", "breed", "-C", str(vault), "--color", "always")
    assert HIGHLIGHT_ON + "bread" in colored


def test_search_short_w_flag_is_an_option_not_an_exclusion(vault, capsys):
    # -w right after "search" must not be read as excluding the word "w".
    code, out, _ = run(capsys, "search", "-w", "tomato", "-C", str(vault), "--color", "never")
    assert code == 0 and len(out.splitlines()) == 2
    code, out, err = run(capsys, "search", "tomat", "-w", "-C", str(vault))
    assert code == 1 and "no notes matched" in err


def test_search_word_and_regex_json(vault, capsys):
    _, out, _ = run(capsys, "search", "--regex", "--word", "past[a-z]", "-C", str(vault), "--json")
    data = json.loads(out)
    assert data["query"]["whole_word"] is True and data["query"]["regex"] is True
    assert [(r["path"], r["matches"]) for r in data["results"]] == [
        ("pasta.md", 3), ("ideas/todo.md", 1),
    ]
    # Whole-word regex: "pas[a-z]" would need a four-letter word.
    code, _, _ = run(capsys, "search", "--regex", "-w", "pas[a-z]", "-C", str(vault))
    assert code == 1
    _, out, _ = run(capsys, "search", "tomato", "-C", str(vault), "--json")
    assert "regex" not in json.loads(out)["query"]


def test_search_regex_highlights_the_regex_match(vault, capsys):
    _, out, _ = run(capsys, "search", "--regex", "r[a-z]e", "-C", str(vault), "--color", "always")
    assert HIGHLIGHT_ON + "Rye" in out


@pytest.mark.parametrize("args, message", [
    (["--regex", "tomato("], "invalid regex 'tomato('"),
    (["--regex", "a?"], "matches empty text"),
    (["--regex", "--fuzzy", "tomato"], "can't be combined"),
])
def test_search_bad_regex_exit_2(vault, capsys, args, message):
    code, out, err = run(capsys, "search", *args, "-C", str(vault))
    assert code == 2 and out == "" and message in err


def test_color_always_highlights_and_never_does_not(vault, capsys):
    _, colored, _ = run(capsys, "search", "basil", "-C", str(vault), "--color", "always")
    assert HIGHLIGHT_ON + "basil" in colored
    _, plain, _ = run(capsys, "search", "basil", "-C", str(vault), "--color", "never")
    assert "\x1b[" not in plain


def test_color_auto_is_off_when_captured(vault, capsys):
    _, out, _ = run(capsys, "search", "basil", "-C", str(vault))
    assert "\x1b[" not in out


class FakeTTY(io.StringIO):
    def isatty(self):
        return True


def test_use_color_auto_respects_tty_and_no_color():
    assert use_color("auto", FakeTTY(), environ={}) is True
    assert use_color("auto", FakeTTY(), environ={"NO_COLOR": "1"}) is False
    assert use_color("auto", io.StringIO(), environ={}) is False
    assert use_color("always", io.StringIO(), environ={"NO_COLOR": "1"}) is True
    assert use_color("never", FakeTTY(), environ={}) is False


# --- tags -----------------------------------------------------------------

def test_tags_counts_notes(vault, capsys):
    code, out, _ = run(capsys, "tags", "-C", str(vault))
    assert code == 0
    assert out.splitlines() == ["3  #recipe", "1  #baking", "1  #project/alpha"]


def test_tags_json_shape(vault, capsys):
    _, out, _ = run(capsys, "tags", "-C", str(vault), "--json")
    assert json.loads(out)[0] == {"tag": "recipe", "count": 3}


# --- links ----------------------------------------------------------------

def test_links_reports_broken_and_exit_1(vault, capsys):
    code, out, err = run(capsys, "links", "-C", str(vault))
    assert code == 1
    assert out.splitlines() == [
        "ideas/links.md:1: broken link -> ../missing.md",
        "ideas/todo.md:2: broken link -> Soup",
    ]
    assert "2 broken (4 links checked in 4 notes)" in err


def test_links_clean_folder_exit_0(make_vault, capsys):
    root = make_vault({"a.md": "[[B]]", "B.md": "[back](a.md)"})
    code, out, err = run(capsys, "links", "-C", str(root))
    assert code == 0 and out == "" and "no broken links" in err


def test_links_json_shape(vault, capsys):
    _, out, _ = run(capsys, "links", "-C", str(vault), "--json")
    data = json.loads(out)
    assert data["checked"] == 4
    assert data["broken"][1] == {
        "path": "ideas/todo.md", "line": 2, "kind": "wiki", "target": "Soup", "reason": "no-file",
    }


def test_links_reports_missing_anchors_with_detail(make_vault, capsys):
    root = make_vault({
        "a.md": "[[B#Setup]] [[B#Usage]] [b](B.md#^gone)\n",
        "B.md": "# Setup\nA paragraph. ^kept\n",
    })
    code, out, err = run(capsys, "links", "-C", str(root))
    assert code == 1
    assert out.splitlines() == [
        'a.md:1: broken link -> B#Usage (no heading "Usage" in B.md)',
        'a.md:1: broken link -> B.md#^gone (no block "^gone" in B.md)',
    ]
    assert "2 broken (3 links checked in 2 notes)" in err

    _, out, _ = run(capsys, "links", "-C", str(root), "--json")
    assert [(b["reason"], b["detail"]) for b in json.loads(out)["broken"]] == [
        ("no-heading", 'no heading "Usage" in B.md'),
        ("no-block", 'no block "^gone" in B.md'),
    ]

    code, out, err = run(capsys, "links", "-C", str(root), "--no-anchors")
    assert code == 0 and out == "" and "3 links checked" in err


# --- misc -----------------------------------------------------------------

def test_missing_folder_exit_2(tmp_path, capsys):
    code, _, err = run(capsys, "tags", "-C", str(tmp_path / "nope"))
    assert code == 2 and "not a folder" in err


def test_python_dash_m_entry_point(vault):
    proc = subprocess.run(
        [sys.executable, "-m", "notefind", "search", "basil", "-C", str(vault)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0
    assert proc.stdout.startswith("pasta.md:5:")
