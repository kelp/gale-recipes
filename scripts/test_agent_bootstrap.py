#!/usr/bin/env python3
"""PATH-shimmed tests for the post-farm agent bootstrap.

Solo-clone fallback builds gale from kelp/gale at a named
index-linting commit. It does not read leftover recipes/.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
BOOTSTRAP = SCRIPTS / "agent-bootstrap.sh"
GALE_FALLBACK_SHA = "0b4c78d"


class AgentBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name) / "home"
        self.repo = Path(self._tmp.name) / "repo"
        self.shim = Path(self._tmp.name) / "shim"
        self.log = Path(self._tmp.name) / "log"
        self.home.mkdir()
        (self.repo / "scripts").mkdir(parents=True)
        self.shim.mkdir()
        self.log.mkdir()
        script = (self.repo / "scripts" / "agent-bootstrap.sh")
        script.write_text(BOOTSTRAP.read_text())
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
        self.script = script

    def write_shim(self, name: str, body: str) -> None:
        path = self.shim / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(0o755)

    def populate_safe_bin(self, dest: Path, *, include_go: bool) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        needed = (
            "bash", "flock", "mkdir", "date", "uname", "curl",
            "tar", "install", "find", "python3", "rm", "cat",
            "chmod", "grep", "mktemp", "tr", "git", "dirname",
            "head", "tail", "touch",
        )
        if include_go:
            needed += ("go",)
        for name in needed:
            src = shutil.which(name)
            if src:
                os.symlink(src, dest / name)

    def run_bootstrap(self, path_dirs: list[Path]) -> subprocess.CompletedProcess[str]:
        env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join(str(p) for p in path_dirs),
            "CLAUDE_CODE_REMOTE": "true",
        }
        return subprocess.run(
            [str(self.script), "--force"],
            check=False,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.repo),
        )

    def test_solo_clone_builds_named_gale_commit(self) -> None:
        clone_log = self.log / "git.log"
        build_log = self.log / "go.log"
        self.write_shim("git", f"""
echo "$@" >> "{clone_log}"
if [ "$1" = "clone" ]; then
  dest=""
  for dest; do :; done
  mkdir -p "$dest/cmd/gale"
  exit 0
fi
exit 0
""")
        self.write_shim("go", f"""
echo "$@" >> "{build_log}"
while [ $# -gt 0 ]; do
  if [ "$1" = "-o" ]; then
    mkdir -p "$(dirname "$2")"
    printf 'ok\\n' > "$2"
    chmod +x "$2"
    exit 0
  fi
  shift
done
exit 0
""")
        safe = Path(self._tmp.name) / "safe"
        self.populate_safe_bin(safe, include_go=False)
        got = self.run_bootstrap([self.shim, safe])
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        git_args = clone_log.read_text() if clone_log.exists() else ""
        self.assertIn("kelp/gale", git_args, git_args)
        self.assertIn(GALE_FALLBACK_SHA, git_args, git_args)
        go_args = build_log.read_text() if build_log.exists() else ""
        self.assertIn("./cmd/gale", go_args, go_args)
        status = (self.home / ".cache" / "gale-agent-bootstrap" / "status-recipes")
        self.assertTrue(status.is_file(), got.stdout)
        self.assertNotIn("recipes/g/gale", status.read_text())

    def test_no_go_records_skipped(self) -> None:
        safe = Path(self._tmp.name) / "safe"
        self.populate_safe_bin(safe, include_go=False)
        got = self.run_bootstrap([safe])
        self.assertEqual(got.returncode, 0, got.stdout + got.stderr)
        status = self.home / ".cache" / "gale-agent-bootstrap" / "status-recipes"
        self.assertTrue(status.is_file(), got.stdout)
        text = status.read_text()
        self.assertIn("SKIPPED", text)
        self.assertNotIn("recipes/g/gale", text)


if __name__ == "__main__":
    unittest.main()
