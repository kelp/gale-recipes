#!/usr/bin/env python3
"""One-shot binary audit for the gale-recipes sweep.

For every recipe with a .binaries.toml, for each declared platform:
  - download the GHCR blob (anonymous token), verify sha256
  - linux-*: extract, find ELF executables in bin/, run --version/--help
  - darwin-*: extract, parse Mach-O, flag unresolvable @rpath/<lib> refs
    (the dyld-abort class) and report rpaths + self dylib refs

Writes a JSON report to the path given as argv[1].
Pure-Python Mach-O parser so it runs on Linux (no otool needed).
"""
from __future__ import annotations
import json, os, re, struct, subprocess, sys, tempfile, urllib.request
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parent.parent
PLATFORMS_DEFAULT = ["darwin-arm64", "linux-amd64", "linux-arm64"]

# ---------- Mach-O parsing ----------
FAT_MAGIC = {0xCAFEBABE, 0xBEBAFECA}
MH_MAGIC = {0xFEEDFACE, 0xCEFAEDFE, 0xFEEDFACF, 0xCFFAEDFE}
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x18
LC_REEXPORT_DYLIB = 0x1F
LC_RPATH = 0x8000001C
LC_ID_DYLIB = 0x0D

def _machos_in(data: bytes):
    """Yield (offset, little_endian, is64) for each thin slice."""
    if len(data) < 4:
        return
    magic = struct.unpack(">I", data[:4])[0]
    if magic in FAT_MAGIC:
        be = magic == 0xCAFEBABE
        nfat = struct.unpack(">I" if be else "<I", data[4:8])[0]
        off = 8
        for _ in range(nfat):
            # fat_arch: cputype, cpusubtype, offset, size, align (all u32 BE)
            fields = struct.unpack(">5I", data[off:off+20])
            yield from _thin(data, fields[2])
            off += 20
    else:
        yield from _thin(data, 0)

def _thin(data: bytes, off: int):
    if off + 4 > len(data):
        return
    magic = struct.unpack("<I", data[off:off+4])[0]
    magic_be = struct.unpack(">I", data[off:off+4])[0]
    if magic in MH_MAGIC:
        le = magic in (0xFEEDFACE, 0xFEEDFACF)
        is64 = magic in (0xFEEDFACF, 0xCFFAEDFE)
        yield (off, le, is64)
    elif magic_be in MH_MAGIC:
        le = magic_be in (0xFEEDFACE, 0xFEEDFACF)
        is64 = magic_be in (0xFEEDFACF, 0xCFFAEDFE)
        yield (off, le, is64)

def macho_refs(path: Path):
    """Return (dylib_deps, rpaths, install_id) for a Mach-O file, or None."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if len(data) < 4:
        return None
    m = struct.unpack(">I", data[:4])[0]
    if m not in FAT_MAGIC and m not in MH_MAGIC:
        return None
    deps, rpaths, install_id = [], [], None
    for off, le, is64 in _machos_in(data):
        e = "<" if le else ">"
        hdr = off + (32 if is64 else 28)
        ncmds = struct.unpack(e+"I", data[off+16:off+20])[0]
        p = hdr
        for _ in range(ncmds):
            if p + 8 > len(data):
                break
            cmd, csize = struct.unpack(e+"II", data[p:p+8])
            if csize == 0:
                break
            blob = data[p:p+csize]
            if cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB, LC_REEXPORT_DYLIB):
                stroff = struct.unpack(e+"I", blob[8:12])[0]
                s = blob[stroff:].split(b"\x00")[0].decode("utf-8","replace")
                if s not in deps:
                    deps.append(s)
            elif cmd == LC_RPATH:
                stroff = struct.unpack(e+"I", blob[8:12])[0]
                s = blob[stroff:].split(b"\x00")[0].decode("utf-8","replace")
                if s not in rpaths:
                    rpaths.append(s)
            elif cmd == LC_ID_DYLIB:
                stroff = struct.unpack(e+"I", blob[8:12])[0]
                install_id = blob[stroff:].split(b"\x00")[0].decode("utf-8","replace")
            p += csize
        break  # one slice is enough (arm64)
    return deps, rpaths, install_id

def expand_rpath(rp: str, binary: Path) -> str:
    for tok in ("@executable_path", "@loader_path"):
        if rp == tok:
            return str(binary.parent)
        if rp.startswith(tok+"/"):
            return str(binary.parent / rp[len(tok)+1:])
    return rp

def unresolvable(binary: Path, deps, rpaths):
    bad = []
    for dep in deps:
        if not dep.startswith("@rpath/"):
            continue
        lib = dep[len("@rpath/"):]
        ok = any(Path(expand_rpath(rp, binary), lib).exists() for rp in rpaths)
        if not ok:
            bad.append(lib)
    return bad

def is_macho(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            h = f.read(4)
    except OSError:
        return False
    m = struct.unpack(">I", h)[0] if len(h) == 4 else 0
    return m in FAT_MAGIC or m in MH_MAGIC

def is_elf(p: Path) -> bool:
    try:
        with p.open("rb") as f:
            return f.read(4) == b"\x7fELF"
    except OSError:
        return False

# ---------- download ----------
_tok_cache = {}
def token(name: str) -> str:
    if name in _tok_cache:
        return _tok_cache[name]
    u = (f"https://ghcr.io/token?service=ghcr.io"
         f"&scope=repository:kelp/gale-recipes/{name}:pull")
    with urllib.request.urlopen(u, timeout=60) as r:
        t = json.load(r).get("token", "")
    _tok_cache[name] = t
    return t

def fetch(name: str, url: str, dest: Path):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token(name)}",
        "Accept": "application/vnd.oci.image.layer.v1.tar+zstd, */*",
    })
    with urllib.request.urlopen(req, timeout=300) as r, dest.open("wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)

def sha256(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()

def extract(arc: Path, into: Path):
    subprocess.run(["tar", "--zstd", "-xf", str(arc), "-C", str(into)],
                   check=True, capture_output=True)

# ---------- recipe deps ----------
def runtime_deps(recipe: dict) -> set[str]:
    out = set()
    for e in recipe.get("dependencies", {}).get("runtime", []):
        if isinstance(e, str):
            out.add(e)
        elif isinstance(e, dict) and "name" in e:
            out.add(e["name"])
    return out

def main():
    out_path = Path(sys.argv[1])
    only = set(sys.argv[2:]) if len(sys.argv) > 2 else None
    results = {}
    btomls = sorted(ROOT.glob("recipes/*/*.binaries.toml"))
    for bt in btomls:
        name = bt.name[:-len(".binaries.toml")]
        if only and name not in only:
            continue
        recipe_path = bt.with_name(name + ".toml")
        if not recipe_path.exists():
            continue
        with recipe_path.open("rb") as f:
            recipe = tomllib.load(f)
        with bt.open("rb") as f:
            binmeta = tomllib.load(f)
        rdeps = runtime_deps(recipe)
        rec = {"deps": sorted(rdeps), "platforms": {}}
        version_top = binmeta.get("version")
        for plat, meta in binmeta.items():
            # platform tables are top-level dicts: [darwin-arm64] etc.
            if not isinstance(meta, dict):
                continue
            if "-" not in plat:
                continue
            want = meta.get("sha256")
            if not want:
                continue
            # GHCR blob URL is derived from the sha256; no url field.
            url = (f"https://ghcr.io/v2/kelp/gale-recipes/"
                   f"{name}/blobs/sha256:{want}")
            pr = {"version": version_top}
            tmp = Path(tempfile.mkdtemp(prefix=f"aud-{name}-"))
            arc = tmp / "a.tar.zst"
            try:
                fetch(name, url, arc)
                got = sha256(arc)
                pr["sha_ok"] = (got == want)
                if got != want:
                    pr["error"] = f"sha mismatch got={got[:12]} want={want[:12]}"
                    rec["platforms"][plat] = pr; continue
                ex = tmp / "x"; ex.mkdir()
                extract(arc, ex)
                bins = sorted([p for p in (ex/"bin").glob("*")
                               if p.is_file() and not p.is_symlink()]) \
                       if (ex/"bin").is_dir() else []
                pr["bins"] = [b.name for b in bins]
                if plat.startswith("linux"):
                    # Flag absolute gale-store RPATH/RUNPATH (non-
                    # relocatable). gale 0.16.x bakes $ORIGIN-relative.
                    elf_issues = []
                    for p in ex.rglob("*"):
                        if p.is_symlink() or not p.is_file() or not is_elf(p):
                            continue
                        try:
                            out = subprocess.run(
                                ["readelf", "-d", str(p)],
                                capture_output=True, text=True,
                                timeout=20).stdout
                        except Exception:
                            continue
                        for line in out.splitlines():
                            m = re.search(r"\((?:RUNPATH|RPATH)\)\s+.*\[(.+)\]",
                                          line)
                            if not m:
                                continue
                            for seg in m.group(1).split(":"):
                                if seg.startswith("/") and ".gale/pkg" in seg:
                                    elf_issues.append(
                                        f"{p.relative_to(ex)}: ABSOLUTE store "
                                        f"RPATH {seg}")
                    if elf_issues:
                        pr["elf_issues"] = elf_issues
                    # only run amd64 natively; arm64 just structural
                    ran = {}
                    if plat == "linux-amd64":
                        for b in bins[:6]:
                            ok = False; ver = ""
                            for flag in ("--version", "--help", "version"):
                                try:
                                    cp = subprocess.run(
                                        [str(b), flag], capture_output=True,
                                        text=True, timeout=20)
                                    if cp.returncode == 0:
                                        ok = True
                                        ver = (cp.stdout or cp.stderr).strip().split("\n")[0][:80]
                                        break
                                except Exception as ex2:
                                    ver = f"EXC {type(ex2).__name__}"
                            ran[b.name] = {"ok": ok, "out": ver}
                        pr["run"] = ran
                    # ELF dep check via readelf-free: just record NEEDED via parser? skip
                else:  # darwin
                    # Set of dylib basenames the archive itself ships.
                    # A @rpath/<x> whose basename is bundled MUST be
                    # reachable within the archive; if not, dyld aborts
                    # (real bug). A @rpath/<x> NOT bundled is a
                    # dependency-farm dylib resolved at install time via a
                    # farm rpath -- not verifiable offline, not a failure.
                    bundled = set()
                    machos = []
                    for p in ex.rglob("*"):
                        if p.is_symlink() or not p.is_file():
                            continue
                        if not is_macho(p):
                            continue
                        machos.append(p)
                        if p.name.endswith(".dylib") or ".dylib" in p.name:
                            bundled.add(p.name)
                    issues = []
                    rpath_report = {}
                    for p in machos:
                        r = macho_refs(p)
                        if not r:
                            continue
                        deps, rpaths, _ = r
                        rel = str(p.relative_to(ex))
                        # absolute store paths => non-relocatable (pre-0.16
                        # behavior leaking through). Hard failure.
                        abs_store_rp = [rp for rp in rpaths
                                        if ".gale/pkg" in rp and rp.startswith("/")]
                        abs_store_dep = [d for d in deps
                                         if d.startswith("/") and ".gale/pkg" in d]
                        rpath_deps = [d for d in deps if d.startswith("@rpath/")]
                        self_unreach = []
                        farm_deps = []
                        for d in rpath_deps:
                            lib = d[len("@rpath/"):]
                            base = lib.split("/")[-1]
                            if base in bundled:
                                # package's own dylib -- must resolve here
                                ok = any(Path(expand_rpath(rp, p), lib).exists()
                                         for rp in rpaths)
                                if not ok:
                                    self_unreach.append(lib)
                            else:
                                farm_deps.append(lib)
                        if (abs_store_rp or abs_store_dep or self_unreach
                                or rpath_deps):
                            rpath_report[rel] = {
                                "rpaths": rpaths,
                                "self_unreachable": self_unreach,
                                "farm_deps": farm_deps,
                                "abs_store_rpaths": abs_store_rp,
                                "abs_store_deps": abs_store_dep,
                            }
                        if abs_store_rp:
                            issues.append(f"{rel}: ABSOLUTE store rpath "
                                          f"(non-relocatable) {abs_store_rp}")
                        if abs_store_dep:
                            issues.append(f"{rel}: ABSOLUTE store dep "
                                          f"(non-relocatable) {abs_store_dep}")
                        if self_unreach:
                            issues.append(f"{rel}: own dylib unreachable "
                                          f"@rpath {self_unreach}")
                    pr["macho_issues"] = issues
                    pr["macho_detail"] = rpath_report
            except Exception as e:
                pr["error"] = f"{type(e).__name__}: {e}"
            finally:
                subprocess.run(["rm", "-rf", str(tmp)], check=False)
            rec["platforms"][plat] = pr
        results[name] = rec
        # incremental flush
        out_path.write_text(json.dumps(results, indent=1))
    out_path.write_text(json.dumps(results, indent=1))
    print(f"audited {len(results)} recipes -> {out_path}")

if __name__ == "__main__":
    main()
