#!/usr/bin/env python3
"""Skip-on-base and continue-on-failure for Darwin admit.

Does not download assets or run gale admit.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import admit_darwin as ad
import admit_manifest as am


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo() -> tempfile.TemporaryDirectory[str]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    _git(root, "init")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "test")
    (root / "README").write_text("x\n")
    _git(root, "add", "README")
    _git(root, "commit", "-m", "init")
    return tmp


class IndexedOnBaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = _init_repo()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)

    def test_missing_path_is_not_indexed(self) -> None:
        self.assertFalse(ad.indexed_on_base(self.root, "fzf", "HEAD"))

    def test_file_on_base_is_indexed(self) -> None:
        path = self.root / "index" / "f" / "fzf.toml"
        path.parent.mkdir(parents=True)
        path.write_text("ok\n")
        _git(self.root, "add", "index/f/fzf.toml")
        _git(self.root, "commit", "-m", "index fzf")
        self.assertTrue(ad.indexed_on_base(self.root, "fzf", "HEAD"))

    def test_working_tree_only_is_not_indexed(self) -> None:
        path = self.root / "index" / "f" / "fzf.toml"
        path.parent.mkdir(parents=True)
        path.write_text("draft\n")
        self.assertFalse(ad.indexed_on_base(self.root, "fzf", "HEAD"))

    def test_empty_file_on_base_is_indexed(self) -> None:
        path = self.root / "index" / "f" / "fzf.toml"
        path.parent.mkdir(parents=True)
        path.write_text("")
        _git(self.root, "add", "index/f/fzf.toml")
        _git(self.root, "commit", "-m", "empty fzf")
        self.assertTrue(ad.indexed_on_base(self.root, "fzf", "HEAD"))

    def test_symlink_on_base_is_not_indexed(self) -> None:
        path = self.root / "index" / "f" / "fzf.toml"
        path.parent.mkdir(parents=True)
        (self.root / "index" / "f" / "other.toml").write_text("x\n")
        path.symlink_to("other.toml")
        _git(self.root, "add", "index/f")
        _git(self.root, "commit", "-m", "symlink")
        self.assertFalse(ad.indexed_on_base(self.root, "fzf", "HEAD"))

    def test_unresolvable_base_is_error(self) -> None:
        with self.assertRaises(ad.UnresolvableBase):
            ad.indexed_on_base(self.root, "fzf", "origin/main")


def _pkg(name: str, *, sha256: str = "", hash_source: str = "computed") -> am.Package:
    return am.Package(
        name=name,
        version="1.0.0",
        description=name,
        license="MIT",
        homepage="https://example.com",
        repo="ex/ex",
        url=f"https://github.com/ex/{name}/releases/download/v1/{name}.tar.gz",
        format="tar.gz",
        strip=0,
        hash_source=hash_source,
        sha256=sha256,
        files=(f"{name}:bin/{name}:755",),
    )


class AdmitPackagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = _init_repo()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.out = self.root / "fragments"
        self.work = self.root / "work"
        self.out.mkdir()
        self.work.mkdir()

    def _run(
        self,
        packages: tuple[am.Package, ...],
        *,
        run_admit,
        download=None,
    ) -> int:
        def _download(pkg: am.Package, dest: Path) -> None:
            dest.write_bytes(b"archive")

        return ad.admit_packages(
            packages,
            gale="gale",
            out=self.out,
            work=self.work,
            repo_root=self.root,
            base_ref="HEAD",
            download=download or _download,
            run_admit=run_admit,
        )

    def test_all_skipped_exits_zero(self) -> None:
        path = self.root / "index" / "a" / "alpha.toml"
        path.parent.mkdir(parents=True)
        path.write_text("ok\n")
        _git(self.root, "add", "index/a/alpha.toml")
        _git(self.root, "commit", "-m", "index alpha")

        def boom(argv: list[str]) -> SimpleNamespace:
            raise AssertionError(f"admit should not run: {argv}")

        code = self._run((_pkg("alpha"),), run_admit=boom)
        self.assertEqual(code, 0)
        self.assertEqual(list(self.out.glob("*.fragment.toml")), [])

    def test_one_failure_keeps_other_fragments(self) -> None:
        def run_admit(argv: list[str]) -> SimpleNamespace:
            name = argv[argv.index("--name") + 1]
            if name == "beta":
                return SimpleNamespace(returncode=1, stdout="", stderr="dylib\n")
            return SimpleNamespace(returncode=0, stdout=f"ok {name}\n", stderr="")

        code = self._run(
            (_pkg("alpha"), _pkg("beta"), _pkg("gamma")),
            run_admit=run_admit,
        )
        self.assertEqual(code, 0)
        self.assertTrue((self.out / "alpha.fragment.toml").is_file())
        self.assertTrue((self.out / "gamma.fragment.toml").is_file())
        self.assertFalse((self.out / "beta.fragment.toml").exists())
        self.assertIn("dylib", (self.out / "beta.failed.txt").read_text())

    def test_all_attempted_fail_exits_one(self) -> None:
        def run_admit(argv: list[str]) -> SimpleNamespace:
            return SimpleNamespace(returncode=2, stdout="", stderr="codesign\n")

        code = self._run((_pkg("alpha"), _pkg("beta")), run_admit=run_admit)
        self.assertEqual(code, 1)
        self.assertEqual(list(self.out.glob("*.fragment.toml")), [])
        self.assertTrue((self.out / "alpha.failed.txt").is_file())
        self.assertTrue((self.out / "beta.failed.txt").is_file())


if __name__ == "__main__":
    unittest.main()
