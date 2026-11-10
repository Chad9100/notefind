"""Parallel note reading (load_notes jobs= and the -j/--jobs option)."""

import json

import pytest

from notefind import scan
from notefind.cli import main
from notefind.scan import PARALLEL_THRESHOLD, load_notes


def _write_vault(root, count):
    for i in range(count):
        folder = root / f"dir{i % 5}"
        folder.mkdir(parents=True, exist_ok=True)
        text = f"# Note {i}\n\nbody {i} shared [[note{(i + 1) % count}]]\r\n"
        (folder / f"note{i}.md").write_bytes(("﻿" + text).encode("utf-8"))
    (root / "skip.txt").write_text("not a note", encoding="utf-8")


def _snapshot(notes):
    return [(n.rel, n.text) for n in notes]


@pytest.mark.parametrize("jobs", [None, 1, 2, 4, 32])
def test_same_result_for_any_job_count(tmp_path, jobs):
    _write_vault(tmp_path, PARALLEL_THRESHOLD + 10)
    expected = _snapshot(load_notes(tmp_path, jobs=1))
    assert len(expected) == PARALLEL_THRESHOLD + 10
    assert _snapshot(load_notes(tmp_path, jobs=jobs)) == expected
    rels = [rel for rel, _ in expected]
    assert rels == sorted(rels)
    assert all(not text.startswith("﻿") and "\r" not in text for _, text in expected)


def test_more_jobs_than_notes(tmp_path):
    _write_vault(tmp_path, 3)
    assert len(load_notes(tmp_path, jobs=16)) == 3


def test_empty_folder_with_jobs(tmp_path):
    assert load_notes(tmp_path, jobs=4) == []


def test_invalid_jobs_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_notes(tmp_path, jobs=0)


def test_unreadable_file_skipped_in_parallel(tmp_path, monkeypatch):
    _write_vault(tmp_path, PARALLEL_THRESHOLD)
    real = scan.read_text

    def flaky(path):
        if path.name == "note7.md":
            raise OSError("gone")
        return real(path)

    monkeypatch.setattr(scan, "read_text", flaky)
    rels = [n.rel for n in load_notes(tmp_path, jobs=4)]
    assert len(rels) == PARALLEL_THRESHOLD - 1
    assert "dir2/note7.md" not in rels


def test_auto_mode_uses_threads_only_for_big_folders(tmp_path, monkeypatch):
    created = []
    real_pool = scan.ThreadPoolExecutor

    def spy(*args, **kwargs):
        created.append(kwargs.get("max_workers"))
        return real_pool(*args, **kwargs)

    monkeypatch.setattr(scan, "ThreadPoolExecutor", spy)
    monkeypatch.setattr(scan, "default_jobs", lambda: 3)
    small = tmp_path / "small"
    _write_vault(small, PARALLEL_THRESHOLD - 1)
    load_notes(small)
    assert created == []
    big = tmp_path / "big"
    _write_vault(big, PARALLEL_THRESHOLD)
    load_notes(big)
    assert created == [3]


def test_default_jobs_bounds():
    assert 1 <= scan.default_jobs() <= scan.MAX_AUTO_JOBS


def test_cli_jobs_option_same_output(tmp_path, capsys):
    _write_vault(tmp_path, PARALLEL_THRESHOLD + 5)
    outputs = []
    for extra in (["-j", "1"], ["--jobs", "4"], []):
        code = main(["search", "shared", "-C", str(tmp_path), "--json", "--limit", "500", *extra])
        assert code == 0
        outputs.append(json.loads(capsys.readouterr().out))
    assert outputs[0] == outputs[1] == outputs[2]
    for cmd in (["links"], ["tags"], ["orphans"]):
        results = []
        for jobs in ("1", "3"):
            main([*cmd, "-C", str(tmp_path), "--json", "-j", jobs])
            results.append(capsys.readouterr().out)
        assert results[0] == results[1]


@pytest.mark.parametrize("bad", ["0", "-2", "many"])
def test_cli_rejects_bad_jobs(tmp_path, capsys, bad):
    with pytest.raises(SystemExit) as exc:
        main(["links", "-C", str(tmp_path), "--jobs", bad])
    assert exc.value.code == 2
    assert "--jobs" in capsys.readouterr().err
