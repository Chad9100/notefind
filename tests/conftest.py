from pathlib import Path

import pytest


@pytest.fixture
def make_vault(tmp_path):
    """Create a notes folder from {relative/path: text or bytes}."""

    def _make(files: dict) -> Path:
        root = tmp_path / "vault"
        root.mkdir(exist_ok=True)
        for rel, content in files.items():
            path = root.joinpath(*rel.split("/"))
            path.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                path.write_bytes(content)
            else:
                path.write_text(content, encoding="utf-8", newline="\n")
        return root

    return _make
