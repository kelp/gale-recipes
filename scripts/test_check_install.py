#!/usr/bin/env python3
"""Tests for check_install.py's ELF DT_NEEDED resolution (gh#160).

check_install.py walks every shipped ELF and asserts each
DT_NEEDED soname is either host-provided (system allowlist) or
resolvable through the binary's $ORIGIN-expanded RUNPATH (which
reaches the package's own lib/ and the ~/.gale/lib farm). A
soname that is neither would make ld.so abort at runtime with
"cannot open shared object file" — the class of bug behind
awscli's missing libpython3.14 and the patchelf-corrupted gale.

The unit tests exercise the resolution logic directly (no need
to synthesize ELF binaries); the integration tests drive the
whole script against real system binaries.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
SCRIPT = SCRIPTS / "check_install.py"

sys.path.insert(0, str(SCRIPTS))
import check_install  # noqa: E402


def recipe_text(name: str, version: str = "1.0.0") -> str:
    return "\n".join([
        "[package]",
        f'name = "{name}"',
        f'version = "{version}"',
        "",
        "[source]",
        'url = "https://example.invalid/s.tar.gz"',
        'sha256 = "' + "0" * 64 + '"',
        "",
        "[build]",
        'steps = ["true"]',
    ]) + "\n"


class ExpandRpathOriginTests(unittest.TestCase):
    """$ORIGIN / ${ORIGIN} expand relative to the binary's dir."""

    def setUp(self) -> None:
        self.binary = Path("/opt/pkg/foo/1.0.0-1/bin/foo")

    def test_bare_origin(self) -> None:
        self.assertEqual(
            check_install.expand_rpath("$ORIGIN", self.binary),
            str(self.binary.parent))

    def test_origin_with_suffix(self) -> None:
        self.assertEqual(
            check_install.expand_rpath("$ORIGIN/../lib", self.binary),
            str(self.binary.parent / "../lib"))

    def test_braced_origin(self) -> None:
        self.assertEqual(
            check_install.expand_rpath("${ORIGIN}/../lib", self.binary),
            str(self.binary.parent / "../lib"))

    def test_loader_path_still_expands(self) -> None:
        # Existing Mach-O behavior must be preserved.
        self.assertEqual(
            check_install.expand_rpath("@loader_path/../lib", self.binary),
            str(self.binary.parent / "../lib"))

    def test_plain_path_unchanged(self) -> None:
        self.assertEqual(
            check_install.expand_rpath("/abs/lib", self.binary),
            "/abs/lib")


class IsSystemSonameTests(unittest.TestCase):
    def test_glibc_family_allowed(self) -> None:
        for soname in ("libc.so.6", "libm.so.6", "libpthread.so.0",
                       "libdl.so.2", "libgcc_s.so.1", "libstdc++.so.6"):
            self.assertTrue(check_install.is_system_soname(soname), soname)

    def test_dynamic_loader_allowed_by_prefix(self) -> None:
        self.assertTrue(
            check_install.is_system_soname("ld-linux-x86-64.so.2"))
        self.assertTrue(
            check_install.is_system_soname("ld-linux-aarch64.so.1"))

    def test_farmed_deps_not_allowed(self) -> None:
        for soname in ("libpython3.14.so.1.0", "libpcre2-8.so.0",
                       "libssl.so.3", "libcurl.so.4"):
            self.assertFalse(check_install.is_system_soname(soname), soname)


class UnresolvableElfNeededTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        # A fake package layout: bin/foo with a sibling lib/ that
        # plays the role of the farm reached via $ORIGIN/../lib.
        self.binary = root / "bin" / "foo"
        self.binary.parent.mkdir(parents=True)
        self.binary.write_bytes(b"\x7fELF stub")
        self.libdir = root / "lib"
        self.libdir.mkdir()
        (self.libdir / "libpcre2-8.so.0").write_bytes(b"stub")

    def test_soname_resolved_via_runpath(self) -> None:
        problems = check_install.unresolvable_elf_needed(
            self.binary, ["libpcre2-8.so.0"], ["$ORIGIN/../lib"])
        self.assertEqual(problems, [])

    def test_missing_soname_reported_with_tried_dirs(self) -> None:
        problems = check_install.unresolvable_elf_needed(
            self.binary, ["libmissing.so.1"], ["$ORIGIN/../lib"])
        self.assertEqual(len(problems), 1)
        soname, tried = problems[0]
        self.assertEqual(soname, "libmissing.so.1")
        # The expanded RUNPATH dir searched is reported for the
        # failure message.
        self.assertEqual(tried, [str(self.binary.parent / "../lib")])

    def test_system_soname_with_empty_runpath_ok(self) -> None:
        problems = check_install.unresolvable_elf_needed(
            self.binary, ["libc.so.6"], [])
        self.assertEqual(problems, [])

    def test_missing_soname_with_empty_runpath_reported(self) -> None:
        problems = check_install.unresolvable_elf_needed(
            self.binary, ["libmissing.so.1"], [])
        self.assertEqual(problems, [("libmissing.so.1", [])])


def _first_dynamic_elf(*candidates: str) -> Path | None:
    """Return the first candidate that is a dynamically linked
    ELF check_install can inspect (readelf present, NEEDED
    non-empty), or None."""
    for cand in candidates:
        p = Path(cand)
        if not p.exists() or p.is_symlink():
            continue
        if check_install.sniff(p) != "elf":
            continue
        needed, _ = check_install.elf_refs(p)
        if needed:
            return p
    return None


def _elf_with_foreign_needed(*candidates: str):
    """Return (path, foreign_sonames) for the first candidate ELF
    whose NEEDED contains a non-allowlisted soname that its own
    RUNPATH cannot resolve — i.e. one the check must flag once the
    binary is copied into a bare prefix. Returns (None, None)."""
    for cand in candidates:
        p = Path(cand)
        if not p.exists() or p.is_symlink():
            continue
        if check_install.sniff(p) != "elf":
            continue
        needed, _ = check_install.elf_refs(p)
        foreign = [s for s in needed
                   if not check_install.is_system_soname(s)]
        if foreign:
            return p, foreign
    return None, None


class IntegrationTests(unittest.TestCase):
    """Drive the whole script against real system binaries."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.recipe = self.home / "foo.toml"
        self.recipe.write_text(recipe_text("foo"))

    def _install(self, src: Path) -> None:
        binp = self.home / ".gale" / "pkg" / "foo" / "1.0.0-1" / "bin"
        binp.mkdir(parents=True)
        shutil.copy(src, binp / "foo")

    def _run(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--recipe", str(self.recipe)],
            capture_output=True, text=True,
            env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
        )

    def test_allowlisted_binary_passes(self) -> None:
        """A stock glibc binary (NEEDED = libc.so.6) must pass —
        the ELF branch must not false-positive on system libs."""
        src = _first_dynamic_elf("/bin/true", "/usr/bin/true")
        if src is None:
            self.skipTest("no dynamically linked /bin/true available")
        self._install(src)
        r = self._run()
        self.assertEqual(r.returncode, 0,
                         msg=f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("foo OK", r.stdout)

    def test_unresolvable_soname_fails(self) -> None:
        """A binary whose NEEDED carries a non-system soname with
        no RUNPATH to resolve it must fail, naming the soname."""
        src, foreign = _elf_with_foreign_needed(
            "/bin/ls", "/usr/bin/ls", "/bin/grep", "/usr/bin/grep")
        if src is None:
            self.skipTest("no ELF with a non-allowlisted NEEDED found")
        self._install(src)
        r = self._run()
        self.assertEqual(r.returncode, 1,
                         msg=f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("DT_NEEDED", r.stderr)
        self.assertIn(foreign[0], r.stderr)


if __name__ == "__main__":
    unittest.main()
