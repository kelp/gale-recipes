#!/usr/bin/env python3
"""Tests for verify_binary.py — the farm-aware binary-run check.

Each test builds a throwaway installed-prefix and recipe and
runs verify_binary.py as a subprocess with an explicit
--prefix, exercising the same branches the inline shell used to
cover: a running binary, a binary killed by a signal (the dyld
case the whole change exists for), a library recipe, and a
missing prefix.
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "verify_binary.py"


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


class VerifyBinaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def write_recipe(self, name: str) -> Path:
        p = self.root / f"{name}.toml"
        p.write_text(recipe_text(name))
        return p

    def make_exec(self, path: Path, body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR
                   | stat.S_IXGRP | stat.S_IXOTH)

    def run_check(self, recipe: Path,
                  prefix: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--recipe", str(recipe),
             "--prefix", str(prefix)],
            capture_output=True, text=True,
        )

    def test_binary_runs_passes(self) -> None:
        prefix = self.root / "install"
        # exits 0 on --version
        self.make_exec(prefix / "bin" / "tool",
                       'case "$1" in --version) exit 0;; esac\n'
                       "exit 1\n")
        res = self.run_check(self.write_recipe("tool"), prefix)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_binary_killed_by_signal_fails(self) -> None:
        # The dyld-abort case the farm-aware change exists for:
        # the binary is killed (exit >= 128) on every probe.
        prefix = self.root / "install"
        self.make_exec(prefix / "bin" / "tool",
                       "kill -SEGV $$\n")
        res = self.run_check(self.write_recipe("tool"), prefix)
        self.assertEqual(res.returncode, 1)
        self.assertIn("killed by a signal", res.stderr)

    def test_library_recipe_passes(self) -> None:
        prefix = self.root / "install"
        (prefix / "lib").mkdir(parents=True)
        (prefix / "lib" / "libfoo.dylib").write_text("x")
        (prefix / "include").mkdir(parents=True)
        (prefix / "include" / "foo.h").write_text("x")
        res = self.run_check(self.write_recipe("libfoo"), prefix)
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_empty_prefix_fails(self) -> None:
        prefix = self.root / "install"
        prefix.mkdir()
        res = self.run_check(self.write_recipe("tool"), prefix)
        self.assertEqual(res.returncode, 1)

    def test_missing_prefix_fails(self) -> None:
        prefix = self.root / "nope"
        res = self.run_check(self.write_recipe("tool"), prefix)
        self.assertEqual(res.returncode, 1)
        self.assertIn("does not exist", res.stderr)

    def test_no_version_flag_but_executable_passes(self) -> None:
        # Runs but every probe is nonzero (not signal-killed):
        # a real executable with no version/help flag passes.
        prefix = self.root / "install"
        self.make_exec(prefix / "bin" / "tool", "exit 3\n")
        res = self.run_check(self.write_recipe("tool"), prefix)
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
