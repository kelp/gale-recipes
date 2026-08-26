#!/usr/bin/env python3
"""Index-update bot: cooldown, URL rewrite, append-only merge.

Does not call GitHub or gale admit. Network and admit are
injected.
"""

from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import index_update as iu

JQ = """\
[package]
name = "jq"
description = "JSON processor"
license = "MIT"
homepage = "https://jqlang.github.io/jq"
repo = "jqlang/jq"
latest = "1.8.2"

[versions."1.8.2".artifacts."darwin/arm64"]
url = "https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-macos-arm64"
format = "binary"
sha256 = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
tree_digest = "sha256:bb"
hash_source = "upstream-sha256sums"
strip = 0

[[versions."1.8.2".artifacts."darwin/arm64".files]]
src = "jq-macos-arm64"
dest = "bin/jq"
mode = 0o755
"""

FD = """\
[package]
name = "fd"
description = "find"
license = "Apache-2.0"
homepage = "https://github.com/sharkdp/fd"
repo = "sharkdp/fd"
latest = "10.4.2"

[versions."10.4.2".artifacts."darwin/arm64"]
url = "https://github.com/sharkdp/fd/releases/download/v10.4.2/fd-v10.4.2-aarch64-apple-darwin.tar.gz"
format = "tar.gz"
sha256 = "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc"
tree_digest = "sha256:dd"
hash_source = "computed"
strip = 1

[[versions."10.4.2".artifacts."darwin/arm64".files]]
src = "fd"
dest = "bin/fd"
mode = 0o755
"""

NOW = datetime(2026, 8, 24, tzinfo=timezone.utc)


class TagToVersionTests(unittest.TestCase):
    def test_strips_v_prefix(self) -> None:
        self.assertEqual(iu.tag_to_version("v10.4.3", "fd"), "10.4.3")

    def test_strips_name_hyphen_prefix(self) -> None:
        self.assertEqual(iu.tag_to_version("jq-1.8.3", "jq"), "1.8.3")

    def test_bare_semver(self) -> None:
        self.assertEqual(iu.tag_to_version("1.58.1", "just"), "1.58.1")

    def test_go_tag(self) -> None:
        self.assertEqual(iu.tag_to_version("go1.26.2", "go"), "1.26.2")


class SubstVersionTests(unittest.TestCase):
    def test_jq_download_path(self) -> None:
        url = "https://github.com/jqlang/jq/releases/download/jq-1.8.2/jq-macos-arm64"
        got = iu.subst_version(url, "1.8.2", "1.8.3")
        self.assertEqual(
            got,
            "https://github.com/jqlang/jq/releases/download/jq-1.8.3/jq-macos-arm64",
        )

    def test_v_prefixed_asset(self) -> None:
        url = (
            "https://github.com/sharkdp/fd/releases/download/"
            "v10.4.2/fd-v10.4.2-aarch64-apple-darwin.tar.gz"
        )
        got = iu.subst_version(url, "10.4.2", "10.4.3")
        self.assertEqual(
            got,
            "https://github.com/sharkdp/fd/releases/download/"
            "v10.4.3/fd-v10.4.3-aarch64-apple-darwin.tar.gz",
        )

    def test_does_not_eat_longer_patch(self) -> None:
        url = (
            "https://github.com/sharkdp/fd/releases/download/"
            "v10.4.2/fd-v10.4.2-aarch64-apple-darwin.tar.gz"
        )
        got = iu.subst_version(url, "10.4.2", "10.4.20")
        self.assertIn("v10.4.20", got)
        self.assertNotIn("v10.4.200", got)

    def test_go_tarball_name(self) -> None:
        url = "https://go.dev/dl/go1.26.1.darwin-arm64.tar.gz"
        got = iu.subst_version(url, "1.26.1", "1.26.2")
        self.assertEqual(got, "https://go.dev/dl/go1.26.2.darwin-arm64.tar.gz")


class CooldownTests(unittest.TestCase):
    def test_two_days_is_too_soon(self) -> None:
        published = NOW - timedelta(days=2)
        self.assertFalse(iu.cooldown_elapsed(published, NOW))

    def test_three_days_is_enough(self) -> None:
        published = NOW - timedelta(days=3)
        self.assertTrue(iu.cooldown_elapsed(published, NOW))

    def test_four_days_is_enough(self) -> None:
        published = NOW - timedelta(days=4)
        self.assertTrue(iu.cooldown_elapsed(published, NOW))


class CandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.pkg = iu.load_package_text(JQ, Path("index/j/jq.toml"))

    def test_already_latest(self) -> None:
        rel = iu.Release(
            version="1.8.2",
            tag="jq-1.8.2",
            published_at=NOW - timedelta(days=10),
        )
        self.assertEqual(
            iu.skip_reason(self.pkg, rel, NOW, {"1.8.2"}),
            "already latest",
        )

    def test_version_already_in_index(self) -> None:
        rel = iu.Release(
            version="1.8.1",
            tag="jq-1.8.1",
            published_at=NOW - timedelta(days=10),
        )
        self.assertEqual(
            iu.skip_reason(self.pkg, rel, NOW, {"1.8.1", "1.8.2"}),
            "version exists",
        )

    def test_cooldown(self) -> None:
        rel = iu.Release(
            version="1.8.3",
            tag="jq-1.8.3",
            published_at=NOW - timedelta(days=1),
        )
        self.assertEqual(
            iu.skip_reason(self.pkg, rel, NOW, {"1.8.2"}),
            "cooldown",
        )

    def test_eligible(self) -> None:
        rel = iu.Release(
            version="1.8.3",
            tag="jq-1.8.3",
            published_at=NOW - timedelta(days=4),
        )
        self.assertIsNone(iu.skip_reason(self.pkg, rel, NOW, {"1.8.2"}))


class LoadPackageTests(unittest.TestCase):
    def test_jq_fields(self) -> None:
        pkg = iu.load_package_text(JQ, Path("index/j/jq.toml"))
        self.assertEqual(pkg.name, "jq")
        self.assertEqual(pkg.latest, "1.8.2")
        self.assertEqual(pkg.repo, "jqlang/jq")
        self.assertEqual(pkg.format, "binary")
        self.assertEqual(pkg.strip, 0)
        self.assertEqual(pkg.hash_source, "upstream-sha256sums")
        self.assertEqual(pkg.files, (("jq-macos-arm64", "bin/jq", 0o755),))
        self.assertEqual(pkg.versions, frozenset({"1.8.2"}))


class BuildCandidateTests(unittest.TestCase):
    def test_rewrites_url_and_files(self) -> None:
        pkg = iu.load_package_text(JQ, Path("index/j/jq.toml"))
        rel = iu.Release(
            version="1.8.3",
            tag="jq-1.8.3",
            published_at=NOW - timedelta(days=4),
        )
        cand = iu.build_candidate(pkg, rel)
        self.assertEqual(cand.version, "1.8.3")
        self.assertIn("jq-1.8.3", cand.url)
        self.assertEqual(cand.files, ("jq-macos-arm64:bin/jq:755",))
        self.assertEqual(cand.hash_source, "upstream-sha256sums")


class ApplyFragmentTests(unittest.TestCase):
    def test_moves_latest_and_keeps_old_block(self) -> None:
        fragment = (
            '[versions."1.8.3".artifacts."darwin/arm64"]\n'
            'url = "https://example/jq-1.8.3"\n'
            'format = "binary"\n'
            'sha256 = "ee"\n'
            'tree_digest = "sha256:from-admit"\n'
            'hash_source = "computed"\n'
            "strip = 0\n"
        )
        got = iu.apply_fragment(JQ, "1.8.3", fragment)
        self.assertNotIn('latest = "1.8.2"', got)
        self.assertIn("[versions.\"1.8.2\".artifacts.\"darwin/arm64\"]", got)
        self.assertIn("[versions.\"1.8.3\".artifacts.\"darwin/arm64\"]", got)
        self.assertIn("sha256:from-admit", got)
        self.assertNotIn("sha256:invented", got)

    def test_latest_line_is_the_new_version(self) -> None:
        fragment = '[versions."1.8.3".artifacts."darwin/arm64"]\nurl = "x"\n'
        got = iu.apply_fragment(JQ, "1.8.3", fragment)
        first = [ln for ln in got.splitlines() if ln.startswith("latest = ")]
        self.assertEqual(first, ['latest = "1.8.3"'])


class BranchTests(unittest.TestCase):
    def test_branch_name(self) -> None:
        self.assertEqual(iu.branch_name("jq", "1.8.3"), "index-update/jq-1.8.3")

    def test_push_ref_rejects_main(self) -> None:
        with self.assertRaises(ValueError):
            iu.push_ref("main")

    def test_push_ref_allows_bot_branch(self) -> None:
        self.assertEqual(
            iu.push_ref("index-update/jq-1.8.3"),
            "index-update/jq-1.8.3",
        )


class DiscoverTests(unittest.TestCase):
    def test_skips_prerelease(self) -> None:
        pkg = iu.load_package_text(JQ, Path("index/j/jq.toml"))
        releases = {
            "jqlang/jq": {
                "tag_name": "jq-1.8.3",
                "published_at": (NOW - timedelta(days=4)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "draft": False,
                "prerelease": True,
            }
        }
        cands, skips = iu.discover_packages(
            [pkg], NOW, github=lambda repo: releases[repo]
        )
        self.assertEqual(cands, [])
        self.assertEqual(skips[0][1], "prerelease")

    def test_emits_eligible_candidate(self) -> None:
        pkg = iu.load_package_text(JQ, Path("index/j/jq.toml"))
        releases = {
            "jqlang/jq": {
                "tag_name": "jq-1.8.3",
                "published_at": (NOW - timedelta(days=4)).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                ),
                "draft": False,
                "prerelease": False,
            }
        }
        cands, skips = iu.discover_packages(
            [pkg], NOW, github=lambda repo: releases[repo]
        )
        self.assertEqual(skips, [])
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].version, "1.8.3")

    def test_go_stable_from_json(self) -> None:
        go = """\
[package]
name = "go"
description = "Go"
license = "BSD-3-Clause"
homepage = "https://go.dev"
repo = "golang/go"
latest = "1.26.1"

[versions."1.26.1".artifacts."darwin/arm64"]
url = "https://go.dev/dl/go1.26.1.darwin-arm64.tar.gz"
format = "tar.gz"
sha256 = "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff"
tree_digest = "sha256:gg"
hash_source = "upstream-sha256sums"
strip = 1

[[versions."1.26.1".artifacts."darwin/arm64".files]]
src = "bin"
dest = "bin"
mode = 0o755
"""
        pkg = iu.load_package_text(go, Path("index/g/go.toml"))
        listings = [
            {
                "version": "go1.26.2",
                "stable": True,
                "files": [
                    {
                        "filename": "go1.26.2.darwin-arm64.tar.gz",
                        "os": "darwin",
                        "arch": "arm64",
                        "sha256": "ab" * 32,
                        "kind": "archive",
                    }
                ],
            }
        ]
        rel = iu.go_release(
            listings, NOW - timedelta(days=4)
        )
        self.assertEqual(rel.version, "1.26.2")
        self.assertIsNone(iu.skip_reason(pkg, rel, NOW, {"1.26.1"}))


class AdmitLoopTests(unittest.TestCase):
    def test_continues_after_one_failure(self) -> None:
        jq = iu.load_package_text(JQ, Path("index/j/jq.toml"))
        fd = iu.load_package_text(FD, Path("index/f/fd.toml"))
        cands = [
            iu.build_candidate(
                jq,
                iu.Release("1.8.3", "jq-1.8.3", NOW - timedelta(days=4)),
            ),
            iu.build_candidate(
                fd,
                iu.Release("10.4.3", "v10.4.3", NOW - timedelta(days=4)),
            ),
        ]

        def run_admit(argv: list[str]) -> SimpleNamespace:
            name = argv[argv.index("--name") + 1]
            if name == "jq":
                return SimpleNamespace(returncode=1, stdout="", stderr="boom\n")
            return SimpleNamespace(
                returncode=0,
                stdout='[versions."10.4.3".artifacts."darwin/arm64"]\nurl = "x"\n',
                stderr="",
            )

        out = Path(self.id().replace(".", "_"))
        # use tmp via TemporaryDirectory in the helper
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = iu.admit_candidates(
                cands,
                gale="gale",
                out=root / "out",
                work=root / "work",
                download=lambda cand, dest: dest.write_bytes(b"ok"),
                run_admit=run_admit,
            )
            self.assertEqual(result.ok, ["fd"])
            self.assertEqual(result.failed, ["jq"])
            self.assertTrue((root / "out" / "fd.fragment.toml").is_file())
            self.assertTrue((root / "out" / "jq.failed.txt").is_file())
            frag = (root / "out" / "fd.fragment.toml").read_text()
            self.assertIn("10.4.3", frag)
            self.assertNotIn("tree_digest = \"sha256:invented\"", frag)


class CandidateJsonTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        pkg = iu.load_package_text(JQ, Path("index/j/jq.toml"))
        cand = iu.build_candidate(
            pkg,
            iu.Release("1.8.3", "jq-1.8.3", NOW - timedelta(days=4)),
        )
        blob = json.dumps(iu.candidate_to_json(cand))
        got = iu.candidate_from_json(json.loads(blob), pkg)
        self.assertEqual(got.version, cand.version)
        self.assertEqual(got.url, cand.url)


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = (
            Path(__file__).resolve().parent.parent
            / ".github" / "workflows" / "index-update.yml"
        ).read_text()

    def test_workflow_exists(self) -> None:
        self.assertIn("Index Update", self.text)

    def test_does_not_push_main(self) -> None:
        self.assertNotIn("git push origin main", self.text)
        self.assertNotIn('git push -u origin main', self.text)
        self.assertIn("iu.push_ref", self.text)
        self.assertIn('git push -u origin "$branch"', self.text)

    def test_no_farm_token_on_fetch(self) -> None:
        self.assertNotIn("GALE_GITHUB_TOKEN", self.text)

    def test_not_the_farm_job(self) -> None:
        self.assertNotIn("auto-update.yml", self.text)
        self.assertNotIn("auto-update.sh", self.text)

    def test_three_day_lag_is_named(self) -> None:
        self.assertIn("3-day", self.text)


if __name__ == "__main__":
    unittest.main()
