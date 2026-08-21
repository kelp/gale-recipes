#!/usr/bin/env python3
"""Download official Darwin assets and run gale admit.

Must run on macOS: Native.CodeSign execs codesign --verify.
Writes header + admit stdout under --out.

Skips a package only when its index document is a
regular file on INDEX_BASE (default origin/main).
Continue on admit failure: write {name}.failed.txt
and keep going. Exit 1 only when something was
attempted and no fragment was written.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import urllib.request
from collections.abc import Callable, Sequence
from pathlib import Path

import admit_manifest as am

DownloadFn = Callable[[am.Package, Path], None]
RunAdmitFn = Callable[[list[str]], subprocess.CompletedProcess[str]]


class UnresolvableBase(RuntimeError):
    """INDEX_BASE is not a git revision in repo_root."""


def index_relpath(name: str) -> str:
    return f"index/{name[0]}/{name}.toml"


def indexed_on_base(repo_root: Path, name: str, base_ref: str) -> bool:
    probe = subprocess.run(
        ["git", "rev-parse", "--verify", base_ref],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode != 0:
        raise UnresolvableBase(f"{base_ref}: {probe.stderr.strip()}")
    listed = subprocess.run(
        ["git", "ls-tree", base_ref, index_relpath(name)],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0 or not listed.stdout.strip():
        return False
    mode, typ, _rest = listed.stdout.split(None, 2)
    return typ == "blob" and mode in ("100644", "100755")


def _default_download(pkg: am.Package, dest: Path) -> None:
    urllib.request.urlretrieve(pkg.url, dest)


def _default_run_admit(argv: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=False, capture_output=True, text=True)


def admit_packages(
    packages: Sequence[am.Package],
    *,
    gale: str,
    out: Path,
    work: Path,
    repo_root: Path,
    base_ref: str,
    download: DownloadFn = _default_download,
    run_admit: RunAdmitFn = _default_run_admit,
) -> int:
    out.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    attempted = 0
    fragments = 0
    for pkg in packages:
        if indexed_on_base(repo_root, pkg.name, base_ref):
            print(f"skip {pkg.name}: indexed on {base_ref}", file=sys.stderr)
            continue
        attempted += 1
        dest = work / Path(pkg.url).name
        print(f"download {pkg.name} {pkg.version}", file=sys.stderr)
        try:
            download(pkg, dest)
        except Exception as exc:
            (out / f"{pkg.name}.failed.txt").write_text(f"{exc}\n")
            print(f"{pkg.name}: download failed: {exc}", file=sys.stderr)
            continue
        if pkg.hash_source == "upstream-sha256sums":
            got = hashlib.sha256(dest.read_bytes()).hexdigest()
            if got != pkg.sha256:
                msg = f"{pkg.name}: sha256 {got} != {pkg.sha256}\n"
                (out / f"{pkg.name}.failed.txt").write_text(msg)
                sys.stderr.write(msg)
                continue
        argv = am.admit_argv(pkg, str(dest))
        argv[0] = gale
        print(" ".join(argv), file=sys.stderr)
        proc = run_admit(argv)
        if proc.returncode != 0:
            err = proc.stderr or proc.stdout or f"exit {proc.returncode}\n"
            (out / f"{pkg.name}.failed.txt").write_text(err)
            sys.stderr.write(proc.stderr)
            continue
        (out / f"{pkg.name}.fragment.toml").write_text(
            am.header(pkg) + "\n" + proc.stdout,
        )
        fragments += 1
    if attempted == 0:
        return 0
    if fragments == 0:
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--work", default="")
    p.add_argument("--repo", default=".")
    args = p.parse_args()
    gale = os.environ.get("GALE", "gale")
    base_ref = os.environ.get("INDEX_BASE", "origin/main")
    out = Path(args.out)
    work = Path(args.work) if args.work else out / "work"
    return admit_packages(
        am.PACKAGES,
        gale=gale,
        out=out,
        work=work,
        repo_root=Path(args.repo),
        base_ref=base_ref,
    )


if __name__ == "__main__":
    raise SystemExit(main())
