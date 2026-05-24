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
from datetime import date
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

# A recipe behind upstream graduates from "outdated"
# (informational) to "stale" (needs attention) once the
# upstream release is this many days old.
STALE_UPSTREAM_AGE_DAYS = 7


@dataclass
class Platform:
    # "ok"   — built; sha256 is set
    # "fail" — eligible but no binary (real failure)
    # "na"   — recipe excludes this platform via
    #          [package].platforms; not a failure
    state: str
    sha256: str | None

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    @property
    def is_failing(self) -> bool:
        return self.state == "fail"

    @property
    def is_na(self) -> bool:
        return self.state == "na"


@dataclass
class VersionEntry:
    version: str
    commit: str


@dataclass
class Upstream:
    """Upstream release status for a recipe, loaded from
    ``_data/upstream.json``. Written by the daily auto-update
    workflow."""

    status: str  # up_to_date | outdated | tampered | untracked | error
    current_version: str
    checked_at: str
    latest_version: str | None = None
    latest_released_at: str | None = None  # YYYY-MM-DD
    latest_release_url: str | None = None
    reason: str | None = None
    # Tier-1 supply-chain fields, all optional. Older
    # upstream.json entries (pre-rollout) won't have any.
    vulnerabilities: list[dict] | None = None
    swh_archived: bool | None = None
    swh_revision: str | None = None
    repo_id: str | None = None
    owner_id: str | None = None
    # "release" (default — /releases/latest) or "tag"
    # (fallback — /repos/{repo}/tags for projects that don't
    # publish releases). Pre-rollout entries are None.
    source_type: str | None = None
    first_observed_commit_sha: str | None = None

    @property
    def is_outdated(self) -> bool:
        return self.status == "outdated"

    @property
    def is_tampered(self) -> bool:
        return self.status == "tampered"

    @property
    def is_tracked(self) -> bool:
        return self.status in ("up_to_date", "outdated", "tampered")

    @property
    def has_current_vulns(self) -> bool:
        """True if any recorded advisory affects the
        currently-shipped version. Renders even on
        ``up_to_date`` rows."""
        return any(
            "current" in (v.get("applies_to") or [])
            for v in (self.vulnerabilities or [])
        )

    @property
    def has_upstream_vulns(self) -> bool:
        """True if any recorded advisory affects the
        proposed bump-to version."""
        return any(
            "upstream" in (v.get("applies_to") or [])
            for v in (self.vulnerabilities or [])
        )

    def age_days(self, today: date | None = None) -> int | None:
        """Days since upstream released ``latest_version``.
        Computed at render time so the pill stays accurate
        between daily regenerations."""
        if not self.latest_released_at:
            return None
        try:
            released = date.fromisoformat(self.latest_released_at)
        except ValueError:
            return None
        return ((today or date.today()) - released).days

    def to_json(self) -> dict:
        out: dict = {
            "status": self.status,
            "current_version": self.current_version,
            "checked_at": self.checked_at,
        }
        if self.latest_version:
            out["latest_version"] = self.latest_version
        if self.latest_released_at:
            out["latest_released_at"] = self.latest_released_at
            age = self.age_days()
            if age is not None:
                out["age_days"] = age
        if self.latest_release_url:
            out["latest_release_url"] = self.latest_release_url
        if self.reason:
            out["reason"] = self.reason
        if self.vulnerabilities:
            out["vulnerabilities"] = self.vulnerabilities
        if self.swh_archived is not None:
            out["swh_archived"] = self.swh_archived
        if self.swh_revision:
            out["swh_revision"] = self.swh_revision
        if self.source_type:
            out["source_type"] = self.source_type
        if self.first_observed_commit_sha:
            out["first_observed_commit_sha"] = (
                self.first_observed_commit_sha
            )
        return out


@dataclass
class Recipe:
    name: str
    letter: str
    recipe_path: str
    version: str
    revision: int
    description: str
    homepage: str
    license: str
    binaries_version: str | None
    platforms: dict[str, Platform]
    eligible_platforms: tuple[str, ...]
    versions_history: list[VersionEntry]
    upstream: Upstream | None = None

    @property
    def all_green(self) -> bool:
        # n/a counts as fine — design, not failure.
        return not any(p.is_failing for p in self.platforms.values())

    @property
    def any_red(self) -> bool:
        return any(p.is_failing for p in self.platforms.values())

    @property
    def expected_binaries_version(self) -> str:
        # .binaries.toml writes the joined "X.Y.Z-N" form
        # when revision > 1, bare version otherwise.
        if self.revision > 1:
            return f"{self.version}-{self.revision}"
        return self.version

    @property
    def is_stale_drift(self) -> bool:
        """Recipe and binaries disagree on version. CI hasn't
        rebuilt yet."""
        return (
            self.binaries_version is not None
            and self.binaries_version != self.expected_binaries_version
        )

    def is_stale_upstream_on(self, today: date | None = None) -> bool:
        """Behind upstream by at least STALE_UPSTREAM_AGE_DAYS
        days. Today is parameterized so tests don't depend on
        the wall clock."""
        u = self.upstream
        if u is None or not u.is_outdated:
            return False
        age = u.age_days(today)
        return age is not None and age >= STALE_UPSTREAM_AGE_DAYS

    def is_stale_on(self, today: date | None = None) -> bool:
        return self.is_stale_drift or self.is_stale_upstream_on(today)

    @property
    def is_stale(self) -> bool:
        return self.is_stale_on()

    @property
    def is_outdated(self) -> bool:
        return self.upstream is not None and self.upstream.is_outdated

    def failing_platforms(self) -> list[str]:
        return [p for p in PLATFORMS if self.platforms[p].is_failing]

    def to_json(self) -> dict:
        out = {
            "name": self.name,
            "letter": self.letter,
            "recipe_path": self.recipe_path,
            "version": self.version,
            "description": self.description,
            "homepage": self.homepage,
            "license": self.license,
            "binaries_version": self.binaries_version,
            "stale": self.is_stale,
            "eligible_platforms": list(self.eligible_platforms),
            "platforms": {
                p: {"state": v.state, "sha256": v.sha256}
                for p, v in self.platforms.items()
            },
            "versions_history": [
                {"version": v.version, "commit": v.commit}
                for v in self.versions_history
            ],
        }
        if self.upstream is not None:
            out["upstream"] = self.upstream.to_json()
        return out


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

    rev = pkg.get("revision")
    revision = rev if isinstance(rev, int) and rev >= 1 else 1

    # A recipe may declare [package].platforms to restrict
    # which targets it builds for (e.g. linux-only tools).
    # Anything outside that list is "n/a", not a failure.
    declared = pkg.get("platforms")
    if isinstance(declared, list):
        eligible = tuple(
            p for p in PLATFORMS
            if isinstance(p, str) and p in declared
        )
    else:
        eligible = PLATFORMS

    binaries_path = toml_path.with_name(f"{name}.binaries.toml")
    binaries_version: str | None = None
    platforms: dict[str, Platform] = {
        p: Platform(
            state=("fail" if p in eligible else "na"),
            sha256=None,
        )
        for p in PLATFORMS
    }
    if binaries_path.exists():
        try:
            with binaries_path.open("rb") as f:
                b = tomllib.load(f)
            bv = b.get("version")
            if isinstance(bv, str):
                binaries_version = bv
            for p in PLATFORMS:
                if p not in eligible:
                    continue
                entry = b.get(p)
                if isinstance(entry, dict):
                    sha = entry.get("sha256")
                    if isinstance(sha, str) and sha:
                        platforms[p] = Platform(
                            state="ok", sha256=sha
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
        revision=revision,
        description=pkg_str("description"),
        homepage=pkg_str("homepage"),
        license=pkg_str("license"),
        binaries_version=binaries_version,
        platforms=platforms,
        eligible_platforms=eligible,
        versions_history=history,
    )


def load_upstream_map(
    repo_root: Path,
) -> dict[str, Upstream]:
    """Parse ``_data/upstream.json`` into a name→Upstream map.
    Returns an empty map if the file is missing (first run,
    before the auto-update workflow has ever succeeded)."""
    path = repo_root / "_data" / "upstream.json"
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(
            f"warning: could not parse {path}: {e}",
            file=sys.stderr,
        )
        return {}
    recipes = data.get("recipes")
    if not isinstance(recipes, dict):
        return {}
    out: dict[str, Upstream] = {}
    for name, entry in recipes.items():
        if not isinstance(entry, dict):
            continue
        status = entry.get("status")
        if not isinstance(status, str):
            continue
        current = entry.get("current_version")
        checked = entry.get("checked_at")
        if not isinstance(current, str) or not isinstance(checked, str):
            continue

        def _opt(key: str) -> str | None:
            v = entry.get(key)
            return v if isinstance(v, str) and v else None

        vulns_raw = entry.get("vulnerabilities")
        vulns = (
            [v for v in vulns_raw if isinstance(v, dict)]
            if isinstance(vulns_raw, list)
            else None
        )
        swh = entry.get("swh_archived")
        swh = swh if isinstance(swh, bool) else None
        out[name] = Upstream(
            status=status,
            current_version=current,
            checked_at=checked,
            latest_version=_opt("latest_version"),
            latest_released_at=_opt("latest_released_at"),
            latest_release_url=_opt("latest_release_url"),
            reason=_opt("reason"),
            vulnerabilities=vulns,
            swh_archived=swh,
            swh_revision=_opt("swh_revision"),
            repo_id=_opt("repo_id"),
            owner_id=_opt("owner_id"),
            source_type=_opt("source_type"),
            first_observed_commit_sha=_opt("first_observed_commit_sha"),
        )
    return out


def load_all_recipes(repo_root: Path) -> list[Recipe]:
    recipes_dir = repo_root / "recipes"
    if not recipes_dir.is_dir():
        sys.exit(f"recipes dir not found: {recipes_dir}")
    upstream_map = load_upstream_map(repo_root)
    out: list[Recipe] = []
    for toml_path in sorted(recipes_dir.glob("*/*.toml")):
        if toml_path.name.endswith(".binaries.toml"):
            continue
        r = load_recipe(toml_path, repo_root)
        if r is not None:
            r.upstream = upstream_map.get(r.name)
            out.append(r)
    out.sort(key=lambda r: r.name)
    return out


# ---------- rendering helpers ----------


def stale_pill_html(r: Recipe) -> str:
    if not r.is_stale:
        return ""
    reasons: list[str] = []
    if r.is_stale_drift:
        reasons.append(
            f"recipe at {r.expected_binaries_version}, binaries at "
            f"{r.binaries_version or ''}"
        )
    if r.is_stale_upstream_on():
        u = r.upstream
        assert u is not None and u.latest_version is not None
        age = u.age_days()
        age_bit = f" · {_age_phrase(age)}" if age is not None else ""
        reasons.append(f"upstream {u.latest_version}{age_bit}")
    title = " · ".join(reasons)
    return (
        f' <span class="pill stale" title="{html.escape(title)}">'
        "stale</span>"
    )


def _age_phrase(days: int) -> str:
    if days < 1:
        return "today"
    if days == 1:
        return "1d ago"
    return f"{days}d ago"


def upstream_pill_html(r: Recipe) -> str:
    u = r.upstream
    if u is None:
        return ""
    if u.status == "up_to_date":
        # No pill when current — keeps the row quiet.
        return ""
    if u.status == "outdated" and u.latest_version:
        age = u.age_days()
        age_bit = f" · {_age_phrase(age)}" if age is not None else ""
        title = (
            f"upstream {u.latest_version}"
            f" (released {u.latest_released_at or '?'})"
        )
        return (
            f' <span class="pill outdated" title="{html.escape(title)}">'
            f"upstream {html.escape(u.latest_version)}{age_bit}"
            "</span>"
        )
    if u.status == "tampered":
        # sha256 mismatch on same version, or upstream
        # attestation failed. Explicit red pill — the whole
        # point of the auto-update cooldown is to surface
        # this.
        title = u.reason or "upstream artifact changed after first observation"
        latest = u.latest_version or "?"
        return (
            f' <span class="pill tampered" title="{html.escape(title)}">'
            f"tampered ({html.escape(latest)})"
            "</span>"
        )
    # untracked or error
    title = u.reason or u.status
    return (
        f' <span class="pill untracked" title="{html.escape(title)}">'
        "untracked</span>"
    )


def upstream_cell_html(r: Recipe) -> str:
    """Render the upstream-version column cell. Shows the
    latest upstream version when known (same string as our
    own version when up-to-date), the new version in an
    "upstream-newer" cell when behind, or a muted dash when
    upstream is untracked."""
    u = r.upstream
    if u is None or u.status in ("untracked", "error"):
        return '<td class="upstream muted">—</td>'
    if u.status == "up_to_date":
        v = u.latest_version or r.version
        return f'<td class="upstream">{html.escape(v)}</td>'
    if u.status == "outdated" and u.latest_version:
        url = u.latest_release_url or ""
        label = html.escape(u.latest_version)
        inner = (
            f'<a href="{html.escape(url)}">{label}</a>'
            if url else label
        )
        return f'<td class="upstream upstream-newer">{inner}</td>'
    if u.status == "tampered":
        latest = u.latest_version or "?"
        return (
            '<td class="upstream upstream-tampered">'
            f'{html.escape(latest)}</td>'
        )
    return '<td class="upstream muted">—</td>'


def vulnerability_pill_html(r: Recipe) -> str:
    """Render a `vulnerable` pill on any recipe whose
    currently-shipped version matches a published GHSA.
    Stacks with the upstream/tampered/stale pills — the
    signal is independent."""
    u = r.upstream
    if u is None or not u.has_current_vulns:
        return ""
    cves = sorted({
        v.get("cve_id") or v.get("ghsa_id") or "advisory"
        for v in (u.vulnerabilities or [])
        if "current" in (v.get("applies_to") or [])
    })
    title = "; ".join(cves) if cves else "GHSA match"
    return (
        f' <span class="pill vulnerable" title="{html.escape(title)}">'
        f"vulnerable ({len(cves)})"
        "</span>"
    )


def _per_platform_counts(
    recipes: list[Recipe],
) -> dict[str, tuple[int, int]]:
    """For each platform return ``(built, eligible)``.
    n/a recipes are excluded from the denominator so the
    success rate isn't deflated by linux-only or macOS-only
    tools."""
    out: dict[str, tuple[int, int]] = {}
    for p in PLATFORMS:
        eligible = sum(
            1 for r in recipes if not r.platforms[p].is_na
        )
        built = sum(
            1 for r in recipes if r.platforms[p].state == "ok"
        )
        out[p] = (built, eligible)
    return out


def platform_cell_html(p: Platform) -> str:
    if p.state == "ok":
        return '<td class="ok" aria-label="built">✓</td>'
    if p.state == "na":
        return (
            '<td class="na" aria-label="not applicable" '
            'title="recipe excludes this platform">—</td>'
        )
    return '<td class="fail" aria-label="failed">✗</td>'


# ---------- index page ----------


def render_index(recipes: list[Recipe]) -> str:
    total = len(recipes)
    all_green = sum(1 for r in recipes if r.all_green)
    with_fail = sum(1 for r in recipes if r.any_red)
    stale = sum(1 for r in recipes if r.is_stale)
    outdated = sum(1 for r in recipes if r.is_outdated)
    per_plat = _per_platform_counts(recipes)

    rows: list[str] = []
    for r in recipes:
        row_classes = []
        if r.is_stale:
            row_classes.append("row-stale")
        if r.is_outdated:
            row_classes.append("row-outdated")
        row_class = " ".join(row_classes)
        data_outdated = "true" if r.is_outdated else "false"
        version_cls = "version"
        u = r.upstream
        if u is not None and u.status in ("outdated", "tampered"):
            version_cls += " version-behind"
        cells = [
            f'<tr class="{row_class}" '
            f'data-name="{html.escape(r.name)}" '
            f'data-outdated="{data_outdated}">',
            '<td class="name">'
            f'<a href="recipes/{html.escape(r.name)}.html">'
            f"{html.escape(r.name)}</a>"
            f"{stale_pill_html(r)}"
            f"{upstream_pill_html(r)}"
            f"{vulnerability_pill_html(r)}</td>",
            f'<td class="{version_cls}">{html.escape(r.version)}</td>',
            upstream_cell_html(r),
        ]
        for p in PLATFORMS:
            cells.append(platform_cell_html(r.platforms[p]))
        cells.append("</tr>")
        rows.append("".join(cells))

    summary = (
        f"{all_green} of {total} recipes green on all platforms · "
        f"{with_fail} with failures · {stale} stale · "
        f"{outdated} behind upstream"
    )
    per_plat_bits = " · ".join(
        f"{p}: {per_plat[p][0]}/{per_plat[p][1]}"
        for p in PLATFORMS
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
    <label><input type="checkbox" id="outdated-only">
      behind upstream only</label>
  </div>
  <table id="status">
    <thead>
      <tr>
        <th data-sort="name">recipe</th>
        <th data-sort="version">version</th>
        <th data-sort="upstream">upstream</th>
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
        if plat.state == "ok":
            status = '<span class="ok">✓ built</span>'
        elif plat.state == "na":
            status = (
                '<span class="muted" '
                'title="recipe excludes this platform">'
                "— n/a</span>"
            )
        else:
            status = '<span class="fail">✗ failed</span>'
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

    u = recipe.upstream
    swh_html = ""
    if u is not None and u.swh_archived is True:
        swh_html = (
            '<span class="ok">archived</span>'
        )
        if u.swh_revision:
            swh_html += (
                f' (<code>{html.escape(u.swh_revision[:12])}</code>)'
            )
    elif u is not None and u.swh_archived is False:
        swh_html = '<span class="muted">not yet archived</span>'

    security_section_html = ""
    if u is not None and u.vulnerabilities:
        rows = []
        for v in u.vulnerabilities:
            cve = v.get("cve_id") or v.get("ghsa_id") or "advisory"
            sev = v.get("severity") or "?"
            rng = v.get("range") or ""
            url = v.get("html_url") or ""
            applies = ", ".join(v.get("applies_to") or [])
            link = (
                f'<a href="{html.escape(url)}">{html.escape(cve)}</a>'
                if url else html.escape(cve)
            )
            rows.append(
                f"<tr><td>{link}</td>"
                f"<td>{html.escape(sev)}</td>"
                f"<td><code>{html.escape(rng)}</code></td>"
                f"<td>{html.escape(applies)}</td></tr>"
            )
        security_section_html = (
            '<section><h2>security advisories</h2>'
            '<table><thead><tr>'
            '<th>id</th><th>severity</th>'
            '<th>vulnerable range</th><th>applies to</th>'
            '</tr></thead><tbody>'
            + "".join(rows)
            + '</tbody></table></section>'
        )

    if u is None:
        upstream_html = (
            '<span class="muted">no upstream data yet</span>'
        )
    elif u.status == "up_to_date" and u.latest_version:
        age = u.age_days()
        age_bit = (
            f" · released {_age_phrase(age)}"
            if age is not None
            else ""
        )
        upstream_html = (
            f'<span class="ok">up to date</span> '
            f"({html.escape(u.latest_version)}{age_bit})"
        )
    elif u.status == "outdated" and u.latest_version:
        age = u.age_days()
        age_bit = f" · {_age_phrase(age)}" if age is not None else ""
        url = u.latest_release_url or ""
        link = (
            f'<a href="{html.escape(url)}">'
            f"{html.escape(u.latest_version)}</a>"
            if url
            else html.escape(u.latest_version)
        )
        upstream_html = (
            f'<span class="fail">behind</span> '
            f"(upstream {link}{age_bit})"
        )
    elif u.status == "tampered":
        reason = (
            f" ({html.escape(u.reason)})"
            if u.reason
            else ""
        )
        latest = u.latest_version or "?"
        upstream_html = (
            f'<span class="fail">tampered</span> '
            f"(upstream {html.escape(latest)}){reason}"
        )
    else:
        reason = (
            f" ({html.escape(u.reason)})"
            if u.reason
            else ""
        )
        upstream_html = (
            f'<span class="muted">untracked</span>{reason}'
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
  <h1>{html.escape(recipe.name)}{stale_pill_html(recipe)}{upstream_pill_html(recipe)}{vulnerability_pill_html(recipe)}</h1>
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
      <dt>upstream</dt>
      <dd>{upstream_html}</dd>
      {f'<dt>software heritage</dt><dd>{swh_html}</dd>' if swh_html else ''}
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
  {security_section_html}
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
    outdated = sum(1 for r in recipes if r.is_outdated)
    per_plat = _per_platform_counts(recipes)

    lines: list[str] = []
    lines.append("# gale-recipes build status")
    lines.append("")
    lines.append(f"- Total recipes: **{total}**")
    lines.append(
        f"- Green on all platforms: **{all_green}**"
    )
    lines.append(f"- With failures: **{with_fail}**")
    lines.append(f"- Stale (version skew): **{stale}**")
    lines.append(f"- Behind upstream: **{outdated}**")
    lines.append("")
    lines.append("Per platform (built / eligible):")
    for p in PLATFORMS:
        built, eligible = per_plat[p]
        lines.append(f"- `{p}`: {built}/{eligible}")
    lines.append("")

    # Failures grouped by platform — the triage view.
    lines.append("## Failing builds by platform")
    lines.append("")
    any_failure = False
    for p in PLATFORMS:
        failing = [
            r for r in recipes if r.platforms[p].is_failing
        ]
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

    # Recipes behind upstream.
    outdated_recipes = [r for r in recipes if r.is_outdated]
    if outdated_recipes:
        lines.append("## Behind upstream")
        lines.append("")
        lines.append(
            "Recipe version is older than the latest upstream "
            "release. Sorted by release age (oldest first)."
        )
        lines.append("")
        outdated_recipes.sort(
            key=lambda r: (r.upstream.age_days() or 0),
            reverse=True,
        )
        for r in outdated_recipes:
            u = r.upstream
            assert u is not None
            age = u.age_days()
            age_bit = f" ({_age_phrase(age)})" if age is not None else ""
            lines.append(
                f"- `{r.name}`: recipe {r.version}, "
                f"upstream {u.latest_version}{age_bit}"
            )
        lines.append("")

    # Security advisories on currently-shipped versions.
    # Surface above tamper because it directly affects users
    # running today's binaries.
    vuln_recipes = [
        r for r in recipes
        if r.upstream is not None and r.upstream.has_current_vulns
    ]
    if vuln_recipes:
        sev_rank = {"critical": 4, "high": 3, "medium": 2, "low": 1}
        def _max_sev(r: Recipe) -> int:
            u = r.upstream
            assert u is not None
            return max(
                (sev_rank.get((v.get("severity") or "").lower(), 0)
                 for v in (u.vulnerabilities or [])
                 if "current" in (v.get("applies_to") or [])),
                default=0,
            )
        vuln_recipes.sort(key=_max_sev, reverse=True)
        lines.append("## Security advisories on shipped versions")
        lines.append("")
        lines.append(
            "Recipe's currently-shipped version matches a "
            "published GitHub Security Advisory. Sorted by "
            "severity descending."
        )
        lines.append("")
        for r in vuln_recipes:
            u = r.upstream
            assert u is not None
            for v in (u.vulnerabilities or []):
                if "current" not in (v.get("applies_to") or []):
                    continue
                cve = v.get("cve_id") or v.get("ghsa_id") or "advisory"
                sev = v.get("severity") or "?"
                rng = v.get("range") or ""
                lines.append(
                    f"- `{r.name}` {r.version}: **{cve}** "
                    f"({sev}) — range `{rng}`"
                )
        lines.append("")

    # Tamper alerts — highest priority, surface prominently.
    tampered = [
        r for r in recipes
        if r.upstream is not None and r.upstream.is_tampered
    ]
    if tampered:
        lines.append("## Tampered upstream artifacts")
        lines.append("")
        lines.append(
            "Upstream artifact changed after our first "
            "observation, or attestation verification failed. "
            "Review before any version bump."
        )
        lines.append("")
        for r in tampered:
            u = r.upstream
            assert u is not None
            reason = f" — {u.reason}" if u.reason else ""
            lines.append(
                f"- `{r.name}`: recipe {r.version}, "
                f"upstream {u.latest_version or '?'}{reason}"
            )
        lines.append("")

    # Full table (useful for scanning).
    lines.append("## Full status")
    lines.append("")
    header = ["recipe", "version"] + list(PLATFORMS)
    lines.append("| " + " | ".join(header) + " |")
    lines.append("|" + "|".join("---" for _ in header) + "|")
    glyph = {"ok": "✓", "fail": "✗", "na": "—"}
    for r in recipes:
        cells = [f"`{r.name}`", r.version]
        for p in PLATFORMS:
            cells.append(glyph[r.platforms[p].state])
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
