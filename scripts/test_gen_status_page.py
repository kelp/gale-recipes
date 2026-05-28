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
import re
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
    revision: int | None = None,
    platforms: list[str] | None = None,
    binaries: dict[str, str] | None = None,
    binaries_version: str | None = None,
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
    ]
    if revision is not None:
        lines.append(f"revision = {revision}")
    lines.extend(
        [
            f'description = "test recipe {name}"',
            'homepage = ""',
            'license = "MIT"',
        ]
    )
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
        bv = (
            binaries_version
            if binaries_version is not None
            else version
        )
        bl = [f'version = "{bv}"', ""]
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


def _write_upstream(repo_root: Path, recipes: dict[str, dict]) -> None:
    data = {
        "generated_at": "2026-05-18T10:44:50Z",
        "recipes": recipes,
    }
    out = repo_root / "_data" / "upstream.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data))


def _row_for(html_doc: str, name: str) -> str:
    """Return the <tr ...> block for a given recipe row."""
    pattern = re.compile(
        rf'<tr [^>]*data-name="{re.escape(name)}".*?</tr>',
        re.DOTALL,
    )
    m = pattern.search(html_doc)
    assert m, f"no row for {name} in:\n{html_doc}"
    return m.group(0)


class RevisionStaleTests(unittest.TestCase):
    """``.binaries.toml`` records ``version`` as the joined
    ``X.Y.Z-N`` form when revision > 1. The recipe stores
    version (bare) and revision (int) separately. Stale must
    compare the joined form, not the bare version."""

    def test_revision_2_matching_binaries_not_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "agelike",
                version="1.3.1",
                revision=2,
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.3.1-2",
            )
            (r,) = g.load_all_recipes(root)
        self.assertFalse(r.is_stale)

    def test_revision_1_matching_binaries_not_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "plain",
                version="1.7.2",
                revision=1,
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.7.2",
            )
            (r,) = g.load_all_recipes(root)
        self.assertFalse(r.is_stale)

    def test_revision_default_matching_binaries_not_stale(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "defaultrev",
                version="2.0.0",
                binaries={"linux-amd64": "a" * 64},
                binaries_version="2.0.0",
            )
            (r,) = g.load_all_recipes(root)
        self.assertFalse(r.is_stale)

    def test_truly_stale_still_detected(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "drift",
                version="2.0.0",
                revision=3,
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.9.0-3",
            )
            (r,) = g.load_all_recipes(root)
        self.assertTrue(r.is_stale)

    def test_stale_pill_uses_synthesized_expected(self) -> None:
        """Pill tooltip should show the expected joined form,
        not the bare recipe version, so the user sees what
        the binaries should match."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "drift",
                version="2.0.0",
                revision=3,
                binaries={"linux-amd64": "a" * 64},
                binaries_version="1.9.0-3",
            )
            (r,) = g.load_all_recipes(root)
            pill = g.stale_pill_html(r)
        self.assertIn("2.0.0-3", pill)
        self.assertIn("1.9.0-3", pill)


class StalePlatformDisplayTests(unittest.TestCase):
    """When the recipe drifts past ``.binaries.toml`` the
    per-platform indicators must stop reading green: every
    platform's sha is for the old version, so every user
    falls back to source. Regression for the neovim case
    where the row was correctly tagged stale but cells
    still rendered ✓."""

    def _drifted(self, root: Path) -> g.Recipe:
        _write_recipe(
            root,
            "drift",
            version="2.0.0",
            revision=3,
            binaries={
                "darwin-arm64": "a" * 64,
                "linux-amd64": "b" * 64,
                "linux-arm64": "c" * 64,
            },
            binaries_version="1.9.0-3",
        )
        (r,) = g.load_all_recipes(root)
        return r

    def test_display_state_is_stale_when_drifted(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._drifted(Path(tmp))
        for p in g.PLATFORMS:
            self.assertEqual(r.platforms[p].state, "ok")
            self.assertEqual(r.platform_display_state(p), "stale")

    def test_drifted_recipe_is_not_all_green(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._drifted(Path(tmp))
        self.assertFalse(r.all_green)

    def test_platform_cell_renders_stale_class(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._drifted(Path(tmp))
        cell = g.platform_cell_html(r, "linux-amd64")
        self.assertIn('class="stale"', cell)
        self.assertNotIn('class="ok"', cell)

    def test_per_platform_built_count_excludes_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._drifted(Path(tmp))
        counts = g._per_platform_counts([r])
        for p in g.PLATFORMS:
            built, eligible = counts[p]
            self.assertEqual(built, 0)
            self.assertEqual(eligible, 1)

    def test_status_json_marks_platforms_stale(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._drifted(Path(tmp))
        doc = r.to_json()
        for p in g.PLATFORMS:
            self.assertEqual(doc["platforms"][p]["state"], "stale")

    def test_fresh_recipe_unaffected(self) -> None:
        """No drift → display state matches Platform.state and
        all_green stays true."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root,
                "fresh",
                version="2.0.0",
                binaries={
                    "darwin-arm64": "a" * 64,
                    "linux-amd64": "b" * 64,
                    "linux-arm64": "c" * 64,
                },
            )
            (r,) = g.load_all_recipes(root)
        self.assertTrue(r.all_green)
        for p in g.PLATFORMS:
            self.assertEqual(r.platform_display_state(p), "ok")


class StaleByUpstreamAgeTests(unittest.TestCase):
    """A recipe behind upstream becomes stale once the
    upstream release is ``STALE_UPSTREAM_AGE_DAYS`` (7) or
    more days old. Fresher upstreams just show as outdated.

    Tests use ``Recipe.is_stale_on(today)`` so the result
    doesn't depend on the real wall clock."""

    def _make_outdated(
        self, root: Path, name: str, released: str
    ) -> g.Recipe:
        _write_recipe(
            root, name, version="0.9.0",
            binaries={"linux-amd64": "a" * 64},
        )
        _write_upstream(root, {
            name: {
                "status": "outdated",
                "current_version": "0.9.0",
                "checked_at": "2026-05-18T10:44:50Z",
                "latest_version": "1.0.0",
                "latest_released_at": released,
                "latest_release_url": "https://example/v1.0.0",
            },
        })
        return g.load_all_recipes(root)[0]

    def test_outdated_under_7_days_is_not_stale(self) -> None:
        import datetime as dt
        with TemporaryDirectory() as tmp:
            r = self._make_outdated(Path(tmp), "fresh", "2026-05-15")
        today = dt.date(2026, 5, 18)
        self.assertEqual(r.upstream.age_days(today), 3)
        self.assertFalse(r.is_stale_on(today))

    def test_outdated_at_7_days_is_stale(self) -> None:
        import datetime as dt
        with TemporaryDirectory() as tmp:
            r = self._make_outdated(Path(tmp), "edge", "2026-05-11")
        today = dt.date(2026, 5, 18)
        self.assertEqual(r.upstream.age_days(today), 7)
        self.assertTrue(r.is_stale_on(today))

    def test_outdated_well_past_7_days_is_stale(self) -> None:
        import datetime as dt
        with TemporaryDirectory() as tmp:
            r = self._make_outdated(Path(tmp), "rotten", "2026-04-01")
        today = dt.date(2026, 5, 18)
        self.assertTrue(r.is_stale_on(today))

    def test_up_to_date_recipe_is_not_stale(self) -> None:
        import datetime as dt
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_recipe(
                root, "fine", version="1.0.0",
                binaries={"linux-amd64": "a" * 64},
            )
            _write_upstream(root, {
                "fine": {
                    "status": "up_to_date",
                    "current_version": "1.0.0",
                    "checked_at": "2026-05-18T10:44:50Z",
                    "latest_version": "1.0.0",
                    "latest_released_at": "2025-01-01",
                },
            })
            (r,) = g.load_all_recipes(root)
        self.assertFalse(r.is_stale_on(dt.date(2026, 5, 18)))

    def test_stale_pill_renders_for_upstream_reason(self) -> None:
        with TemporaryDirectory() as tmp:
            r = self._make_outdated(Path(tmp), "old", "2026-04-01")
        pill = g.stale_pill_html(r)
        # Yellow stale pill renders.
        self.assertIn('pill stale', pill)
        # Tooltip names the upstream version, not just the
        # binaries-vs-recipe skew.
        self.assertIn("1.0.0", pill)


class UpstreamColumnTests(unittest.TestCase):
    """Index has an upstream-version column. The cell always
    shows a version when upstream data exists; rows behind
    upstream render the recipe's own version in red."""

    def _make(self, root: Path) -> list[g.Recipe]:
        _write_recipe(root, "uptodate", version="1.2.3",
                      binaries={"linux-amd64": "a" * 64})
        _write_recipe(root, "behind", version="0.9.0",
                      binaries={"linux-amd64": "b" * 64})
        _write_recipe(root, "lonely", version="0.1.0",
                      binaries={"linux-amd64": "c" * 64})
        _write_upstream(root, {
            "uptodate": {
                "status": "up_to_date",
                "current_version": "1.2.3",
                "checked_at": "2026-05-18T10:44:50Z",
                "latest_version": "1.2.3",
                "latest_released_at": "2026-01-01",
            },
            "behind": {
                "status": "outdated",
                "current_version": "0.9.0",
                "checked_at": "2026-05-18T10:44:50Z",
                "latest_version": "1.0.0",
                "latest_released_at": "2026-04-01",
                "latest_release_url": "https://example/v1.0.0",
            },
        })
        return g.load_all_recipes(root)

    def test_index_has_upstream_column_header(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipes = self._make(root)
            html_doc = g.render_index(recipes)
        self.assertIn('data-sort="upstream"', html_doc)

    def test_up_to_date_row_shows_same_version_in_upstream(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipes = self._make(root)
            html_doc = g.render_index(recipes)
        row = _row_for(html_doc, "uptodate")
        # New upstream cell present with version text.
        self.assertRegex(
            row, r'<td class="upstream[^"]*"[^>]*>[^<]*1\.2\.3'
        )
        # Version cell isn't red.
        self.assertNotIn("version-behind", row)

    def test_outdated_row_shows_latest_and_reds_our_version(
        self,
    ) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipes = self._make(root)
            html_doc = g.render_index(recipes)
        row = _row_for(html_doc, "behind")
        # Upstream cell shows the new version.
        self.assertIn("1.0.0", row)
        # Upstream cell is flagged as newer.
        self.assertIn("upstream-newer", row)
        # Our version cell is rendered red.
        self.assertIn("version-behind", row)

    def test_unknown_upstream_renders_dash(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            recipes = self._make(root)
            html_doc = g.render_index(recipes)
        row = _row_for(html_doc, "lonely")
        # Upstream cell is the muted dash.
        self.assertRegex(
            row, r'<td class="upstream[^"]*muted[^"]*"[^>]*>\s*—'
        )
        self.assertNotIn("version-behind", row)


if __name__ == "__main__":
    unittest.main()
