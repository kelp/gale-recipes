#!/usr/bin/env python3
"""Write per-recipe ``.binaries.toml`` files from CI build metadata.

Replaces the bash ``Write .binaries.toml files`` step in
``.github/workflows/build.yml``. Reads one metadata JSON per
built (recipe, platform) cell from ``--metadata-dir`` and
regenerates each recipe's ``.binaries.toml`` with two parts:

1. **Head mirror** — what deployed gale v0.16.5 clients parse:
   a top-level ``version`` string plus one flat ``[<platform>]``
   table per built platform with ``sha256``, ``manifest_digest``,
   and ``deps``. The version string is *exactly* the bare
   ``<version>`` for revision <= 1 and ``<version>-<revision>``
   otherwise — gale's binaryIndexMatchesRecipe accepts the bare
   form only for revision <= 1, so a wrong string silently
   source-builds the catalog.
2. **Append-only ledger** — ``[[history]]`` blocks keyed by the
   always-full ``<version>-<revision>`` string with one
   ``<platform> = { sha256, manifest_digest }`` inline table per
   platform. v0.16.5's ParseBinaryIndex skips arrays-of-tables,
   so the ledger is invisible to deployed clients. Existing
   history text is preserved VERBATIM (text splice from the
   first ``[[history]]`` line); only the mirror prefix above it
   is regenerated.

Rules:

- Per-recipe all-eligible gate: a recipe's file is rewritten
  only when every eligible platform (declared
  ``[package].platforms`` intersected with the CI matrix from
  ``.github/platforms.json``, else the full matrix) produced
  metadata. Partial builds keep the existing file.
- Hard fail when any metadata JSON lacks a well-formed
  ``manifest_digest`` (``sha256:<64 hex>``) or ``sha256``
  (``<64 hex>``) — the ledger must never silently lose digests.
- Idempotency: a ``[[history]]`` entry that already records the
  same ``<version>-<revision>`` with identical per-platform
  digests appends nothing (the re-promote-after-adopt path).
  The same key with DIFFERENT digests is a hard error: the
  ledger is append-only; bump ``[package].revision`` to publish
  new bytes.
- Self-check before writing: the produced text must parse as
  TOML, the preserved history must survive byte-identical, and
  the mirror digests must equal the newest history entry's.

Stdlib only. Usage:

    python3 scripts/write_binaries.py \\
        --metadata-dir /tmp/metadata --repo-root .
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("write_binaries.py requires Python 3.11+ (tomllib)")

import tomllib

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
HISTORY_LINE_RE = re.compile(r"(?m)^\[\[history\]\]$")


class WriterError(Exception):
    """Fatal condition; main() prints it as ::error:: and
    exits 1."""


def load_matrix(platforms_path: Path) -> set[str]:
    """Platform names from .github/platforms.json — the single
    source of truth for the CI matrix. Never hardcode it."""
    data = json.loads(platforms_path.read_text())
    if not isinstance(data, list) or not data:
        raise WriterError(
            f"{platforms_path} must be a non-empty JSON array"
        )
    platforms: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict) or not isinstance(
            entry.get("platform"), str
        ):
            raise WriterError(
                f"{platforms_path}: each entry needs a string "
                f"'platform'; bad entry {entry!r}"
            )
        platforms.add(entry["platform"])
    return platforms


def validate_metadata(meta: dict, source: Path) -> None:
    """The ledger must never silently lose digests: every
    consumed metadata JSON must carry well-formed sha256 and
    manifest_digest values."""
    for key in ("recipe", "platform"):
        if not isinstance(meta.get(key), str) or not meta[key]:
            raise WriterError(
                f"{source}: missing or empty '{key}'"
            )
    sha = meta.get("sha256")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        raise WriterError(
            f"{source}: sha256 must match ^[0-9a-f]{{64}}$, "
            f"got {sha!r}"
        )
    digest = meta.get("manifest_digest")
    if not isinstance(digest, str) or not MANIFEST_DIGEST_RE.match(
        digest
    ):
        raise WriterError(
            f"{source}: manifest_digest must match "
            f"^sha256:[0-9a-f]{{64}}$, got {digest!r}"
        )


def eligible_platforms(
    recipe_data: dict, matrix: set[str], recipe_name: str
) -> set[str]:
    """Declared [package].platforms intersected with the CI
    matrix when declared, else the full matrix."""
    declared = recipe_data.get("package", {}).get("platforms")
    if not isinstance(declared, list):
        return set(matrix)
    eligible = {p for p in declared if p in matrix}
    if not eligible:
        raise WriterError(
            f"{recipe_name}: declared platforms {declared!r} "
            f"have no overlap with the CI matrix {sorted(matrix)}"
        )
    return eligible


def mirror_version(version: str, revision: int) -> str:
    """Bare for revision <= 1, exact full form otherwise.
    Load-bearing exactness — see module docstring."""
    if revision <= 1:
        return version
    return f"{version}-{revision}"


def render_mirror(version_str: str, entries: dict[str, dict]) -> str:
    """The v0.16.5-readable head mirror, byte-compatible with
    the bash writer this replaces (manifest_digest is the one
    additive line; deployed clients ignore unknown keys)."""
    parts = [f'version = "{version_str}"\n']
    for platform in sorted(entries):
        e = entries[platform]
        parts.append(f"\n[{platform}]\n")
        parts.append(f'sha256 = "{e["sha256"]}"\n')
        parts.append(
            f'manifest_digest = "{e["manifest_digest"]}"\n'
        )
        deps = e.get("deps") or []
        if deps:
            parts.append("deps = [\n")
            for dep in deps:
                name = dep.get("name", "")
                ver = dep.get("version", "")
                rev = int(dep.get("revision", 1) or 1)
                parts.append(
                    f'  {{ name = "{name}", version = "{ver}", '
                    f"revision = {rev} }},\n"
                )
            parts.append("]\n")
    return "".join(parts)


def render_history_entry(
    full_version: str, entries: dict[str, dict]
) -> str:
    parts = ["[[history]]\n", f'version = "{full_version}"\n']
    for platform in sorted(entries):
        e = entries[platform]
        parts.append(
            f'{platform} = {{ sha256 = "{e["sha256"]}", '
            f'manifest_digest = "{e["manifest_digest"]}" }}\n'
        )
    return "".join(parts)


def split_history(text: str) -> str:
    """Return the verbatim history region: everything from the
    first line that is exactly ``[[history]]`` to EOF. Empty
    string when the file has no ledger yet."""
    m = HISTORY_LINE_RE.search(text)
    if not m:
        return ""
    return text[m.start():]


def build_output(
    existing_text: str | None,
    version: str,
    revision: int,
    entries: dict[str, dict],
) -> str:
    """Compose the new file text: regenerated mirror prefix,
    verbatim-preserved prior history, and (unless idempotent)
    one appended history entry."""
    full = f"{version}-{revision}"
    new_platforms = {
        p: {
            "sha256": e["sha256"],
            "manifest_digest": e["manifest_digest"],
        }
        for p, e in entries.items()
    }

    preserved = split_history(existing_text or "")
    append_entry = True
    if preserved:
        try:
            prior = tomllib.loads(preserved).get("history", [])
        except tomllib.TOMLDecodeError as exc:
            raise WriterError(
                f"existing [[history]] region does not parse: {exc}"
            ) from exc
        for entry in prior:
            if entry.get("version") != full:
                continue
            recorded = {
                k: v for k, v in entry.items() if k != "version"
            }
            if recorded == new_platforms:
                append_entry = False
            else:
                raise WriterError(
                    f"ledger already records {full} with "
                    f"different digests; the ledger is "
                    f"append-only — bump [package].revision "
                    f"to publish new bytes"
                )

    out = render_mirror(mirror_version(version, revision), entries)
    if preserved:
        out += "\n" + preserved
    if append_entry:
        if not out.endswith("\n"):
            out += "\n"
        out += "\n" + render_history_entry(full, entries)

    self_check(out, preserved, entries)
    return out


def self_check(
    out: str, preserved: str, entries: dict[str, dict]
) -> None:
    """Final safety net before any bytes hit disk."""
    try:
        doc = tomllib.loads(out)
    except tomllib.TOMLDecodeError as exc:
        raise WriterError(
            f"self-check: produced text is not valid TOML: {exc}"
        ) from exc
    if preserved and preserved not in out:
        raise WriterError(
            "self-check: prior history blocks did not survive "
            "byte-identical"
        )
    history = doc.get("history", [])
    if not history:
        raise WriterError("self-check: output has no history entry")
    newest = history[-1]
    for platform, e in entries.items():
        mirror = doc.get(platform, {})
        recorded = newest.get(platform, {})
        if mirror.get("sha256") != e["sha256"] or recorded.get(
            "sha256"
        ) != e["sha256"]:
            raise WriterError(
                f"self-check: {platform} sha256 mismatch between "
                f"mirror and newest history entry"
            )
        if mirror.get("manifest_digest") != e[
            "manifest_digest"
        ] or recorded.get("manifest_digest") != e["manifest_digest"]:
            raise WriterError(
                f"self-check: {platform} manifest_digest mismatch "
                f"between mirror and newest history entry"
            )


def load_recipe(repo_root: Path, name: str) -> tuple[Path, dict]:
    recipe_file = repo_root / "recipes" / name[0] / f"{name}.toml"
    if not recipe_file.is_file():
        raise WriterError(
            f"metadata names recipe '{name}' but "
            f"{recipe_file} does not exist"
        )
    with recipe_file.open("rb") as fh:
        return recipe_file, tomllib.load(fh)


def recipe_version(recipe_data: dict, name: str) -> tuple[str, int]:
    pkg = recipe_data.get("package", {})
    version = pkg.get("version")
    if not isinstance(version, str) or not version:
        raise WriterError(f"{name}: recipe has no [package].version")
    try:
        revision = int(pkg.get("revision", 1) or 1)
    except (TypeError, ValueError):
        revision = 1
    if revision < 1:
        revision = 1
    return version, revision


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--metadata-dir",
        type=Path,
        required=True,
        help="directory of per-(recipe,platform) metadata JSONs",
    )
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="repository root (default: .)",
    )
    args = ap.parse_args(argv)

    try:
        matrix = load_matrix(
            args.repo_root / ".github" / "platforms.json"
        )

        groups: dict[str, dict[str, dict]] = {}
        for meta_file in sorted(args.metadata_dir.glob("*.json")):
            try:
                meta = json.loads(meta_file.read_text())
            except json.JSONDecodeError as exc:
                raise WriterError(
                    f"{meta_file}: invalid JSON: {exc}"
                ) from exc
            validate_metadata(meta, meta_file)
            groups.setdefault(meta["recipe"], {})[
                meta["platform"]
            ] = meta

        if not groups:
            print("No build metadata found; nothing to write")
            return 0

        for recipe in sorted(groups):
            metas = groups[recipe]
            _, recipe_data = load_recipe(args.repo_root, recipe)
            version, revision = recipe_version(recipe_data, recipe)
            eligible = eligible_platforms(
                recipe_data, matrix, recipe
            )
            built = set(metas)
            binaries_file = (
                args.repo_root
                / "recipes"
                / recipe[0]
                / f"{recipe}.binaries.toml"
            )
            if not eligible <= built:
                print(
                    f"::warning::Skipping {recipe}: "
                    f"{len(built)}/{len(eligible)} platforms "
                    f"built; keeping existing {binaries_file}"
                )
                continue

            existing = (
                binaries_file.read_text()
                if binaries_file.is_file()
                else None
            )
            out = build_output(existing, version, revision, metas)
            if existing == out:
                print(f"Unchanged {binaries_file}")
                continue
            binaries_file.write_text(out)
            print(f"Wrote {binaries_file}")
    except WriterError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
