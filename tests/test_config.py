""".notefind.toml: the Python 3.10 fallback parser and command defaults."""

import json

import pytest

from notefind import config
from notefind.cli import main
from notefind.config import _parse_simple, parse_toml


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def test_fallback_parser_reads_tables_and_scalars():
    text = (
        "# defaults\n"
        'color = "never"  # trailing comment\n'
        "limit = 5\n"
        "fuzzy = true\n"
        "ratio = 1.5\n"
        "name = 'a # b'\n"
        "\n[links]\n"
        "no_anchors = false\n"
    )
    assert _parse_simple(text) == {
        "color": "never", "limit": 5, "fuzzy": True, "ratio": 1.5,
        "name": "a # b", "links": {"no_anchors": False},
    }


@pytest.mark.parametrize("text", [
    "limit = [1, 2]", "limit", "[a.b]", "limit = 1\nlimit = 2",
    "[x]\n[x]", 'name = "unterminated',
])
def test_fallback_parser_rejects_what_it_cannot_read(text):
    with pytest.raises(ValueError):
        _parse_simple(text)


def test_parse_toml_agrees_with_fallback_on_simple_input():
    text = 'limit = 3\ncolor = "always"\n[search]\nfuzzy = true\n'
    assert parse_toml(text) == _parse_simple(text)


@pytest.fixture
def vault(tmp_path):
    for i in range(4):
        _write(tmp_path / f"n{i}.md", f"tomato {i}")
    return tmp_path


def _search(vault, *extra):
    return main(["search", "tomato", "-C", str(vault), "--json", *extra])


def test_limit_default_from_config(vault, capsys):
    _write(vault / ".notefind.toml", "limit = 2\n")
    _search(vault)
    out = json.loads(capsys.readouterr().out)
    assert out["total"] == 4 and len(out["results"]) == 2


def test_command_line_beats_config(vault, capsys):
    _write(vault / ".notefind.toml", "limit = 2\n")
    _search(vault, "--limit", "3")
    assert len(json.loads(capsys.readouterr().out)["results"]) == 3


def test_command_table_overrides_top_level(vault, capsys):
    _write(vault / ".notefind.toml", "limit = 2\n[search]\nlimit = 1\n")
    _search(vault)
    assert len(json.loads(capsys.readouterr().out)["results"]) == 1


def test_no_config_flag_ignores_file(vault, capsys):
    _write(vault / ".notefind.toml", "limit = 1\n")
    _search(vault, "--no-config")
    assert len(json.loads(capsys.readouterr().out)["results"]) == 4


def test_boolean_default_and_other_commands(vault, capsys):
    _write(vault / ".notefind.toml", "json = true\nlimit = 1\n")
    assert main(["tags", "-C", str(vault)]) == 0
    assert json.loads(capsys.readouterr().out) == []  # tags has json, no limit


def test_color_default(vault, capsys):
    _write(vault / ".notefind.toml", 'color = "always"\n')
    main(["search", "tomato", "-C", str(vault)])
    assert "\x1b[" in capsys.readouterr().out


@pytest.mark.parametrize("text, message", [
    ("bogus = 1", "unknown option 'bogus'"),
    ("[nothing]\nx = 1", "unknown command table [nothing]"),
    ("[search]\nfix = true", "no option 'fix'"),
    ('limit = "ten"', "limit: expected a whole number"),
    ('color = "red"', "color: expected one of"),
    ("fuzzy = 1", "fuzzy: expected true or false"),
    ("jobs = 0", "jobs: must be at least 1"),
    ("limit = [", "notefind: .notefind.toml: "),
])
def test_bad_config_exits_2(vault, capsys, text, message):
    _write(vault / ".notefind.toml", text)
    assert _search(vault) == 2
    err = capsys.readouterr().err
    assert ".notefind.toml" in err and message in err


def test_config_file_is_not_a_note(vault):
    _write(vault / ".notefind.toml", "limit = 1\n")
    assert config.load_config(vault) == {"limit": 1}
    assert config.load_config(vault / "n0.md") is None


def test_watch_inner_command_reads_config(vault, capsys):
    _write(vault / ".notefind.toml", "bogus = 1")
    assert main(["watch", "search", "tomato", "-C", str(vault)]) == 2
    assert "unknown option" in capsys.readouterr().err
