#!/usr/bin/env python3
"""Argv construction for Darwin admission. Does not run gale admit."""

from __future__ import annotations

import unittest

import admit_manifest as am


class AdmitManifestTests(unittest.TestCase):
    def test_phase1_packages(self) -> None:
        names = [p.name for p in am.PACKAGES]
        self.assertEqual(
            names,
            ["jq", "ripgrep", "fd", "just", "gh", "direnv"],
        )

    def test_jq_binary_uses_url_basename(self) -> None:
        jq = am.by_name("jq")
        argv = am.admit_argv(jq, "/tmp/jq-macos-arm64")
        self.assertIn("--format", argv)
        self.assertIn("binary", argv)
        self.assertIn("--file", argv)
        self.assertIn("jq-macos-arm64:bin/jq:755", argv)
        self.assertIn("--hash-source", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(jq.sha256, argv)

    def test_ripgrep_strips_prefix(self) -> None:
        rg = am.by_name("ripgrep")
        argv = am.admit_argv(rg, "/tmp/rg.tar.gz")
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("rg:bin/rg:755", argv)
        self.assertIn("upstream-sha256sums", argv)

    def test_fd_computed_hash(self) -> None:
        fd = am.by_name("fd")
        argv = am.admit_argv(fd, "/tmp/fd.tar.gz")
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)
        self.assertIn("fd:bin/fd:755", argv)

    def test_just_root_tarball(self) -> None:
        just = am.by_name("just")
        argv = am.admit_argv(just, "/tmp/just.tar.gz")
        self.assertIn("--strip", argv)
        self.assertIn("0", argv)
        self.assertIn("just:bin/just:755", argv)
        self.assertIn("upstream-sha256sums", argv)

    def test_gh_zip_strips_prefix(self) -> None:
        gh = am.by_name("gh")
        argv = am.admit_argv(gh, "/tmp/gh.zip")
        self.assertIn("zip", argv)
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("bin/gh:bin/gh:755", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(gh.sha256, argv)

    def test_direnv_binary_computed(self) -> None:
        d = am.by_name("direnv")
        argv = am.admit_argv(d, "/tmp/direnv.darwin-arm64")
        self.assertIn("binary", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)
        self.assertIn("direnv.darwin-arm64:bin/direnv:755", argv)

    def test_all_darwin_arm64(self) -> None:
        for p in am.PACKAGES:
            argv = am.admit_argv(p, "/tmp/a")
            self.assertIn("--os", argv)
            self.assertIn("darwin", argv)
            self.assertIn("--arch", argv)
            self.assertIn("arm64", argv)
            self.assertTrue(p.url.startswith("https://github.com/"))


if __name__ == "__main__":
    unittest.main()
