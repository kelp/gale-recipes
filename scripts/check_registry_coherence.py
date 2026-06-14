#!/usr/bin/env python3
"""Daily registry-coherence audit: ledger vs GHCR.

The in-tree Ledger Check (scripts/check_ledger.py) proves a
PR's ledger is self-consistent, but it structurally cannot
see the registry. This watchdog covers the one remaining
blind spot: EXTERNAL mutation of GHCR content that the ledger
already anchors. For every ``[[history]]`` entry in every
``recipes/**/*.binaries.toml``, for every platform recorded
in it, it fetches the immutable revisioned tag
``<version>-<revision>-<platform>`` and fails when:

- the tag 404s — "anchor lost": it was published once and
  must never disappear (external deletion or GC);
- the served manifest digest (Docker-Content-Digest, cross-
  checked against the sha256 of the served body) differs
  from the ledgered ``manifest_digest``, or the manifest's
  ``layers[0].digest`` differs from the ledgered ``sha256`` —
  "immutable tag conflict": registry content changed
  externally; bump revision to republish.

A 5xx (or transport error) is retried and then counted as an
audit error — never treated as absent. Recipes with no
history yet are skipped and counted in the summary, so the
audit stays quiet during the bridge and becomes comprehensive
after backfill + republish.

Anonymous-token + Accept-OCI flow (same as build-chunk.yml's
adopt-or-push probe): GHCR's token endpoint hands out pull
tokens for public packages without credentials.

Usage:

    python3 scripts/check_registry_coherence.py --repo-root .

Exits 0 when coherent, 1 on any failure, 2 on usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(
        "check_registry_coherence.py requires Python 3.11+ (tomllib)"
    )

import tomllib

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MANIFEST_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ACCEPT_OCI = "application/vnd.oci.image.manifest.v1+json"

# Manifest fetch attempts before a 5xx/transport error counts
# as an audit error. Tests assert this exact count.
ATTEMPTS = 3

# Injection point so tests don't sleep for real.
_sleep = time.sleep


def default_http_get(
    url: str, headers: dict[str, str]
) -> tuple[int, dict[str, str], bytes]:
    """(status, headers, body). HTTP errors are returned as
    statuses, not raised, so the caller owns classification."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read()


def header(headers: dict[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value.strip()
    return None


def fetch_token(name: str, ghcr_repo: str, http_get) -> str | None:
    url = (
        "https://ghcr.io/token?service=ghcr.io"
        f"&scope=repository:{ghcr_repo}/{name}:pull"
    )
    status, _, body = http_get(url, {})
    if status != 200:
        return None
    try:
        token = json.loads(body).get("token")
    except json.JSONDecodeError:
        return None
    return token if isinstance(token, str) and token else None


def fetch_manifest(
    name: str, tag: str, ghcr_repo: str, http_get
) -> tuple[int, dict[str, str], bytes] | None:
    """Manifest response after retries, or None when every
    attempt errored at the transport/5xx level."""
    token = fetch_token(name, ghcr_repo, http_get)
    if token is None:
        return None
    url = f"https://ghcr.io/v2/{ghcr_repo}/{name}/manifests/{tag}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": ACCEPT_OCI,
    }
    for attempt in range(1, ATTEMPTS + 1):
        try:
            status, resp_headers, body = http_get(url, headers)
        except OSError:
            status = None
        if status is not None and status < 500:
            return status, resp_headers, body
        if attempt < ATTEMPTS:
            _sleep(attempt * 10)
    return None


def audit_entry_platform(
    name: str,
    entry_version: str,
    platform: str,
    record: dict,
    ghcr_repo: str,
    http_get,
) -> str | None:
    """One (history entry, platform) check. Returns a failure
    string or None."""
    tag = f"{entry_version}-{platform}"
    ref = f"{name}:{tag}"

    sha = record.get("sha256")
    ledgered_md = record.get("manifest_digest")
    if not isinstance(sha, str) or not SHA256_RE.match(sha):
        return (
            f"{ref}: ledgered sha256 {sha!r} is malformed; "
            f"fix the ledger entry before auditing"
        )
    if not isinstance(ledgered_md, str) or not MANIFEST_DIGEST_RE.match(
        ledgered_md
    ):
        return (
            f"{ref}: ledgered manifest_digest {ledgered_md!r} is "
            f"malformed; fix the ledger entry before auditing"
        )

    resp = fetch_manifest(name, tag, ghcr_repo, http_get)
    if resp is None:
        # SAFETY-CRITICAL: a transient registry error must
        # never be classified as an absent tag.
        return (
            f"{ref}: audit error — GHCR unreachable or 5xx after "
            f"{ATTEMPTS} attempts; re-run the audit (never "
            f"treated as absent)"
        )
    status, headers, body = resp

    if status == 404:
        return (
            f"anchor lost: {ref} was published but no longer "
            f"exists (external deletion/GC)"
        )
    if status != 200:
        return (
            f"{ref}: audit error — unexpected HTTP {status} from "
            f"GHCR manifest endpoint"
        )

    served_md = header(headers, "Docker-Content-Digest")
    body_md = "sha256:" + hashlib.sha256(body).hexdigest()
    if served_md and served_md != body_md:
        return (
            f"{ref}: audit error — Docker-Content-Digest "
            f"{served_md} disagrees with the sha256 of the served "
            f"manifest {body_md}"
        )
    served_md = served_md or body_md

    try:
        layers = json.loads(body).get("layers") or []
        layer_digest = layers[0].get("digest", "")
    except (json.JSONDecodeError, AttributeError, IndexError):
        layer_digest = ""

    if served_md != ledgered_md or layer_digest != f"sha256:{sha}":
        return (
            f"immutable tag conflict: registry content for {ref} "
            f"changed externally (manifest {served_md} vs ledgered "
            f"{ledgered_md}; layer {layer_digest or '<missing>'} vs "
            f"ledgered sha256:{sha}); bump revision to republish"
        )
    return None


def audit(
    repo_root: Path,
    ghcr_repo: str,
    http_get=default_http_get,
) -> tuple[list[str], int, int]:
    """(failures, audited entry-platform count, recipes with no
    history skipped)."""
    failures: list[str] = []
    audited = 0
    skipped = 0
    for path in sorted(repo_root.glob("recipes/**/*.binaries.toml")):
        name = path.name[: -len(".binaries.toml")]
        try:
            doc = tomllib.loads(path.read_text())
        except (tomllib.TOMLDecodeError, OSError) as exc:
            failures.append(f"{path}: unreadable: {exc}")
            continue
        history = doc.get("history")
        if not isinstance(history, list) or not history:
            skipped += 1
            continue
        for entry in history:
            if not isinstance(entry, dict):
                failures.append(
                    f"{name}: malformed [[history]] entry {entry!r}"
                )
                continue
            entry_version = entry.get("version")
            if not isinstance(entry_version, str) or not entry_version:
                failures.append(
                    f"{name}: [[history]] entry without a version key"
                )
                continue
            for platform, record in entry.items():
                if platform == "version":
                    continue
                if not isinstance(record, dict):
                    failures.append(
                        f"{name}:{entry_version}-{platform}: "
                        f"platform record is not a table"
                    )
                    continue
                audited += 1
                failure = audit_entry_platform(
                    name,
                    entry_version,
                    platform,
                    record,
                    ghcr_repo,
                    http_get,
                )
                if failure:
                    failures.append(failure)
    return failures, audited, skipped


def write_step_summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="repository root containing recipes/ (default: .)",
    )
    ap.add_argument(
        "--ghcr-repo",
        default=os.environ.get("GITHUB_REPOSITORY", "kelp/gale-recipes"),
        help="GHCR namespace (default: $GITHUB_REPOSITORY or "
        "kelp/gale-recipes)",
    )
    args = ap.parse_args(argv)

    repo_root = args.repo_root.resolve()
    if not (repo_root / "recipes").is_dir():
        print(
            f"error: {repo_root} has no recipes/ directory",
            file=sys.stderr,
        )
        return 2

    failures, audited, skipped = audit(repo_root, args.ghcr_repo)

    lines = ["# Registry coherence audit", ""]
    if audited == 0 and not failures:
        lines.append(
            f"No ledger entries to audit yet ({skipped} recipe(s) "
            f"without history — expected during the bridge)."
        )
    else:
        lines.append(
            f"Audited {audited} (entry, platform) pair(s); "
            f"{skipped} recipe(s) without history skipped."
        )
    if failures:
        lines.append("")
        lines.append(f"{len(failures)} failure(s):")
        lines.extend(f"- {f}" for f in failures)
    summary = "\n".join(lines) + "\n"
    write_step_summary(summary)
    print(summary, end="")

    if failures:
        for failure in failures:
            print(f"::error::{failure}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
