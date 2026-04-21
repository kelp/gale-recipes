"""Tests for gen_status_page.py.

The script honors each recipe's ``[package].platforms``
declaration. Platforms outside that list are reported as
"n/a" rather than as failing builds, so the generated
status page reflects design (a Linux-only tool isn't
"failing" on darwin-arm64) rather than just absence in
``.binaries.toml``.

Run with: ``python3 -m unittest scripts.test_gen_status_page``
or ``python3 scripts/test_gen_status_page.py``.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import gen_status_page as g  # noqa: E402


def _write_recipe(
    repo_root: Path,
    name: str,
    *,
    version: str = "1.0.0",
    platforms: list[str] | None = None,
    binaries: dict[str, str] | None = None,
) -> Path:
    """Materialize a recipe and (optionally) its binaries
    file. Returns the recipe TOML path."""
    letter_dir = repo_root / "recipes" / name[0]
    letter_dir.mkdir(parents=True, exist_ok=True)
    recipe = letter_dir / f"{name}.toml"
    lines = [
        "[package]",
        f'name = "{name}"',
        f'version = "{version}"',
        f'description = "test recipe {name}"',
        'homepage = ""',
        'license = "MIT"',
    ]
    if platforms is not None:
        rendered = ", ".join(f'"{p}"' for p in platforms)
        lines.append(f"platforms = [{rendered}]")
    lines.extend(
        [
            "",
            "[source]",
            'url = "https://example.invalid/x.tar.gz"',
            f'sha256 = "{"0" * 64}"',
            "",
            "[build]",
            'steps = ["true"]',
        ]
    )
    recipe.write_text("\n".join(lines) + "\n")

    if binaries is not None:
        b = letter_dir / f"{name}.binaries.toml"
        bl = [f'version = "{version}"', ""]
        for plat, sha in binaries.items():
            bl.append(f"[{plat}]")
            bl.append(f'sha256 = "{sha}"')
            bl.append("")
        b.write_text("\n".join(bl))
    return recipe


class PlatformGateTests(unittest.TestCase):
    """Recipes that declare ``[package].platforms`` are not
    failing on platforms outside that list."""

    def test_excluded_platform_marked_na(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "linuxonly",
                platforms=["linux-amd64", "linux-arm64"],
                binaries={
                    "linux-amd64": "a" * 64,
                    "linux-arm64": "b" * 64,
                },
            )
            recipes = g.load_all_recipes(root)
        self.assertEqual(len(recipes), 1)
        r = recipes[0]
        self.assertEqual(r.platforms["darwin-arm64"].state, "na")
        self.assertEqual(r.platforms["linux-amd64"].state, "ok")
        self.assertEqual(r.platforms["linux-arm64"].state, "ok")

    def test_excluded_platform_does_not_count_as_failing(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "linuxonly",
                platforms=["linux-amd64", "linux-arm64"],
                binaries={
                    "linux-amd64": "a" * 64,
                    "linux-arm64": "b" * 64,
                },
            )
            recipes = g.load_all_recipes(root)
        r = recipes[0]
        self.assertFalse(r.any_red)
        self.assertTrue(r.all_green)
        self.assertEqual(r.failing_platforms(), [])

    def test_unbuilt_eligible_platform_still_failing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "halfdone",
                platforms=["darwin-arm64", "linux-amd64"],
                binaries={"linux-amd64": "a" * 64},
            )
            recipes = g.load_all_recipes(root)
        r = recipes[0]
        self.assertEqual(r.platforms["darwin-arm64"].state, "fail")
        self.assertEqual(r.platforms["linux-amd64"].state, "ok")
        self.assertEqual(r.platforms["linux-arm64"].state, "na")
        self.assertTrue(r.any_red)
        self.assertEqual(
            r.failing_platforms(), ["darwin-arm64"]
        )

    def test_no_platforms_field_means_all_eligible(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "universal",
                binaries={"linux-amd64": "a" * 64},
            )
            recipes = g.load_all_recipes(root)
        r = recipes[0]
        self.assertEqual(r.platforms["darwin-arm64"].state, "fail")
        self.assertEqual(r.platforms["linux-amd64"].state, "ok")
        self.assertEqual(r.platforms["linux-arm64"].state, "fail")

    def test_unknown_platform_in_recipe_is_ignored(self) -> None:
        """``darwin-amd64`` isn't in ``PLATFORMS`` (only
        ``darwin-arm64``, ``linux-amd64``, ``linux-arm64``
        are tracked). A recipe that lists it shouldn't
        crash; the unknown entry is dropped."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "macosonly",
                platforms=["darwin-amd64", "darwin-arm64"],
                binaries={"darwin-arm64": "a" * 64},
            )
            recipes = g.load_all_recipes(root)
        r = recipes[0]
        self.assertEqual(r.platforms["darwin-arm64"].state, "ok")
        self.assertEqual(r.platforms["linux-amd64"].state, "na")
        self.assertEqual(r.platforms["linux-arm64"].state, "na")
        self.assertFalse(r.any_red)


class RenderingTests(unittest.TestCase):
    """The status.md, status.json, and HTML reflect the
    tri-state."""

    def _build(self, root: Path) -> tuple[g.Recipe, g.Recipe]:
        _write_recipe(
            root,
            "linuxonly",
            platforms=["linux-amd64", "linux-arm64"],
            binaries={
                "linux-amd64": "a" * 64,
                "linux-arm64": "b" * 64,
            },
        )
        _write_recipe(
            root,
            "broken",
            binaries={
                "linux-amd64": "c" * 64,
                "linux-arm64": "d" * 64,
            },
        )
        recipes = g.load_all_recipes(root)
        by_name = {r.name: r for r in recipes}
        return by_name["broken"], by_name["linuxonly"]

    def test_status_md_excludes_na_recipes_from_failures(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken, linuxonly = self._build(root)
            md = g.render_status_md([broken, linuxonly])
        # broken is the only thing failing on darwin-arm64.
        self.assertIn("`broken`", md)
        # Slice the failing-builds section: from its h2 to
        # the next h2 (use "\n## " so we don't match h3s).
        after = md.split("## Failing builds by platform", 1)[1]
        failing_section = after.split("\n## ", 1)[0]
        # linuxonly should NOT appear under any platform's
        # failing list — it's n/a, not failing.
        self.assertNotIn("linuxonly", failing_section)
        # darwin-arm64 should show a single failure (broken).
        self.assertIn("### `darwin-arm64` (1)", failing_section)

    def test_status_json_uses_state_field(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, linuxonly = self._build(root)
            payload = json.loads(json.dumps(linuxonly.to_json()))
        plat = payload["platforms"]
        self.assertEqual(plat["darwin-arm64"]["state"], "na")
        self.assertEqual(plat["linux-amd64"]["state"], "ok")
        self.assertEqual(plat["linux-arm64"]["state"], "ok")

    def test_index_html_uses_na_cell_class(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            broken, linuxonly = self._build(root)
            html = g.render_index([broken, linuxonly])
        self.assertIn('class="na"', html)

    def test_recipe_page_marks_na_platform(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, linuxonly = self._build(root)
            html = g.render_recipe_page(linuxonly)
        # The darwin-arm64 row should label this as n/a, not
        # as a failure.
        self.assertIn("n/a", html.lower())
        self.assertNotIn("✗ failed", html)


if __name__ == "__main__":
    unittest.main()
