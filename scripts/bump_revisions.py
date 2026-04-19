#!/usr/bin/env python3
"""Bulk revision bumper for gale recipes.

Walks recipes/<letter>/<name>.toml and increments each
recipe's [package] revision by one. Recipes without a
revision field (implicit revision 1) get `revision = 2`
inserted after the version line.

The edit is regex-based, not a TOML round-trip, so
formatting and comments stay intact. That matters because
recipe TOMLs are human-authored and the diff has to be
auditable.

Usage:
    python3 scripts/bump_revisions.py [--dry-run]

Typical output: one line per recipe with before->after
revisions, plus a summary of how many recipes were at each
starting revision.
"""
import argparse
import pathlib
import re
import sys

# revision = <digits> at column 0. [package] is the first
# section in every recipe and no other section uses a
# revision field, so a file-wide search is safe.
REVISION_RE = re.compile(r'^(\s*revision\s*=\s*)(\d+)\s*$', re.M)

# Matches a bare `version = "..."` line. Used as the anchor
# for inserting a revision field on recipes that don't have
# one yet.
VERSION_RE = re.compile(r'^(\s*version\s*=\s*"[^"]+"\s*)$', re.M)


def bump(path: pathlib.Path, dry_run: bool = False):
    """Increment the recipe's revision by one.

    Returns (old_revision, new_revision). Raises ValueError
    if the recipe has no version line (shouldn't happen —
    version is required).
    """
    text = path.read_text()

    m = REVISION_RE.search(text)
    if m is not None:
        old = int(m.group(2))
        new = old + 1
        if not dry_run:
            updated = text[:m.start()] + f"{m.group(1)}{new}" + text[m.end():]
            path.write_text(updated)
        return old, new

    m = VERSION_RE.search(text)
    if m is None:
        raise ValueError(f"no version = \"...\" line in {path}")
    if not dry_run:
        inserted = f"{m.group(1)}\nrevision = 2"
        path.write_text(text[:m.start()] + inserted + text[m.end():])
    return 1, 2


def iter_recipes(root: pathlib.Path):
    """Yield every recipe TOML under root, excluding binary
    index and signature sidecar files."""
    for p in sorted(root.rglob('*.toml')):
        if p.name.endswith('.binaries.toml'):
            continue
        yield p


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bump [package] revision for every recipe.")
    parser.add_argument(
        '--dry-run', action='store_true',
        help="Show what would change without writing files.")
    parser.add_argument(
        '--recipes-dir', default='recipes',
        help="Path to the recipes/ directory (default: recipes).")
    args = parser.parse_args()

    root = pathlib.Path(args.recipes_dir)
    if not root.is_dir():
        print(f"not a directory: {root}", file=sys.stderr)
        return 1

    paths = list(iter_recipes(root))
    print(f"Found {len(paths)} recipes under {root}/")
    if args.dry_run:
        print("DRY RUN — no files modified")
    print()

    from_counts: dict[int, int] = {}
    failed = 0
    for p in paths:
        try:
            old, new = bump(p, dry_run=args.dry_run)
        except ValueError as exc:
            print(f"!! {exc}")
            failed += 1
            continue
        print(f"{p}: {old} -> {new}")
        from_counts[old] = from_counts.get(old, 0) + 1

    print()
    print(f"Total: {len(paths)} recipes, {failed} failed")
    for old in sorted(from_counts):
        print(f"  {from_counts[old]} at revision {old} -> {old + 1}")
    return 0 if failed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
