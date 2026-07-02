#!/usr/bin/env python3
"""Tests for check_install.py targeting the installed store prefix
(gh#95).

verify.yml drops the extra `gale build` and runs the rpath check
against the INSTALLED prefix instead of an extracted archive. For
that, check_install.py must resolve
$HOME/.gale/pkg/<name>/<version>-<revision> from the recipe alone,
the same way verify_binary.py and run_smoke.py already do, and
fail loudly when that prefix is absent (a failed install must not
silently pass the check).
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


def recipe_text(name: str, version: str = "1.0.0",
                revision: int | None = None) -> str:
    lines = ["[package]", f'name = "{name}"',
             f'version = "{version}"']
    if revision is not None:
        lines.append(f"revision = {revision}")
    lines += ["", "[source]",
              'url = "https://example.invalid/s.tar.gz"',
              'sha256 = "' + "0" * 64 + '"',
              "", "[build]", 'steps = ["true"]']
    return "\n".join(lines) + "\n"


class ResolvePrefixTests(unittest.TestCase):
    def test_appends_revision_suffix_default_one(self) -> None:
        p = check_install.resolve_prefix("foo", "1.2.3", 1)
        self.assertEqual(p.parts[-3:], ("pkg", "foo", "1.2.3-1"))

    def test_uses_explicit_revision(self) -> None:
        p = check_install.resolve_prefix("bar", "2.0.0", 4)
        self.assertEqual(p.name, "2.0.0-4")
        self.assertEqual(p.parent.name, "bar")


class DefaultPrefixCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.recipe = self.home / "foo.toml"
        self.recipe.write_text(recipe_text("foo", "1.0.0"))

    def run_check(self, extra: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--recipe",
             str(self.recipe), *extra],
            capture_output=True, text=True,
            env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
        )

    def make_installed_prefix(self) -> Path:
        prefix = (self.home / ".gale" / "pkg" / "foo" / "1.0.0-1")
        binp = prefix / "bin"
        binp.mkdir(parents=True)
        # A real ELF/Mach-O so walk_binaries yields at least one
        # file, proving the scan hit the resolved store prefix.
        src = shutil.which("true") or "/bin/true"
        shutil.copy(src, binp / "foo")
        return prefix

    def test_defaults_to_installed_store_prefix(self) -> None:
        self.make_installed_prefix()
        r = self.run_check([])
        self.assertEqual(r.returncode, 0,
                         msg=f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("foo OK", r.stdout)

    def test_missing_prefix_fails_loudly(self) -> None:
        # No install performed: the default store prefix is absent.
        r = self.run_check([])
        self.assertEqual(r.returncode, 1,
                         msg=f"stdout={r.stdout}\nstderr={r.stderr}")
        self.assertIn("does not exist", r.stderr)


class VerifyWorkflowEvictionTests(unittest.TestCase):
    """verify.yml must force a real build under install-only (gh#95).

    The restore-only dep cache repopulates ~/.gale/pkg, which
    includes any previously built revision of the target recipe
    (deps-<platform>- is saved by privileged build-chunk runs and
    keyed per-platform, not per-runner or per-PR). gale's installer
    returns MethodCached with NO build when the store path already
    exists, and `gale install --recipe` has no --force. Without
    evicting the target first, the single install compiles nothing
    and the checks validate a stale cached binary — breaking #95's
    invariant that verify still exercises a real build and the
    runner-override re-verify path. Deps stay cached (speedup kept).
    """

    WORKFLOW = SCRIPTS.parent / ".github" / "workflows" / "verify.yml"
    EVICT = 'rm -rf "$HOME/.gale/pkg/${RECIPE_NAME}"'

    def setUp(self) -> None:
        self.text = self.WORKFLOW.read_text()

    def test_evicts_target_store_before_install(self) -> None:
        self.assertIn(
            self.EVICT, self.text,
            msg="verify.yml must evict the target from the restored "
                "store before the install-only build so the installer "
                "does a real build instead of returning MethodCached")

    def test_eviction_precedes_build_and_checks(self) -> None:
        text = self.text
        evict_idx = text.find(self.EVICT)
        self.assertGreaterEqual(
            evict_idx, 0, "eviction command missing from verify.yml")
        for marker in ("gale install --global",
                       "verify_binary.py", "check_install.py"):
            idx = text.find(marker)
            self.assertGreaterEqual(
                idx, 0, f"{marker!r} missing from verify.yml")
            self.assertLess(
                evict_idx, idx,
                f"store eviction must run before {marker!r}")


if __name__ == "__main__":
    unittest.main()
