#!/usr/bin/env python3
"""Required PR gate: 'version changed => ledger entry appended'.

Run by .github/workflows/ledger-check.yml — the single
required status check on main. Pure tomllib + subprocess git;
ZERO registry calls. The daily registry-coherence audit
(scripts/check_registry_coherence.py) covers what this check
structurally cannot see: external registry mutation.

Rules enforced against ``merge-base(--base, HEAD)``:

1. A changed ``recipes/<l>/<name>.toml`` whose (version,
   revision) differs from base (a missing base file is a new
   recipe, i.e. changed) must have a ``<name>.binaries.toml``
   at HEAD where:

   a. the top-level ``version`` is the bare ``<version>`` when
      revision <= 1 and exactly ``<version>-<revision>``
      otherwise — load-bearing exactness for gale's
      binaryIndexMatchesRecipe;
   b. some ``[[history]]`` entry carries
      ``version = "<version>-<revision>"`` (always full form);
   c. that entry records, for EVERY eligible platform
      (declared ``[package].platforms`` intersected with the
      CI matrix in ``.github/platforms.json``, else the full
      matrix), a well-formed ``sha256`` (64 hex) and
      ``manifest_digest`` (``sha256:<64 hex>``);
   d. the head mirror's per-platform ``sha256`` and
      ``manifest_digest`` echo that entry's values.

2. EVERY changed ``*.binaries.toml`` (whether or not its
   recipe changed) must preserve the base file's
   ``[[history]]`` entries verbatim, in order, as a prefix of
   HEAD's history. Rewriting, dropping, or reordering an
   entry fails: history is append-only.

A PR touching no recipe versions passes trivially. Exit 0
with a per-recipe summary, 1 on any violation, 2 on usage
error.

Usage:

    python3 scripts/check_ledger.py --base origin/main
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import PurePosixPath

if sys.version_info < (3, 11):
    sys.exit("check_ledger.py requires Python 3.11+ (tomllib)")

import tomllib

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

REMEDY_UNPUBLISHED = (
    "promote has not published this version yet — apply "
    "approved-for-build and wait for CI to commit the ledger"
)
REMEDY_APPEND_ONLY = "history is append-only"


class CheckError(Exception):
    """Usage-level failure (bad git state); exits 2."""


def git(*args: str) -> str:
    proc = subprocess.run(
        ["git", *args], capture_output=True, text=True
    )
    if proc.returncode != 0:
        raise CheckError(
            f"git {' '.join(args)} failed: {proc.stderr.strip()}"
        )
    return proc.stdout


def git_show(ref: str, path: str) -> str | None:
    """File content at ref, or None when it does not exist
    there."""
    proc = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    return proc.stdout


def load_matrix(repo_root: str) -> set[str]:
    """CI platform names from .github/platforms.json — the
    single source of truth for the matrix."""
    path = f"{repo_root}/.github/platforms.json"
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    platforms = {
        entry["platform"]
        for entry in data
        if isinstance(entry, dict)
        and isinstance(entry.get("platform"), str)
    }
    if not platforms:
        raise CheckError(f"{path} declares no platforms")
    return platforms


def parse_recipe(text: str, path: str) -> tuple[str, int, list | None]:
    """(version, revision, declared platforms) from recipe
    TOML text."""
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CheckError(f"{path}: invalid TOML: {exc}") from exc
    pkg = doc.get("package", {})
    version = pkg.get("version")
    if not isinstance(version, str) or not version:
        raise CheckError(f"{path}: no [package].version")
    try:
        revision = int(pkg.get("revision", 1) or 1)
    except (TypeError, ValueError):
        revision = 1
    if revision < 1:
        revision = 1
    declared = pkg.get("platforms")
    if not isinstance(declared, list):
        declared = None
    return version, revision, declared


def mirror_version(version: str, revision: int) -> str:
    """Bare for revision <= 1, exact full form otherwise."""
    if revision <= 1:
        return version
    return f"{version}-{revision}"


def eligible_platforms(
    declared: list | None, matrix: set[str]
) -> set[str]:
    """Declared [package].platforms intersected with the CI
    matrix; the full matrix when nothing (usable) is
    declared — same fallback as the CI writer."""
    if declared is None:
        return set(matrix)
    eligible = {p for p in declared if p in matrix}
    return eligible or set(matrix)


def check_published(
    name: str,
    binaries_text: str | None,
    binaries_path: str,
    version: str,
    revision: int,
    eligible: set[str],
) -> list[str]:
    """Rules 1a-1d for one version-changed recipe. Returns
    error strings (empty = pass)."""
    full = f"{version}-{revision}"
    if binaries_text is None:
        return [
            f"{name}: {binaries_path} is missing at HEAD; a "
            f"(version, revision) change requires a [[history]] "
            f"entry for '{full}' — {REMEDY_UNPUBLISHED}"
        ]
    try:
        doc = tomllib.loads(binaries_text)
    except tomllib.TOMLDecodeError as exc:
        return [f"{name}: {binaries_path}: invalid TOML: {exc}"]

    errors: list[str] = []

    expected_mirror = mirror_version(version, revision)
    actual_mirror = doc.get("version")
    if actual_mirror != expected_mirror:
        errors.append(
            f"{name}: head mirror version is "
            f"{actual_mirror!r}, expected {expected_mirror!r} "
            f"(bare for revision <= 1, exact "
            f"'<version>-<revision>' otherwise) — "
            f"{REMEDY_UNPUBLISHED}"
        )

    history = doc.get("history")
    if not isinstance(history, list):
        history = []
    matches = [
        e
        for e in history
        if isinstance(e, dict) and e.get("version") == full
    ]
    if not matches:
        errors.append(
            f"{name}: no [[history]] entry with version = "
            f"'{full}' in {binaries_path} — {REMEDY_UNPUBLISHED}"
        )
        return errors
    entry = matches[-1]

    for platform in sorted(eligible):
        rec = entry.get(platform)
        if not isinstance(rec, dict):
            errors.append(
                f"{name}: history entry '{full}' lacks platform "
                f"'{platform}' — {REMEDY_UNPUBLISHED}"
            )
            continue
        sha = rec.get("sha256")
        digest = rec.get("manifest_digest")
        if not isinstance(sha, str) or not SHA256_RE.match(sha):
            errors.append(
                f"{name}: history entry '{full}' platform "
                f"'{platform}' sha256 must match "
                f"^[0-9a-f]{{64}}$, got {sha!r}"
            )
        if not isinstance(digest, str) or not MANIFEST_DIGEST_RE.match(
            digest
        ):
            errors.append(
                f"{name}: history entry '{full}' platform "
                f"'{platform}' manifest_digest must match "
                f"^sha256:[0-9a-f]{{64}}$, got {digest!r}"
            )

        mirror = doc.get(platform)
        if not isinstance(mirror, dict):
            errors.append(
                f"{name}: head mirror has no [{platform}] table "
                f"to echo history entry '{full}' — "
                f"{REMEDY_UNPUBLISHED}"
            )
            continue
        if mirror.get("sha256") != sha:
            errors.append(
                f"{name}: [{platform}] mirror sha256 "
                f"{mirror.get('sha256')!r} does not echo history "
                f"entry '{full}' ({sha!r})"
            )
        if mirror.get("manifest_digest") != digest:
            errors.append(
                f"{name}: [{platform}] mirror manifest_digest "
                f"{mirror.get('manifest_digest')!r} does not echo "
                f"history entry '{full}' ({digest!r})"
            )
    return errors


def parse_history(text: str | None, path: str) -> list[dict]:
    if text is None:
        return []
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise CheckError(f"{path}: invalid TOML: {exc}") from exc
    history = doc.get("history")
    return history if isinstance(history, list) else []


def check_append_only(
    path: str, base_text: str | None, head_text: str | None
) -> list[str]:
    """Rule 2: base history entries survive verbatim, in
    order, as a prefix of HEAD history."""
    try:
        base_history = parse_history(base_text, f"{path}@base")
    except CheckError as exc:
        # A base file that never parsed can't constrain HEAD.
        print(f"note: {exc}; skipping append-only check")
        return []
    if not base_history:
        return []
    try:
        head_history = parse_history(head_text, f"{path}@HEAD")
    except CheckError as exc:
        return [str(exc)]
    if head_history[: len(base_history)] != base_history:
        return [
            f"{path}: a base [[history]] entry was rewritten, "
            f"dropped, or reordered ({len(base_history)} base "
            f"entries must survive verbatim as a prefix) — "
            f"{REMEDY_APPEND_ONLY}"
        ]
    return []


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--base",
        default="origin/main",
        help="base ref to diff against (default: origin/main)",
    )
    args = ap.parse_args(argv)

    try:
        repo_root = git("rev-parse", "--show-toplevel").strip()
        merge_base = git("merge-base", args.base, "HEAD").strip()
        changed = [
            line
            for line in git(
                "diff",
                "--name-only",
                merge_base,
                "HEAD",
                "--",
                "recipes/",
            ).splitlines()
            if line
        ]
        matrix = load_matrix(repo_root)
    except (CheckError, OSError, json.JSONDecodeError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 2

    errors: list[str] = []
    summary: list[str] = []

    recipe_paths = sorted(
        p
        for p in changed
        if p.endswith(".toml") and not p.endswith(".binaries.toml")
    )
    for path in recipe_paths:
        name = PurePosixPath(path).stem
        head_text = git_show("HEAD", path)
        if head_text is None:
            # Recipe deleted: nothing to publish. Its ledger
            # is still guarded by the append-only rule below.
            summary.append(f"{name}: recipe deleted; no entry required")
            continue
        try:
            version, revision, declared = parse_recipe(
                head_text, path
            )
        except CheckError as exc:
            errors.append(str(exc))
            continue

        base_text = git_show(merge_base, path)
        if base_text is not None:
            try:
                base_version, base_revision, _ = parse_recipe(
                    base_text, f"{path}@base"
                )
            except CheckError:
                base_version, base_revision = None, None
            if (version, revision) == (base_version, base_revision):
                summary.append(
                    f"{name}: (version, revision) unchanged "
                    f"({version}-{revision}); no entry required"
                )
                continue

        binaries_path = path[: -len(".toml")] + ".binaries.toml"
        eligible = eligible_platforms(declared, matrix)
        recipe_errors = check_published(
            name,
            git_show("HEAD", binaries_path),
            binaries_path,
            version,
            revision,
            eligible,
        )
        if recipe_errors:
            errors.extend(recipe_errors)
        else:
            summary.append(
                f"{name}: ledger entry {version}-{revision} "
                f"complete ({len(eligible)} platform(s)), mirror "
                f"in agreement"
            )

    for path in sorted(p for p in changed if p.endswith(".binaries.toml")):
        append_errors = check_append_only(
            path, git_show(merge_base, path), git_show("HEAD", path)
        )
        if append_errors:
            errors.extend(append_errors)
        else:
            summary.append(f"{path}: history append-only OK")

    for line in summary:
        print(f"OK {line}")
    if errors:
        for err in errors:
            print(f"::error::{err}", file=sys.stderr)
        print(
            f"ledger check FAILED with {len(errors)} error(s)",
            file=sys.stderr,
        )
        return 1
    if not changed:
        print("OK no recipe changes; ledger check passes trivially")
    print("ledger check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
