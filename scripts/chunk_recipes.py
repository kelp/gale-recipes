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
                      expansion cap. Cells are emitted only
                      for a recipe's eligible platforms: its
                      declared ``[package].platforms``
                      intersected with the matrix when
                      declared, else the full matrix. An
                      empty intersection is a hard error.
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
import tomllib
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


# GitHub-hosted runner images a recipe may opt into via
# .github/runner-overrides.json. An override redirects a single
# (recipe, platform) cell onto one of these images; anything
# else (a self-hosted label, a typo'd image) is a hard error.
# This bounds what a recipe PR can do to the privileged build's
# runs-on: build.yml chooses runs-on from files at the reviewed
# SHA, so the allowlist keeps a merged override on a known
# hosted runner rather than an attacker-controlled label.
ALLOWED_RUNNER_OVERRIDES = {
    "macos-15",
    "macos-26",
    "ubuntu-latest",
    "ubuntu-24.04",
    "ubuntu-24.04-arm",
    "ubuntu-22.04",
}


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


def load_runner_overrides(path: Path) -> dict[str, dict[str, str]]:
    """Parse the optional per-recipe runner-override map.

    Shape: ``{recipe: {platform: runner_os}}``. A missing file
    is not an error -- overrides are opt-in and the common case
    is none. Every override value must be in
    ``ALLOWED_RUNNER_OVERRIDES``; an unknown image is a hard
    error naming the recipe, platform, and value, so a typo or a
    self-hosted label can't silently redirect a build."""
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict):
        raise ValueError(f"{path} must be a JSON object")
    for recipe, by_platform in data.items():
        if not isinstance(by_platform, dict):
            raise ValueError(
                f"{path}: '{recipe}' must map to an object of "
                f"platform->runner, got "
                f"{type(by_platform).__name__}"
            )
        for platform, runner in by_platform.items():
            if not isinstance(runner, str):
                raise ValueError(
                    f"{path}: {recipe}.{platform} runner must be "
                    f"a string, got {type(runner).__name__}"
                )
            if runner not in ALLOWED_RUNNER_OVERRIDES:
                raise ValueError(
                    f"{path}: {recipe}.{platform} runner "
                    f"'{runner}' is not an allowed runner image "
                    f"{sorted(ALLOWED_RUNNER_OVERRIDES)}"
                )
    return data


def read_recipe_names(stream) -> list[str]:
    """Stdin reader that filters blank lines and dedup-sorts
    so the output is stable across runs."""
    names = {line.strip() for line in stream if line.strip()}
    return sorted(names)


def eligible_platforms(
    recipe: str,
    platforms: list[dict],
    recipes_dir: Path,
) -> list[dict]:
    """The recipe's declared ``[package].platforms``
    intersected with the matrix when declared, else the full
    matrix. The declaration is authoritative: ineligible
    platforms get no cell at all, so there is no 'skipped'
    build to special-case downstream — a build failure is a
    failure, full stop.

    A missing or unparsable recipe file degrades to the full
    matrix (callers validate recipe existence before invoking
    the chunker; this matches the pre-filtering behavior).
    An empty intersection is a hard error naming the recipe —
    a recipe no platform can build must not silently vanish
    from the run."""
    recipe_file = recipes_dir / recipe[0] / f"{recipe}.toml"
    try:
        with recipe_file.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return list(platforms)
    declared = data.get("package", {}).get("platforms")
    if not isinstance(declared, list):
        return list(platforms)
    eligible = [p for p in platforms if p["platform"] in declared]
    if not eligible:
        raise ValueError(
            f"recipe '{recipe}' declares platforms {declared!r} "
            f"with no overlap with the build matrix "
            f"{[p['platform'] for p in platforms]}"
        )
    return eligible


def build_cells(
    recipes: list[str],
    platforms: list[dict],
    recipes_dir: Path = Path("recipes"),
    overrides: dict[str, dict[str, str]] | None = None,
) -> list[dict]:
    """Flatten the recipe × eligible-platform product into one
    cell per matrix job. Order is (recipe-major,
    platform-minor) so chunks group platforms of the same
    recipe together when chunk boundaries fall mid-recipe —
    slightly tighter sccache locality, no other reason.

    ``overrides`` (``{recipe: {platform: runner_os}}``, see
    ``load_runner_overrides``) only swaps which runner image a
    matching cell runs on. It never adds or removes a cell: an
    override for a platform a recipe isn't eligible for has no
    cell to rewrite, so it is a no-op."""
    overrides = overrides or {}
    cells: list[dict] = []
    for recipe in recipes:
        recipe_overrides = overrides.get(recipe, {})
        for plat in eligible_platforms(
            recipe, platforms, recipes_dir
        ):
            cells.append({
                "recipe": recipe,
                "platform": plat["platform"],
                "os": recipe_overrides.get(
                    plat["platform"], plat["os"]
                ),
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
    p.add_argument(
        "--recipes-dir",
        type=Path,
        default=Path("recipes"),
        help="recipe TOML directory (default: recipes)",
    )
    p.add_argument(
        "--runner-overrides",
        type=Path,
        default=Path(".github/runner-overrides.json"),
        help=(
            "path to runner-overrides.json "
            "(default: .github/runner-overrides.json; "
            "absent = no overrides)"
        ),
    )
    args = p.parse_args(argv)

    try:
        platforms = load_platforms(args.platforms)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        overrides = load_runner_overrides(args.runner_overrides)
    except (OSError, ValueError, json.JSONDecodeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    recipes = read_recipe_names(sys.stdin)
    try:
        cells = build_cells(
            recipes, platforms,
            recipes_dir=args.recipes_dir,
            overrides=overrides,
        )
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
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
