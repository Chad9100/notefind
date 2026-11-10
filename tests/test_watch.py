"""watch: snapshots, change detection and re-running commands."""

import io
import os

import pytest

from notefind import watch as watching
from notefind.cli import main
from notefind.watch import changed_files, describe, snapshot


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _bump(path, text):
    """Rewrite a file and move its mtime forward, so coarse clocks still see it."""
    st = path.stat()
    _write(path, text)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 2_000_000_000))


class Steps:
    """A fake sleep that applies one change per call, then stops the watch."""

    def __init__(self, *actions):
        self.actions = list(actions)
        self.calls = []

    def __call__(self, seconds):
        self.calls.append(seconds)
        if not self.actions:
            raise KeyboardInterrupt
        self.actions.pop(0)()


def test_snapshot_skips_hidden_and_node_modules(tmp_path):
    _write(tmp_path / "a.md", "a")
    _write(tmp_path / "img" / "pic.png", "png")
    _write(tmp_path / ".obsidian" / "workspace.json", "{}")
    _write(tmp_path / "node_modules" / "x.md", "x")
    _write(tmp_path / ".hidden.md", "h")
    snap = snapshot(tmp_path)
    assert sorted(snap) == ["a.md", "img/pic.png"]
    assert snap["a.md"][1] == 1


def test_changed_files_finds_added_removed_and_modified():
    old = {"a.md": (1, 1), "b.md": (1, 1), "c.md": (1, 1)}
    new = {"a.md": (1, 1), "b.md": (2, 1), "d.md": (1, 1)}
    assert changed_files(old, new) == ["b.md", "c.md", "d.md"]
    assert changed_files(old, dict(old)) == []


def test_size_change_counts_even_with_same_mtime():
    assert changed_files({"a.md": (5, 1)}, {"a.md": (5, 2)}) == ["a.md"]


def test_describe():
    assert describe(["a.md"]) == "1 file changed: a.md"
    assert describe(["a", "b", "c", "d", "e"]) == "5 files changed: a, b, c and 2 more"


def test_watch_runs_again_only_after_changes(tmp_path):
    note = tmp_path / "a.md"
    _write(note, "one")
    runs = []
    sleep = Steps(
        lambda: None,                       # nothing changed: no run
        lambda: _bump(note, "two two"),     # modified
        lambda: _write(tmp_path / "b.md", "new"),  # added
        lambda: note.unlink(),              # removed
    )
    err = io.StringIO()
    code = watching.watch(
        tmp_path, lambda: runs.append(1) or len(runs), 0.5,
        out=io.StringIO(), err=err, sleep=sleep,
    )
    assert len(runs) == 4
    assert code == 4  # exit code of the last run
    assert sleep.calls == [0.5] * 5
    log = err.getvalue()
    assert "1 file changed: a.md; running again" in log
    assert "1 file changed: b.md; running again" in log
    assert log.rstrip().endswith("stopped watching")


def test_files_written_by_the_command_do_not_retrigger(tmp_path):
    note = tmp_path / "a.md"
    _write(note, "x")
    runs = []

    def run():
        runs.append(1)
        _bump(note, "x" * (len(runs) + 1))  # like links --fix rewriting a note
        return 0

    watching.watch(tmp_path, run, 1, out=io.StringIO(), err=io.StringIO(),
                   sleep=Steps(lambda: None, lambda: None))
    assert len(runs) == 1


def test_clear_writes_escape_before_each_run(tmp_path):
    _write(tmp_path / "a.md", "x")
    out = io.StringIO()
    watching.watch(tmp_path, lambda: 0, 1, clear=True, out=out, err=io.StringIO(),
                   sleep=Steps(lambda: _write(tmp_path / "b.md", "y")))
    assert out.getvalue() == watching.CLEAR_SCREEN * 2


def test_interval_must_be_positive(tmp_path):
    with pytest.raises(ValueError):
        watching.watch(tmp_path, lambda: 0, 0, out=io.StringIO(), err=io.StringIO())


def test_cli_watch_reruns_links(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    _write(vault / "a.md", "see [[Missing]]\n")
    fix = lambda: _bump(vault / "a.md", "see [[b]]\n")
    add = lambda: _write(vault / "b.md", "# B\n")
    monkeypatch.setattr(watching.time, "sleep", Steps(fix, add))
    code = main(["watch", "--interval", "0.1", "links", "-C", str(vault)])
    out, err = capsys.readouterr()
    assert out.count("a.md:1: broken link -> Missing") == 1
    assert out.count("a.md:1: broken link -> b") == 1
    assert "1 file changed: a.md; running again" in err
    assert "1 file changed: b.md; running again" in err
    assert "no broken links" in err
    assert code == 0  # the last run found nothing broken


def test_cli_watch_passes_search_exclusions_through(tmp_path, monkeypatch, capsys):
    vault = tmp_path / "vault"
    _write(vault / "a.md", "tomato basil\n")
    _write(vault / "b.md", "tomato\n")
    monkeypatch.setattr(watching.time, "sleep", Steps())
    code = main(["watch", "search", "tomato", "-basil", "-C", str(vault)])
    out, _ = capsys.readouterr()
    assert out.splitlines() == ["b.md:1: tomato"]
    assert code == 0


def test_cli_watch_needs_a_command(capsys):
    assert main(["watch"]) == 2
    assert "needs a command" in capsys.readouterr().err
    assert main(["watch", "--"]) == 2


def test_cli_watch_rejects_nested_watch(capsys):
    assert main(["watch", "watch", "links"]) == 2
    assert "can't run watch" in capsys.readouterr().err


def test_cli_watch_checks_folder_and_options_first(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(watching.time, "sleep", Steps())
    assert main(["watch", "links", "-C", str(tmp_path / "nope")]) == 2
    assert "not a folder" in capsys.readouterr().err
    with pytest.raises(SystemExit) as exc:
        main(["watch", "links", "--bogus"])
    assert exc.value.code == 2


@pytest.mark.parametrize("value", ["0", "-1", "soon", "inf", "nan"])
def test_cli_watch_rejects_bad_interval(value, capsys):
    with pytest.raises(SystemExit) as exc:
        main(["watch", "--interval", value, "links"])
    assert exc.value.code == 2
