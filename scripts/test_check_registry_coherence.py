#!/usr/bin/env python3
"""Tests for check_registry_coherence.py — the daily audit of
ledgered history entries against GHCR's revisioned tags.

The HTTP layer is injected: a fake ``http_get`` serves the
token endpoint and per-tag manifest responses from a dict, so
the 200-match / 200-mismatch / 404 / 5xx-retry-exhausted paths
run without any network.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import check_registry_coherence as crc

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
    """Maps URL -> (status, headers, body); records calls."""

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


def write_binaries(
    root: Path,
    name: str,
    history: list[tuple[str, dict[str, tuple[str, str]]]],
) -> None:
    parts = ['version = "1.0.0"\n']
    for entry_version, platforms in history:
        parts.append("\n[[history]]\n")
        parts.append(f'version = "{entry_version}"\n')
        for platform, (sha, md) in sorted(platforms.items()):
            parts.append(
                f'{platform} = {{ sha256 = "{sha}", '
                f'manifest_digest = "{md}" }}\n'
            )
    path = root / "recipes" / name[0] / f"{name}.binaries.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(parts))


class CoherenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        (self.root / "recipes").mkdir()
        self.http = FakeHTTP()
        # Audit retries must not sleep for real in tests.
        self._old_sleep = crc._sleep
        crc._sleep = lambda _s: None
        self.addCleanup(
            lambda: setattr(crc, "_sleep", self._old_sleep)
        )

    def audit(self):
        return crc.audit(self.root, GHCR_REPO, http_get=self.http)

    def test_matching_entry_passes(self) -> None:
        body = manifest_body(SHA_A)
        md = digest_of(body)
        write_binaries(
            self.root,
            "testpkg",
            [("1.0.0-1", {"linux-amd64": (SHA_A, md)})],
        )
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-1-linux-amd64", 200, body, md
        )
        failures, audited, skipped = self.audit()
        self.assertEqual(failures, [])
        self.assertEqual(audited, 1)
        self.assertEqual(skipped, 0)

    def test_layer_digest_mismatch_is_immutable_tag_conflict(
        self,
    ) -> None:
        body = manifest_body(SHA_B)  # registry serves other bytes
        md = digest_of(body)
        write_binaries(
            self.root,
            "testpkg",
            [("1.0.0-1", {"linux-amd64": (SHA_A, md)})],
        )
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-1-linux-amd64", 200, body, md
        )
        failures, _, _ = self.audit()
        self.assertEqual(len(failures), 1)
        self.assertIn("immutable tag conflict", failures[0])
        self.assertIn("bump revision to republish", failures[0])
        self.assertIn("testpkg:1.0.0-1-linux-amd64", failures[0])

    def test_manifest_digest_mismatch_is_immutable_tag_conflict(
        self,
    ) -> None:
        body = manifest_body(SHA_A)
        served_md = digest_of(body)
        ledgered_md = "sha256:" + "f" * 64
        write_binaries(
            self.root,
            "testpkg",
            [("1.0.0-1", {"linux-amd64": (SHA_A, ledgered_md)})],
        )
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-1-linux-amd64", 200, body, served_md
        )
        failures, _, _ = self.audit()
        self.assertEqual(len(failures), 1)
        self.assertIn("immutable tag conflict", failures[0])

    def test_404_is_anchor_lost(self) -> None:
        write_binaries(
            self.root,
            "testpkg",
            [
                (
                    "1.0.0-1",
                    {"linux-amd64": (SHA_A, "sha256:" + "d" * 64)},
                )
            ],
        )
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-1-linux-amd64", 404
        )
        failures, _, _ = self.audit()
        self.assertEqual(len(failures), 1)
        self.assertIn("anchor lost", failures[0])
        self.assertIn("no longer exists", failures[0])

    def test_5xx_retries_then_fails_never_absent(self) -> None:
        write_binaries(
            self.root,
            "testpkg",
            [
                (
                    "1.0.0-1",
                    {"linux-amd64": (SHA_A, "sha256:" + "d" * 64)},
                )
            ],
        )
        self.http.add_token("testpkg")
        self.http.add_manifest(
            "testpkg", "1.0.0-1-linux-amd64", 503
        )
        failures, _, _ = self.audit()
        self.assertEqual(len(failures), 1)
        self.assertNotIn("anchor lost", failures[0])
        self.assertIn("audit error", failures[0])
        manifest_calls = [
            c for c in self.http.calls if "/manifests/" in c
        ]
        self.assertEqual(len(manifest_calls), crc.ATTEMPTS)

    def test_no_history_is_skipped_and_counted(self) -> None:
        path = self.root / "recipes" / "t" / "testpkg.binaries.toml"
        path.parent.mkdir(parents=True)
        path.write_text(
            'version = "1.0.0"\n\n[linux-amd64]\n'
            f'sha256 = "{SHA_A}"\n'
        )
        failures, audited, skipped = self.audit()
        self.assertEqual(failures, [])
        self.assertEqual(audited, 0)
        self.assertEqual(skipped, 1)
        self.assertEqual(self.http.calls, [])

    def test_malformed_ledgered_digest_fails(self) -> None:
        write_binaries(
            self.root,
            "testpkg",
            [("1.0.0-1", {"linux-amd64": ("nothex", "sha256:bad")})],
        )
        failures, _, _ = self.audit()
        self.assertEqual(len(failures), 1)
        self.assertEqual(self.http.calls, [])


if __name__ == "__main__":
    unittest.main()
