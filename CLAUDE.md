# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code)
when working with code in this repository.

## Overview

Official recipe repository for
[Gale](https://github.com/kelp/gale), a package manager
that replaces Homebrew, Nix, and home-manager. Each
recipe is a TOML file describing how to build a package
from source. Any package is a valid recipe candidate —
languages, compilers, system utilities, CLI tools, and
libraries. See README.md for the format and layout.

## Recipe Format

See README.md for the full format. Required fields:
`[package]` name + version, `[source]` url + sha256,
`[build]` steps. Optional: `[dependencies]`.
Binary metadata lives in separate `.binaries.toml`
files managed by CI.

Recipes may also declare `[package] revision = N`
(integer, defaults to 1). Bump the revision when the
binary should change but upstream didn't — build-flag
change, post-install cleanup, dep soname bump that
requires re-linking, CI toolchain upgrade. Don't bump
for doc-only edits; a revision bump triggers a rebuild
across every platform and surfaces as an update on
every user machine. Full semantics, `.gale-deps.toml`
staleness model, and shared dylib farm in
[`../gale/docs/revisions.md`](../gale/docs/revisions.md).

### Binary trust policy

A recipe that ships an inline `[binary.<platform>]`
section (rare — CI-produced binaries use the separate
`.binaries.toml` path instead) may declare a `trust`
field. Valid values:

- `trust = "sigstore"` (default when omitted) — the
  binary must be served from `ghcr.io` and carry a
  Sigstore attestation tied to gale-recipes CI. This
  is the fail-safe default: forgetting the field
  enforces attestation, not bypasses it.
- `trust = "sha256-only"` — the binary is served from
  an upstream host that doesn't publish attestations
  keyed to our signing identity (vendor CDN, language
  toolchain release artifact, etc.). Only the SHA256
  is verified. Recipes must opt in explicitly.

Typos in `[binary.<platform>]` field names fail parsing
(same strict-schema rule as `[package]` and `[source]`).

### Dependencies

`[dependencies.build]` and `[dependencies.runtime]` each
accept a list of entries in either form:

```toml
[dependencies]
build = ["curl", "expat", "gnumake", "pkgconf"]
runtime = [
  "zlib",
  { name = "openssl", version = ">=3.6.0-1" },
]
```

- **Bare string** — resolves to whatever the current
  registry says is latest. No constraint; the installer
  accepts any version the resolver returns. Default for
  everything the catalog ships today.
- **Inline table** — pins the dep against a version
  constraint. Keys: `name` (required), `version`
  (optional constraint expression). The expression uses
  the same syntax as `.gale-deps.toml` range constraints:
  `"=1.2.3-2"` (exact), `">=1.2.3-2"` (floor), `"<2.0.0"`
  (ceiling), or any of `>`, `>=`, `<`, `<=`, `=`. A bare
  `"1.2.3"` is treated as `=1.2.3-1`.

The constraint is enforced at install time — if the
resolved dep's version doesn't satisfy it, the install
fails with a message naming the dep, the required
constraint, and the version actually found. Bare deps
skip this check entirely.

Pin a dep when a soname or ABI change in the dep would
require rebuilding the dependent. Leave deps bare when
they're ABI-stable across revisions or the dependent
statically links them.

CI records the resolved (name, version, revision)
closure each build was linked against into a per-platform
`deps` array-of-tables inside `.binaries.toml`. That
block is informational — the archive's own
`.gale-deps.toml` remains authoritative for staleness
detection. See
[`../gale/docs/revisions.md`](../gale/docs/revisions.md).

## Testing a Recipe

Build a recipe (produces a tar.zst archive):

```
gale build recipes/<letter>/<name>.toml
```

Verify the binary after build:

```
tmpdir=$(mktemp -d)
python3 -c "import tarfile; tarfile.open('<name>-<ver>.tar.zst','r:*').extractall('$tmpdir')"
$tmpdir/bin/<name> --version
rm -rf $tmpdir
```

Install from a local recipe:

```
gale install <name> --recipe recipes/<letter>/<name>.toml
```

## Creating Recipes

Use `/new-recipe <name>` or dispatch the
`recipe-creator` agent for batch creation. Start with
`gale import homebrew <name>` for a baseline.

Recipes live at `recipes/<first-letter>/<name>.toml`.
Get source sha256:

```
curl -sL <url> | shasum -a 256
```

## Build Environment

Build steps run in a clean shell with these variables:

- `${PREFIX}` — install destination directory
- `${JOBS}` — CPU count for parallel make
- `${VERSION}` — recipe package version
- `${OS}` — `darwin` or `linux`
- `${ARCH}` — `arm64` or `amd64`
- `${PLATFORM}` — `darwin-arm64` or `linux-amd64`

### sccache passthrough

If `sccache` is on the host PATH (e.g. installed in CI via
`mozilla-actions/sccache-action`), gale's build sandbox
auto-sets `RUSTC_WRAPPER=sccache` and forwards these host
env vars into the build:

- any `SCCACHE_*` key (e.g. `SCCACHE_GHA_ENABLED`,
  `SCCACHE_DIR`, `SCCACHE_BUCKET`)
- `ACTIONS_CACHE_URL`, `ACTIONS_RUNTIME_TOKEN`,
  `ACTIONS_RESULTS_URL`, `ACTIONS_CACHE_SERVICE_V2`

Trigger condition: `sccache` resolvable via the host PATH.
Nothing else is needed in the recipe — `cargo install`
picks up `RUSTC_WRAPPER` automatically. A recipe can set
its own `RUSTC_WRAPPER` (including `""` to opt out) under
`[build] env` to override the auto-wiring.

## Build Patterns

**Autotools** (jq): Use `--disable-docs
--disable-maintainer-mode` to skip optional tooling.
Bundle dependencies when possible
(`--with-oniguruma=builtin`).

**Cargo** (bat, fd, ripgrep, starship): Always use
`cargo install --path . --root ${PREFIX}`. The `--path .`
flag is required — without it cargo fetches from
crates.io instead of building local source.

**Go** (fzf): No install-to-prefix convention. Use
`mkdir -p ${PREFIX}/bin` then
`go build -o ${PREFIX}/bin/<name>`.

**cmake** (zstd, duckdb, neovim): Use
`cmake -S . -B build -DCMAKE_INSTALL_PREFIX=${PREFIX}
-DCMAKE_BUILD_TYPE=Release`, then
`cmake --build build -j ${JOBS}`,
`cmake --install build`.

## Two-Repo Architecture

This is the content repo. The tool lives at `../gale`.

- **gale-recipes** (this repo) — recipe TOML files for
  all packages: system tools, languages, compilers,
  libraries, CLI utilities. CI builds changed recipes
  on each platform, pushes tar.zst binaries to GHCR
  via ORAS, attests provenance, and writes
  `.binaries.toml` files alongside each recipe.
- **gale** — the package manager. Pulls prebuilt
  binaries from GHCR when available, falls back to
  source builds.

**CI flow**: on push, GitHub Actions detects changed
recipes via git diff, builds only those on macOS ARM64
and Linux AMD64 runners, attests provenance via Sigstore,
pushes tar.zst to GHCR via ORAS, writes `.binaries.toml`
and appends `.versions` entries, and commits back via
GraphQL (auto-signed "Verified"). workflow_dispatch
builds all or a named recipe.

## Auto-update workflow

`.github/workflows/auto-update.yml` runs daily and, for
each recipe with a `[source].repo`, queries the upstream's
latest GitHub release. All status (up_to_date / outdated /
tampered / untracked) is written to `_data/upstream.json`
for the dashboard; version-bump PRs are opened under the
`auto-update/<name>-<version>` branch name.

The 3-day cooldown is a supply-chain gate, not a
scheduling delay. Its timestamp comes from our own
*first-observation* clock (recorded in `upstream.json`
alongside the tarball's sha256), not upstream's tag
publish date — a maintainer re-tagging to reset
`published_at` does not move our clock. A sha256 change
on an already-observed version flips status to
`tampered`, halts the PR, and surfaces on the dashboard.
The workflow also runs `gh attestation verify` against
each downloaded tarball; repos listed in
`.github/auto-update-attest-required.txt` require a
valid attestation.

Non-semver tags (release candidates, dated builds with
dashes, etc.) are recorded as `untracked` and skipped.

### Auto-merge policy

Auto-update PRs are **never** auto-merged. Gates, in
order:

1. **Pre-PR** — first-observation 3-day cooldown,
   attestation verification, non-semver filter.
2. **CI** — `build.yml` rebuilds the recipe on all
   platforms and smoke-tests the resulting binary
   (`--help`/`--version`), same as any other PR.
3. **Human** — a reviewer presses merge.

Do not add `--auto-merge` or a merge-bot. The cooldown
only protects against issues the *ecosystem* notices;
the human gate is the last backstop for anything the
ecosystem missed.

## Linting

Run all lints:

```
just lint
```

Or individually:

```
gale lint recipes/**/*.toml
actionlint
```

SC2016 warnings are suppressed in
`.github/actionlint.yaml` — jq and GraphQL use `$`
for their own variables, not shell expansion.

## Dev Environment

`gale.toml` + `.envrc` provide dev tools via gale and
direnv. Run `gale sync --local` to install from local
recipes, or let direnv activate automatically on cd.

Update gale from source (use this when gale has been
updated in the sibling repo):

```
just update-gale
```

Do NOT use `gale remove gale` — it removes the binary
from PATH and you can't run gale to reinstall.

Note: this project has a local `.gale/` with an old
binary. Use `$HOME/.gale/current/bin/gale` if the
local one is stale.

## Recipe Quality

Don't strip features or drop dependencies to make a
build easier. Recipes should build the package the way
upstream and Homebrew intend — with full functionality.
If a dependency is missing, add the recipe for it. The
goal is to replace Homebrew, not ship lesser versions.

## Linking Policy

Prefer static linking for CLI tools where practical.
On Linux, prefer static linking of non-system deps and
C++ runtime where feasible, but keep glibc dynamic.
On macOS, full static linking is usually not viable,
so use dynamic linking with correct rpaths/fixups.
Do not force static linking for libraries, language
runtimes, or packages that are intended to be linked
against by other packages. See
`docs/dev/linking-policy.md`.

## Gotchas

- Recipes imported via `gale import homebrew <name>` carry
  a BSD-2-Clause attribution comment. The heuristic parser
  may produce warnings — review before committing.
- eza requires Rust edition2024 (newer than rustc 1.82).
- Autotools clock-skew errors are handled by gale's build
  module (timestamp reset), not the recipe.
- Cargo workspaces with virtual manifests need
  `--path <crate-dir>` not `--path .`. Check for
  `[workspace]` without `[package]` in root Cargo.toml.
- CI commits use GITHUB_TOKEN so they don't re-trigger
  workflows. Switching to a PAT or App token would cause
  an infinite rebuild loop — add commit-message filtering
  first.
- CI's update-recipes job commits binary sections back
  to main. Always `git pull --rebase` before pushing to
  avoid rejected pushes.
- Revision bumps cascade: once a recipe's revision
  increments, CI rebuilds it across every platform and
  the rebuild shows up as a pullable update on every
  user machine. Any dependent recipe with a strict
  runtime dep (bare string, no version range constraint)
  will also be flagged stale on users' machines. See
  [`../gale/docs/revisions.md`](../gale/docs/revisions.md).
