"""Tests for update_recipe.py.

Fixtures cover the shapes auto-update.sh actually hits:
a recipe with two `[binary.*]` sections surrounded by
other sections, a recipe whose binary section is last in
the file with no trailing newline, and a recipe with no
binary section at all. Also exercises set_field across
two sections to confirm the old-value guard.

Run with: ``python3 -m unittest scripts.test_update_recipe``
or ``python3 scripts/test_update_recipe.py``.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

from update_recipe import set_field, strip_binary_sections  # noqa: E402


RECIPE_STANDARD = """\
[package]
name = "fd"
version = "10.4.2"
revision = 2

[source]
repo = "sharkdp/fd"
url = "https://github.com/sharkdp/fd/archive/refs/tags/v10.4.2.tar.gz"
sha256 = "aaaa"
released_at = "2026-03-10"

[binary.darwin-arm64]
url = "ghcr.io/foo/fd:10.4.2-darwin-arm64"
sha256 = "bbbb"

[binary.linux-amd64]
url = "ghcr.io/foo/fd:10.4.2-linux-amd64"
sha256 = "cccc"

[build]
steps = ["cargo install --path . --root ${PREFIX}"]

[dependencies]
build = ["rust"]
"""


RECIPE_TRAILING_BINARY = """\
[package]
name = "fd"
version = "10.4.2"

[source]
url = "https://example.com/fd.tar.gz"
sha256 = "aaaa"

[binary.darwin-arm64]
url = "ghcr.io/foo/fd:10.4.2-darwin-arm64"
sha256 = "bbbb"
"""  # no trailing blank line after last section


RECIPE_NO_BINARY = """\
[package]
name = "fd"
version = "10.4.2"

[source]
url = "https://example.com/fd.tar.gz"
sha256 = "aaaa"
"""


class SetFieldTests(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content)
        return p

    def test_replaces_version(self):
        p = self._write("r.toml", RECIPE_STANDARD)
        self.assertTrue(set_field(p, "version", "10.4.2", "10.5.0"))
        text = p.read_text()
        self.assertIn('version = "10.5.0"', text)
        self.assertNotIn('version = "10.4.2"', text)

    def test_replaces_source_url_leaves_binary_urls(self):
        p = self._write("r.toml", RECIPE_STANDARD)
        old = "https://github.com/sharkdp/fd/archive/refs/tags/v10.4.2.tar.gz"
        new = "https://github.com/sharkdp/fd/archive/refs/tags/v10.5.0.tar.gz"
        self.assertTrue(set_field(p, "url", old, new))
        text = p.read_text()
        self.assertIn(new, text)
        self.assertNotIn(old, text)
        # Binary URLs untouched — different value, guarded by old_value.
        self.assertIn("ghcr.io/foo/fd:10.4.2-darwin-arm64", text)
        self.assertIn("ghcr.io/foo/fd:10.4.2-linux-amd64", text)

    def test_missing_field_returns_false(self):
        p = self._write("r.toml", RECIPE_NO_BINARY)
        self.assertFalse(set_field(p, "released_at", "2020-01-01", "2026-04-24"))
        self.assertEqual(p.read_text(), RECIPE_NO_BINARY)

    def test_wrong_old_value_returns_false(self):
        p = self._write("r.toml", RECIPE_STANDARD)
        self.assertFalse(set_field(p, "version", "99.99.99", "10.5.0"))
        self.assertIn('version = "10.4.2"', p.read_text())

    def test_preserves_comments_and_spacing(self):
        content = (
            "# Generated from Homebrew formula (BSD-2-Clause)\n\n"
            '[package]\nname = "fd"\nversion = "10.4.2"\n'
        )
        p = self._write("r.toml", content)
        set_field(p, "version", "10.4.2", "10.5.0")
        out = p.read_text()
        self.assertTrue(out.startswith(
            "# Generated from Homebrew formula (BSD-2-Clause)\n\n"))
        self.assertIn('[package]\nname = "fd"\nversion = "10.5.0"\n', out)


class StripBinaryTests(unittest.TestCase):
    def setUp(self):
        self._td = TemporaryDirectory()
        self.tmp = Path(self._td.name)
        self.addCleanup(self._td.cleanup)

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp / name
        p.write_text(content)
        return p

    def test_removes_both(self):
        p = self._write("r.toml", RECIPE_STANDARD)
        self.assertEqual(strip_binary_sections(p), 2)
        text = p.read_text()
        self.assertNotIn("[binary.", text)
        self.assertIn("[source]", text)
        self.assertIn("[build]", text)
        self.assertIn("[dependencies]", text)

    def test_trailing_binary_no_newline(self):
        p = self._write("r.toml", RECIPE_TRAILING_BINARY)
        self.assertEqual(strip_binary_sections(p), 1)
        text = p.read_text()
        self.assertNotIn("[binary.", text)
        self.assertIn("[source]", text)
        self.assertIn('sha256 = "aaaa"', text)

    def test_noop_when_absent(self):
        p = self._write("r.toml", RECIPE_NO_BINARY)
        self.assertEqual(strip_binary_sections(p), 0)
        self.assertEqual(p.read_text(), RECIPE_NO_BINARY)

    def test_no_triple_blank_lines_after_strip(self):
        p = self._write("r.toml", RECIPE_STANDARD)
        strip_binary_sections(p)
        self.assertNotIn("\n\n\n", p.read_text())


if __name__ == "__main__":
    unittest.main()
