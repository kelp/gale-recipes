#!/usr/bin/env python3
"""Regex-based edits for recipe TOMLs.

Matches the pattern in bump_revisions.py — read text,
regex substitute, write back. Keeps comments and
whitespace intact because recipe files are human-authored
and the PR diffs have to be auditable.

Used by .github/scripts/auto-update.sh to bump version,
url, sha256, and released_at fields, and to strip stale
[binary.*] sections (CI repopulates them after merge).

CLI:
    update_recipe.py set-field <path> <field> <old> <new>
    update_recipe.py strip-binary <path>
"""
import argparse
import pathlib
import re
import sys


# Match `[binary.<anything>]` section header through the
# section body, stopping at the next top-level section
# header or end of string. [^\[] is safe inside a binary
# section because the only content there is key = "value"
# lines — no inline arrays with `[` at column 0.
BINARY_SECTION_RE = re.compile(
    r'^\[binary\.[^\]]+\][^\[]*(?=^\[|\Z)', re.M)


def set_field(path: pathlib.Path, field: str,
              old_value: str, new_value: str) -> bool:
    """Replace `<field> = "<old_value>"` with the new value.

    Returns True on replacement, False if the exact line
    wasn't found. Requiring the old value makes this safe
    even when the same field name appears in multiple
    sections (e.g. `url` in both `[source]` and
    `[binary.*]`).
    """
    text = path.read_text()
    pattern = re.compile(
        rf'^({re.escape(field)}\s*=\s*)"{re.escape(old_value)}"',
        re.M)
    m = pattern.search(text)
    if m is None:
        return False
    updated = text[:m.start()] + f'{m.group(1)}"{new_value}"' + text[m.end():]
    path.write_text(updated)
    return True


def strip_binary_sections(path: pathlib.Path) -> int:
    """Remove every [binary.*] section from the file.

    Returns the number of sections removed. CI rewrites
    these blocks after an auto-update PR merges, so
    stripping them here keeps the PR diff clean (no stale
    hashes pointing at the prior version's build).
    """
    text = path.read_text()
    stripped, count = BINARY_SECTION_RE.subn('', text)
    if count:
        path.write_text(stripped)
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='cmd', required=True)

    sf = sub.add_parser('set-field')
    sf.add_argument('path', type=pathlib.Path)
    sf.add_argument('field')
    sf.add_argument('old')
    sf.add_argument('new')

    sb = sub.add_parser('strip-binary')
    sb.add_argument('path', type=pathlib.Path)

    args = parser.parse_args()

    if args.cmd == 'set-field':
        ok = set_field(args.path, args.field, args.old, args.new)
        if not ok:
            print(
                f"{args.path}: no line matching "
                f'{args.field} = "{args.old}"',
                file=sys.stderr)
            return 1
        return 0

    if args.cmd == 'strip-binary':
        n = strip_binary_sections(args.path)
        print(f"{args.path}: stripped {n} binary section(s)")
        return 0

    return 2


if __name__ == '__main__':
    sys.exit(main())
