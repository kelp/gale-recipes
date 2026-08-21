"""Path rules for the fetch catalog under index/.

A document lives at index/<first letter of stem>/<stem>.toml.
The letter is one [a-z0-9]. This module does not parse TOML.
"""

from __future__ import annotations

from pathlib import Path

_LETTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")


def list_index_files(root: Path) -> list[Path]:
    index = root / "index"
    if not index.is_dir():
        return []
    return sorted(p for p in index.rglob("*.toml") if p.is_file())


def layout_ok(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root)
    except ValueError:
        return False
    if len(rel.parts) != 3 or rel.parts[0] != "index":
        return False
    letter, name = rel.parts[1], rel.parts[2]
    if not name.endswith(".toml"):
        return False
    stem = name[: -len(".toml")]
    if not stem or len(letter) != 1 or letter not in _LETTERS:
        return False
    return letter == stem[0]


def issues(root: Path) -> list[str]:
    found = []
    for path in list_index_files(root):
        if not layout_ok(path, root):
            found.append(f"{path.relative_to(root)}: bad index path")
    return found
