#!/usr/bin/env python3
"""apply_fragment is idempotent. Does not run gale admit."""

from __future__ import annotations

import stat
import tempfile
import tomllib
import unittest
from pathlib import Path

import admit_linux as al

JQ = """\
[package]
name = "jq"
latest = "1.8.2"

[versions."1.8.2".artifacts."darwin/arm64"]
url = "https://example/darwin"
format = "binary"
sha256 = "aa"
tree_digest = "sha256:bb"
hash_source = "computed"
strip = 0
"""

FRAG = """\
[versions."1.8.2".artifacts."linux/amd64"]
url = "https://example/linux"
format = "binary"
sha256 = "cc"
tree_digest = "sha256:dd"
hash_source = "computed"
strip = 0

[[versions."1.8.2".artifacts."linux/amd64".files]]
src = "jq-linux-amd64"
dest = "bin/jq"
mode = 0o755
"""

FRAG2 = FRAG.replace("sha256:dd", "sha256:ee")


class ApplyFragmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "jq.toml"
        self.path.write_text(JQ)

    def test_second_apply_does_not_duplicate_table(self) -> None:
        al.apply_fragment(self.path, FRAG)
        al.apply_fragment(self.path, FRAG)
        text = self.path.read_text()
        self.assertEqual(text.count('artifacts."linux/amd64"]'), 1)
        data = tomllib.loads(text)
        linux = data["versions"]["1.8.2"]["artifacts"]["linux/amd64"]
        self.assertEqual(linux["tree_digest"], "sha256:dd")
        self.assertIn("darwin/arm64", data["versions"]["1.8.2"]["artifacts"])

    def test_second_apply_replaces_digest(self) -> None:
        al.apply_fragment(self.path, FRAG)
        al.apply_fragment(self.path, FRAG2)
        data = tomllib.loads(self.path.read_text())
        linux = data["versions"]["1.8.2"]["artifacts"]["linux/amd64"]
        self.assertEqual(linux["tree_digest"], "sha256:ee")


class ExecutableTests(unittest.TestCase):
    def test_admit_linux_is_executable(self) -> None:
        path = Path(al.__file__)
        mode = path.stat().st_mode
        self.assertTrue(
            mode & stat.S_IXUSR,
            f"{path.name} mode {oct(mode)} is not executable",
        )


if __name__ == "__main__":
    unittest.main()
