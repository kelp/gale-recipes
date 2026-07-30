# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code)
when working with code in this repository.

## Overview

Official recipe repository for
[Gale](https://github.com/kelp/gale). Any package is a
valid recipe candidate — languages, compilers, system
utilities, CLI tools, and libraries. See README.md for
the format and layout.

## Recipe Format

See README.md for the full format. Binary metadata
lives in separate `.binaries.toml` files managed by CI.

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

## Build Environment

Build steps run in a clean shell with the six variables
listed in README.md.

Substitution is textual over the whole build step, and
only those six variables are defined. Any other
`${...}` in a step — pkg-config-internal vars, shell
vars written as `${var}` — expands to nothing and breaks
the build silently (root cause of the lua no-op-fix
saga, 11c902a → ec7b024). Write shell variables as
`$var` without braces, or inline the value.

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

Per-buildsystem patterns (autotools, cargo, go, cmake,
zig) are in the `recipe-build-patterns` skill. One rule
belongs here because omitting it ships a broken binary:
**Zig builds must pass `-Dcpu=baseline`** to `zig build`.
The default `native` target bakes in the CI runner's
instruction set and the binary then SIGILLs on hosts that
lack it.

## Two-Repo Architecture

This is the content repo. The tool lives at `../gale`.

- **gale-recipes** (this repo) — recipe TOML files for
  all packages: system tools, languages, compilers,
  libraries, CLI utilities. CI builds promoted recipes
  on each platform, pushes tar.zst binaries to GHCR
  via ORAS, attests provenance, and writes
  `.binaries.toml` files alongside each recipe.
- **gale** — the package manager. Pulls prebuilt
  binaries from GHCR when available, falls back to
  source builds.

**CI flow**: one writer. Pre-merge, the unprivileged
`verify.yml` builds and smoke-tests a PR's changed
recipes with no write-capable token. A maintainer then
applies the `approved-for-build` label; `promote.yml`
dispatches the privileged `build.yml` pinned to the
reviewed head SHA, which builds every eligible platform
(declared `[package].platforms` are authoritative — no
skipped cells), attests provenance via Sigstore, pushes
tar.zst to GHCR via ORAS, and commits `.binaries.toml`
(the v0.16.5-readable head mirror plus the append-only
`[[history]]` ledger) and `.versions` back onto the PR
branch via GraphQL (auto-signed "Verified",
expectedHeadOid-locked to the reviewed SHA). Recipe,
binaries, and ledger merge to main atomically in the
PR. CI never writes to main; the dashboard republishes
from the merge push (`pages.yml`). A reconcile is the
same flow done by hand: branch from main, dispatch
`build.yml` at that branch, merge the PR. The
two-commit `.versions` append and the merge-commit-only
repo setting persist for exactly as long as `.versions`
files exist — they are the deployed-v0.16.5 client
bridge.

## Bridge invariants

Two named invariants protect deployed gale v0.16.5
clients while `.versions` files still exist. The
merge-commit-only setting and the .versions append
persist for exactly as long as .versions files exist.
Do not enable squash/rebase merges, and do not stop
build.yml's two-commit `.binaries.toml`-then-`.versions`
append, until the cutover PR deletes every `.versions`
file (deletion is the safe end shape; in-place
reformatting would hard-fail old clients and is
forbidden).

Each `.binaries.toml` carries an append-only
`[[history]]` ledger below the v0.16.5-readable head
mirror. The required Ledger Check
(`.github/workflows/ledger-check.yml` →
`scripts/check_ledger.py`) makes "version changed =>
ledger entry appended" the sole merge gate, and rejects
any rewrite of prior history. Expect this on version
bumps: verify green != mergeable — a version-bump PR's
Ledger Check stays red until promote publishes and
commits the ledger; this is the design working, not
flakiness. The daily registry-coherence audit
(`scripts/check_registry_coherence.py` via
drift-check.yml) covers the one gap in-tree checks
cannot see: external mutation of GHCR content. Its
"immutable tag conflict" failure ships its recovery:
bump revision to republish.

## Auto-update workflow

`.github/workflows/auto-update.yml` runs daily, opens
version-bump PRs on `auto-update/<name>-<version>`
branches, and writes per-recipe status to
`_data/upstream.json`. Mechanics — the first-observation
cooldown clock, the `tampered` signals, attestation
requirements, and the tag fallback for upstreams without
releases — are in `.github/CLAUDE.md`.

### Auto-merge policy

Auto-update PRs are **never** auto-merged. Gates, in
order:

1. **Pre-PR** — first-observation 7-day cooldown,
   attestation verification, non-semver filter.
2. **CI** — `verify.yml` rebuilds the recipe on all
   eligible platforms and smoke-tests the resulting
   binary (`--help`/`--version`), same as any other PR.
3. **Human** — a reviewer presses merge.

Do not add `--auto-merge` or a merge-bot. The cooldown
only protects against issues the *ecosystem* notices;
the human gate is the last backstop for anything the
ecosystem missed.

## Linting

`just lint` runs all lints.

SC2016 warnings are suppressed in
`.github/actionlint.yaml` — jq and GraphQL use `$`
for their own variables, not shell expansion.

## Dev Environment

`gale.toml` + `.envrc` provide dev tools via gale and
direnv. Run `gale sync --recipes recipes` to install from
local recipes, or let direnv activate automatically on cd.

Update gale from source (use this when gale has been
updated in the sibling repo):

```
just update-gale
```

Do NOT use `gale remove gale` — it removes the binary
from PATH and you can't run gale to reinstall.

Note: on a dev machine this project may have a local
`.gale/` with an old binary; use
`$HOME/.gale/current/bin/gale` if the local one is
stale. Neither path exists in an agent container —
see the section below.

## Agent Sandbox Environment

Agent containers (Claude Code on the web and similar)
have no `gale`, `just`, `actionlint` or `direnv`, so
`just lint` and the recipe-lint hook cannot run out of
the box. A `SessionStart` hook runs
`scripts/agent-bootstrap.sh` in the background to
install them. Full reference:
[`docs/dev/agent-environment.md`](docs/dev/agent-environment.md).

Three things to know before the first command:

- **The bootstrap is async.** To wait for it, run it
  again — `just agent-bootstrap` takes an flock and
  blocks until the in-flight run finishes.
  `just agent-status` shows what landed.
- **Recipes cannot be built in the sandbox.** `gale
  build` and `gale install` need hosts the egress
  policy blocks (GHCR's blob host, go.dev, gnu.org,
  codeload), and they burn minutes before failing. A
  PreToolUse hook blocks them. `gale lint` is fully
  offline and is the local gate; `verify.yml` is the
  real one. Never weaken a recipe to make something
  pass locally.
- `gh` and `api.github.com` are unavailable; GitHub
  work goes through the GitHub MCP tools.

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

"Runs on the build host" is not evidence of correct
linkage: a dynamically linked binary segfaults only on
hosts whose glibc differs from the CI runner's (gh
2.92.0-2, 8231a6e). For Go, set `CGO_ENABLED=0`. Assert
the linkage property itself in a smoke command (e.g.
`file`/`ldd` output), not just a `--help` probe.

**rpath / verifiability (gale 0.16.3+):** install no longer
rewrites rpaths — the installed binary must equal the
CI-built, hashed, attested artifact. gale bakes the
dependency-farm rpath at build time but does NOT auto-fix a
package's own `@rpath/lib<self>.dylib` refs (e.g. a `bin/`
tool or `lib/<pkg>/` plugin linking a sibling dylib); an
unresolved one makes dyld abort and fails
`scripts/check_install.py`. Fix order: (1) static-link to
remove the dylib (preferred), (2) bake the rpath in a build
step with `install_name_tool -add_rpath @loader_path/<rel>/lib`
(Mach-O-gated, so it no-ops on Linux), (3) never use a
post-install hook or rely on install-time patching. Examples:
`recipes/o/openssl4.toml`, `recipes/p/postgresql.toml`.

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
- Before a version bump, verify the upstream tag is the
  artifact's own release, not a parent monorepo or SDK
  tag (flarectl 7.2.0 was the Go SDK's release, b5f11ae).
- Stage a major-version ABI break as a new recipe
  (openssl → openssl4, b49de15) instead of bumping in
  place; dependents that compile against the old ABI
  break otherwise.
- github-actions[bot] PR events are HELD, not run: since
  GitHub's 2026-06 policy change, GITHUB_TOKEN-authored PR
  commits create pull_request runs stuck at
  action_required (before that they were suppressed
  outright), and no API can approve non-fork held runs.
  That is why auto-update's branch pushes and PR creation
  use the gale-recipes-automation App token — App-authored
  events run unheld. Everything else stays on
  GITHUB_TOKEN deliberately: pages.yml hooks the scheduled
  Auto-Update run because build-run events don't fire, and
  build.yml's post-promote commit-back produces one
  ignorable held run pair per PR while the required
  ledger-check is credited via its dispatched run's commit
  status (gh#146). Don't widen the App token's use to
  build.yml's commits.
- build.yml's update-recipes job commits binaries onto
  the PR branch, never main. After a promote, pull the
  PR branch before pushing more commits to it; any push
  after approval moves the tip and requires re-applying
  `approved-for-build` to re-authorize.
- Revision bumps cascade: once a recipe's revision
  increments, CI rebuilds it across every platform and
  the rebuild shows up as a pullable update on every
  user machine. Any dependent recipe with a strict
  runtime dep (bare string, no version range constraint)
  will also be flagged stale on users' machines. See
  [`../gale/docs/revisions.md`](../gale/docs/revisions.md).
