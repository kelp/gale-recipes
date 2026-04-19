#!/usr/bin/env python3
"""Generate a static build-status dashboard for gale-recipes.

Walks ``recipes/<letter>/<name>.toml``, reads each sibling
``<name>.binaries.toml`` and ``<name>.versions``, and writes
an ``_site/`` tree:

    _site/
      index.html
      recipes/<name>.html
      status.json
      status.md
      styles.css
      app.js

An absent platform entry in ``.binaries.toml`` renders as a
failed build (red). Version skew between ``[package].version``
and the ``.binaries.toml`` version renders as a "stale" pill,
not a failure.

``status.md`` is a concise human- and Claude-readable report
for triage: summary counts, failures grouped by platform,
then a full table. ``status.json`` is the machine-readable
sidecar with the same data.

Stdlib only — no third-party dependencies.
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit("gen_status_page.py requires Python 3.11+ (tomllib)")

import tomllib


PLATFORMS: tuple[str, ...] = (
    "darwin-arm64",
    "linux-amd64",
    "linux-arm64",
)

REPO_URL = "https://github.com/kelp/gale-recipes"


@dataclass
class Platform:
    ok: bool
    sha256: str | None


@dataclass
class VersionEntry:
    version: str
    commit: str


@dataclass
class Recipe:
    name: str
    letter: str
    recipe_path: str
    version: str
    description: str
    homepage: str
    license: str
    binaries_version: str | None
    platforms: dict[str, Platform]
    versions_history: list[VersionEntry]

    @property
    def all_green(self) -> bool:
        return all(p.ok for p in self.platforms.values())

    @property
    def any_red(self) -> bool:
        return any(not p.ok for p in self.platforms.values())

    @property
    def is_stale(self) -> bool:
        return (
            self.binaries_version is not None
            and self.binaries_version != self.version
        )

    def failing_platforms(self) -> list[str]:
        return [p for p in PLATFORMS if not self.platforms[p].ok]

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "letter": self.letter,
            "recipe_path": self.recipe_path,
            "version": self.version,
            "description": self.description,
            "homepage": self.homepage,
            "license": self.license,
            "binaries_version": self.binaries_version,
            "stale": self.is_stale,
            "platforms": {
                p: {"ok": v.ok, "sha256": v.sha256}
                for p, v in self.platforms.items()
            },
            "versions_history": [
                {"version": v.version, "commit": v.commit}
                for v in self.versions_history
            ],
        }


# ---------- loading ----------


def load_recipe(
    toml_path: Path, repo_root: Path
) -> Recipe | None:
    """Parse a recipe TOML and its sibling files. Return
    None if the file is not a recipe (e.g. a .binaries.toml
    or a malformed file)."""
    if toml_path.name.endswith(".binaries.toml"):
        return None
    try:
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        print(
            f"warning: could not parse {toml_path}: {e}",
            file=sys.stderr,
        )
        return None

    pkg = data.get("package") or {}
    name = pkg.get("name")
    if not isinstance(name, str) or not name:
        return None

    def pkg_str(key: str) -> str:
        v = pkg.get(key)
        return v if isinstance(v, str) else ""

    binaries_path = toml_path.with_name(f"{name}.binaries.toml")
    binaries_version: str | None = None
    platforms: dict[str, Platform] = {
        p: Platform(ok=False, sha256=None) for p in PLATFORMS
    }
    if binaries_path.exists():
        try:
            with binaries_path.open("rb") as f:
                b = tomllib.load(f)
            bv = b.get("version")
            if isinstance(bv, str):
                binaries_version = bv
            for p in PLATFORMS:
                entry = b.get(p)
                if isinstance(entry, dict):
                    sha = entry.get("sha256")
                    if isinstance(sha, str) and sha:
                        platforms[p] = Platform(
                            ok=True, sha256=sha
                        )
        except (OSError, tomllib.TOMLDecodeError) as e:
            print(
                f"warning: could not parse {binaries_path}: {e}",
                file=sys.stderr,
            )

    versions_path = toml_path.with_name(f"{name}.versions")
    history: list[VersionEntry] = []
    if versions_path.exists():
        try:
            for line in versions_path.read_text().splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    history.append(
                        VersionEntry(parts[0], parts[1])
                    )
        except OSError as e:
            print(
                f"warning: could not read {versions_path}: {e}",
                file=sys.stderr,
            )

    rel = toml_path.relative_to(repo_root).as_posix()
    return Recipe(
        name=name,
        letter=name[0],
        recipe_path=rel,
        version=pkg_str("version"),
        description=pkg_str("description"),
        homepage=pkg_str("homepage"),
        license=pkg_str("license"),
        binaries_version=binaries_version,
        platforms=platforms,
        versions_history=history,
    )


def load_all_recipes(repo_root: Path) -> list[Recipe]:
    recipes_dir = repo_root / "recipes"
    if not recipes_dir.is_dir():
        sys.exit(f"recipes dir not found: {recipes_dir}")
    out: list[Recipe] = []
    for toml_path in sorted(recipes_dir.glob("*/*.toml")):
        if toml_path.name.endswith(".binaries.toml"):
            continue
        r = load_recipe(toml_path, repo_root)
        if r is not None:
            out.append(r)
    out.sort(key=lambda r: r.name)
    return out


# ---------- rendering helpers ----------


def stale_pill_html(r: Recipe) -> str:
    if not r.is_stale:
        return ""
    title = (
        f"recipe at {r.version}, binaries at "
        f"{r.binaries_version or ''}"
    )
    return (
        f' <span class="pill stale" title="{html.escape(title)}">'
        "stale</span>"
    )


def platform_cell_html(p: Platform) -> str:
    if p.ok:
        return '<td class="ok" aria-label="built">✓</td>'
    return '<td class="fail" aria-label="failed">✗</td>'


# ---------- index page ----------


def render_index(recipes: list[Recipe]) -> str:
    total = len(recipes)
    all_green = sum(1 for r in recipes if r.all_green)
    with_fail = sum(1 for r in recipes if r.any_red)
    stale = sum(1 for r in recipes if r.is_stale)
    per_plat = {
        p: sum(1 for r in recipes if r.platforms[p].ok)
        for p in PLATFORMS
    }

    rows: list[str] = []
    for r in recipes:
        row_class = "row-stale" if r.is_stale else ""
        cells = [
            f'<tr class="{row_class}" '
            f'data-name="{html.escape(r.name)}">',
            '<td class="name">'
            f'<a href="recipes/{html.escape(r.name)}.html">'
            f"{html.escape(r.name)}</a>"
            f"{stale_pill_html(r)}</td>",
            f'<td class="version">{html.escape(r.version)}</td>',
        ]
        for p in PLATFORMS:
            cells.append(platform_cell_html(r.platforms[p]))
        cells.append("</tr>")
        rows.append("".join(cells))

    summary = (
        f"{all_green} of {total} recipes green on all platforms · "
        f"{with_fail} with failures · {stale} stale"
    )
    per_plat_bits = " · ".join(
        f"{p}: {per_plat[p]}/{total}" for p in PLATFORMS
    )
    rows_html = "\n      ".join(rows)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>gale-recipes · build status</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="styles.css">
</head>
<body>
<header>
  <h1>gale-recipes build status</h1>
  <p class="summary">{summary}</p>
  <p class="subsummary">{per_plat_bits}</p>
  <p class="repo-link"><a href="{REPO_URL}">kelp/gale-recipes</a> ·
    <a href="status.json">status.json</a> ·
    <a href="status.md">status.md</a></p>
</header>
<main>
  <div class="filter">
    <input id="filter" type="search"
           placeholder="Filter recipes…" autocomplete="off">
    <label><input type="checkbox" id="failing-only">
      failing only</label>
  </div>
  <table id="status">
    <thead>
      <tr>
        <th data-sort="name">recipe</th>
        <th data-sort="version">version</th>
        <th data-sort="darwin-arm64">darwin-arm64</th>
        <th data-sort="linux-amd64">linux-amd64</th>
        <th data-sort="linux-arm64">linux-arm64</th>
      </tr>
    </thead>
    <tbody>
      {rows_html}
    </tbody>
  </table>
</main>
<footer>
  <p>Built from <code>.binaries.toml</code> files. Absent
     platform entry = failed build.</p>
</footer>
<script src="app.js"></script>
</body>
</html>
"""


# ---------- per-recipe detail page ----------


def render_recipe_page(recipe: Recipe) -> str:
    plat_rows: list[str] = []
    for p in PLATFORMS:
        plat = recipe.platforms[p]
        status = (
            '<span class="ok">✓ built</span>'
            if plat.ok
            else '<span class="fail">✗ failed</span>'
        )
        sha = (
            f'<code>{html.escape(plat.sha256)}</code>'
            if plat.sha256
            else '<span class="muted">—</span>'
        )
        plat_rows.append(
            f"<tr><td>{p}</td><td>{status}</td>"
            f'<td class="sha">{sha}</td></tr>'
        )
    platforms_table = "\n        ".join(plat_rows)

    if recipe.versions_history:
        hist_rows = []
        for v in recipe.versions_history:
            short = v.commit[:7]
            commit_url = f"{REPO_URL}/commit/{html.escape(v.commit)}"
            hist_rows.append(
                f"<tr><td>{html.escape(v.version)}</td>"
                f'<td><a href="{commit_url}">'
                f"<code>{short}</code></a></td></tr>"
            )
        history_html = (
            "<table class=\"history\">"
            "<thead><tr><th>version</th><th>commit</th></tr></thead>"
            "<tbody>" + "".join(hist_rows) + "</tbody></table>"
        )
    else:
        history_html = '<p class="muted">no history recorded</p>'

    homepage_html = (
        f'<a href="{html.escape(recipe.homepage)}">'
        f"{html.escape(recipe.homepage)}</a>"
        if recipe.homepage
        else '<span class="muted">—</span>'
    )
    license_html = (
        html.escape(recipe.license)
        if recipe.license
        else '<span class="muted">—</span>'
    )
    recipe_url = (
        f"{REPO_URL}/blob/main/{html.escape(recipe.recipe_path)}"
    )
    binaries_version_html = (
        html.escape(recipe.binaries_version)
        if recipe.binaries_version is not None
        else '<span class="muted">not yet built</span>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{html.escape(recipe.name)} · gale-recipes</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="../styles.css">
</head>
<body>
<header>
  <p class="crumbs"><a href="../index.html">← all recipes</a></p>
  <h1>{html.escape(recipe.name)}{stale_pill_html(recipe)}</h1>
  <p class="description">{html.escape(recipe.description)}</p>
</header>
<main>
  <section>
    <h2>metadata</h2>
    <dl>
      <dt>recipe version</dt>
      <dd>{html.escape(recipe.version)}</dd>
      <dt>binaries version</dt>
      <dd>{binaries_version_html}</dd>
      <dt>license</dt>
      <dd>{license_html}</dd>
      <dt>homepage</dt>
      <dd>{homepage_html}</dd>
      <dt>recipe</dt>
      <dd><a href="{recipe_url}">
          <code>{html.escape(recipe.recipe_path)}</code></a></dd>
    </dl>
  </section>
  <section>
    <h2>platforms</h2>
    <table>
      <thead><tr><th>platform</th><th>status</th><th>sha256</th></tr></thead>
      <tbody>
        {platforms_table}
      </tbody>
    </table>
  </section>
  <section>
    <h2>version history</h2>
    {history_html}
  </section>
</main>
<footer>
  <p><a href="../index.html">← all recipes</a></p>
</footer>
</body>
</html>
"""


# ---------- markdown sidecar ----------


def render_status_md(recipes: list[Recipe]) -> str:
    total = len(recipes)
    all_green = sum(1 for r in recipes if r.all_green)
    with_fail = sum(1 for r in recipes if r.any_red)
    stale = sum(1 for r in recipes if r.is_stale)
    per_plat = {
        p: sum(1 for r in recipes if r.platforms[p].ok)
        for p in PLATFORMS
    }

    lines: list[str] = []
    lines.append("# gale-recipes build status")
    lines.append("")
    lines.append(f"- Total recipes: **{total}**")
    lines.append(
        f"- Green on all platforms: **{all_green}**"
    )
    lines.append(f"- With failures: **{with_fail}**")
    lines.append(f"- Stale (version skew): **{stale}**")
    lines.append("")
    lines.append("Per platform:")
    for p in PLATFORMS:
        lines.append(f"- `{p}`: {per_plat[p]}/{total}")
    lines.append("")

    # Failures grouped by platform — the triage view.
    lines.append("## Failing builds by platform")
    lines.append("")
    any_failure = False
    for p in PLATFORMS:
        failing = [r for r in recipes if not r.platforms[p].ok]
        if not failing:
            continue
        any_failure = True
        lines.append(f"### `{p}` ({len(failing)})")
        lines.append("")
        for r in failing:
            lines.append(
                f"- `{r.name}` {r.version} — {r.recipe_path}"
            )
        lines.append("")
    if not any_failure:
        lines.append("All platforms green. 🎉")
        lines.append("")

    # Stale recipes.
    stale_recipes = [r for r in recipes if r.is_stale]
    if stale_recipes:
        lines.append("## Stale recipes (version skew)")
        lines.append("")
        lines.append(
            "Recipe version differs from `.binaries.toml` — "
            "a rebuild is pending."
        )
        lines.append("")
        for r in stale_recipes:
            lines.append(
                f"- `{r.name}`: recipe {r.version}, "
                f"binaries {r.binaries_version}"
            )
        lines.append("")

    # Full table (useful for scanning).
    lines.append("## Full status")
    lines.append("")
    header = ["recipe", "version"] + list(PLATFORMS)
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")
    for r in recipes:
        cells = [f"`{r.name}`", r.version]
        for p in PLATFORMS:
            cells.append("✓" if r.platforms[p].ok else "✗")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    return "\n".join(lines)


# ---------- driver ----------


def write_outputs(
    recipes: list[Recipe], out_dir: Path, templates_dir: Path
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "recipes").mkdir(exist_ok=True)

    (out_dir / "index.html").write_text(render_index(recipes))
    for r in recipes:
        (out_dir / "recipes" / f"{r.name}.html").write_text(
            render_recipe_page(r)
        )

    (out_dir / "status.json").write_text(
        json.dumps(
            {
                "platforms": list(PLATFORMS),
                "recipes": [r.to_json() for r in recipes],
            },
            indent=2,
        )
        + "\n"
    )
    (out_dir / "status.md").write_text(render_status_md(recipes))

    # Copy static assets.
    for asset in ("styles.css", "app.js"):
        shutil.copyfile(templates_dir / asset, out_dir / asset)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="repo root (default: .)",
    )
    ap.add_argument(
        "--out-dir",
        type=Path,
        default=Path("_site"),
        help="output directory (default: _site)",
    )
    ap.add_argument(
        "--templates-dir",
        type=Path,
        default=None,
        help="directory with styles.css and app.js "
        "(default: <script_dir>/templates)",
    )
    args = ap.parse_args()

    repo_root = args.repo_root.resolve()
    out_dir = args.out_dir.resolve()
    templates_dir = (
        args.templates_dir
        if args.templates_dir
        else Path(__file__).resolve().parent / "templates"
    )
    if not templates_dir.is_dir():
        sys.exit(
            f"templates dir not found: {templates_dir}"
        )

    recipes = load_all_recipes(repo_root)
    write_outputs(recipes, out_dir, templates_dir)
    print(
        f"wrote {len(recipes)} recipe pages to {out_dir}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
