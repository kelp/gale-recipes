"""Tests for chunk_recipes.py.

The script's stdout contract — the JSON object's shape and
the per-chunk cell cap — is the discover→build→update
pipeline's invariant. The chunker getting it wrong silently
is exactly the failure mode that lost neovim for nine days
on 2026-05-18, so the tests are deliberately paranoid about
boundary conditions.

Run with: ``python3 -m unittest scripts.test_chunk_recipes``
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent))

import chunk_recipes as c  # noqa: E402


THREE_PLATFORMS = [
    {"os": "macos-26", "platform": "darwin-arm64"},
    {"os": "ubuntu-latest", "platform": "linux-amd64"},
    {"os": "ubuntu-24.04-arm", "platform": "linux-arm64"},
]


def _write_platforms(tmp: Path, platforms: list[dict]) -> Path:
    path = tmp / "platforms.json"
    path.write_text(json.dumps(platforms))
    return path


def _write_recipe(
    recipes_dir: Path,
    name: str,
    platforms: list[str] | None = None,
) -> Path:
    d = recipes_dir / name[0]
    d.mkdir(parents=True, exist_ok=True)
    lines = ["[package]", f'name = "{name}"', 'version = "1.0"']
    if platforms is not None:
        lines.append(
            "platforms = ["
            + ", ".join(f'"{p}"' for p in platforms)
            + "]"
        )
    path = d / f"{name}.toml"
    path.write_text("\n".join(lines) + "\n")
    return path


def _write_overrides(tmp: Path, overrides: dict) -> Path:
    path = tmp / "runner-overrides.json"
    path.write_text(json.dumps(overrides))
    return path


class LoadPlatformsTests(unittest.TestCase):
    def test_loads_well_formed_file(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_platforms(Path(tmp), THREE_PLATFORMS)
            self.assertEqual(c.load_platforms(path), THREE_PLATFORMS)

    def test_rejects_empty_list(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_platforms(Path(tmp), [])
            with self.assertRaisesRegex(ValueError, "non-empty"):
                c.load_platforms(path)

    def test_rejects_non_list(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "platforms.json"
            path.write_text('{"os": "ubuntu-latest"}')
            with self.assertRaisesRegex(ValueError, "JSON array"):
                c.load_platforms(path)

    def test_rejects_missing_keys(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_platforms(
                Path(tmp), [{"os": "ubuntu-latest"}]
            )
            with self.assertRaisesRegex(ValueError, "platform"):
                c.load_platforms(path)


class ReadRecipeNamesTests(unittest.TestCase):
    def test_filters_blanks_and_whitespace(self) -> None:
        stream = io.StringIO("foo\n\n   \nbar\n")
        self.assertEqual(c.read_recipe_names(stream), ["bar", "foo"])

    def test_dedup_sorts(self) -> None:
        stream = io.StringIO("zeta\nalpha\nzeta\nalpha\n")
        self.assertEqual(c.read_recipe_names(stream), ["alpha", "zeta"])

    def test_empty_input(self) -> None:
        self.assertEqual(c.read_recipe_names(io.StringIO("")), [])


class BuildCellsTests(unittest.TestCase):
    def test_recipe_major_platform_minor_ordering(self) -> None:
        cells = c.build_cells(["a", "b"], THREE_PLATFORMS)
        self.assertEqual(
            [(x["recipe"], x["platform"]) for x in cells],
            [
                ("a", "darwin-arm64"),
                ("a", "linux-amd64"),
                ("a", "linux-arm64"),
                ("b", "darwin-arm64"),
                ("b", "linux-amd64"),
                ("b", "linux-arm64"),
            ],
        )

    def test_cell_shape_carries_os(self) -> None:
        cells = c.build_cells(["solo"], THREE_PLATFORMS)
        self.assertEqual(set(cells[0]), {"recipe", "platform", "os"})

    def test_empty_recipes_yields_no_cells(self) -> None:
        self.assertEqual(c.build_cells([], THREE_PLATFORMS), [])


class DeclaredPlatformTests(unittest.TestCase):
    """Declared [package].platforms are authoritative: the
    chunker emits cells only for eligible platforms, so a
    linux-only recipe never schedules a darwin job that would
    'skip' (the skip machinery is gone — a build failure is a
    failure, full stop)."""

    def test_undeclared_recipe_gets_all_matrix_cells(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(rdir, "jq")
            cells = c.build_cells(
                ["jq"], THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(len(cells), 3)
            self.assertEqual(
                {x["platform"] for x in cells},
                {"darwin-arm64", "linux-amd64", "linux-arm64"},
            )

    def test_declared_subset_filters_cells(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(
                rdir,
                "traceroute",
                platforms=["linux-amd64", "linux-arm64"],
            )
            cells = c.build_cells(
                ["traceroute"], THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(
                {x["platform"] for x in cells},
                {"linux-amd64", "linux-arm64"},
            )

    def test_declared_platform_outside_matrix_ignored(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(
                rdir,
                "bun",
                platforms=["darwin-arm64", "windows-amd64"],
            )
            cells = c.build_cells(
                ["bun"], THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(
                {x["platform"] for x in cells}, {"darwin-arm64"}
            )

    def test_empty_intersection_is_a_hard_error(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(rdir, "wintool", platforms=["windows-amd64"])
            with self.assertRaisesRegex(ValueError, "wintool"):
                c.build_cells(
                    ["wintool"], THREE_PLATFORMS, recipes_dir=rdir
                )

    def test_missing_recipe_file_treated_as_undeclared(self) -> None:
        # Callers (build.yml discover, verify.yml) validate
        # recipe existence before invoking the chunker; a
        # missing file here degrades to the full matrix, same
        # as the pre-filtering behavior.
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            rdir.mkdir()
            cells = c.build_cells(
                ["ghost"], THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(len(cells), 3)

    def test_mixed_recipes_emit_only_eligible_cells(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(rdir, "jq")
            _write_recipe(rdir, "qemu", platforms=["darwin-arm64"])
            cells = c.build_cells(
                ["jq", "qemu"], THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(
                [(x["recipe"], x["platform"]) for x in cells],
                [
                    ("jq", "darwin-arm64"),
                    ("jq", "linux-amd64"),
                    ("jq", "linux-arm64"),
                    ("qemu", "darwin-arm64"),
                ],
            )


class LoadRunnerOverridesTests(unittest.TestCase):
    """The override map redirects a (recipe, platform) cell onto
    a different GitHub-hosted runner. Values are allowlisted so a
    recipe PR can't point a privileged build at a self-hosted
    label or a typo'd image."""

    def test_missing_file_is_no_overrides(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner-overrides.json"
            self.assertEqual(c.load_runner_overrides(path), {})

    def test_loads_well_formed_map(self) -> None:
        with TemporaryDirectory() as tmp:
            ov = {"herdr": {"darwin-arm64": "macos-15"}}
            path = _write_overrides(Path(tmp), ov)
            self.assertEqual(c.load_runner_overrides(path), ov)

    def test_empty_object_is_valid(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_overrides(Path(tmp), {})
            self.assertEqual(c.load_runner_overrides(path), {})

    def test_rejects_non_object_top_level(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "runner-overrides.json"
            path.write_text('["herdr"]')
            with self.assertRaisesRegex(ValueError, "JSON object"):
                c.load_runner_overrides(path)

    def test_rejects_non_object_recipe_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_overrides(Path(tmp), {"herdr": "macos-15"})
            with self.assertRaisesRegex(ValueError, "herdr"):
                c.load_runner_overrides(path)

    def test_rejects_non_string_runner(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_overrides(
                Path(tmp), {"herdr": {"darwin-arm64": 15}}
            )
            with self.assertRaisesRegex(ValueError, "string"):
                c.load_runner_overrides(path)

    def test_rejects_runner_outside_allowlist(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_overrides(
                Path(tmp),
                {"herdr": {"darwin-arm64": "self-hosted-evil"}},
            )
            # Error names the offending recipe, platform, and value.
            with self.assertRaisesRegex(
                ValueError, "herdr.*darwin-arm64.*self-hosted-evil"
            ):
                c.load_runner_overrides(path)


class RepoRunnerOverridesTests(unittest.TestCase):
    """Pin the *checked-in* override map, not a synthetic one.

    The tests above prove the loader honors whatever map it is
    handed; these prove the map this repo actually ships routes
    the cells we intend. Both recipes here need zig 0.15.2,
    whose link step cannot resolve libSystem against the
    macos-26 runner's SDK (gh#106, gh#194), so their darwin
    cells must land on macos-15.

    Scope note: this asserts the *routing*, which is all the
    chunker decides. Whether zig 0.15.2 actually links on
    macos-15 is a property of the runner image and is only
    provable by a real CI run.
    """

    REPO_ROOT = Path(__file__).resolve().parent.parent

    def _overrides(self) -> dict:
        return c.load_runner_overrides(
            self.REPO_ROOT / ".github" / "runner-overrides.json"
        )

    def test_shipped_map_passes_the_allowlist(self) -> None:
        # load_runner_overrides raises on an unknown runner image,
        # so a clean load is the allowlist assertion.
        self.assertIsInstance(self._overrides(), dict)

    def test_zmx_darwin_pinned_to_macos_15(self) -> None:
        self.assertEqual(
            self._overrides().get("zmx", {}).get("darwin-arm64"),
            "macos-15",
        )

    def test_herdr_darwin_pinned_to_macos_15(self) -> None:
        self.assertEqual(
            self._overrides().get("herdr", {}).get("darwin-arm64"),
            "macos-15",
        )

    def test_zmx_cells_route_through_build_cells(self) -> None:
        # End-to-end through the same call verify.yml and
        # build.yml make: real recipe, real platforms, real
        # override map.
        cells = c.build_cells(
            ["zmx"],
            c.load_platforms(
                self.REPO_ROOT / ".github" / "platforms.json"
            ),
            recipes_dir=self.REPO_ROOT / "recipes",
            overrides=self._overrides(),
        )
        by_platform = {x["platform"]: x["os"] for x in cells}
        self.assertEqual(by_platform["darwin-arm64"], "macos-15")
        # Linux cells build fine on the default runners and must
        # not be redirected.
        for platform, os_name in by_platform.items():
            if platform != "darwin-arm64":
                self.assertNotEqual(os_name, "macos-15")


class BuildCellsOverrideTests(unittest.TestCase):
    """An override only swaps which runner a cell runs on; it
    never adds or removes cells."""

    def test_override_swaps_os_for_matching_cell_only(self) -> None:
        # Fictional recipe name (no file on disk) so eligibility
        # degrades to the full matrix, independent of repo state.
        ov = {"tooly": {"darwin-arm64": "macos-15"}}
        cells = c.build_cells(
            ["tooly"], THREE_PLATFORMS, overrides=ov
        )
        by_platform = {x["platform"]: x["os"] for x in cells}
        self.assertEqual(by_platform["darwin-arm64"], "macos-15")
        self.assertEqual(by_platform["linux-amd64"], "ubuntu-latest")
        self.assertEqual(by_platform["linux-arm64"], "ubuntu-24.04-arm")

    def test_override_scoped_to_named_recipe(self) -> None:
        ov = {"tooly": {"darwin-arm64": "macos-15"}}
        cells = c.build_cells(
            ["tooly", "other"], THREE_PLATFORMS, overrides=ov
        )
        other_darwin = next(
            x for x in cells
            if x["recipe"] == "other" and x["platform"] == "darwin-arm64"
        )
        self.assertEqual(other_darwin["os"], "macos-26")

    def test_override_for_ineligible_platform_is_noop(self) -> None:
        # herdr declares linux only; a darwin override has no cell
        # to rewrite and must not resurrect the darwin cell.
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(
                rdir, "herdr",
                platforms=["linux-amd64", "linux-arm64"],
            )
            ov = {"herdr": {"darwin-arm64": "macos-15"}}
            cells = c.build_cells(
                ["herdr"], THREE_PLATFORMS,
                recipes_dir=rdir, overrides=ov,
            )
            self.assertEqual(
                {x["platform"] for x in cells},
                {"linux-amd64", "linux-arm64"},
            )

    def test_none_and_empty_reproduce_default(self) -> None:
        baseline = c.build_cells(["a", "b"], THREE_PLATFORMS)
        self.assertEqual(
            c.build_cells(["a", "b"], THREE_PLATFORMS, overrides=None),
            baseline,
        )
        self.assertEqual(
            c.build_cells(["a", "b"], THREE_PLATFORMS, overrides={}),
            baseline,
        )


class ChunkCellsTests(unittest.TestCase):
    """The per-chunk size cap is the contract. Test it
    around every boundary."""

    def test_empty_input(self) -> None:
        self.assertEqual(c.chunk_cells([]), [])

    def test_single_cell(self) -> None:
        self.assertEqual(
            c.chunk_cells([{"recipe": "x"}]),
            [[{"recipe": "x"}]],
        )

    def test_exactly_cap_fits_in_one_chunk(self) -> None:
        cells = [{"i": i} for i in range(c.MAX_CELLS_PER_CHUNK)]
        chunks = c.chunk_cells(cells)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(chunks[0]), c.MAX_CELLS_PER_CHUNK)

    def test_cap_plus_one_splits_into_two(self) -> None:
        cells = [{"i": i} for i in range(c.MAX_CELLS_PER_CHUNK + 1)]
        chunks = c.chunk_cells(cells)
        self.assertEqual(len(chunks), 2)
        self.assertEqual(len(chunks[0]), c.MAX_CELLS_PER_CHUNK)
        self.assertEqual(len(chunks[1]), 1)

    def test_no_chunk_exceeds_cap(self) -> None:
        """Pin the invariant explicitly — a future regression
        that bumps chunk size past the cap would silently lose
        jobs in CI."""
        cells = [{"i": i} for i in range(c.MAX_CELLS_PER_CHUNK * 5 + 7)]
        chunks = c.chunk_cells(cells)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), c.MAX_CELLS_PER_CHUNK)

    def test_cells_preserved_across_chunks(self) -> None:
        """No cells lost or duplicated by chunking."""
        cells = [{"i": i} for i in range(523)]
        chunks = c.chunk_cells(cells)
        flat = [cell for chunk in chunks for cell in chunk]
        self.assertEqual(flat, cells)


class MainTests(unittest.TestCase):
    """End-to-end: stdin in, JSON object out, exit 0."""

    def _run(
        self,
        stdin_text: str,
        platforms: list[dict],
        recipes_dir: Path | None = None,
    ):
        with TemporaryDirectory() as tmp:
            path = _write_platforms(Path(tmp), platforms)
            argv = ["--platforms", str(path)]
            if recipes_dir is not None:
                argv += ["--recipes-dir", str(recipes_dir)]
            old_stdin, old_stdout = sys.stdin, sys.stdout
            sys.stdin = io.StringIO(stdin_text)
            sys.stdout = io.StringIO()
            try:
                rc = c.main(argv)
                out = sys.stdout.getvalue()
            finally:
                sys.stdin, sys.stdout = old_stdin, old_stdout
        return rc, out

    def test_declared_subset_filters_through_main(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(
                rdir, "traceroute", platforms=["linux-amd64"]
            )
            rc, out = self._run(
                "traceroute\n", THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(rc, 0)
            doc = json.loads(out)
            self.assertEqual(doc["all_recipes"], ["traceroute"])
            self.assertEqual(len(doc["chunks"]), 1)
            self.assertEqual(
                [x["platform"] for x in doc["chunks"][0]],
                ["linux-amd64"],
            )

    def test_empty_intersection_returns_two_through_main(self) -> None:
        with TemporaryDirectory() as tmp:
            rdir = Path(tmp) / "recipes"
            _write_recipe(rdir, "wintool", platforms=["windows-amd64"])
            rc, _ = self._run(
                "wintool\n", THREE_PLATFORMS, recipes_dir=rdir
            )
            self.assertEqual(rc, 2)

    def test_empty_input_emits_empty_chunks(self) -> None:
        rc, out = self._run("", THREE_PLATFORMS)
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["chunks"], [])
        self.assertEqual(doc["all_recipes"], [])
        self.assertEqual(doc["platforms"], THREE_PLATFORMS)

    def test_single_recipe_three_platforms_one_chunk(self) -> None:
        rc, out = self._run("neovim\n", THREE_PLATFORMS)
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        self.assertEqual(doc["all_recipes"], ["neovim"])
        self.assertEqual(len(doc["chunks"]), 1)
        self.assertEqual(len(doc["chunks"][0]), 3)
        platforms_in_chunk = {
            cell["platform"] for cell in doc["chunks"][0]
        }
        self.assertEqual(
            platforms_in_chunk,
            {"darwin-arm64", "linux-amd64", "linux-arm64"},
        )

    def test_high_recipe_count_packs_into_multiple_chunks(self) -> None:
        # MAX_CELLS_PER_CHUNK is 255 today; 200 recipes × 3
        # platforms = 600 cells → 3 chunks (255+255+90).
        # The math should hold regardless of exact cap value.
        n_recipes = (c.MAX_CELLS_PER_CHUNK // 3) * 2 + 30
        stdin = "\n".join(f"r{i:04d}" for i in range(n_recipes)) + "\n"
        rc, out = self._run(stdin, THREE_PLATFORMS)
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        total_cells = sum(len(chunk) for chunk in doc["chunks"])
        self.assertEqual(total_cells, n_recipes * 3)
        for chunk in doc["chunks"]:
            self.assertLessEqual(len(chunk), c.MAX_CELLS_PER_CHUNK)

    def test_adding_a_platform_repacks_automatically(self) -> None:
        """The killer feature of the platforms.json indirection:
        a hypothetical fourth platform just makes cells denser
        without requiring chunk-size tuning."""
        four_platforms = THREE_PLATFORMS + [
            {"os": "windows-latest", "platform": "windows-amd64"},
        ]
        stdin = "\n".join(f"r{i:03d}" for i in range(100)) + "\n"
        rc, out = self._run(stdin, four_platforms)
        self.assertEqual(rc, 0)
        doc = json.loads(out)
        # 100 recipes × 4 platforms = 400 cells, packs into
        # ceil(400 / MAX_CELLS_PER_CHUNK) chunks.
        self.assertEqual(
            sum(len(chunk) for chunk in doc["chunks"]),
            400,
        )
        for chunk in doc["chunks"]:
            self.assertLessEqual(len(chunk), c.MAX_CELLS_PER_CHUNK)

    def test_bad_platforms_path_returns_two(self) -> None:
        rc, _ = self._run("foo\n", [])  # writes empty list, which fails load
        self.assertEqual(rc, 2)


class CapConstantTests(unittest.TestCase):
    """The cap is the only number that's documented externally;
    pin its identity so a future copy-paste from the bug report
    doesn't drift."""

    def test_cap_matches_gh_documented_value(self) -> None:
        self.assertEqual(c.GH_MATRIX_CELL_CAP, 256)

    def test_margin_is_one_cell(self) -> None:
        self.assertEqual(c.SAFETY_MARGIN, 1)

    def test_effective_budget_derives_cleanly(self) -> None:
        self.assertEqual(
            c.MAX_CELLS_PER_CHUNK,
            c.GH_MATRIX_CELL_CAP - c.SAFETY_MARGIN,
        )


if __name__ == "__main__":
    unittest.main()
