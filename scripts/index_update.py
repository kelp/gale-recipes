#!/usr/bin/env python3
"""Discover lagged upstream versions and admit them into index/.

PR-only. Never push main. tree_digest comes from gale admit.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from collections.abc import Callable, Sequence

COOLDOWN = timedelta(days=3)
PLATFORM = "darwin/arm64"

DownloadFn = Callable[["Candidate", Path], None]
RunAdmitFn = Callable[[list[str]], subprocess.CompletedProcess[str]]
GitHubFn = Callable[[str], dict]


@dataclass(frozen=True)
class IndexPackage:
    name: str
    latest: str
    repo: str
    url: str
    format: str
    strip: int
    hash_source: str
    sha256: str
    files: tuple[tuple[str, str, int], ...]
    path: Path
    description: str
    license: str
    homepage: str
    versions: frozenset[str]


@dataclass(frozen=True)
class Release:
    version: str
    tag: str
    published_at: datetime


@dataclass(frozen=True)
class Candidate:
    pkg: IndexPackage
    version: str
    url: str
    published_at: datetime
    hash_source: str
    sha256: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class AdmitResult:
    ok: list[str]
    failed: list[str]


def tag_to_version(tag: str, name: str) -> str:
    t = tag.strip()
    if t.startswith("v") and len(t) > 1 and t[1].isdigit():
        t = t[1:]
    prefix = name + "-"
    if t.startswith(prefix):
        t = t[len(prefix):]
    if name == "go" and t.startswith("go") and len(t) > 2 and t[2].isdigit():
        t = t[2:]
    return t


def subst_version(text: str, old: str, new: str) -> str:
    old_re = re.escape(old)
    text = re.sub(rf"(?<![0-9])v{old_re}(?![0-9])", "v" + new, text)
    text = re.sub(rf"(?<![0-9]){old_re}(?![0-9])", new, text)
    return text


def cooldown_elapsed(
    published_at: datetime, now: datetime, lag: timedelta = COOLDOWN
) -> bool:
    return now - published_at >= lag


def skip_reason(
    pkg: IndexPackage,
    rel: Release,
    now: datetime,
    existing_versions: set[str] | frozenset[str],
) -> str | None:
    if rel.version == pkg.latest:
        return "already latest"
    if rel.version in existing_versions:
        return "version exists"
    if not cooldown_elapsed(rel.published_at, now):
        return "cooldown"
    return None


def load_package_text(text: str, path: Path) -> IndexPackage:
    data = tomllib.loads(text)
    pkg = data["package"]
    latest = pkg["latest"]
    versions = data["versions"]
    art = versions[latest]["artifacts"][PLATFORM]
    files = tuple(
        (str(f["src"]), str(f["dest"]), int(f["mode"]))
        for f in art.get("files", [])
    )
    return IndexPackage(
        name=pkg["name"],
        latest=latest,
        repo=pkg.get("repo", ""),
        url=art["url"],
        format=art["format"],
        strip=int(art.get("strip", 0)),
        hash_source=art["hash_source"],
        sha256=art["sha256"],
        files=files,
        path=path,
        description=pkg.get("description", ""),
        license=pkg.get("license", ""),
        homepage=pkg.get("homepage", ""),
        versions=frozenset(versions),
    )


def load_index(root: Path) -> list[IndexPackage]:
    import index_layout

    pkgs = []
    for path in index_layout.list_index_files(root):
        pkgs.append(load_package_text(path.read_text(), path.relative_to(root)))
    return pkgs


def file_flag(src: str, dest: str, mode: int) -> str:
    perm = "755" if mode == 0o755 else "644"
    return f"{src}:{dest}:{perm}"


def build_candidate(pkg: IndexPackage, rel: Release) -> Candidate:
    url = subst_version(pkg.url, pkg.latest, rel.version)
    files = tuple(
        subst_version(file_flag(*fe), pkg.latest, rel.version)
        for fe in pkg.files
    )
    return Candidate(
        pkg=pkg,
        version=rel.version,
        url=url,
        published_at=rel.published_at,
        hash_source=pkg.hash_source,
        sha256="",
        files=files,
    )


def apply_fragment(existing: str, new_latest: str, fragment: str) -> str:
    lines = []
    replaced = False
    for ln in existing.splitlines():
        if not replaced and ln.startswith("latest = "):
            lines.append(f'latest = "{new_latest}"')
            replaced = True
        else:
            lines.append(ln)
    text = "\n".join(lines) + "\n"
    return text + "\n" + fragment.strip() + "\n"


def branch_name(name: str, version: str) -> str:
    return f"index-update/{name}-{version}"


def push_ref(ref: str) -> str:
    if not ref.startswith("index-update/"):
        raise ValueError(f"refusing to push {ref}")
    return ref


def _parse_github_time(stamp: str) -> datetime:
    stamp = stamp.replace("Z", "+00:00")
    return datetime.fromisoformat(stamp).astimezone(timezone.utc)


def discover_packages(
    pkgs: Sequence[IndexPackage],
    now: datetime,
    *,
    github: GitHubFn,
) -> tuple[list[Candidate], list[tuple[str, str]]]:
    cands: list[Candidate] = []
    skips: list[tuple[str, str]] = []
    for pkg in pkgs:
        if not pkg.repo:
            skips.append((pkg.name, "no repo"))
            continue
        try:
            payload = github(pkg.repo)
        except Exception as exc:
            skips.append((pkg.name, f"github: {exc}"))
            continue
        if payload.get("draft"):
            skips.append((pkg.name, "draft"))
            continue
        if payload.get("prerelease"):
            skips.append((pkg.name, "prerelease"))
            continue
        rel = Release(
            version=tag_to_version(payload["tag_name"], pkg.name),
            tag=payload["tag_name"],
            published_at=_parse_github_time(payload["published_at"]),
        )
        reason = skip_reason(pkg, rel, now, pkg.versions)
        if reason:
            skips.append((pkg.name, reason))
            continue
        cands.append(build_candidate(pkg, rel))
    return cands, skips


def go_release(listings: list, published_at: datetime) -> Release:
    for row in listings:
        if not row.get("stable"):
            continue
        tag = str(row["version"])
        return Release(
            version=tag_to_version(tag, "go"),
            tag=tag,
            published_at=published_at,
        )
    raise ValueError("no stable go release")


def candidate_to_json(cand: Candidate) -> dict:
    return {
        "name": cand.pkg.name,
        "version": cand.version,
        "url": cand.url,
        "format": cand.pkg.format,
        "strip": cand.pkg.strip,
        "hash_source": cand.hash_source,
        "sha256": cand.sha256,
        "files": list(cand.files),
        "path": str(cand.pkg.path),
        "description": cand.pkg.description,
        "license": cand.pkg.license,
        "homepage": cand.pkg.homepage,
        "repo": cand.pkg.repo,
        "published_at": cand.published_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latest": cand.pkg.latest,
        "versions": sorted(cand.pkg.versions),
        "src_files": [
            {"src": s, "dest": d, "mode": m} for s, d, m in cand.pkg.files
        ],
        "src_url": cand.pkg.url,
        "src_hash_source": cand.pkg.hash_source,
        "src_sha256": cand.pkg.sha256,
    }


def candidate_from_json(data: dict, pkg: IndexPackage | None = None) -> Candidate:
    if pkg is None:
        files = tuple(
            (f["src"], f["dest"], int(f["mode"])) for f in data["src_files"]
        )
        pkg = IndexPackage(
            name=data["name"],
            latest=data["latest"],
            repo=data["repo"],
            url=data["src_url"],
            format=data["format"],
            strip=int(data["strip"]),
            hash_source=data["src_hash_source"],
            sha256=data["src_sha256"],
            files=files,
            path=Path(data["path"]),
            description=data["description"],
            license=data["license"],
            homepage=data["homepage"],
            versions=frozenset(data["versions"]),
        )
    return Candidate(
        pkg=pkg,
        version=data["version"],
        url=data["url"],
        published_at=_parse_github_time(data.get("published_at", "1970-01-01T00:00:00Z")),
        hash_source=data["hash_source"],
        sha256=data.get("sha256", ""),
        files=tuple(data["files"]),
    )


def _default_download(cand: Candidate, dest: Path) -> None:
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(cand.url, dest)


def _default_run_admit(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=False, capture_output=True, text=True)


def admit_argv(cand: Candidate, archive: str, gale: str) -> list[str]:
    hash_source = cand.hash_source
    sha256 = cand.sha256
    if hash_source == "upstream-sha256sums" and not sha256:
        hash_source = "computed"
    argv = [
        gale, "admit",
        "--archive", archive,
        "--name", cand.pkg.name,
        "--version", cand.version,
        "--os", "darwin",
        "--arch", "arm64",
        "--url", cand.url,
        "--format", cand.pkg.format,
        "--strip", str(cand.pkg.strip),
        "--hash-source", hash_source,
    ]
    if hash_source == "upstream-sha256sums":
        argv.extend(["--sha256", sha256])
    for fe in cand.files:
        argv.extend(["--file", fe])
    return argv


def admit_candidates(
    cands: Sequence[Candidate],
    *,
    gale: str,
    out: Path,
    work: Path,
    download: DownloadFn = _default_download,
    run_admit: RunAdmitFn = _default_run_admit,
) -> AdmitResult:
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    ok: list[str] = []
    failed: list[str] = []
    for cand in cands:
        dest = work / Path(cand.url).name
        print(f"download {cand.pkg.name} {cand.version}", file=sys.stderr)
        try:
            download(cand, dest)
        except Exception as exc:
            (out / f"{cand.pkg.name}.failed.txt").write_text(f"{exc}\n")
            print(f"{cand.pkg.name}: download failed: {exc}", file=sys.stderr)
            failed.append(cand.pkg.name)
            continue
        argv = admit_argv(cand, str(dest), gale)
        print(" ".join(argv), file=sys.stderr)
        proc = run_admit(argv)
        if proc.returncode != 0:
            err = proc.stderr or proc.stdout or f"exit {proc.returncode}\n"
            (out / f"{cand.pkg.name}.failed.txt").write_text(err)
            sys.stderr.write(proc.stderr or "")
            failed.append(cand.pkg.name)
            continue
        (out / f"{cand.pkg.name}.fragment.toml").write_text(proc.stdout)
        ok.append(cand.pkg.name)
    return AdmitResult(ok=ok, failed=failed)


def _github_latest(repo: str) -> dict:
    import json
    import urllib.request

    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def cmd_discover(args: argparse.Namespace) -> int:
    root = Path(args.root)
    now = datetime.now(timezone.utc)
    pkgs = load_index(root)
    cands, skips = discover_packages(pkgs, now, github=_github_latest)
    for name, reason in skips:
        print(f"skip {name}: {reason}", file=sys.stderr)
    out = Path(args.out)
    out.write_text(
        __import__("json").dumps(
            [candidate_to_json(c) for c in cands], indent=2
        )
        + "\n"
    )
    print(f"{len(cands)} candidates", file=sys.stderr)
    return 0


def apply_candidate(root: Path, cand: Candidate, fragment: str) -> Path:
    dest = root / cand.pkg.path
    dest.write_text(apply_fragment(dest.read_text(), cand.version, fragment))
    return dest


def cmd_apply(args: argparse.Namespace) -> int:
    import json

    root = Path(args.root)
    pkgs = {p.name: p for p in load_index(root)}
    raw = json.loads(Path(args.candidates).read_text())
    names = {args.name} if args.name else None
    applied = 0
    for row in raw:
        if names is not None and row["name"] not in names:
            continue
        pkg = pkgs.get(row["name"])
        cand = candidate_from_json(row, pkg)
        frag = Path(args.fragment) if args.fragment else (
            Path(args.fragments) / f"{cand.pkg.name}.fragment.toml"
        )
        if not frag.is_file():
            print(f"skip {cand.pkg.name}: no fragment", file=sys.stderr)
            continue
        path = apply_candidate(root, cand, frag.read_text())
        print(f"{cand.pkg.name} {cand.version} {path.relative_to(root)}")
        applied += 1
    return 0 if applied else 1


def cmd_admit(args: argparse.Namespace) -> int:
    import json

    root = Path(args.root)
    raw = json.loads(Path(args.candidates).read_text())
    pkgs = {p.name: p for p in load_index(root)}
    cands = []
    for row in raw:
        pkg = pkgs.get(row["name"])
        cands.append(candidate_from_json(row, pkg))
    gale = os.environ.get("GALE", "gale")
    result = admit_candidates(
        cands,
        gale=gale,
        out=Path(args.out),
        work=Path(args.work) if args.work else Path(args.out) / "work",
    )
    if result.failed and not result.ok:
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("discover")
    d.add_argument("--root", default=".")
    d.add_argument("--out", required=True)
    d.set_defaults(func=cmd_discover)

    a = sub.add_parser("admit")
    a.add_argument("--root", default=".")
    a.add_argument("--candidates", required=True)
    a.add_argument("--out", required=True)
    a.add_argument("--work", default="")
    a.set_defaults(func=cmd_admit)

    ap = sub.add_parser("apply")
    ap.add_argument("--root", default=".")
    ap.add_argument("--candidates", required=True)
    ap.add_argument("--fragments", default="")
    ap.add_argument("--fragment", default="")
    ap.add_argument("--name", default="")
    ap.set_defaults(func=cmd_apply)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
