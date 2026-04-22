#!/usr/bin/env python3
"""Run a recipe's [smoke] commands against an installed
package to catch runtime regressions the static rpath
check can't see (e.g. a feature that links fine but
segfaults, a --version flag that was renamed, a broken
git-remote helper).

Recipe format:

    [smoke]
    commands = [
      "${PREFIX}/bin/git --version",
      "${PREFIX}/bin/git clone --depth 1 ...",
    ]

Substitutions available inside each command:
  ${PREFIX}  ${VERSION}  ${NAME}
  ${TMPDIR}  ${OS}  ${ARCH}  ${PLATFORM}

A recipe with no [smoke] section is a no-op (exit 0).

Exits nonzero if any command fails.
"""

from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from string import Template

if sys.version_info < (3, 11):
    sys.exit("run_smoke.py requires Python 3.11+ (tomllib)")

import tomllib


def platform_triple() -> tuple[str, str, str]:
    """Return (os, arch, platform) matching gale's convention."""
    sysname = platform.system()
    os_name = "darwin" if sysname == "Darwin" else "linux"
    mach = platform.machine().lower()
    arch = "arm64" if mach in {"arm64", "aarch64"} else "amd64"
    return os_name, arch, f"{os_name}-{arch}"


def resolve_prefix(name: str, version: str, revision: int) -> Path:
    """Default install path under the gale store.

    Gale's canonical store dir is
    $HOME/.gale/pkg/<name>/<version>-<revision>/, including
    the -1 suffix when revision is 1. Recipes without an
    explicit [package] revision default to 1.

    Override $HOME to target a different store (e.g. a fresh
    temp dir for clean-install smoke testing).
    """
    return (Path.home() / ".gale" / "pkg" / name
            / f"{version}-{revision}")


def substitute(cmd: str, env: dict[str, str]) -> str:
    """Expand ${VAR} references; leave shell constructs alone."""
    # Use safe_substitute so $$, $PATH etc. pass through
    # untouched to the shell.
    return Template(cmd).safe_substitute(env)


def run_command(cmd: str, env: dict[str, str]) -> int:
    """Run one smoke command in a subshell. Inherit stdio."""
    expanded = substitute(cmd, env)
    print(f"  $ {expanded}", flush=True)
    proc = subprocess.run(
        ["bash", "-c", expanded], check=False)
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--recipe", required=True, type=Path)
    ap.add_argument("--prefix", type=Path,
                    help="installed prefix (defaults to "
                         "~/.gale/pkg/<name>/<version>)")
    ap.add_argument("--required", action="store_true",
                    help="fail if no [smoke] section")
    args = ap.parse_args()

    with args.recipe.open("rb") as f:
        recipe = tomllib.load(f)

    name = recipe["package"]["name"]
    version = recipe["package"]["version"]
    revision = int(recipe["package"].get("revision", 1))
    smoke = recipe.get("smoke", {})
    commands = smoke.get("commands", [])

    if not commands:
        if args.required:
            print(f"run_smoke: {name} has no [smoke].commands",
                  file=sys.stderr)
            return 1
        print(f"run_smoke: {name} has no [smoke] section "
              f"(skipping)")
        return 0

    prefix = (args.prefix if args.prefix
              else resolve_prefix(name, version, revision))
    if not prefix.is_dir():
        print(f"run_smoke: prefix {prefix} does not exist; "
              f"install the package first", file=sys.stderr)
        return 1

    os_name, arch, plat = platform_triple()
    with tempfile.TemporaryDirectory(
            prefix=f"smoke-{name}-") as tmpdir:
        env = {
            "PREFIX": str(prefix),
            "VERSION": version,
            "NAME": name,
            "TMPDIR": tmpdir,
            "OS": os_name,
            "ARCH": arch,
            "PLATFORM": plat,
        }

        print(f"run_smoke: {name} {version} "
              f"({len(commands)} command(s))", flush=True)
        failures = 0
        for i, cmd in enumerate(commands, 1):
            rc = run_command(cmd, env)
            if rc != 0:
                print(f"  -> FAIL (exit {rc})")
                failures += 1

    if failures:
        print(f"run_smoke: {name}: {failures}/{len(commands)} "
              f"failed", file=sys.stderr)
        return 1

    print(f"run_smoke: {name}: all {len(commands)} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
