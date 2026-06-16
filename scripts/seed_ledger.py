#!/usr/bin/env python3
"""Maintainer-run ledger backfill: anchor legacy bare tags.

Used in the republish prerequisites; no workflow runs this.
For each recipe with a ``.binaries.toml``, for each mirror
platform entry, it fetches the legacy bare tag
``<bare-version>-<platform>`` from GHCR and compares the
manifest's ``layers[0].digest`` against the mirror's sha256:

- **healthy** (digest matches): ``oras tag
  ghcr.io/<repo>/<name>@<manifest-digest>
  <version>-<revision>-<platform>`` — idempotent; tags the
  existing manifest, pushes no content — and the platform's
  ``{sha256, manifest_digest}`` pair is recorded.
- **mismatch or 404**: the recipe goes on the republish
  worklist (JSON output) and is not seeded.
- **5xx / unreachable after retries**: an audit error — never
  treated as absent; the recipe is neither seeded nor put on
  the worklist. Re-run.

Only recipes where EVERY mirror platform is healthy get a
seeded ``[[history]]`` block appended. The emit function is
shared with scripts/write_binaries.py (the CI ledger writer)
so seeded blocks are byte-identical to CI-written ones; the
mirror bytes above the ledger are never touched. A recipe
whose mirror already records the recipe's
``<version>-<revision>`` in history is skipped (idempotent).
A recipe whose mirror version disagrees with the recipe's
(version, revision) — drift — goes on the republish worklist:
its mirror digests describe an older version.

Requires ``oras login ghcr.io`` with a packages:write PAT for
the tagging step. ``--dry-run`` prints planned actions
without tagging or writing.

Usage:

    python3 scripts/seed_ledger.py --repo-root . --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("seed_ledger.py requires Python 3.11+ (tomllib)")

import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_registry_coherence import (  # noqa: E402
    SHA256_RE,
    default_http_get,
    fetch_manifest,
    header,
)


class SeedError(Exception):
    """Per-recipe fatal condition recorded in result errors."""


def _writer():
    """The CI ledger writer owns the [[history]] emit format;
    seeding must share it so seeded blocks are byte-identical
    to CI-written ones."""
    try:
        import write_binaries
    except ImportError as exc:
        raise SeedError(
            "scripts/write_binaries.py (the CI ledger writer) is "
            "required for seeding; run from a tree where it exists"
        ) from exc
    return write_binaries


def default_runner(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def recipe_version(repo_root: Path, name: str) -> tuple[str, int]:
    recipe_file = repo_root / "recipes" / name[0] / f"{name}.toml"
    if not recipe_file.is_file():
        raise SeedError(f"{name}: no recipe at {recipe_file}")
    with recipe_file.open("rb") as fh:
        pkg = tomllib.load(fh).get("package", {})
    version = pkg.get("version")
    if not isinstance(version, str) or not version:
        raise SeedError(f"{name}: recipe has no [package].version")
    try:
        revision = int(pkg.get("revision", 1) or 1)
    except (TypeError, ValueError):
        revision = 1
    return version, max(revision, 1)


def mirror_version(version: str, revision: int) -> str:
    if revision <= 1:
        return version
    return f"{version}-{revision}"


def probe_platform(
    name: str,
    bare_tag: str,
    mirror_sha: str,
    ghcr_repo: str,
    http_get,
) -> tuple[str, str | None]:
    """('healthy', manifest_digest) | ('republish', None) on
    mismatch/404. Raises SeedError on audit errors (5xx,
    unreachable) — never treated as absent."""
    resp = fetch_manifest(name, bare_tag, ghcr_repo, http_get)
    if resp is None:
        raise SeedError(
            f"{name}:{bare_tag}: GHCR unreachable or 5xx after "
            f"retries — never treated as absent; re-run"
        )
    status, headers, body = resp
    if status == 404:
        print(
            f"REPUBLISH {name}: legacy tag {bare_tag} not found",
            file=sys.stderr,
        )
        return "republish", None
    if status != 200:
        raise SeedError(
            f"{name}:{bare_tag}: unexpected HTTP {status}"
        )
    body_md = "sha256:" + hashlib.sha256(body).hexdigest()
    served_md = header(headers, "Docker-Content-Digest") or body_md
    if served_md != body_md:
        raise SeedError(
            f"{name}:{bare_tag}: Docker-Content-Digest "
            f"{served_md} disagrees with served body {body_md}"
        )
    try:
        layers = json.loads(body).get("layers") or []
        layer_digest = layers[0].get("digest", "")
    except (json.JSONDecodeError, AttributeError, IndexError):
        layer_digest = ""
    if layer_digest != f"sha256:{mirror_sha}":
        print(
            f"REPUBLISH {name}: {bare_tag} layer "
            f"{layer_digest or '<missing>'} != mirror "
            f"sha256:{mirror_sha}",
            file=sys.stderr,
        )
        return "republish", None
    return "healthy", served_md


def append_history(
    path: Path, full: str, entries: dict[str, dict]
) -> None:
    """Append one seeded [[history]] block, mirror bytes
    untouched, then self-check the result parses and carries
    the entry."""
    render = _writer().render_history_entry
    text = path.read_text()
    out = text
    if not out.endswith("\n"):
        out += "\n"
    out += "\n" + render(full, entries)
    doc = tomllib.loads(out)  # self-check: must stay valid TOML
    if not any(
        e.get("version") == full for e in doc.get("history", [])
    ):
        raise SeedError(
            f"{path}: self-check failed — appended entry "
            f"'{full}' not parseable back"
        )
    if not out.startswith(text):
        raise SeedError(
            f"{path}: self-check failed — existing bytes changed"
        )
    path.write_text(out)


def seed_one(
    repo_root: Path,
    binaries_path: Path,
    ghcr_repo: str,
    http_get,
    runner,
    dry_run: bool,
) -> str:
    """'seeded' | 'republish' | 'already' for one recipe."""
    name = binaries_path.name[: -len(".binaries.toml")]
    doc = tomllib.loads(binaries_path.read_text())
    version, revision = recipe_version(repo_root, name)
    full = f"{version}-{revision}"

    history = doc.get("history")
    if isinstance(history, list) and any(
        isinstance(e, dict) and e.get("version") == full
        for e in history
    ):
        print(f"ALREADY {name}: history has {full}", file=sys.stderr)
        return "already"

    if doc.get("version") != mirror_version(version, revision):
        print(
            f"REPUBLISH {name}: mirror version "
            f"{doc.get('version')!r} != recipe "
            f"{mirror_version(version, revision)!r} (drift)",
            file=sys.stderr,
        )
        return "republish"

    mirror_platforms = {
        key: value
        for key, value in doc.items()
        if isinstance(value, dict) and key != "history"
    }
    if not mirror_platforms:
        print(
            f"REPUBLISH {name}: mirror has no platform tables",
            file=sys.stderr,
        )
        return "republish"

    seeded_entries: dict[str, dict] = {}
    for platform, table in sorted(mirror_platforms.items()):
        sha = table.get("sha256")
        if not isinstance(sha, str) or not SHA256_RE.match(sha):
            print(
                f"REPUBLISH {name}: [{platform}] sha256 {sha!r} "
                f"malformed",
                file=sys.stderr,
            )
            return "republish"
        status, manifest_digest = probe_platform(
            name, f"{version}-{platform}", sha, ghcr_repo, http_get
        )
        if status != "healthy":
            return "republish"
        seeded_entries[platform] = {
            "sha256": sha,
            "manifest_digest": manifest_digest,
        }

    for platform, entry in sorted(seeded_entries.items()):
        cmd = [
            "oras",
            "tag",
            f"ghcr.io/{ghcr_repo}/{name}@{entry['manifest_digest']}",
            f"{full}-{platform}",
        ]
        if dry_run:
            print(f"DRY-RUN would run: {' '.join(cmd)}", file=sys.stderr)
        else:
            runner(cmd)

    if dry_run:
        print(
            f"DRY-RUN would append [[history]] {full} to "
            f"{binaries_path} ({len(seeded_entries)} platform(s))",
            file=sys.stderr,
        )
    else:
        append_history(binaries_path, full, seeded_entries)
        print(f"SEEDED {name}: {full}", file=sys.stderr)
    return "seeded"


def seed(
    repo_root: Path,
    ghcr_repo: str,
    http_get=default_http_get,
    runner=default_runner,
    dry_run: bool = True,
    only: set[str] | None = None,
) -> dict:
    result: dict = {
        "seeded": [],
        "republish": [],
        "already": [],
        "errors": [],
    }
    for path in sorted(repo_root.glob("recipes/**/*.binaries.toml")):
        name = path.name[: -len(".binaries.toml")]
        if only is not None and name not in only:
            continue
        try:
            outcome = seed_one(
                repo_root, path, ghcr_repo, http_get, runner, dry_run
            )
        except (SeedError, tomllib.TOMLDecodeError, OSError) as exc:
            result["errors"].append(f"{name}: {exc}")
            continue
        result[outcome].append(name)
    return result


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo-root", type=Path, default=Path("."))
    ap.add_argument(
        "--ghcr-repo",
        default=os.environ.get(
            "GITHUB_REPOSITORY", "kelp/gale-recipes"
        ),
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="print actions without tagging or writing",
    )
    ap.add_argument(
        "--recipe",
        action="append",
        default=None,
        metavar="NAME",
        help="limit to the named recipe(s); repeatable "
        "(spot-check mode)",
    )
    args = ap.parse_args(argv)

    repo_root = args.repo_root.resolve()
    if not (repo_root / "recipes").is_dir():
        print(
            f"error: {repo_root} has no recipes/ directory",
            file=sys.stderr,
        )
        return 2

    result = seed(
        repo_root,
        args.ghcr_repo,
        dry_run=args.dry_run,
        only=set(args.recipe) if args.recipe else None,
    )
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
