"""Tests for write_binaries.py.

The writer produces each recipe's `.binaries.toml`: a head
mirror that deployed gale v0.16.5 clients parse (top-level
``version`` plus flat ``[<platform>]`` tables) and an
append-only ``[[history]]`` ledger that v0.16.5 provably
ignores (BurntSushi arrays-of-tables are skipped by
ParseBinaryIndex). The mirror's version-string exactness is
load-bearing — gale's binaryIndexMatchesRecipe accepts the
bare version only for revision <= 1 — so the format rules
here are pinned byte-for-byte.

Run with: ``python3 -m unittest scripts.test_write_binaries``
"""

from __future__ import annotations

import io
import json
import sys
import tomllib
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import write_binaries as wb  # noqa: E402


MATRIX = [
    {"os": "macos-26", "platform": "darwin-arm64"},
    {"os": "ubuntu-latest", "platform": "linux-amd64"},
    {"os": "ubuntu-24.04-arm", "platform": "linux-arm64"},
]

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
DIG_A = "sha256:" + "1" * 64
DIG_B = "sha256:" + "2" * 64
DIG_C = "sha256:" + "3" * 64
COMMIT = "1234567890abcdef1234567890abcdef12345678"


def make_repo(tmp: Path) -> Path:
    repo = tmp / "repo"
    (repo / ".github").mkdir(parents=True)
    (repo / ".github" / "platforms.json").write_text(
        json.dumps(MATRIX)
    )
    (repo / "recipes").mkdir()
    return repo


def make_recipe(
    repo: Path,
    name: str,
    version: str,
    revision: int | None = None,
    platforms: list[str] | None = None,
) -> Path:
    letter = name[0]
    d = repo / "recipes" / letter
    d.mkdir(parents=True, exist_ok=True)
    lines = [
        "[package]",
        f'name = "{name}"',
        f'version = "{version}"',
    ]
    if revision is not None:
        lines.append(f"revision = {revision}")
    if platforms is not None:
        lines.append(
            "platforms = ["
            + ", ".join(f'"{p}"' for p in platforms)
            + "]"
        )
    path = d / f"{name}.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def make_meta(
    metadir: Path,
    recipe: str,
    platform: str,
    sha256: str,
    manifest_digest: str | None,
    deps: list[dict] | None = None,
    omit_digest: bool = False,
) -> Path:
    metadir.mkdir(parents=True, exist_ok=True)
    doc: dict = {
        "recipe": recipe,
        "platform": platform,
        "sha256": sha256,
        "deps": deps or [],
    }
    if not omit_digest:
        doc["manifest_digest"] = manifest_digest
    path = metadir / f"{recipe}-{platform}.json"
    path.write_text(json.dumps(doc))
    return path


def binaries_path(repo: Path, name: str) -> Path:
    return repo / "recipes" / name[0] / f"{name}.binaries.toml"


def run_main(
    repo: Path, metadir: Path, commit: str | None = None
) -> tuple[int, str, str]:
    argv = [
        "--metadata-dir",
        str(metadir),
        "--repo-root",
        str(repo),
    ]
    if commit is not None:
        argv += ["--commit", commit]
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = wb.main(argv)
    return rc, out.getvalue(), err.getvalue()


def entries_from(
    shas: dict[str, tuple[str, str]],
) -> dict[str, dict]:
    """Shape the (platform -> (sha, digest)) test fixtures into
    the entry dicts render_history_entry/build_output consume."""
    return {
        p: {"sha256": sha, "manifest_digest": dig}
        for p, (sha, dig) in shas.items()
    }


def full_build(
    repo: Path,
    metadir: Path,
    name: str,
    shas: dict[str, tuple[str, str]],
) -> None:
    """Write one metadata JSON per (platform -> (sha, digest))."""
    for platform, (sha, dig) in shas.items():
        make_meta(metadir, name, platform, sha, dig)


THREE = {
    "darwin-arm64": (SHA_A, DIG_A),
    "linux-amd64": (SHA_B, DIG_B),
    "linux-arm64": (SHA_C, DIG_C),
}


class MirrorVersionTests(unittest.TestCase):
    """Revision 1 mirrors the bare version; revision >= 2
    mirrors the exact <version>-<revision> string. A wrong
    string silently source-builds the catalog."""

    def test_rev1_mirror_is_bare_version(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            text = binaries_path(repo, "jq").read_text()
            self.assertIn('version = "1.8.1"\n', text)
            self.assertNotIn('version = "1.8.1-1"\n', text.split("[[history]]")[0])

    def test_rev2_mirror_is_exact_full_version(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1", revision=2)
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            text = binaries_path(repo, "jq").read_text()
            self.assertTrue(text.startswith('version = "1.8.1-2"\n'))

    def test_history_key_is_always_full_form(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")  # revision 1
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            doc = tomllib.loads(binaries_path(repo, "jq").read_text())
            self.assertEqual(len(doc["history"]), 1)
            self.assertEqual(doc["history"][0]["version"], "1.8.1-1")


class FreshFileTests(unittest.TestCase):
    def test_fresh_file_mirror_and_ledger(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            doc = tomllib.loads(binaries_path(repo, "jq").read_text())
            self.assertEqual(doc["version"], "1.8.1")
            for platform, (sha, dig) in THREE.items():
                self.assertEqual(doc[platform]["sha256"], sha)
                self.assertEqual(doc[platform]["manifest_digest"], dig)
                self.assertEqual(
                    doc["history"][0][platform],
                    {"sha256": sha, "manifest_digest": dig},
                )

    def test_empty_deps_omitted(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            self.assertNotIn(
                "deps", binaries_path(repo, "jq").read_text()
            )


class HistoryPreservationTests(unittest.TestCase):
    def test_prior_history_preserved_verbatim(self) -> None:
        # Comments and irregular whitespace inside the history
        # region must survive byte-identical: the writer splices
        # text, it never reformats the ledger.
        prior_history = (
            "[[history]]\n"
            'version = "1.8.0-1"\n'
            "# adopted from registry after darwin rebuild\n"
            "darwin-arm64 = { sha256 = \"%s\", manifest_digest = \"%s\" }\n"
            "\n"
            "linux-amd64 = { sha256 = \"%s\", manifest_digest = \"%s\" }\n"
            "linux-arm64 = { sha256 = \"%s\", manifest_digest = \"%s\" }\n"
        ) % (SHA_A, DIG_A, SHA_B, DIG_B, SHA_C, DIG_C)
        existing = (
            'version = "1.8.0"\n'
            "\n"
            "[darwin-arm64]\n"
            f'sha256 = "{SHA_A}"\n'
            "\n"
            "[linux-amd64]\n"
            f'sha256 = "{SHA_B}"\n'
            "\n"
            "[linux-arm64]\n"
            f'sha256 = "{SHA_C}"\n'
            "\n" + prior_history
        )
        new = {
            "darwin-arm64": ("d" * 64, "sha256:" + "4" * 64),
            "linux-amd64": ("e" * 64, "sha256:" + "5" * 64),
            "linux-arm64": ("f" * 64, "sha256:" + "6" * 64),
        }
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            binaries_path(repo, "jq").write_text(existing)
            full_build(repo, metadir, "jq", new)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            text = binaries_path(repo, "jq").read_text()
            self.assertIn(prior_history, text)
            doc = tomllib.loads(text)
            self.assertEqual(doc["version"], "1.8.1")
            self.assertEqual(len(doc["history"]), 2)
            self.assertEqual(doc["history"][1]["version"], "1.8.1-1")

    def test_legacy_file_without_history_gets_seeded(self) -> None:
        existing = (
            'version = "1.8.0"\n'
            "\n"
            "[darwin-arm64]\n"
            f'sha256 = "{SHA_A}"\n'
        )
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            binaries_path(repo, "jq").write_text(existing)
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            doc = tomllib.loads(binaries_path(repo, "jq").read_text())
            self.assertEqual(len(doc["history"]), 1)
            self.assertEqual(doc["history"][0]["version"], "1.8.1-1")


class PartialPlatformGateTests(unittest.TestCase):
    def test_partial_build_keeps_existing_file(self) -> None:
        existing = 'version = "1.8.0"\n\n[darwin-arm64]\nsha256 = "%s"\n' % SHA_A
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            binaries_path(repo, "jq").write_text(existing)
            # Only 2 of 3 eligible platforms produced metadata.
            make_meta(metadir, "jq", "darwin-arm64", SHA_A, DIG_A)
            make_meta(metadir, "jq", "linux-amd64", SHA_B, DIG_B)
            rc, out, err = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            self.assertEqual(
                binaries_path(repo, "jq").read_text(), existing
            )
            self.assertIn("::warning::Skipping jq: 2/3", out + err)

    def test_declared_subset_recipe_writes_on_subset(self) -> None:
        # A recipe declaring 2 platforms is complete with 2
        # metadata files — the gate is per-recipe eligibility,
        # not the full CI matrix.
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(
                repo,
                "traceroute",
                "2.1.6",
                platforms=["linux-amd64", "linux-arm64"],
            )
            make_meta(metadir, "traceroute", "linux-amd64", SHA_B, DIG_B)
            make_meta(metadir, "traceroute", "linux-arm64", SHA_C, DIG_C)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            doc = tomllib.loads(
                binaries_path(repo, "traceroute").read_text()
            )
            self.assertEqual(
                set(doc) - {"version", "history"},
                {"linux-amd64", "linux-arm64"},
            )


class DigestValidationTests(unittest.TestCase):
    def test_missing_manifest_digest_hard_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            make_meta(
                metadir, "jq", "darwin-arm64", SHA_A, None,
                omit_digest=True,
            )
            make_meta(metadir, "jq", "linux-amd64", SHA_B, DIG_B)
            make_meta(metadir, "jq", "linux-arm64", SHA_C, DIG_C)
            rc, out, err = run_main(repo, metadir)
            self.assertEqual(rc, 1)
            self.assertIn("manifest_digest", out + err)

    def test_malformed_manifest_digest_hard_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            make_meta(
                metadir, "jq", "darwin-arm64", SHA_A, "sha256:nope"
            )
            make_meta(metadir, "jq", "linux-amd64", SHA_B, DIG_B)
            make_meta(metadir, "jq", "linux-arm64", SHA_C, DIG_C)
            rc, out, err = run_main(repo, metadir)
            self.assertEqual(rc, 1)
            self.assertIn("manifest_digest", out + err)

    def test_malformed_sha256_hard_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            make_meta(metadir, "jq", "darwin-arm64", "zz", DIG_A)
            make_meta(metadir, "jq", "linux-amd64", SHA_B, DIG_B)
            make_meta(metadir, "jq", "linux-arm64", SHA_C, DIG_C)
            rc, out, err = run_main(repo, metadir)
            self.assertEqual(rc, 1)
            self.assertIn("sha256", out + err)


class AppendOnlyLedgerTests(unittest.TestCase):
    def _seeded_repo(self, tmp: Path) -> tuple[Path, Path]:
        repo = make_repo(tmp)
        metadir = tmp / "meta"
        make_recipe(repo, "jq", "1.8.1")
        full_build(repo, metadir, "jq", THREE)
        rc, _, _ = run_main(repo, metadir)
        self.assertEqual(rc, 0)
        return repo, metadir

    def test_same_key_identical_digests_is_noop(self) -> None:
        # Re-promote after adopt: same version key, same
        # digests — nothing appended, file unchanged.
        with TemporaryDirectory() as tmp:
            repo, metadir = self._seeded_repo(Path(tmp))
            before = binaries_path(repo, "jq").read_text()
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            after = binaries_path(repo, "jq").read_text()
            self.assertEqual(before, after)
            doc = tomllib.loads(after)
            self.assertEqual(len(doc["history"]), 1)

    def test_same_key_different_digests_errors(self) -> None:
        with TemporaryDirectory() as tmp:
            repo, metadir = self._seeded_repo(Path(tmp))
            before = binaries_path(repo, "jq").read_text()
            # Same (version, revision), different bytes.
            changed = dict(THREE)
            changed["darwin-arm64"] = ("9" * 64, "sha256:" + "9" * 64)
            full_build(repo, metadir, "jq", changed)
            rc, out, err = run_main(repo, metadir)
            self.assertEqual(rc, 1)
            self.assertIn("append-only", out + err)
            self.assertIn("1.8.1-1", out + err)
            # The file must not have been touched.
            self.assertEqual(
                binaries_path(repo, "jq").read_text(), before
            )


class GoldenFormatTests(unittest.TestCase):
    """Byte-for-byte mirror compatibility with the bash writer
    this script replaces. The expected text below (minus the
    manifest_digest lines, which are new and ignored by
    v0.16.5) is the exact output shape of the old
    `Write .binaries.toml files` step for pixman 0.46.4-2."""

    maxDiff = None

    def test_pixman_shaped_recipe_matches_bash_writer(self) -> None:
        deps = [
            {"name": "libpng", "version": "1.6.50", "revision": 2},
            {"name": "pkgconf", "version": "2.5.1", "revision": 2},
        ]
        shas = {
            "darwin-arm64": (SHA_A, DIG_A),
            "linux-amd64": (SHA_B, DIG_B),
            "linux-arm64": (SHA_C, DIG_C),
        }
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "pixman", "0.46.4", revision=2)
            for platform, (sha, dig) in shas.items():
                make_meta(
                    metadir, "pixman", platform, sha, dig, deps=deps
                )
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            text = binaries_path(repo, "pixman").read_text()

        mirror = text.split("[[history]]")[0]
        # Drop the (new, v0.16.5-invisible) manifest_digest
        # lines; the rest must be byte-identical to the bash
        # writer's output.
        legacy = "".join(
            line
            for line in mirror.splitlines(keepends=True)
            if not line.startswith("manifest_digest = ")
        )
        expected = (
            'version = "0.46.4-2"\n'
            "\n"
            "[darwin-arm64]\n"
            f'sha256 = "{SHA_A}"\n'
            "deps = [\n"
            '  { name = "libpng", version = "1.6.50", revision = 2 },\n'
            '  { name = "pkgconf", version = "2.5.1", revision = 2 },\n'
            "]\n"
            "\n"
            "[linux-amd64]\n"
            f'sha256 = "{SHA_B}"\n'
            "deps = [\n"
            '  { name = "libpng", version = "1.6.50", revision = 2 },\n'
            '  { name = "pkgconf", version = "2.5.1", revision = 2 },\n'
            "]\n"
            "\n"
            "[linux-arm64]\n"
            f'sha256 = "{SHA_C}"\n'
            "deps = [\n"
            '  { name = "libpng", version = "1.6.50", revision = 2 },\n'
            '  { name = "pkgconf", version = "2.5.1", revision = 2 },\n'
            "]\n"
            "\n"
        )
        self.assertEqual(legacy, expected)


class SelfCheckTests(unittest.TestCase):
    def test_output_parses_and_mirror_echoes_newest_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1", revision=3)
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)
            doc = tomllib.loads(binaries_path(repo, "jq").read_text())
            newest = doc["history"][-1]
            self.assertEqual(newest["version"], "1.8.1-3")
            for platform in THREE:
                self.assertEqual(
                    doc[platform]["sha256"],
                    newest[platform]["sha256"],
                )
                self.assertEqual(
                    doc[platform]["manifest_digest"],
                    newest[platform]["manifest_digest"],
                )


class MainEdgeTests(unittest.TestCase):
    def test_no_metadata_is_a_noop(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            metadir.mkdir()
            rc, _, _ = run_main(repo, metadir)
            self.assertEqual(rc, 0)

    def test_metadata_for_unknown_recipe_fails(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            full_build(repo, metadir, "ghost", THREE)
            rc, out, err = run_main(repo, metadir)
            self.assertEqual(rc, 1)
            self.assertIn("ghost", out + err)


class CommitFieldTests(unittest.TestCase):
    """gh#121 item 3 Part A: a newly appended [[history]] entry
    records the reviewed head SHA the binaries were built from
    as ``commit``, placed right after ``version``. Old entries
    predating the field carry none and must stay untouched."""

    def test_render_emits_commit_after_version(self) -> None:
        out = wb.render_history_entry(
            "1.8.1-5", entries_from(THREE), COMMIT
        )
        lines = out.splitlines()
        self.assertEqual(lines[0], "[[history]]")
        self.assertEqual(lines[1], 'version = "1.8.1-5"')
        self.assertEqual(lines[2], f'commit = "{COMMIT}"')

    def test_render_omits_commit_when_empty(self) -> None:
        out = wb.render_history_entry(
            "1.8.1-5", entries_from(THREE), ""
        )
        self.assertNotIn("commit", out)

    def test_render_omits_commit_by_default(self) -> None:
        out = wb.render_history_entry("1.8.1-5", entries_from(THREE))
        self.assertNotIn("commit", out)

    def test_build_output_appends_entry_with_commit(self) -> None:
        out = wb.build_output(
            None, "1.8.1", 1, entries_from(THREE), COMMIT
        )
        doc = tomllib.loads(out)
        self.assertEqual(doc["history"][0]["commit"], COMMIT)
        # commit must sit between version and the platform tables.
        body = out.split("[[history]]\n", 1)[1]
        self.assertTrue(
            body.startswith(
                f'version = "1.8.1-1"\ncommit = "{COMMIT}"\n'
            )
        )

    def test_preserved_entries_get_no_commit_injected(self) -> None:
        # Existing ledger entry predates the commit field. A new
        # version bump appends its own commit; the old entry must
        # survive byte-identical, commit-free.
        prior_history = (
            "[[history]]\n"
            'version = "1.8.0-1"\n'
            f'darwin-arm64 = {{ sha256 = "{SHA_A}", '
            f'manifest_digest = "{DIG_A}" }}\n'
            f'linux-amd64 = {{ sha256 = "{SHA_B}", '
            f'manifest_digest = "{DIG_B}" }}\n'
            f'linux-arm64 = {{ sha256 = "{SHA_C}", '
            f'manifest_digest = "{DIG_C}" }}\n'
        )
        existing = (
            'version = "1.8.0"\n'
            "\n[darwin-arm64]\n"
            f'sha256 = "{SHA_A}"\n'
            "\n[linux-amd64]\n"
            f'sha256 = "{SHA_B}"\n'
            "\n[linux-arm64]\n"
            f'sha256 = "{SHA_C}"\n'
            "\n" + prior_history
        )
        new = {
            "darwin-arm64": ("d" * 64, "sha256:" + "4" * 64),
            "linux-amd64": ("e" * 64, "sha256:" + "5" * 64),
            "linux-arm64": ("f" * 64, "sha256:" + "6" * 64),
        }
        out = wb.build_output(
            existing, "1.8.1", 1, entries_from(new), COMMIT
        )
        self.assertIn(prior_history, out)
        doc = tomllib.loads(out)
        self.assertNotIn("commit", doc["history"][0])
        self.assertEqual(doc["history"][1]["commit"], COMMIT)

    def test_cli_commit_lands_in_file(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir, commit=COMMIT)
            self.assertEqual(rc, 0)
            text = binaries_path(repo, "jq").read_text()
            self.assertIn(f'commit = "{COMMIT}"\n', text)
            doc = tomllib.loads(text)
            self.assertEqual(doc["history"][0]["commit"], COMMIT)

    def test_rerun_with_commit_is_byte_identical(self) -> None:
        with TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            metadir = Path(tmp) / "meta"
            make_recipe(repo, "jq", "1.8.1")
            full_build(repo, metadir, "jq", THREE)
            rc, _, _ = run_main(repo, metadir, commit=COMMIT)
            self.assertEqual(rc, 0)
            before = binaries_path(repo, "jq").read_text()
            rc, _, _ = run_main(repo, metadir, commit=COMMIT)
            self.assertEqual(rc, 0)
            after = binaries_path(repo, "jq").read_text()
            self.assertEqual(before, after)
            doc = tomllib.loads(after)
            self.assertEqual(len(doc["history"]), 1)


if __name__ == "__main__":
    unittest.main()
