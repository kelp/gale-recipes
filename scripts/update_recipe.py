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
    update_recipe.py derive-url <old_url> <old_ver> <new_ver> <new_tag>
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


# Characters allowed in an upstream tag or version before it
# is substituted into a source URL. Covers every real tag we
# ship (v1.2.3, go1.26.1, openssl-4.0.0, gopls/v0.22.0, 1.2.3+x)
# while rejecting the shell/sed metacharacters that made the
# old `sed "s|${old_tag}|${new_tag}|g"` pipeline injectable —
# `|` enabled GNU sed's `e` (execute) command, `$()`/backticks
# enabled command substitution upstream of that. Anchored and
# non-empty.
SAFE_TAG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._+~/-]*$')


def _check_safe(label: str, value: str) -> None:
    if not SAFE_TAG_RE.match(value):
        raise ValueError(
            f"unsafe {label} {value!r}: must match "
            f"[A-Za-z0-9][A-Za-z0-9._+~/-]*")


def derive_url(old_url: str, old_version: str,
               new_version: str, new_tag: str) -> str:
    """Compute the new source URL via literal string
    substitution — the injection-safe replacement for the
    sed pipeline in auto-update.sh.

    Mirrors the original logic: detect the old tag from the
    URL shape, replace old_tag -> new_tag then
    old_version -> new_version. Raises ValueError on an
    unrecognized URL pattern or on a tag/version carrying
    shell/sed metacharacters.
    """
    _check_safe("new tag", new_tag)
    _check_safe("new version", new_version)

    marker_tags = "/archive/refs/tags/"
    marker_rel = "/releases/download/"
    if marker_tags in old_url:
        old_tag = old_url.split(marker_tags, 1)[1]
        if old_tag.endswith(".tar.gz"):
            old_tag = old_tag[: -len(".tar.gz")]
    elif marker_rel in old_url:
        old_tag = old_url.split(marker_rel, 1)[1].split("/", 1)[0]
    elif old_version in old_url:
        # No tag segment, but the version appears literally
        # (mirror URLs for tag-source recipes). Version
        # substitution alone does the work.
        old_tag = ""
    else:
        raise ValueError(
            f"unrecognized URL pattern for auto-rewrite: {old_url}")

    url = old_url
    if old_tag:
        _check_safe("old tag", old_tag)
        url = url.replace(old_tag, new_tag)
    url = url.replace(old_version, new_version)
    return url


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

    du = sub.add_parser('derive-url')
    du.add_argument('old_url')
    du.add_argument('old_version')
    du.add_argument('new_version')
    du.add_argument('new_tag')

    args = parser.parse_args()

    if args.cmd == 'derive-url':
        try:
            print(derive_url(args.old_url, args.old_version,
                             args.new_version, args.new_tag))
        except ValueError as exc:
            print(f"derive-url: {exc}", file=sys.stderr)
            return 1
        return 0

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
