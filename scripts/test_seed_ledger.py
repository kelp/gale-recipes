#!/usr/bin/env python3
"""Tests for seed_ledger.py — the maintainer-run backfill tool.

Network and oras are injected: a fake ``http_get`` serves the
GHCR token + legacy bare-tag manifests, and a recording runner
stands in for ``oras tag``. The history-emit function is
shared with scripts/write_binaries.py (the CI ledger writer);
these tests inject a minimal stand-in module so the plumbing
is testable on trees where the writer has not landed yet.
"""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

import check_registry_coherence as crc
import seed_ledger

SHA_A = "a" * 64
SHA_B = "b" * 64
GHCR_REPO = "kelp/gale-recipes"


def manifest_body(layer_sha: str) -> bytes:
    return json.dumps(
        {
            "schemaVersion": 2,
            "layers": [{"digest": f"sha256:{layer_sha}"}],
        }
    ).encode()


def digest_of(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class FakeHTTP:
    def __init__(self) -> None:
        self.routes: dict[str, tuple[int, dict, bytes]] = {}
        self.calls: list[str] = []

    def add_token(self, name: str) -> None:
        url = (
            "https://ghcr.io/token?service=ghcr.io"
            f"&scope=repository:{GHCR_REPO}/{name}:pull"
        )
        self.routes[url] = (
            200,
            {},
            json.dumps({"token": "tok"}).encode(),
        )

    def add_manifest(
        self,
        name: str,
        tag: str,
        status: int,
        body: bytes = b"",
        header_digest: str | None = None,
    ) -> None:
        url = f"https://ghcr.io/v2/{GHCR_REPO}/{name}/manifests/{tag}"
        headers = {}
        if header_digest is not None:
            headers["Docker-Content-Digest"] = header_digest
        self.routes[url] = (status, headers, body)

    def __call__(self, url: str, headers: dict) -> tuple:
        self.calls.append(url)
        if url not in self.routes:
            raise AssertionError(f"unexpected URL: {url}")
        return self.routes[url]


class RecordingRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def __call__(self, cmd: list[str]) -> None:
        self.commands.append(cmd)


def stub_writer_module() -> types.ModuleType:
    """Minimal stand-in for scripts/write_binaries.py exposing
    the shared emit function seed_ledger imports."""
    mod = types.ModuleType("write_binaries")

    def render_history_entry(full_version, entries):
        parts = ["[[history]]\n", f'version = "{full_version}"\n']
        for platform in sorted(entries):
            e = entries[platform]
            parts.append(
                f'{platform} = {{ sha256 = "{e["sha256"]}", '
                f'manifest_digest = "{e["manifest_digest"]}" }}\n'
            )
        return "".join(parts)

    mod.render_history_entry = render_history_entry
    return mod


class SeedCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.http = FakeHTTP()
        self.runner = RecordingRunner()
        self._old_sleep = crc._sleep
        crc._sleep = lambda _s: None
        self.addCleanup(
            lambda: setattr(crc, "_sleep", self._old_sleep)
        )

    def write_recipe(
        self, name: str, version: str, revision: int | None = None
    ) -> None:
        lines = [
            "[package]",
            f'name = "{name}"',
            f'version = "{version}"',
        ]
        if revision is not None:
            lines.append(f"revision = {revision}")
        lines += ["", "[build]", 'steps = ["true"]']
        path = self.root / "recipes" / name[0] / f"{name}.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines) + "\n")

    def write_binaries(
        self,
        name: str,
        mirror_version: str,
        platforms: dict[str, str],
    ) -> Path:
        parts = [f'version = "{mirror_version}"\n']
        for platform, sha in sorted(platforms.items()):
            parts.append(f"\n[{platform}]\n")
            parts.append(f'sha256 = "{sha}"\n')
        path = (
            self.root / "recipes" / name[0] / f"{name}.binaries.toml"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(parts))
        return path

    def seed(self, dry_run: bool) -> dict:
        return seed_ledger.seed(
            self.root,
            GHCR_REPO,
            http_get=self.http,
            runner=self.runner,
            dry_run=dry_run,
        )

    def test_healthy_dry_run_reports_without_writing(self) -> None:
        self.write_recipe("testpkg", "1.0.0")
        path = self.write_binaries(
            "testpkg", "1.0.0", {"linux-amd64": SHA_A}
        )
        before = path.read_text()
        body = manifest_body(SHA_A)
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-linux-amd64", 200, body, digest_of(body)
        )
        result = self.seed(dry_run=True)
        self.assertEqual(result["seeded"], ["testpkg"])
        self.assertEqual(result["republish"], [])
        self.assertEqual(self.runner.commands, [])
        self.assertEqual(path.read_text(), before)

    def test_mismatch_goes_to_republish(self) -> None:
        self.write_recipe("testpkg", "1.0.0")
        path = self.write_binaries(
            "testpkg", "1.0.0", {"linux-amd64": SHA_A}
        )
        before = path.read_text()
        body = manifest_body(SHA_B)  # registry has other bytes
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-linux-amd64", 200, body, digest_of(body)
        )
        result = self.seed(dry_run=True)
        self.assertEqual(result["seeded"], [])
        self.assertEqual(result["republish"], ["testpkg"])
        self.assertEqual(path.read_text(), before)

    def test_404_goes_to_republish(self) -> None:
        self.write_recipe("testpkg", "1.0.0")
        self.write_binaries(
            "testpkg", "1.0.0", {"linux-amd64": SHA_A}
        )
        self.http.add_token("testpkg")
        self.http.add_manifest("testpkg", "1.0.0-linux-amd64", 404)
        result = self.seed(dry_run=True)
        self.assertEqual(result["republish"], ["testpkg"])

    def test_partial_health_goes_to_republish(self) -> None:
        """One healthy platform + one mismatched: seeding
        requires EVERY mirror platform healthy."""
        self.write_recipe("testpkg", "1.0.0")
        self.write_binaries(
            "testpkg",
            "1.0.0",
            {"linux-amd64": SHA_A, "darwin-arm64": SHA_B},
        )
        good = manifest_body(SHA_A)
        bad = manifest_body(SHA_A)  # serves SHA_A, mirror says SHA_B
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-linux-amd64", 200, good, digest_of(good)
        )
        self.http.add_manifest(
            "testpkg", "1.0.0-darwin-arm64", 200, bad, digest_of(bad)
        )
        result = self.seed(dry_run=True)
        self.assertEqual(result["seeded"], [])
        self.assertEqual(result["republish"], ["testpkg"])

    def test_mirror_drift_goes_to_republish(self) -> None:
        """Recipe version moved ahead of the mirror: the mirror
        digests describe an older version, so seeding under the
        recipe's (version, revision) would lie."""
        self.write_recipe("testpkg", "2.0.0")
        self.write_binaries(
            "testpkg", "1.0.0", {"linux-amd64": SHA_A}
        )
        result = self.seed(dry_run=True)
        self.assertEqual(result["seeded"], [])
        self.assertEqual(result["republish"], ["testpkg"])
        self.assertEqual(self.http.calls, [])

    def test_5xx_exhausted_is_error_not_republish(self) -> None:
        self.write_recipe("testpkg", "1.0.0")
        self.write_binaries(
            "testpkg", "1.0.0", {"linux-amd64": SHA_A}
        )
        self.http.add_token("testpkg")
        self.http.add_manifest("testpkg", "1.0.0-linux-amd64", 503)
        result = self.seed(dry_run=True)
        self.assertEqual(result["seeded"], [])
        self.assertEqual(result["republish"], [])
        self.assertEqual(len(result["errors"]), 1)

    def test_seed_tags_and_appends_history(self) -> None:
        """Non-dry-run: oras-tags the manifest under the
        immutable revisioned tag and appends one [[history]]
        block, leaving the mirror bytes untouched."""
        self.write_recipe("testpkg", "1.0.0", revision=2)
        path = self.write_binaries(
            "testpkg", "1.0.0-2", {"linux-amd64": SHA_A}
        )
        before = path.read_text()
        body = manifest_body(SHA_A)
        md = digest_of(body)
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-linux-amd64", 200, body, md
        )
        sys.modules["write_binaries"] = stub_writer_module()
        self.addCleanup(
            lambda: sys.modules.pop("write_binaries", None)
        )
        result = self.seed(dry_run=False)
        self.assertEqual(result["seeded"], ["testpkg"])
        self.assertEqual(
            self.runner.commands,
            [
                [
                    "oras",
                    "tag",
                    f"ghcr.io/{GHCR_REPO}/testpkg@{md}",
                    "1.0.0-2-linux-amd64",
                ]
            ],
        )
        after = path.read_text()
        self.assertTrue(after.startswith(before))
        self.assertIn("[[history]]", after)
        self.assertIn('version = "1.0.0-2"', after)
        self.assertIn(md, after)

    def test_recipe_filter_limits_scope(self) -> None:
        """--recipe spot-checks named recipes only; nothing
        else is probed."""
        self.write_recipe("testpkg", "1.0.0")
        self.write_binaries(
            "testpkg", "1.0.0", {"linux-amd64": SHA_A}
        )
        self.write_recipe("otherpkg", "2.0.0")
        self.write_binaries(
            "otherpkg", "2.0.0", {"linux-amd64": SHA_B}
        )
        body = manifest_body(SHA_A)
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-linux-amd64", 200, body, digest_of(body)
        )
        result = seed_ledger.seed(
            self.root,
            GHCR_REPO,
            http_get=self.http,
            runner=self.runner,
            dry_run=True,
            only={"testpkg"},
        )
        self.assertEqual(result["seeded"], ["testpkg"])
        self.assertEqual(result["republish"], [])
        self.assertTrue(
            all("otherpkg" not in url for url in self.http.calls)
        )

    def test_already_seeded_is_idempotent(self) -> None:
        self.write_recipe("testpkg", "1.0.0")
        path = (
            self.root / "recipes" / "t" / "testpkg.binaries.toml"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        md = "sha256:" + "d" * 64
        path.write_text(
            f'version = "1.0.0"\n\n[linux-amd64]\n'
            f'sha256 = "{SHA_A}"\n\n[[history]]\n'
            f'version = "1.0.0-1"\n'
            f"linux-amd64 = {{ sha256 = \"{SHA_A}\", "
            f'manifest_digest = "{md}" }}\n'
        )
        before = path.read_text()
        result = self.seed(dry_run=False)
        self.assertEqual(result["seeded"], [])
        self.assertEqual(result["already"], ["testpkg"])
        self.assertEqual(self.http.calls, [])
        self.assertEqual(self.runner.commands, [])
        self.assertEqual(path.read_text(), before)


if __name__ == "__main__":
    unittest.main()
