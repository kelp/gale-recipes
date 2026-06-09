#!/usr/bin/env python3
"""Classify the audit_binaries.py report into actionable buckets.

Reads the JSON written by audit_binaries.py and prints:
  - SHA failures (download/integrity)
  - linux run failures (binary doesn't execute)
  - linux absolute-store RUNPATH (non-relocatable ELF)
  - darwin genuine breakage (own dylib unreachable via relative rpath)
  - darwin farm-dep risk (farm dep ref with NO relative rpath at all)
  - darwin cosmetic residue (dead absolute store/tmp rpaths only)
  - missing platforms (declared platforms with no audited binary)
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ALL = {"darwin-arm64", "linux-amd64", "linux-arm64"}
ROOT = Path(__file__).resolve().parent.parent

def declared_platforms(name: str) -> set[str]:
    """Eligible platforms = [package].platforms or all three."""
    import tomllib
    for sub in ROOT.glob(f"recipes/*/{name}.toml"):
        with sub.open("rb") as f:
            r = tomllib.load(f)
        pl = r.get("package", {}).get("platforms")
        if pl:
            return set(pl)
        return set(ALL)
    return set(ALL)

def is_relative(rp: str) -> bool:
    return rp.startswith("@loader_path") or rp.startswith("@executable_path")

def main():
    data = json.load(open(sys.argv[1]))
    sha_fail, run_fail, elf_abs = [], [], []
    dar_break, farm_risk, residue, errors = [], [], [], []
    missing = []
    for name, rec in sorted(data.items()):
        plats = rec.get("platforms", {})
        decl = declared_platforms(name)
        for p in sorted(decl - set(plats.keys())):
            missing.append(f"{name} [{p}]")
        for plat, pr in plats.items():
            tag = f"{name} [{plat}]"
            if pr.get("error"):
                errors.append(f"{tag}: {pr['error']}")
            if pr.get("sha_ok") is False:
                sha_fail.append(tag)
            if plat == "linux-amd64":
                for b, rr in (pr.get("run") or {}).items():
                    if not rr.get("ok"):
                        run_fail.append(f"{tag} {b}: {rr.get('out')}")
            for ei in pr.get("elf_issues", []):
                elf_abs.append(f"{tag}: {ei}")
            # darwin analysis
            detail = pr.get("macho_detail") or {}
            for rel, info in detail.items():
                rpaths = info.get("rpaths", [])
                has_rel = any(is_relative(r) for r in rpaths)
                if info.get("self_unreachable"):
                    dar_break.append(
                        f"{tag} {rel}: own dylib unreachable "
                        f"{info['self_unreachable']}")
                if info.get("farm_deps") and not has_rel:
                    farm_risk.append(
                        f"{tag} {rel}: farm deps {info['farm_deps']} "
                        f"but NO relative rpath (only {rpaths})")
                if info.get("abs_store_rpaths") or info.get("abs_store_deps"):
                    residue.append(
                        f"{tag} {rel}: residue "
                        f"{info.get('abs_store_rpaths',[]) + info.get('abs_store_deps',[])}")

    def section(title, items):
        print(f"\n## {title}: {len(items)}")
        for i in items:
            print(f"  {i}")

    print(f"# Audit classification ({len(data)} recipes)")
    section("SHA / integrity failures", sha_fail)
    section("Linux run failures", run_fail)
    section("Linux absolute-store RUNPATH (non-relocatable ELF)", elf_abs)
    section("DARWIN genuine breakage (own dylib unreachable)", dar_break)
    section("DARWIN farm-dep risk (no relative rpath)", farm_risk)
    section("Download/parse errors", errors)
    section("Missing declared platforms", missing)
    # residue is high-volume + cosmetic; summarize by recipe
    res_recipes = sorted({r.split(" [")[0] for r in residue})
    print(f"\n## DARWIN cosmetic residue (dead abs rpaths): "
          f"{len(residue)} files across {len(res_recipes)} recipes")
    print("  recipes:", ", ".join(res_recipes))

if __name__ == "__main__":
    main()
