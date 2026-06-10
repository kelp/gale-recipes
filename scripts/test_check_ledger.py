#!/usr/bin/env python3
"""Tests for check_ledger.py — the required PR gate.

Each test builds a throwaway git repo: a base commit holding
the pre-PR state, then one or more commits representing the
PR head. check_ledger.py runs as a subprocess with
``--base <base-sha>`` exactly as the Ledger Check workflow
invokes it, so the git plumbing (merge-base, git show) is
exercised for real.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "check_ledger.py"

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
MD_A = "sha256:" + "1" * 64
MD_B = "sha256:" + "2" * 64
MD_C = "sha256:" + "3" * 64

PLATFORMS = ["darwin-arm64", "linux-amd64", "linux-arm64"]

PLATFORMS_JSON = """\
[
  { "os": "macos-26", "platform": "darwin-arm64" },
  { "os": "ubuntu-latest", "platform": "linux-amd64" },
  { "os": "ubuntu-24.04-arm", "platform": "linux-arm64" }
]
"""


def recipe_text(
    version: str, revision: int | None = None,
    platforms: list[str] | None = None,
) -> str:
    lines = ['[package]', 'name = "testpkg"', f'version = "{version}"']
    if revision is not None:
        lines.append(f"revision = {revision}")
    if platforms is not None:
        plist = ", ".join(f'"{p}"' for p in platforms)
        lines.append(f"platforms = [{plist}]")
    lines += [
        "",
        "[source]",
        'url = "https://example.invalid/src.tar.gz"',
        f'sha256 = "{SHA_A}"',
        "",
        "[build]",
        'steps = ["true"]',
    ]
    return "\n".join(lines) + "\n"


def binaries_text(
    mirror_version: str,
    mirror: dict[str, tuple[str, str]],
    history: list[tuple[str, dict[str, tuple[str, str]]]],
) -> str:
    """Render a .binaries.toml in the CI writer's shape: head
    mirror first, [[history]] blocks appended."""
    parts = [f'version = "{mirror_version}"\n']
    for platform in sorted(mirror):
        sha, md = mirror[platform]
        parts.append(f"\n[{platform}]\n")
        parts.append(f'sha256 = "{sha}"\n')
        parts.append(f'manifest_digest = "{md}"\n')
    for entry_version, entries in history:
        parts.append("\n[[history]]\n")
        parts.append(f'version = "{entry_version}"\n')
        for platform in sorted(entries):
            sha, md = entries[platform]
            parts.append(
                f'{platform} = {{ sha256 = "{sha}", '
                f'manifest_digest = "{md}" }}\n'
            )
    return "".join(parts)


def all_platform_digests(
    sha: str = SHA_A, md: str = MD_A
) -> dict[str, tuple[str, str]]:
    return {p: (sha, md) for p in PLATFORMS}


class RepoCase(unittest.TestCase):
    """Base: temp git repo with platforms.json committed."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.write(".github/platforms.json", PLATFORMS_JSON)

    def git(self, *args: str) -> str:
        out = subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin:/usr/local/bin",
                "HOME": str(self.repo),
                "GIT_CONFIG_NOSYSTEM": "1",
            },
        )
        self.assertEqual(
            out.returncode, 0, f"git {args}: {out.stderr}"
        )
        return out.stdout.strip()

    def write(self, rel: str, content: str) -> None:
        path = self.repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def delete(self, rel: str) -> None:
        (self.repo / rel).unlink()

    def commit(self, msg: str) -> str:
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        return self.git("rev-parse", "HEAD")

    def run_check(self, base: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--base", base],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    # -- common fixture -------------------------------------

    def seed_published_v1(self) -> str:
        """Base state: testpkg 1.0.0 rev 1, fully published
        (mirror + history in agreement). Returns base SHA."""
        self.write("recipes/t/testpkg.toml", recipe_text("1.0.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.0.0",
                all_platform_digests(),
                [("1.0.0-1", all_platform_digests())],
            ),
        )
        return self.commit("base: testpkg 1.0.0 published")


class VersionBumpTests(RepoCase):
    def test_bump_without_history_entry_fails(self) -> None:
        base = self.seed_published_v1()
        self.write("recipes/t/testpkg.toml", recipe_text("1.1.0"))
        self.commit("bump without ledger")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1, res.stdout + res.stderr)
        combined = res.stdout + res.stderr
        self.assertIn("testpkg", combined)
        self.assertIn("1.1.0-1", combined)
        self.assertIn(
            "promote has not published this version yet", combined
        )

    def test_bump_with_complete_entry_passes(self) -> None:
        base = self.seed_published_v1()
        self.write("recipes/t/testpkg.toml", recipe_text("1.1.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.1.0",
                all_platform_digests(SHA_B, MD_B),
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.1.0-1", all_platform_digests(SHA_B, MD_B)),
                ],
            ),
        )
        self.commit("bump to 1.1.0 + ledger")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertIn("testpkg", res.stdout)

    def test_entry_missing_one_platform_fails(self) -> None:
        base = self.seed_published_v1()
        incomplete = all_platform_digests(SHA_B, MD_B)
        del incomplete["linux-arm64"]
        mirror = dict(incomplete)
        self.write("recipes/t/testpkg.toml", recipe_text("1.1.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.1.0",
                mirror,
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.1.0-1", incomplete),
                ],
            ),
        )
        self.commit("bump missing linux-arm64")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("linux-arm64", res.stdout + res.stderr)

    def test_platform_restricted_recipe_passes(self) -> None:
        """A recipe declaring [package].platforms only needs
        ledger coverage for the declared intersection."""
        base = self.seed_published_v1()
        only = {"darwin-arm64": (SHA_B, MD_B)}
        self.write(
            "recipes/t/testpkg.toml",
            recipe_text("1.1.0", platforms=["darwin-arm64"]),
        )
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.1.0",
                only,
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.1.0-1", only),
                ],
            ),
        )
        self.commit("darwin-only bump")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_mirror_history_digest_mismatch_fails(self) -> None:
        base = self.seed_published_v1()
        self.write("recipes/t/testpkg.toml", recipe_text("1.1.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.1.0",
                all_platform_digests(SHA_C, MD_B),  # mirror differs
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.1.0-1", all_platform_digests(SHA_B, MD_B)),
                ],
            ),
        )
        self.commit("mirror disagrees with ledger")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("mirror", (res.stdout + res.stderr).lower())

    def test_missing_binaries_file_fails(self) -> None:
        self.write("recipes/t/testpkg.toml", recipe_text("1.0.0"))
        base = self.commit("recipe without binaries")
        self.write("recipes/t/testpkg.toml", recipe_text("1.1.0"))
        self.commit("bump, still no binaries")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn(
            "promote has not published this version yet",
            res.stdout + res.stderr,
        )

    def test_new_recipe_requires_ledger(self) -> None:
        self.write("recipes/o/other.toml", recipe_text("0.1.0"))
        base = self.commit("unrelated base")
        self.write("recipes/t/testpkg.toml", recipe_text("2.0.0"))
        self.commit("new recipe, no binaries yet")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)

    def test_new_recipe_with_ledger_passes(self) -> None:
        self.write("recipes/o/other.toml", recipe_text("0.1.0"))
        base = self.commit("unrelated base")
        self.write("recipes/t/testpkg.toml", recipe_text("2.0.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "2.0.0",
                all_platform_digests(),
                [("2.0.0-1", all_platform_digests())],
            ),
        )
        self.commit("new recipe, published")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


class MirrorVersionStringTests(RepoCase):
    """The mirror's top-level version string is load-bearing:
    bare for revision <= 1, exact <version>-<revision>
    otherwise (gale's binaryIndexMatchesRecipe)."""

    def test_revision_2_requires_exact_mirror_string(self) -> None:
        base = self.seed_published_v1()
        self.write(
            "recipes/t/testpkg.toml", recipe_text("1.0.0", revision=2)
        )
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.0.0-2",
                all_platform_digests(SHA_B, MD_B),
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.0.0-2", all_platform_digests(SHA_B, MD_B)),
                ],
            ),
        )
        self.commit("revision bump")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_revision_2_with_bare_mirror_fails(self) -> None:
        base = self.seed_published_v1()
        self.write(
            "recipes/t/testpkg.toml", recipe_text("1.0.0", revision=2)
        )
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.0.0",  # must be "1.0.0-2"
                all_platform_digests(SHA_B, MD_B),
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.0.0-2", all_platform_digests(SHA_B, MD_B)),
                ],
            ),
        )
        self.commit("revision bump, wrong mirror string")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("1.0.0-2", res.stdout + res.stderr)

    def test_revision_1_with_suffixed_mirror_fails(self) -> None:
        self.write("recipes/o/other.toml", recipe_text("0.1.0"))
        base = self.commit("base")
        self.write("recipes/t/testpkg.toml", recipe_text("1.0.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.0.0-1",  # must be bare "1.0.0"
                all_platform_digests(),
                [("1.0.0-1", all_platform_digests())],
            ),
        )
        self.commit("rev-1 with suffixed mirror")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)

    def test_malformed_digests_fail(self) -> None:
        base = self.seed_published_v1()
        bad = {p: ("nothex", "sha256:short") for p in PLATFORMS}
        self.write("recipes/t/testpkg.toml", recipe_text("1.1.0"))
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.1.0",
                bad,
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("1.1.0-1", bad),
                ],
            ),
        )
        self.commit("malformed digests")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)


class AppendOnlyTests(RepoCase):
    def test_history_rewrite_fails(self) -> None:
        base = self.seed_published_v1()
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.0.0",
                all_platform_digests(),
                [("1.0.0-1", all_platform_digests(SHA_C, MD_C))],
            ),
        )
        self.commit("rewrite published digests")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("history is append-only", res.stdout + res.stderr)

    def test_history_entry_deletion_fails(self) -> None:
        base = self.seed_published_v1()
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text("1.0.0", all_platform_digests(), []),
        )
        self.commit("drop the ledger")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("history is append-only", res.stdout + res.stderr)

    def test_binaries_only_append_passes(self) -> None:
        """The seed-PR shape: .binaries.toml gains history
        entries, recipe untouched."""
        base = self.seed_published_v1()
        self.write(
            "recipes/t/testpkg.binaries.toml",
            binaries_text(
                "1.0.0",
                all_platform_digests(),
                [
                    ("1.0.0-1", all_platform_digests()),
                    ("0.9.0-1", all_platform_digests(SHA_B, MD_B)),
                ],
            ),
        )
        self.commit("seed backfill append")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_binaries_file_deletion_with_history_fails(self) -> None:
        base = self.seed_published_v1()
        self.delete("recipes/t/testpkg.binaries.toml")
        self.delete("recipes/t/testpkg.toml")
        self.commit("remove recipe and ledger")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 1)
        self.assertIn("history is append-only", res.stdout + res.stderr)


class TrivialPassTests(RepoCase):
    def test_no_recipe_changes_passes(self) -> None:
        base = self.seed_published_v1()
        self.write("docs/note.md", "irrelevant\n")
        self.commit("docs only")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_non_version_recipe_edit_passes(self) -> None:
        """Editing build steps without touching (version,
        revision) requires no ledger entry."""
        base = self.seed_published_v1()
        text = recipe_text("1.0.0").replace(
            'steps = ["true"]', 'steps = ["true", "true"]'
        )
        self.write("recipes/t/testpkg.toml", text)
        self.commit("steps tweak, same version")
        res = self.run_check(base)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)


if __name__ == "__main__":
    unittest.main()
