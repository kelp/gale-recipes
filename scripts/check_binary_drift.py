#!/usr/bin/env python3
"""Fail-loudly watchdog for recipe/binary version drift.

Walks every recipe and identifies cases where the recipe
version (or revision) has moved ahead of ``.binaries.toml``.
Exits non-zero when drift is found and writes a markdown
summary to ``$GITHUB_STEP_SUMMARY`` (when set) so a daily
GitHub Actions cron surfaces the gap in the Actions tab.

The status dashboard already *displays* drift; this script
closes the loop by making drift a CI signal instead of a
"go look at the page" obligation. It exists because of the
neovim 0.12.2 incident: a recipe bumped on 2026-05-18 went
nine days without prebuilts on any platform because nobody
noticed CI never rewrote ``.binaries.toml``.

Usage:

    python3 scripts/check_binary_drift.py --repo-root .

Exits 0 if no drift, 1 if drift is found, 2 on usage error.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_status_page as g  # noqa: E402


def find_drifted(repo_root: Path) -> list[g.Recipe]:
    """Return recipes whose recipe version disagrees with the
    version written into ``.binaries.toml``. Order is stable
    (alphabetical) so the summary diffs cleanly day-over-day."""
    return [
        r
        for r in g.load_all_recipes(repo_root)
        if r.is_stale_drift
    ]


def format_summary(drifted: list[g.Recipe]) -> str:
    """Markdown report for ``$GITHUB_STEP_SUMMARY``.
    Kept narrow so the Actions UI renders the table without
    horizontal scroll."""
    if not drifted:
        return "# Binary drift check\n\nAll recipes match their `.binaries.toml`.\n"
    lines: list[str] = []
    lines.append("# Binary drift detected")
    lines.append("")
    lines.append(
        f"{len(drifted)} recipe(s) have a version newer than "
        "the latest `.binaries.toml` entry. Users on every "
        "platform are falling back to source builds for these."
    )
    lines.append("")
    lines.append("| recipe | recipe version | binaries version |")
    lines.append("| --- | --- | --- |")
    for r in drifted:
        recipe_v = r.expected_binaries_version
        binaries_v = r.binaries_version or "_(none)_"
        lines.append(f"| `{r.name}` | `{recipe_v}` | `{binaries_v}` |")
    lines.append("")
    lines.append(
        "Triage: check the most recent `Build Recipes` run for "
        "each recipe. Common causes: build failure on one or "
        "more platforms, batched push that missed the change, "
        "or matrix overflow past GitHub's 256-cell cap."
    )
    return "\n".join(lines) + "\n"


def write_step_summary(text: str) -> None:
    """Append to ``$GITHUB_STEP_SUMMARY`` if set, else no-op.
    Lets the script run identically locally and in CI."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root containing recipes/ (default: .)",
    )
    args = p.parse_args(argv)

    repo_root = args.repo_root.resolve()
    if not (repo_root / "recipes").is_dir():
        print(
            f"error: {repo_root} does not look like gale-recipes "
            "(no recipes/ directory)",
            file=sys.stderr,
        )
        return 2

    drifted = find_drifted(repo_root)
    summary = format_summary(drifted)
    write_step_summary(summary)

    # Console output mirrors the summary so logs are readable
    # without leaving the Actions log view.
    print(summary, end="")
    return 1 if drifted else 0


if __name__ == "__main__":
    raise SystemExit(main())
