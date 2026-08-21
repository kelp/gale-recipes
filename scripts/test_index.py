#!/usr/bin/env python3
"""Layout tests for index/{letter}/{name}.toml.

Does not invoke gale. Schema lint is just lint and the
pinned-gale CI job.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import index_layout

SCRIPT = Path(__file__).resolve().parent / "lint_index.sh"
REPO = Path(__file__).resolve().parent.parent
REQUIRED_FIRST_FOUR = ("fd", "jq", "just", "ripgrep")
REQUIRED_GH_DIRENV = ("direnv", "gh")
REQUIRED_GOFUMPT_GOLANGCI = ("gofumpt", "golangci-lint")
REQUIRED_UV = ("uv",)
REQUIRED_GO = ("go",)
REQUIRED_GROWTH_WAVE = (
    "actionlint", "age", "fzf", "shellcheck",
    "shfmt", "starship", "yq", "zoxide",
)


class IndexLayoutTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def touch(self, rel: str) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        return path

    def test_missing_index_dir_is_empty(self) -> None:
        self.assertEqual(index_layout.list_index_files(self.root), [])

    def test_good_path(self) -> None:
        self.touch("index/j/just.toml")
        files = index_layout.list_index_files(self.root)
        self.assertEqual(len(files), 1)
        self.assertTrue(index_layout.layout_ok(files[0], self.root))

    def test_two_files_share_letter_bucket(self) -> None:
        self.touch("index/j/jq.toml")
        self.touch("index/j/just.toml")
        files = index_layout.list_index_files(self.root)
        self.assertEqual(len(files), 2)
        for f in files:
            self.assertTrue(index_layout.layout_ok(f, self.root))

    def test_letter_mismatch(self) -> None:
        path = self.touch("index/x/just.toml")
        self.assertFalse(index_layout.layout_ok(path, self.root))

    def test_uppercase_bucket(self) -> None:
        path = self.touch("index/J/just.toml")
        self.assertFalse(index_layout.layout_ok(path, self.root))

    def test_file_in_index_root(self) -> None:
        path = self.touch("index/just.toml")
        self.assertFalse(index_layout.layout_ok(path, self.root))

    def test_issues_lists_bad_paths(self) -> None:
        self.touch("index/x/just.toml")
        issues = index_layout.issues(self.root)
        self.assertEqual(len(issues), 1)
        self.assertIn("index/x/just.toml", issues[0])

    def test_lint_script_empty_tree(self) -> None:
        got = subprocess.run(
            [str(SCRIPT), str(self.root)],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("no index files", got.stdout)

    def git(self, *args: str) -> None:
        subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
        )

    def test_lint_script_refuses_wiping_the_catalog(self) -> None:
        self.git("init")
        self.git("config", "user.email", "test@example.com")
        self.git("config", "user.name", "test")
        path = self.touch("index/j/just.toml")
        path.write_text("placeholder\n")
        self.git("add", "index/j/just.toml")
        self.git("commit", "-m", "index just")
        path.unlink()
        env = {**os.environ, "INDEX_BASE": "HEAD"}
        got = subprocess.run(
            [str(SCRIPT), str(self.root)],
            check=False,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertNotEqual(got.returncode, 0, got.stdout)
        self.assertIn("index file was removed", got.stderr)


class RequiredIndexNamesTests(unittest.TestCase):
    def test_first_four_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in REQUIRED_FIRST_FOUR if n not in names]
        self.assertEqual(missing, [], f"missing index documents: {missing}")

    def test_first_four_layout(self) -> None:
        for name in REQUIRED_FIRST_FOUR:
            path = REPO / "index" / name[0] / f"{name}.toml"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            self.assertTrue(
                index_layout.layout_ok(path, REPO),
                f"{path.relative_to(REPO)}: bad index path",
            )

    def test_gh_direnv_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in REQUIRED_GH_DIRENV if n not in names]
        self.assertEqual(missing, [], f"missing index documents: {missing}")

    def test_gh_direnv_layout(self) -> None:
        for name in REQUIRED_GH_DIRENV:
            path = REPO / "index" / name[0] / f"{name}.toml"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            self.assertTrue(
                index_layout.layout_ok(path, REPO),
                f"{path.relative_to(REPO)}: bad index path",
            )

    def test_gofumpt_golangci_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in REQUIRED_GOFUMPT_GOLANGCI if n not in names]
        self.assertEqual(missing, [], f"missing index documents: {missing}")

    def test_gofumpt_golangci_layout(self) -> None:
        for name in REQUIRED_GOFUMPT_GOLANGCI:
            path = REPO / "index" / name[0] / f"{name}.toml"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            self.assertTrue(
                index_layout.layout_ok(path, REPO),
                f"{path.relative_to(REPO)}: bad index path",
            )

    def test_uv_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in REQUIRED_UV if n not in names]
        self.assertEqual(missing, [], f"missing index documents: {missing}")

    def test_uv_layout(self) -> None:
        for name in REQUIRED_UV:
            path = REPO / "index" / name[0] / f"{name}.toml"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            self.assertTrue(
                index_layout.layout_ok(path, REPO),
                f"{path.relative_to(REPO)}: bad index path",
            )

    def test_go_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in REQUIRED_GO if n not in names]
        self.assertEqual(missing, [], f"missing index documents: {missing}")

    def test_go_layout(self) -> None:
        for name in REQUIRED_GO:
            path = REPO / "index" / name[0] / f"{name}.toml"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            self.assertTrue(
                index_layout.layout_ok(path, REPO),
                f"{path.relative_to(REPO)}: bad index path",
            )

    def test_growth_wave_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in REQUIRED_GROWTH_WAVE if n not in names]
        self.assertEqual(missing, [], f"missing index documents: {missing}")

    def test_growth_wave_layout(self) -> None:
        for name in REQUIRED_GROWTH_WAVE:
            path = REPO / "index" / name[0] / f"{name}.toml"
            self.assertTrue(path.is_file(), f"missing {path.relative_to(REPO)}")
            self.assertTrue(
                index_layout.layout_ok(path, REPO),
                f"{path.relative_to(REPO)}: bad index path",
            )


if __name__ == "__main__":
    unittest.main()
