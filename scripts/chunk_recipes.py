#!/usr/bin/env python3
"""Build the discover-step output for ``.github/workflows/build.yml``.

Reads recipe names (one per line) from stdin and the build
matrix' platform list from ``.github/platforms.json``, then
emits a single JSON object on stdout with three fields:

- ``chunks``        — list of cell-lists. Each cell is a
                      ``{recipe, platform, os}`` object. Each
                      chunk is dispatched as one
                      ``build-chunk.yml`` reusable-workflow
                      call. Each chunk is sized to stay
                      below GitHub Actions' per-matrix
                      expansion cap.
- ``all_recipes``   — flat sorted list of every recipe name
                      that should produce metadata in this
                      run. Consumed by ``update-recipes``
                      to verify completeness — a recipe that
                      appears here but produces zero
                      artifacts is treated as a build
                      failure, surfacing silent matrix
                      truncation as a visible workflow
                      failure.
- ``platforms``     — the same array read from
                      ``platforms.json``, echoed back so
                      ``build-gale`` can consume it via
                      ``fromJson(needs.discover.outputs.platforms)``
                      without re-reading the file.

Why flat cells, not nested ``recipe × platform`` matrices:
the GH cap counts cells, not recipes. Packing flat means
the chunk size adapts automatically to platform-count
changes — adding a fourth platform reshuffles cells per
chunk without breaking the math.

Why one chunker, not inline Python in the workflow YAML:
the YAML heredoc form is untestable and silently swallowed
its own output on 2026-05-19 (see neovim 9-day stale
incident, gale-recipes commit ``cb8db5e``). A standalone
script gets unit tests and clear error paths.

Usage:

    printf 'neovim\\nduckdb\\n' | python3 scripts/chunk_recipes.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# GitHub Actions caps a single matrix expansion at 256 jobs.
# Source: https://docs.github.com/en/actions/using-jobs/using-a-matrix-for-your-jobs#expanding-or-adding-matrix-configurations
# (the docs phrase it as "A job matrix can generate a maximum
# of 256 jobs per workflow run").
#
# This is the *only* magic number in the build pipeline —
# the chunk size, cell budget, and per-chunk assertions all
# derive from it. If GitHub ever raises the cap, bump this
# constant; no other code changes.
GH_MATRIX_CELL_CAP = 256

# One cell of headroom. GitHub has historically been
# inconsistent about whether the cap is inclusive or
# exclusive. Costing one job to avoid a recurrence of the
# silent-truncation class of bug is a trade I'll take.
SAFETY_MARGIN = 1

# Effective per-chunk budget. Both the chunker and the
# build-chunk startup assertion key off this.
MAX_CELLS_PER_CHUNK = GH_MATRIX_CELL_CAP - SAFETY_MARGIN


def load_platforms(platforms_path: Path) -> list[dict]:
    """Parse the build-matrix platform list. Each entry must
    have ``os`` (the GitHub runner image) and ``platform``
    (the gale target triple)."""
    data = json.loads(platforms_path.read_text())
    if not isinstance(data, list) or not data:
        raise ValueError(
            f"{platforms_path} must be a non-empty JSON array"
        )
    for entry in data:
        if not isinstance(entry, dict):
            raise ValueError(
                f"{platforms_path}: entries must be objects, "
                f"got {type(entry).__name__}"
            )
        for key in ("os", "platform"):
            if key not in entry or not isinstance(entry[key], str):
                raise ValueError(
                    f"{platforms_path}: each entry must have a "
                    f"string '{key}'; missing in {entry}"
                )
    return data


def read_recipe_names(stream) -> list[str]:
    """Stdin reader that filters blank lines and dedup-sorts
    so the output is stable across runs."""
    names = {line.strip() for line in stream if line.strip()}
    return sorted(names)


def build_cells(
    recipes: list[str],
    platforms: list[dict],
) -> list[dict]:
    """Flatten the recipe × platform product into one cell
    per matrix job. Order is (recipe-major, platform-minor)
    so chunks group platforms of the same recipe together
    when chunk boundaries fall mid-recipe — slightly tighter
    sccache locality, no other reason."""
    cells: list[dict] = []
    for recipe in recipes:
        for plat in platforms:
            cells.append({
                "recipe": recipe,
                "platform": plat["platform"],
                "os": plat["os"],
            })
    return cells


def chunk_cells(cells: list[dict]) -> list[list[dict]]:
    """Pack the flat cell list into chunks of at most
    MAX_CELLS_PER_CHUNK each, then assert the invariant
    every consumer downstream depends on."""
    chunks = [
        cells[i:i + MAX_CELLS_PER_CHUNK]
        for i in range(0, len(cells), MAX_CELLS_PER_CHUNK)
    ]
    for i, chunk in enumerate(chunks):
        if len(chunk) > MAX_CELLS_PER_CHUNK:
            raise AssertionError(
                f"chunk {i} has {len(chunk)} cells but the "
                f"cap is {MAX_CELLS_PER_CHUNK}; chunker bug"
            )
    return chunks


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--platforms",
        type=Path,
        default=Path(".github/platforms.json"),
        help="path to platforms.json (default: .github/platforms.json)",
    )
    args = p.parse_args(argv)

    try:
        platforms = load_platforms(args.platforms)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    recipes = read_recipe_names(sys.stdin)
    cells = build_cells(recipes, platforms)
    chunks = chunk_cells(cells)

    # Log to stderr so stdout stays machine-parseable.
    # The line format is grep-friendly: a future workflow
    # change can ::notice:: it without re-deriving counts.
    print(
        f"discover: {len(recipes)} recipes, "
        f"{len(platforms)} platforms, "
        f"{len(cells)} cells, {len(chunks)} chunk(s) "
        f"(cap={GH_MATRIX_CELL_CAP}, margin={SAFETY_MARGIN})",
        file=sys.stderr,
    )

    output = {
        "chunks": chunks,
        "all_recipes": recipes,
        "platforms": platforms,
    }
    json.dump(output, sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
