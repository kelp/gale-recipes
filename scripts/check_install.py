#!/usr/bin/env python3
"""Static rpath check: verify a built package's shared-lib
references match the recipe's declared runtime deps.

Walks every Mach-O / ELF file under a prefix. For each file,
extracts its rpath/runpath entries and any absolute dep
references that point into a gale package store
(~/.gale/pkg/<name>/<version>/...). Every such <name> must
appear in the recipe's [dependencies].runtime list.

This catches the class of bug where a lib dep was listed as
build-only — at runtime the prebuilt's rpath points to a
store dir that was never installed on the user's machine.

Exits nonzero on failure.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("check_install.py requires Python 3.11+ (tomllib)")

import tomllib

# Matches any path fragment like ".gale/pkg/<name>/<version>".
# Works for both /Users/runner/.gale/pkg/... (CI) and
# /Users/tcole/.gale/pkg/... (local) and $HOME/.gale/pkg/...
STORE_RE = re.compile(r"\.gale/pkg/([^/]+)/([^/]+)")

MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",
    b"\xfe\xed\xfa\xcf",
    b"\xce\xfa\xed\xfe",
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
}
ELF_MAGIC = b"\x7fELF"


def sniff(path: Path) -> str | None:
    """Return 'macho', 'elf', or None."""
    try:
        with path.open("rb") as f:
            head = f.read(4)
    except OSError:
        return None
    if head in MACHO_MAGICS:
        return "macho"
    if head == ELF_MAGIC:
        return "elf"
    return None


def macho_refs(path: Path) -> tuple[list[str], list[str]]:
    """Return (deps, rpaths) for a Mach-O file."""
    try:
        otool_l = subprocess.run(
            ["otool", "-l", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
        otool_L = subprocess.run(
            ["otool", "-L", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [], []

    deps = []
    for line in otool_L.splitlines()[1:]:
        line = line.strip()
        if not line or line.endswith(":"):
            continue
        m = re.match(r"^(\S+)\s+\(", line)
        if m:
            deps.append(m.group(1))

    rpaths = []
    lines = otool_l.splitlines()
    for i, line in enumerate(lines):
        if "cmd LC_RPATH" in line and i + 2 < len(lines):
            p = lines[i + 2].strip()
            m = re.match(r"^path\s+(.+?)\s+\(offset", p)
            if m:
                rpaths.append(m.group(1))
    return deps, rpaths


def elf_refs(path: Path) -> tuple[list[str], list[str]]:
    """Return (needed, runpath) for an ELF file."""
    try:
        out = subprocess.run(
            ["readelf", "-d", str(path)],
            capture_output=True, text=True, check=True,
        ).stdout
    except (FileNotFoundError, subprocess.CalledProcessError):
        return [], []

    needed = []
    runpath: list[str] = []
    for line in out.splitlines():
        m = re.search(r"\(NEEDED\)\s+Shared library: \[(.+)\]", line)
        if m:
            needed.append(m.group(1))
            continue
        m = re.search(r"\((?:RUNPATH|RPATH)\)\s+.*\[(.+)\]", line)
        if m:
            runpath.extend(p for p in m.group(1).split(":") if p)
    return needed, runpath


def store_name(path: str) -> str | None:
    """Extract the gale package name from a path, if any."""
    m = STORE_RE.search(path)
    return m.group(1) if m else None


def resolve_pkg(dep: str, rpaths: list[str]) -> str | None:
    """Figure out which gale package provides a dep.

    Returns the package name (e.g. 'curl') or None if the
    dep isn't backed by a gale store path.

    For @rpath/libfoo.dylib, scan rpaths for a dir that
    contains libfoo.dylib and return the pkg from that
    rpath. For absolute paths into a gale store, extract
    directly.
    """
    if dep.startswith("@rpath/"):
        lib = dep[len("@rpath/"):]
        for rp in rpaths:
            if not Path(rp, lib).exists():
                continue
            return store_name(rp)
        return None
    if dep.startswith(("@loader_path", "@executable_path")):
        return None
    return store_name(dep)


def walk_binaries(root: Path):
    """Yield (path, kind) for every Mach-O / ELF file."""
    for dp, _dn, fn in os.walk(root):
        for name in fn:
            p = Path(dp) / name
            if p.is_symlink():
                continue
            kind = sniff(p)
            if kind:
                yield p, kind


def check_prefix(
    prefix: Path,
    recipe_name: str,
    runtime_deps: set[str],
    *,
    verbose: bool = False,
) -> list[str]:
    """Return a list of failure messages (empty = all good)."""
    failures: list[str] = []
    allowed = runtime_deps | {recipe_name}
    checked = 0

    for path, kind in walk_binaries(prefix):
        checked += 1
        if kind == "macho":
            deps, rpaths = macho_refs(path)
        else:
            deps, rpaths = elf_refs(path)

        used_pkgs: dict[str, str] = {}
        for dep in deps:
            pkg = resolve_pkg(dep, rpaths)
            if pkg and pkg not in allowed:
                used_pkgs.setdefault(pkg, dep)

        if used_pkgs:
            rel = path.relative_to(prefix)
            for pkg, dep in sorted(used_pkgs.items()):
                failures.append(
                    f"{rel}: loads '{dep}' from gale "
                    f"store '{pkg}', but '{pkg}' is not "
                    f"in [dependencies].runtime"
                )
        elif verbose:
            resolved = {
                resolve_pkg(d, rpaths)
                for d in deps if resolve_pkg(d, rpaths)
            }
            if resolved:
                rel = path.relative_to(prefix)
                print(f"  ok {rel} -> {sorted(resolved)}")

    if verbose:
        print(f"scanned {checked} binaries under {prefix}")
    return failures


def extract_archive(archive: Path) -> Path:
    """Extract a tar.zst into a temp dir; return the dir.

    Shells out to `tar --zstd` because Python's tarfile
    doesn't support zstd until 3.14.
    """
    tmp = Path(tempfile.mkdtemp(prefix="gale-check-"))
    subprocess.run(
        ["tar", "--zstd", "-xf", str(archive), "-C", str(tmp)],
        check=True,
    )
    return tmp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recipe", required=True, type=Path,
                    help="path to recipe TOML")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--prefix", type=Path,
                     help="installed prefix to scan")
    src.add_argument("--archive", type=Path,
                     help="built tar.zst to extract and scan")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    with args.recipe.open("rb") as f:
        recipe = tomllib.load(f)

    name = recipe["package"]["name"]
    # Deps can be bare strings or {name, version} tables.
    # Extract just the name for the allowed-deps set.
    runtime_deps = set()
    for entry in recipe.get("dependencies", {}).get("runtime", []):
        if isinstance(entry, str):
            runtime_deps.add(entry)
        elif isinstance(entry, dict) and "name" in entry:
            runtime_deps.add(entry["name"])

    cleanup = None
    if args.archive:
        prefix = extract_archive(args.archive)
        cleanup = prefix
    else:
        prefix = args.prefix

    try:
        failures = check_prefix(
            prefix, name, runtime_deps, verbose=args.verbose)
    finally:
        if cleanup is not None:
            subprocess.run(["rm", "-rf", str(cleanup)], check=False)

    if failures:
        print(f"check_install: {len(failures)} issue(s) in "
              f"{name}:", file=sys.stderr)
        for msg in failures:
            print(f"  {msg}", file=sys.stderr)
        print(
            f"\nhint: add the missing package(s) to "
            f"[dependencies].runtime in {args.recipe}",
            file=sys.stderr)
        return 1

    print(f"check_install: {name} OK "
          f"(runtime deps: {sorted(runtime_deps) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
