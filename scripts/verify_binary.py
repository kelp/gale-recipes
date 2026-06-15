#!/usr/bin/env python3
"""Farm-aware binary-run check for CI.

Probes a recipe's INSTALLED binary (the one gale wrote to the
store, with the dependency farm populated and rpaths baked to
its real install location) rather than a relocated tar extract.

Why installed, not extracted: gale bakes the dependency-farm
rpath as @loader_path-relative to the binary's real store path
($HOME/.gale/pkg/<name>/<version>-<revision>/bin). A binary that
dynamically links a declared runtime-dep dylib (eza->libgit2,
flac->libogg, git-delta, bat) resolves that dep only from the
install location. Running a tar extract in a temp dir points the
rpath at a nonexistent path and dyld aborts ("Library not
loaded: @rpath/libX.dylib"), even though the binary is correct.
This probes the binary the way a user actually runs it.

This does NOT replace check_install.py's static rpath check. A
binary that fails to resolve its OWN sibling dylib (e.g. flac's
@rpath/libFLAC.14.dylib) is still caught there and must still
fail; this script's farm-populated run would mask such a bug, so
the two run as separate, complementary gates.

Probe semantics match the prior inline shell exactly:
  - try --version version --help -V -v, success on first that
    exits 0 (PROBE_OK).
  - a probe killed by a signal (exit >= 128) when no probe
    succeeded is a hard failure (dyld could not load a lib).
  - a binary that runs but has no version/help flag, or a
    script with no version flag, passes if it is a real
    executable / script (pass-if-executable tolerance).
  - a library recipe (no runnable binary, but files under lib/
    or include/) passes.

Exit codes: 0 pass, 1 fail.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("verify_binary.py requires Python 3.11+ (tomllib)")

import tomllib


def resolve_prefix(name: str, version: str, revision: int) -> Path:
    """Default gale store path: matches run_smoke.resolve_prefix.

    $HOME/.gale/pkg/<name>/<version>-<revision>/, including the
    -1 suffix when revision is 1.
    """
    return (Path.home() / ".gale" / "pkg" / name
            / f"{version}-{revision}")


def find_binary(prefix: Path, name: str) -> Path | None:
    """Locate the runnable binary under the installed prefix.

    Prefer bin/<name> or sbin/<name> (the recipe's own tool),
    then fall back to the first executable file in bin/ or
    sbin/. Mirrors the prior shell search order.
    """
    for sub in ("bin", "sbin"):
        cand = prefix / sub / name
        if cand.is_file() and os.access(cand, os.X_OK):
            return cand
    for sub in ("bin", "sbin"):
        d = prefix / sub
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if f.is_file() and os.access(f, os.X_OK):
                return f
    return None


def library_payload(prefix: Path) -> int:
    """Count installed files under lib/ and include/."""
    total = 0
    for sub in ("lib", "include"):
        d = prefix / sub
        if d.is_dir():
            total += sum(1 for p in d.rglob("*") if p.is_file())
    return total


def file_type(binary: Path) -> str:
    """Run `file` on the binary; return its description (lower)."""
    try:
        out = subprocess.run(
            ["file", str(binary)],
            capture_output=True, text=True, check=False,
        ).stdout
    except FileNotFoundError:
        return ""
    return out.lower()


def probe(binary: Path) -> tuple[bool, bool]:
    """Run the version/help probe loop.

    Returns (probe_ok, killed_by_signal). The installed binary
    is invoked from its store path so the farm rpath resolves.
    """
    probe_ok = False
    killed = False
    for arg in ("--version", "version", "--help", "-V", "-v"):
        rc = subprocess.run(
            [str(binary), arg], check=False,
        ).returncode
        if rc == 0:
            probe_ok = True
            break
        # subprocess returns a NEGATIVE returncode when the
        # child dies on a signal (e.g. -11 for SIGSEGV) — this
        # is the dyld-abort case the whole check exists for.
        # The shell idiom is 128+signum, so accept either form.
        if rc < 0 or rc >= 128:
            killed = True
    return probe_ok, killed


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recipe", required=True, type=Path)
    ap.add_argument("--prefix", type=Path,
                    help="installed prefix (defaults to "
                         "~/.gale/pkg/<name>/<version>-<rev>)")
    args = ap.parse_args()

    with args.recipe.open("rb") as f:
        recipe = tomllib.load(f)

    name = recipe["package"]["name"]
    version = recipe["package"]["version"]
    revision = int(recipe["package"].get("revision", 1) or 1)

    prefix = (args.prefix if args.prefix
              else resolve_prefix(name, version, revision))
    if not prefix.is_dir():
        print(f"verify_binary: prefix {prefix} does not exist; "
              f"install the package first", file=sys.stderr)
        return 1

    binary = find_binary(prefix, name)

    if binary is None:
        files = library_payload(prefix)
        if files > 0:
            print(f"Library recipe: {files} files in lib/ "
                  f"and/or include/")
            print("Verified: library install produced output")
            return 0
        print(f"::error::No executables or library files under "
              f"{prefix}", file=sys.stderr)
        return 1

    print(f"Testing installed binary: {binary}", flush=True)
    probe_ok, killed = probe(binary)

    if not probe_ok and killed:
        print(f"::error::{binary.name} was killed by a signal "
              f"(likely dyld could not load a required "
              f"library).", file=sys.stderr)
        subprocess.run([str(binary), "--version"], check=False)
        return 1

    if not probe_ok:
        ftype = file_type(binary)
        if "text" in ftype or "script" in ftype:
            print("Script binary with no version flag")
            print(f"Verified: {binary.name} exists and is "
                  f"executable")
            return 0
        if any(k in ftype for k in
               ("executable", "mach-o", "elf")):
            print("Binary ran but has no version/help flag")
            print(f"Verified: {binary.name} is a valid "
                  f"executable")
            return 0
        print(f"::error::{binary.name} failed to run",
              file=sys.stderr)
        return 1

    print(f"Verified: {binary.name} runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
