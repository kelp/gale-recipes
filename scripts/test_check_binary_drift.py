"""Tests for check_binary_drift.py.

The script is the CI watchdog that turns "binaries lagging
behind a bumped recipe" into a red X in the Actions tab.
Exit code is the contract — the daily workflow keys off of
it — so the tests pin it.

Run with: ``python3 -m unittest scripts.test_check_binary_drift``
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_binary_drift as c  # noqa: E402
from test_gen_status_page import _write_recipe  # noqa: E402


class FindDriftedTests(unittest.TestCase):
    def test_matching_binaries_not_drifted(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "fresh",
                version="1.0.0",
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.0.0",
            )
            self.assertEqual(c.find_drifted(root), [])

    def test_drifted_recipe_detected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "drifted",
                version="2.0.0",
                revision=3,
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.9.0-3",
            )
            drifted = c.find_drifted(root)
        self.assertEqual([r.name for r in drifted], ["drifted"])

    def test_no_binaries_file_is_not_drift(self) -> None:
        """A brand-new recipe with no binaries.toml yet is in
        a different bucket (build pending, not drift). is_stale_drift
        requires both versions to exist."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(root, "brandnew", version="0.1.0")
            self.assertEqual(c.find_drifted(root), [])

    def test_results_are_alphabetical(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for n in ["zeta", "alpha", "middle"]:
                _write_recipe(
                    root,
                    n,
                    version="2.0.0",
                    binaries={"linux-amd64": "a" * 64},
                    binaries_version="1.0.0",
                )
            names = [r.name for r in c.find_drifted(root)]
        self.assertEqual(names, sorted(names))


class FormatSummaryTests(unittest.TestCase):
    def test_clean_summary_says_so(self) -> None:
        summary = c.format_summary([])
        self.assertIn("All recipes match", summary)

    def test_drifted_summary_lists_each_recipe(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "drifted",
                version="2.0.0",
                revision=3,
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.9.0-3",
            )
            drifted = c.find_drifted(root)
        summary = c.format_summary(drifted)
        self.assertIn("`drifted`", summary)
        self.assertIn("2.0.0-3", summary)
        self.assertIn("1.9.0-3", summary)


class ExitCodeTests(unittest.TestCase):
    """The daily workflow keys off the exit code — these
    pin the contract."""

    def test_exit_zero_when_clean(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "ok",
                version="1.0.0",
                binaries={"linux-amd64": "a" * 64},
            )
            rc = c.main(["--repo-root", str(root)])
        self.assertEqual(rc, 0)

    def test_exit_one_when_drifted(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "stale",
                version="2.0.0",
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.0.0",
            )
            rc = c.main(["--repo-root", str(root)])
        self.assertEqual(rc, 1)

    def test_exit_two_on_bad_root(self) -> None:
        with TemporaryDirectory() as tmp:
            rc = c.main(["--repo-root", tmp])
        self.assertEqual(rc, 2)

    def test_step_summary_written_when_env_set(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "stale",
                version="2.0.0",
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.0.0",
            )
            summary_path = Path(tmp) / "summary.md"
            old = os.environ.get("GITHUB_STEP_SUMMARY")
            os.environ["GITHUB_STEP_SUMMARY"] = str(summary_path)
            try:
                rc = c.main(["--repo-root", str(root)])
                # Read inside the with-block — TemporaryDirectory
                # deletes tmp on exit, so summary_path goes with it.
                self.assertEqual(rc, 1)
                self.assertTrue(summary_path.exists())
                self.assertIn("`stale`", summary_path.read_text())
            finally:
                if old is None:
                    del os.environ["GITHUB_STEP_SUMMARY"]
                else:
                    os.environ["GITHUB_STEP_SUMMARY"] = old


if __name__ == "__main__":
    unittest.main()
