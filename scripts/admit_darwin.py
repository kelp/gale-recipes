#!/usr/bin/env python3
"""Download official Darwin assets and run gale admit.

Must run on macOS: Native.CodeSign execs codesign --verify.
Writes header + admit stdout under --out.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

import admit_manifest as am


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--work", default="")
    args = p.parse_args()
    gale = os.environ.get("GALE", "gale")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(args.work) if args.work else out / "work"
    work.mkdir(parents=True, exist_ok=True)
    for pkg in am.PACKAGES:
        dest = work / Path(pkg.url).name
        print(f"download {pkg.name} {pkg.version}", file=sys.stderr)
        urllib.request.urlretrieve(pkg.url, dest)
        if pkg.hash_source == "upstream-sha256sums":
            got = hashlib.sha256(dest.read_bytes()).hexdigest()
            if got != pkg.sha256:
                print(f"{pkg.name}: sha256 {got} != {pkg.sha256}", file=sys.stderr)
                return 1
        argv = am.admit_argv(pkg, str(dest))
        argv[0] = gale
        print(" ".join(argv), file=sys.stderr)
        proc = subprocess.run(argv, check=False, capture_output=True, text=True)
        if proc.returncode != 0:
            sys.stderr.write(proc.stderr)
            return proc.returncode
        (out / f"{pkg.name}.fragment.toml").write_text(
            am.header(pkg) + "\n" + proc.stdout,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
