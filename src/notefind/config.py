"""Command defaults from a `.notefind.toml` file in the notes folder."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CONFIG_FILE = ".notefind.toml"

try:  # Python 3.11+
    import tomllib as _tomllib
except ImportError:  # Python 3.10
    _tomllib = None


class ConfigError(Exception):
    """The config file can't be read or holds something notefind can't use."""


_KEY = re.compile(r"^[A-Za-z0-9_-]+$")
_INT = re.compile(r"^[+-]?\d+(?:_\d+)*$")
_FLOAT = re.compile(r"^[+-]?\d+(?:_\d+)*\.\d+(?:_\d+)*$")


def _strip_comment(line: str) -> str:
    """Drop a trailing `# comment`, leaving any `#` inside quotes alone."""
    quote = ""
    for i, ch in enumerate(line):
        if quote:
            if ch == "\\" and quote == '"':
                continue
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return line[:i]
    return line


def _parse_value(raw: str) -> Any:
    if raw == "true":
        return True
    if raw == "false":
        return False
    if len(raw) >= 2 and raw[0] == raw[-1] == "'":
        return raw[1:-1]
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        try:
            return json.loads(raw)  # basic strings share JSON's escapes
        except ValueError:
            raise ValueError(f"bad string {raw}") from None
    if _INT.match(raw):
        return int(raw.replace("_", ""))
    if _FLOAT.match(raw):
        return float(raw.replace("_", ""))
    raise ValueError(f"unsupported value {raw!r} (use a string, number or true/false)")


def parse_toml(text: str) -> dict[str, Any]:
    """Parse TOML with tomllib, or with a small fallback on Python 3.10.

    The fallback reads what a notefind config needs: `[table]` headers and
    `key = value` lines with strings, integers, floats and booleans.
    """
    if _tomllib is not None:
        try:
            return _tomllib.loads(text)
        except _tomllib.TOMLDecodeError as exc:
            raise ValueError(str(exc)) from None
    return _parse_simple(text)


def _parse_simple(text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    table = data
    for number, line in enumerate(text.lstrip("﻿").splitlines(), 1):
        line = _strip_comment(line).strip()
        if not line:
            continue
        try:
            if line.startswith("["):
                name = line[1:-1].strip() if line.endswith("]") else ""
                if not _KEY.match(name):
                    raise ValueError("unsupported table header")
                if name in data:
                    raise ValueError(f"table {name!r} defined twice")
                table = data[name] = {}
                continue
            key, eq, raw = line.partition("=")
            key = key.strip()
            if not eq or not _KEY.match(key):
                raise ValueError("expected key = value")
            if key in table:
                raise ValueError(f"duplicate key {key!r}")
            table[key] = _parse_value(raw.strip())
        except ValueError as exc:
            raise ValueError(f"line {number}: {exc}") from None
    return data


def load_config(root: Path) -> dict[str, Any] | None:
    """Return the parsed `.notefind.toml` in `root`, or None if there isn't one."""
    path = root / CONFIG_FILE
    if not path.is_file():
        return None
    try:
        text = path.read_bytes().decode("utf-8-sig")
        return parse_toml(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise ConfigError(f"{CONFIG_FILE}: {exc}") from None


def command_defaults(
    config: dict[str, Any], valid: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Split a config into per-command defaults and check every value.

    `valid` maps each command to {option name: check function}; a check
    returns the cleaned value or raises ValueError. Top-level keys apply to
    every command that has the option; a `[command]` table overrides them.
    """
    out: dict[str, dict[str, Any]] = {cmd: {} for cmd in valid}
    known = {name for checks in valid.values() for name in checks}
    tables = {k: v for k, v in config.items() if isinstance(v, dict)}
    for key in tables:
        if key not in valid:
            raise ConfigError(f"{CONFIG_FILE}: unknown command table [{key}]")
    for key, value in config.items():
        if key in tables:
            continue
        if key not in known:
            raise ConfigError(f"{CONFIG_FILE}: unknown option {key!r}")
        for cmd, checks in valid.items():
            if key in checks:
                out[cmd][key] = _check(checks[key], key, value)
    for cmd, table in tables.items():
        for key, value in table.items():
            if key not in valid[cmd]:
                raise ConfigError(f"{CONFIG_FILE}: [{cmd}] has no option {key!r}")
            out[cmd][key] = _check(valid[cmd][key], key, value)
    return out


def _check(check: Any, key: str, value: Any) -> Any:
    try:
        return check(value)
    except ValueError as exc:
        raise ConfigError(f"{CONFIG_FILE}: {key}: {exc}") from None
