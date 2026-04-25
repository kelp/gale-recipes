#!/usr/bin/env python3
"""Match GitHub Security Advisories against recipe versions.

Reads `gh api /repos/<owner>/<repo>/security-advisories`
output (a JSON array on stdin or a file path) and one or
more (label, version) pairs. Emits a JSON array of
advisories whose ``vulnerable_version_range`` matches at
least one input version, with ``applies_to`` listing the
matching labels.

Only published advisories are considered. Versions must be
dot-separated integers (the auto-update workflow enforces
this via its non-semver filter, so any string passed here
is already known to be that shape).

Range syntax (npm-style, as emitted by the GitHub API):

    >=1.0.3 <3.5.0          # space-separated AND
    >=1.0.0, <2.0.0         # comma-separated AND
    < 4.0.4                 # whitespace around comparator
    1.0.0                   # bare version → exact match

A range that fails to parse is treated as "no match" — one
malformed advisory shouldn't take down the whole run.

CLI:
    check_ghsa.py <advisories.json|-> <label=version>...

    e.g.
    check_ghsa.py advisories.json current=10.4.2 upstream=10.5.0
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path


# Comparator + version. Whitespace-tolerant. Bare version
# (no comparator) is treated as exact match.
CLAUSE_RE = re.compile(r'^(<=|>=|<|>|=)?\s*(\d+(?:\.\d+)*)$')


def _parse_version(s: str) -> tuple[int, ...]:
    return tuple(int(p) for p in s.split('.'))


def _cmp(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """Compare two version tuples after right-padding with
    zeros (so 1.5 == 1.5.0)."""
    n = max(len(a), len(b))
    a = a + (0,) * (n - len(a))
    b = b + (0,) * (n - len(b))
    return (a > b) - (a < b)


def _match_clause(v: tuple[int, ...], clause: str) -> bool:
    m = CLAUSE_RE.match(clause)
    if not m:
        return False
    op = m.group(1) or '='
    try:
        target = _parse_version(m.group(2))
    except ValueError:
        return False
    c = _cmp(v, target)
    if op == '=':
        return c == 0
    if op == '<':
        return c < 0
    if op == '<=':
        return c <= 0
    if op == '>':
        return c > 0
    if op == '>=':
        return c >= 0
    return False


def matches_range(version: str, range_str: str) -> bool:
    """True iff ``version`` falls inside ``range_str``.

    Range is one or more clauses joined by AND. Clauses
    may be space-separated, comma-separated, or both.
    Returns False on any parse failure rather than
    raising — a malformed advisory should be ignored, not
    propagate a crash to the dashboard.
    """
    if not range_str or not version:
        return False
    try:
        v = _parse_version(version)
    except ValueError:
        return False

    # Tokenize: split on commas and whitespace, then
    # re-join op+version pairs (e.g. ">=" + "1.0.0").
    tokens = range_str.replace(',', ' ').split()
    clauses: list[str] = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ('<', '<=', '>', '>=', '='):
            if i + 1 >= len(tokens):
                return False
            clauses.append(f"{tok}{tokens[i + 1]}")
            i += 2
        else:
            clauses.append(tok)
            i += 1
    if not clauses:
        return False
    return all(_match_clause(v, c) for c in clauses)


def match_advisories(
    advisories: list[dict],
    versions: list[tuple[str, str]],
) -> list[dict]:
    """Return each published advisory whose vulnerability
    range matches one or more of the input versions.

    ``versions`` is a list of (label, version) tuples;
    labels appear in the returned ``applies_to`` array.
    Advisories with multiple vulnerable_version_range
    entries are returned once — one match is enough to
    flag the recipe.
    """
    out: list[dict] = []
    for adv in advisories or []:
        if not isinstance(adv, dict):
            continue
        if adv.get('state') != 'published':
            continue
        applies: list[str] = []
        matched_range = ''
        for vuln in adv.get('vulnerabilities') or []:
            if not isinstance(vuln, dict):
                continue
            range_str = vuln.get('vulnerable_version_range') or ''
            for label, version in versions:
                if label in applies:
                    continue
                if matches_range(version, range_str):
                    applies.append(label)
                    matched_range = range_str
        if applies:
            out.append({
                'ghsa_id':  adv.get('ghsa_id'),
                'cve_id':   adv.get('cve_id'),
                'severity': adv.get('severity'),
                'html_url': adv.get('html_url'),
                'range':    matched_range,
                'applies_to': applies,
            })
    return out


def _load(src: str) -> list[dict]:
    if src == '-':
        data = json.load(sys.stdin)
    else:
        data = json.loads(Path(src).read_text())
    if not isinstance(data, list):
        raise SystemExit(f"expected JSON array, got {type(data).__name__}")
    return data


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    advisories = _load(argv[0])
    versions: list[tuple[str, str]] = []
    for spec in argv[1:]:
        if '=' not in spec:
            print(f"bad label=version: {spec}", file=sys.stderr)
            return 2
        label, _, ver = spec.partition('=')
        if label and ver:
            versions.append((label, ver))
    matches = match_advisories(advisories, versions)
    json.dump(matches, sys.stdout)
    sys.stdout.write('\n')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
