#!/usr/bin/env python3
"""The farm is gone. The catalog is index TOML.

Red while leftover recipes, ledgers, and promote /
verify-build CI still exist. Green after this slice.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import index_layout

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = Path(__file__).resolve().parent
WORKFLOWS = REPO / ".github" / "workflows"

GONE_WORKFLOWS = (
    "promote.yml",
    "build.yml",
    "build-chunk.yml",
    "verify.yml",
    "ledger-check.yml",
    "reproducibility.yml",
    "auto-update.yml",
    "drift-check.yml",
    "pages.yml",
)

GONE_SCRIPTS = (
    "write_binaries.py",
    "seed_ledger.py",
    "chunk_recipes.py",
    "check_ledger.py",
    "check_registry_coherence.py",
    "verify_binary.py",
    "check_install.py",
    "run_smoke.py",
    "audit_binaries.py",
    "classify_audit.py",
    "bump_revisions.py",
    "extract-binaries.sh",
    "update_recipe.py",
    "check_ghsa.py",
    "gen_status_page.py",
    "test_write_binaries.py",
    "test_seed_ledger.py",
    "test_chunk_recipes.py",
    "test_check_ledger.py",
    "test_check_registry_coherence.py",
    "test_verify_binary.py",
    "test_check_install.py",
    "test_issue95_store_prefix.py",
    "test_update_recipe.py",
    "test_gen_status_page.py",
    "test_check_ghsa.py",
    "test_auto_update_sh.sh",
    "test_verify_upstream_attestation.sh",
)

GONE_SCRIPT_REFS = (
    "write_binaries.py",
    "check_ledger.py",
    "auto-update.sh",
    "verify.yml",
    "promote.yml",
    "ledger-check.yml",
)

FIRST_TEN = (
    "jq",
    "ripgrep",
    "fd",
    "just",
    "gh",
    "go",
    "gofumpt",
    "golangci-lint",
    "direnv",
    "uv",
)


class FarmGoneTests(unittest.TestCase):
    def test_recipes_dir_is_gone(self) -> None:
        self.assertFalse(
            (REPO / "recipes").exists(),
            "leftover recipes/ is farm; the catalog is index/",
        )

    def test_no_binaries_toml(self) -> None:
        leftover = list(REPO.rglob("*.binaries.toml"))
        self.assertEqual(leftover, [], f"ledgers remain: {leftover}")

    def test_farm_workflows_are_gone(self) -> None:
        found = [name for name in GONE_WORKFLOWS if (WORKFLOWS / name).exists()]
        self.assertEqual(found, [], f"farm workflows remain: {found}")

    def test_farm_scripts_are_gone(self) -> None:
        found = [name for name in GONE_SCRIPTS if (SCRIPTS / name).exists()]
        self.assertEqual(found, [], f"farm scripts remain: {found}")
        self.assertFalse(
            (REPO / ".github" / "scripts" / "auto-update.sh").exists(),
            "auto-update.sh remains",
        )

    def test_remaining_workflows_do_not_name_farm(self) -> None:
        remaining = sorted(WORKFLOWS.glob("*.yml"))
        self.assertTrue(remaining, "no workflows left")
        hits: list[str] = []
        for path in remaining:
            text = path.read_text()
            for needle in GONE_SCRIPT_REFS:
                if needle in text:
                    hits.append(f"{path.name}:{needle}")
        self.assertEqual(hits, [], f"remaining workflows name farm: {hits}")

    def test_first_ten_index_documents_exist(self) -> None:
        names = {p.stem for p in index_layout.list_index_files(REPO)}
        missing = [n for n in FIRST_TEN if n not in names]
        self.assertEqual(missing, [], f"missing first-ten index: {missing}")

    def test_bootstrap_has_no_recipe_pin(self) -> None:
        text = (SCRIPTS / "agent-bootstrap.sh").read_text()
        self.assertNotIn(
            "recipes/g/gale",
            text,
            "bootstrap still pins gale from leftover recipes/",
        )
        self.assertNotIn("recipe_version", text)


if __name__ == "__main__":
    unittest.main()
