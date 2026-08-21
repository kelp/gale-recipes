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
            [
                "jq", "ripgrep", "fd", "just", "gh", "direnv",
                "gofumpt", "golangci-lint", "go", "uv",
                "fzf", "age", "shfmt", "actionlint",
                "yq", "shellcheck", "starship", "zoxide",
            ],
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

    def test_gofumpt_binary_computed(self) -> None:
        g = am.by_name("gofumpt")
        argv = am.admit_argv(g, "/tmp/gofumpt_v0.11.0_darwin_arm64")
        self.assertIn("binary", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)
        self.assertIn("gofumpt_v0.11.0_darwin_arm64:bin/gofumpt:755", argv)

    def test_uv_ships_uv_and_uvx(self) -> None:
        uv = am.by_name("uv")
        argv = am.admit_argv(uv, "/tmp/uv.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("uv:bin/uv:755", argv)
        self.assertIn("uvx:bin/uvx:755", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(uv.sha256, argv)

    def test_go_directory_map(self) -> None:
        g = am.by_name("go")
        argv = am.admit_argv(g, "/tmp/go.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("https://go.dev/dl/go1.26.1.darwin-arm64.tar.gz", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(g.sha256, argv)
        self.assertIn("bin:bin:755", argv)
        self.assertIn("src:src:755", argv)
        self.assertIn("pkg:pkg:755", argv)
        self.assertIn("VERSION:VERSION:644", argv)
        self.assertNotIn("src:src:644", argv)

    def test_golangci_lint_tarball(self) -> None:
        g = am.by_name("golangci-lint")
        argv = am.admit_argv(g, "/tmp/golangci.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("golangci-lint:bin/golangci-lint:755", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(g.sha256, argv)

    def test_direnv_binary_computed(self) -> None:
        d = am.by_name("direnv")
        argv = am.admit_argv(d, "/tmp/direnv.darwin-arm64")
        self.assertIn("binary", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)
        self.assertIn("direnv.darwin-arm64:bin/direnv:755", argv)

    def test_fzf_root_tarball(self) -> None:
        p = am.by_name("fzf")
        argv = am.admit_argv(p, "/tmp/fzf.tar.gz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("0", argv)
        self.assertIn("fzf:bin/fzf:755", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(
            "1f8501cea4f9c0c2d6110d0ff75d0ec9451cd9d7524d9a26244a154ea89f3bd5",
            argv,
        )

    def test_age_two_bins_computed(self) -> None:
        p = am.by_name("age")
        argv = am.admit_argv(p, "/tmp/age.tar.gz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("age:bin/age:755", argv)
        self.assertIn("age-keygen:bin/age-keygen:755", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)

    def test_shfmt_binary_computed(self) -> None:
        p = am.by_name("shfmt")
        argv = am.admit_argv(p, "/tmp/shfmt_v3.13.1_darwin_arm64")
        self.assertIn("binary", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)
        self.assertIn(
            "shfmt_v3.13.1_darwin_arm64:bin/shfmt:755",
            argv,
        )

    def test_actionlint_tarball(self) -> None:
        p = am.by_name("actionlint")
        argv = am.admit_argv(p, "/tmp/actionlint.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("0", argv)
        self.assertIn("actionlint:bin/actionlint:755", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(
            "aba9ced2dee8d27fecca3dc7feb1a7f9a52caefa1eb46f3271ea66b6e0e6953f",
            argv,
        )

    def test_yq_binary_computed(self) -> None:
        p = am.by_name("yq")
        argv = am.admit_argv(p, "/tmp/yq_darwin_arm64")
        self.assertIn("binary", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)
        self.assertIn("yq_darwin_arm64:bin/yq:755", argv)

    def test_shellcheck_strips_prefix(self) -> None:
        p = am.by_name("shellcheck")
        argv = am.admit_argv(p, "/tmp/shellcheck.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("1", argv)
        self.assertIn("shellcheck:bin/shellcheck:755", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)

    def test_starship_root_tarball(self) -> None:
        p = am.by_name("starship")
        argv = am.admit_argv(p, "/tmp/starship.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("0", argv)
        self.assertIn("starship:bin/starship:755", argv)
        self.assertIn("upstream-sha256sums", argv)
        self.assertIn(
            "c40b27b11f580411e068f2fa6c1be7830a387c0bc47a94d1d37f32b054c5361d",
            argv,
        )

    def test_zoxide_root_tarball(self) -> None:
        p = am.by_name("zoxide")
        argv = am.admit_argv(p, "/tmp/zoxide.tgz")
        self.assertIn("tar.gz", argv)
        self.assertIn("--strip", argv)
        self.assertIn("0", argv)
        self.assertIn("zoxide:bin/zoxide:755", argv)
        self.assertIn("computed", argv)
        self.assertNotIn("--sha256", argv)

    def test_all_darwin_arm64(self) -> None:
        for p in am.PACKAGES:
            argv = am.admit_argv(p, "/tmp/a")
            self.assertIn("--os", argv)
            self.assertIn("darwin", argv)
            self.assertIn("--arch", argv)
            self.assertIn("arm64", argv)
            self.assertTrue(
                p.url.startswith("https://github.com/")
                or p.url.startswith("https://go.dev/"),
                p.url,
            )


if __name__ == "__main__":
    unittest.main()
