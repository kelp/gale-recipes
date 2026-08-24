#!/usr/bin/env python3
"""Download official linux/amd64 assets and run gale admit.

Darwin host is enough: ELF linkage is read from headers,
not ldd. codesign is skipped for ELF.
Writes admit stdout (no package header) under --out.
tree_digest comes from admit stdout only.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import admit_darwin as ad
import admit_manifest as am


def apply_fragment(index_path: Path, fragment: str) -> None:
    text = index_path.read_text()
    if not text.endswith("\n"):
        text += "\n"
    index_path.write_text(text + "\n" + fragment.strip() + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--work", default="")
    p.add_argument("--repo", default=".")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()
    gale = os.environ.get("GALE", "gale")
    repo = Path(args.repo)
    out = Path(args.out)
    work = Path(args.work) if args.work else out / "work"
    rc = ad.admit_packages(
        am.LINUX_PACKAGES,
        gale=gale,
        out=out,
        work=work,
        repo_root=repo,
        base_ref="HEAD",
        skip_indexed=False,
        write_header=False,
    )
    if rc != 0:
        return rc
    if args.apply:
        for pkg in am.LINUX_PACKAGES:
            frag = out / f"{pkg.name}.fragment.toml"
            if not frag.is_file():
                print(f"skip apply {pkg.name}: no fragment", file=sys.stderr)
                continue
            dest = repo / "index" / pkg.name[0] / f"{pkg.name}.toml"
            apply_fragment(dest, frag.read_text())
            print(f"applied {dest.relative_to(repo)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
