#!/usr/bin/env python3
"""CI runs zizmor on GitHub Actions workflows."""

from __future__ import annotations

import re
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST_YML = REPO / ".github" / "workflows" / "test.yml"
IMAGE_PIN = re.compile(
    r"ghcr.io/zizmorcore/zizmor:1\.29\.0@sha256:[0-9a-f]{64}"
)


class ZizmorCiTests(unittest.TestCase):
    def test_test_yml_has_zizmor_job(self) -> None:
        text = TEST_YML.read_text()
        self.assertIn("\n  zizmor:\n", text)
        self.assertRegex(text, IMAGE_PIN)
        self.assertIn("--offline", text)

    def test_zizmor_offline_is_clean(self) -> None:
        if not shutil.which("zizmor"):
            self.skipTest("zizmor not installed")
        got = subprocess.run(
            ["zizmor", "--offline", "."],
            cwd=REPO,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)


if __name__ == "__main__":
    unittest.main()
