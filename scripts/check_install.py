#!/usr/bin/env python3
"""Static rpath check: verify a built package's shared-lib
references match the recipe's declared runtime deps.

Walks every Mach-O / ELF file under a prefix. For each file:

1. Extracts rpath/runpath entries and any absolute dep
   references that point into a gale package store
   (~/.gale/pkg/<name>/<version>/...). Every such <name> must
   appear in the recipe's [dependencies].runtime list. Catches
   the class of bug where a lib dep was listed as build-only —
   at runtime the prebuilt's rpath points to a store dir that
   was never installed on the user's machine.

2. (Mach-O only) Resolves every @rpath/<lib> dep against the
   binary's LC_RPATH entries and reports any that no rpath
   dir can satisfy. Catches the class of bug where a recipe
   deletes or fails to produce a dylib the binary still
   references — dyld aborts at runtime with "Library not
   loaded: @rpath/libX.dylib".

3. (ELF only) Resolves every DT_NEEDED soname against the
   binary's RUNPATH ($ORIGIN-expanded, including the
   ~/.gale/lib farm). A soname that is neither on the system
   allowlist (glibc family) nor found via RUNPATH is reported.
   Catches the class of bug where a shipped binary references
   a dep dylib that is missing at runtime — ld.so aborts with
   "error while loading shared libraries: libX.so: cannot open
   shared object file" (gh#160: awscli's bundled python missing
   libpython3.14, gale corrupted by patchelf).

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

# Sonames the host system provides on Linux (glibc family plus
# the GCC/C++ runtimes). ld.so resolves these from its default
# search path, never through the gale farm, so a DT_NEEDED on
# one of them is not a packaging bug. This mirrors the linking
# policy's "keep glibc dynamic" rule (see CLAUDE.md, Linking
# Policy). libgcc_s / libstdc++ are host-resolvable on any glibc
# box, so listing them avoids false positives; the policy's
# prefer-static-C++ preference is a separate quality concern,
# not a runtime-resolution failure.
SYSTEM_SONAMES = {
    "libc.so.6",
    "libm.so.6",
    "libpthread.so.0",
    "libdl.so.2",
    "librt.so.1",
    "libresolv.so.2",
    "libutil.so.1",
    "libcrypt.so.1",
    "libnsl.so.1",
    "libgcc_s.so.1",
    "libstdc++.so.6",
}
# The dynamic loader is arch-suffixed (ld-linux-x86-64.so.2,
# ld-linux-aarch64.so.1, ...); match it by prefix.
SYSTEM_SONAME_PREFIXES = ("ld-linux",)


def is_system_soname(soname: str) -> bool:
    """Report whether an ELF DT_NEEDED soname is host-provided.

    Host-provided sonames resolve via ld.so's default search
    path, not the gale farm, so they never count as unresolved.
    """
    if soname in SYSTEM_SONAMES:
        return True
    return soname.startswith(SYSTEM_SONAME_PREFIXES)


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


def expand_rpath(rp: str, binary: Path) -> str:
    """Expand loader-relative tokens in an rpath entry to an
    absolute path rooted at the binary's dir.

    Handles the Mach-O tokens @executable_path / @loader_path
    and the ELF token $ORIGIN (also spelled ${ORIGIN}), in both
    the bare form ("$ORIGIN") and the path-prefixed form
    ("$ORIGIN/../lib"). For main executables the Mach-O tokens
    mean the same thing. For dylibs, @loader_path / $ORIGIN is
    the loading file's own dir, which matches the binary arg
    here because we resolve each file relative to itself.
    """
    for token in ("@executable_path", "@loader_path",
                  "${ORIGIN}", "$ORIGIN"):
        if rp == token:
            return str(binary.parent)
        if rp.startswith(token + "/"):
            return str(binary.parent / rp[len(token) + 1:])
    return rp


def resolve_pkg(
    dep: str, rpaths: list[str], binary: Path
) -> str | None:
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
            resolved = expand_rpath(rp, binary)
            if not Path(resolved, lib).exists():
                continue
            return store_name(resolved)
        return None
    if dep.startswith(("@loader_path", "@executable_path")):
        return None
    return store_name(dep)


def unresolvable_rpath_refs(
    binary: Path, deps: list[str], rpaths: list[str]
) -> list[str]:
    """Return @rpath/<lib> dep names that no rpath resolves.

    For each @rpath/X dep, check every LC_RPATH entry (with
    @executable_path / @loader_path expanded) for a file
    named X on disk. If none match, X is unresolvable — dyld
    will abort with "Library not loaded" at runtime.
    """
    unresolved: list[str] = []
    for dep in deps:
        if not dep.startswith("@rpath/"):
            continue
        lib = dep[len("@rpath/"):]
        found = False
        for rp in rpaths:
            resolved = expand_rpath(rp, binary)
            if Path(resolved, lib).exists():
                found = True
                break
        if not found:
            unresolved.append(lib)
    return unresolved


def unresolvable_elf_needed(
    binary: Path, needed: list[str], runpath: list[str]
) -> list[tuple[str, list[str]]]:
    """Return (soname, tried_dirs) for each DT_NEEDED soname
    that ld.so would fail to load.

    A soname is fine if it is host-provided (system allowlist)
    or if it resolves to an existing file through one of the
    binary's RUNPATH entries ($ORIGIN-expanded, which reaches
    both the package's own lib/ and the ~/.gale/lib farm). Any
    other soname is unresolvable: ld.so aborts at runtime with
    "cannot open shared object file". tried_dirs lists the
    expanded RUNPATH dirs searched, for the failure message.
    """
    problems: list[tuple[str, list[str]]] = []
    for soname in needed:
        if is_system_soname(soname):
            continue
        tried: list[str] = []
        found = False
        for rp in runpath:
            resolved = expand_rpath(rp, binary)
            tried.append(resolved)
            if Path(resolved, soname).exists():
                found = True
                break
        if not found:
            problems.append((soname, tried))
    return problems


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

        rel = path.relative_to(prefix)

        # Mach-O carries @rpath/ install names resolved against
        # LC_RPATH; ELF carries bare DT_NEEDED sonames resolved
        # against DT_RUNPATH plus ld.so's default search path.
        # Both are checked, but the ELF side must first exempt
        # the system allowlist (libc, libm, ...) that ld.so
        # supplies outside RUNPATH — otherwise every glibc dep
        # would false-positive.
        if kind == "macho":
            for lib in unresolvable_rpath_refs(path, deps, rpaths):
                failures.append(
                    f"{rel}: references @rpath/{lib} but no "
                    f"rpath entry resolves to a file "
                    f"(dyld would abort at runtime)"
                )
        else:
            for soname, tried in unresolvable_elf_needed(
                path, deps, rpaths
            ):
                where = ", ".join(tried) if tried else "none"
                failures.append(
                    f"{rel}: DT_NEEDED '{soname}' not found on "
                    f"the system allowlist or via RUNPATH "
                    f"[{where}] (ld.so would fail to load it "
                    f"at runtime)"
                )

        used_pkgs: dict[str, str] = {}
        for dep in deps:
            pkg = resolve_pkg(dep, rpaths, path)
            if pkg and pkg not in allowed:
                used_pkgs.setdefault(pkg, dep)

        if used_pkgs:
            for pkg, dep in sorted(used_pkgs.items()):
                failures.append(
                    f"{rel}: loads '{dep}' from gale "
                    f"store '{pkg}', but '{pkg}' is not "
                    f"in [dependencies].runtime"
                )
        elif verbose:
            resolved = {
                resolve_pkg(d, rpaths, path)
                for d in deps if resolve_pkg(d, rpaths, path)
            }
            if resolved:
                print(f"  ok {rel} -> {sorted(resolved)}")

    if verbose:
        print(f"scanned {checked} binaries under {prefix}")
    return failures


def resolve_prefix(name: str, version: str, revision: int) -> Path:
    """Default gale store path: matches run_smoke/verify_binary.

    $HOME/.gale/pkg/<name>/<version>-<revision>/, including the
    -1 suffix when revision is 1. This is where `gale install`
    writes the package, so the installed tree carries the same
    files and the same baked rpaths as the built archive — the
    static rpath check is equivalent against either.

    Override $HOME to target a different store.
    """
    return (Path.home() / ".gale" / "pkg" / name
            / f"{version}-{revision}")


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
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--prefix", type=Path,
                     help="installed prefix to scan (defaults to "
                          "~/.gale/pkg/<name>/<version>-<rev>)")
    src.add_argument("--archive", type=Path,
                     help="built tar.zst to extract and scan")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    with args.recipe.open("rb") as f:
        recipe = tomllib.load(f)

    name = recipe["package"]["name"]
    version = recipe["package"]["version"]
    revision = int(recipe["package"].get("revision", 1) or 1)
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
    elif args.prefix:
        prefix = args.prefix
    else:
        # No source given: scan the installed store prefix, the
        # way verify.yml does after a single `gale install`.
        prefix = resolve_prefix(name, version, revision)
        if not prefix.is_dir():
            print(f"check_install: prefix {prefix} does not "
                  f"exist; install the package first",
                  file=sys.stderr)
            return 1

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
            f"\nhint: undeclared-dep — add the package to "
            f"[dependencies].runtime in {args.recipe}; "
            f"unresolvable @rpath / DT_NEEDED — stop linking the "
            f"lib (static-link it), or declare+keep its provider "
            f"so the dylib is present at runtime and reachable "
            f"via the binary's RUNPATH",
            file=sys.stderr)
        return 1

    print(f"check_install: {name} OK "
          f"(runtime deps: {sorted(runtime_deps) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
