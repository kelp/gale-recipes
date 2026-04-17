#!/usr/bin/env python3
"""Expand a set of changed recipe names to include all
transitive dependents.

Reads one recipe name per line from stdin. Writes the
expanded set (input + all recipes that transitively
declare an input recipe as a build or runtime dep) to
stdout, sorted, one name per line.

The expansion is recursive but terminates because the
dep graph is finite and we memo-ize visited recipes.
Circular deps (if they existed) would be handled by the
visited set.

Deps may be bare strings or {name = ..., version = ...}
tables — both are extracted.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("expand_changed.py requires Python 3.11+ (tomllib)")

import tomllib


def dep_names(entry_list) -> list[str]:
    """Extract names from a deps list whose items can be
    bare strings or {name, version} tables."""
    out: list[str] = []
    for entry in entry_list or []:
        if isinstance(entry, str):
            out.append(entry)
        elif isinstance(entry, dict):
            name = entry.get("name")
            if isinstance(name, str) and name:
                out.append(name)
    return out


def recipe_path(recipes_dir: Path, name: str) -> Path:
    return recipes_dir / name[0] / f"{name}.toml"


def load_deps(recipes_dir: Path) -> dict[str, set[str]]:
    """Return name → set of dep names, for every recipe
    in recipes_dir. Per-platform deps are unioned in."""
    out: dict[str, set[str]] = {}
    for f in recipes_dir.rglob("*.toml"):
        if f.name.endswith(".binaries.toml"):
            continue
        try:
            with f.open("rb") as fh:
                r = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        name = r.get("package", {}).get("name")
        if not name:
            continue
        deps = r.get("dependencies", {})
        names: set[str] = set()
        names.update(dep_names(deps.get("build")))
        names.update(dep_names(deps.get("runtime")))
        # Per-platform overrides: any key that isn't
        # build or runtime and is a table may carry
        # build/runtime lists.
        for k, v in deps.items():
            if k in ("build", "runtime"):
                continue
            if isinstance(v, dict):
                names.update(dep_names(v.get("build")))
                names.update(dep_names(v.get("runtime")))
        out[name] = names
    return out


def reverse_graph(
    graph: dict[str, set[str]],
) -> dict[str, set[str]]:
    """Given name → deps, return dep → dependents."""
    rev: dict[str, set[str]] = {}
    for name, deps in graph.items():
        for d in deps:
            rev.setdefault(d, set()).add(name)
    return rev


def expand(
    changed: set[str],
    reverse: dict[str, set[str]],
) -> set[str]:
    """Return changed plus the transitive set of every
    recipe that depends on any recipe in changed."""
    result = set(changed)
    stack = list(changed)
    while stack:
        name = stack.pop()
        for dependent in reverse.get(name, ()):
            if dependent in result:
                continue
            result.add(dependent)
            stack.append(dependent)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--recipes-dir",
        type=Path,
        default=Path("recipes"),
        help="directory containing recipe TOML files "
        "(default: recipes)",
    )
    args = ap.parse_args()

    if not args.recipes_dir.is_dir():
        print(
            f"recipes dir not found: {args.recipes_dir}",
            file=sys.stderr,
        )
        return 2

    changed = {
        line.strip()
        for line in sys.stdin
        if line.strip()
    }
    if not changed:
        return 0

    graph = load_deps(args.recipes_dir)
    rev = reverse_graph(graph)
    expanded = expand(changed, rev)

    for name in sorted(expanded):
        print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
