# CLAUDE.md

Official recipe repository for
[Gale](https://github.com/kelp/gale). Any package is a
valid recipe candidate — languages, compilers, system
utilities, CLI tools, libraries.

This is the content repo; the tool lives at `../gale`.
CI builds promoted recipes on each platform, pushes
tar.zst binaries to GHCR via ORAS, attests provenance,
and writes `.binaries.toml` alongside each recipe.

Format and layout: [`README.md`](README.md). Per-field
reference and build patterns by language:
[`docs/creating-recipes.md`](docs/creating-recipes.md).
CI internals, the merge flow, and the bridge invariants:
[`docs/dev/ci-architecture.md`](docs/dev/ci-architecture.md).

To create a recipe, use `/new-recipe <name>` or dispatch
the `recipe-creator` agent for batch work; start from
`gale import homebrew <name>` for a baseline. Build
patterns per buildsystem live in the
`recipe-build-patterns` skill.

## Revisions

`[package] revision = N` (integer, default 1). Bump it
when the binary should change but upstream didn't:
build-flag change, post-install cleanup, a dep soname
bump that requires re-linking, a CI toolchain upgrade.
Don't bump for doc-only edits.

**Revision bumps cascade.** One increment rebuilds the
recipe across every platform and surfaces as a pullable
update on every user machine, and any dependent with a
bare (unconstrained) runtime dep gets flagged stale too.
Full semantics, the `.gale-deps.toml` staleness model,
and the shared dylib farm:
[`../gale/docs/revisions.md`](../gale/docs/revisions.md).

## Agent Sandbox Environment

Agent containers (Claude Code on the web and similar)
have no `gale`, `just`, `actionlint` or `direnv`. A
`SessionStart` hook runs `scripts/agent-bootstrap.sh` in
the background to install them. Full reference:
[`docs/dev/agent-environment.md`](docs/dev/agent-environment.md).

- **The bootstrap is async.** To wait for it, run it
  again — `just agent-bootstrap` takes an flock and
  blocks until the in-flight run finishes.
  `just agent-status` shows what landed.
- **Recipes cannot be built here.** `gale build` and
  `gale install` need hosts the egress policy blocks
  (GHCR's blob host, go.dev, gnu.org, codeload); they
  burn minutes before failing, and a PreToolUse hook
  blocks them. `gale lint` is fully offline and is the
  local gate; `verify.yml` is the real one. Never weaken
  a recipe to make something pass locally.
- `gh` and `api.github.com` are unavailable; GitHub work
  goes through the GitHub MCP tools.

On a dev machine, `gale.toml` + `.envrc` provide the dev
tools through direnv. `just update-gale` picks up a
sibling-repo gale build. Do **not** run
`gale remove gale` — it removes the binary from PATH and
you can't run gale to reinstall it.

## Build Environment

Build steps run in a clean shell with the six variables
listed in README.md, and substitution is textual over
the whole step. Any *other* `${...}` — a
pkg-config-internal var, a shell var written `${var}` —
expands to nothing and breaks the build silently. That
was the root cause of the lua no-op-fix saga
(11c902a → ec7b024). Write shell variables as `$var`
without braces, or inline the value.

**Zig builds must pass `-Dcpu=baseline`** to
`zig build`. The default `native` target bakes in the CI
runner's instruction set, and the binary then SIGILLs on
hosts that lack it.

## Recipe Quality

Don't strip features or drop dependencies to make a
build easier. Recipes should build the package the way
upstream and Homebrew intend, with full functionality.
If a dependency is missing, add a recipe for it. The
goal is to replace Homebrew, not to ship lesser
versions.

## Linking Policy

Prefer static linking for CLI tools where practical. Do
not force it for libraries, language runtimes, or
packages meant to be linked against by others. Rules per
platform and the rpath decision order:
[`docs/dev/linking-policy.md`](docs/dev/linking-policy.md).

Two things that cost us builds:

- **"Runs on the build host" is not evidence of correct
  linkage.** A dynamically linked binary segfaults only
  on hosts whose glibc differs from the CI runner's (gh
  2.92.0-2, 8231a6e). For Go, set `CGO_ENABLED=0`.
  Assert the linkage property itself in a smoke command
  (`file`/`ldd` output), not just a `--help` probe.
- **Install no longer rewrites rpaths** (gale 0.16.3+) —
  the installed binary must equal the CI-built, hashed,
  attested artifact. gale bakes the dependency-farm
  rpath at build time but will *not* fix a package's own
  `@rpath/lib<self>.dylib` refs; an unresolved one makes
  dyld abort and fails `scripts/check_install.py`. Fix
  it in the recipe (static-link it away, or
  `install_name_tool -add_rpath` in a build step), never
  with a post-install hook. Examples:
  `recipes/o/openssl4.toml`, `recipes/p/postgresql.toml`.

## Auto-merge Policy

Auto-update PRs are **never** auto-merged. The gates, in
order: the pre-PR checks (7-day first-observation
cooldown, attestation verification, non-semver filter),
then `verify.yml` rebuilding and smoke-testing on every
eligible platform, then a human pressing merge.

Do not add `--auto-merge` or a merge-bot. The cooldown
only protects against issues the *ecosystem* notices;
the human gate is the last backstop for anything it
missed. Auto-update mechanics live in
[`.github/CLAUDE.md`](.github/CLAUDE.md).

## Gotchas

- **A green `verify.yml` does not mean mergeable.** On a
  version bump the required Ledger Check stays red until
  promote publishes and commits the ledger. That is the
  design working, not flakiness.
- Recipes imported via `gale import homebrew <name>`
  carry a BSD-2-Clause attribution comment, and the
  heuristic parser may emit warnings — review before
  committing.
- eza requires Rust edition2024 (newer than rustc 1.82).
- Autotools clock-skew errors are handled by gale's
  build module (timestamp reset), not by the recipe.
- Cargo workspaces with virtual manifests need
  `--path <crate-dir>`, not `--path .`. Check for
  `[workspace]` without `[package]` in the root
  Cargo.toml.
- Before a version bump, verify the upstream tag is the
  artifact's own release, not a parent monorepo or SDK
  tag (flarectl 7.2.0 was the Go SDK's release,
  b5f11ae).
- Stage a major-version ABI break as a new recipe
  (openssl → openssl4, b49de15) rather than bumping in
  place; dependents compiled against the old ABI break
  otherwise.
- github-actions[bot] PR events are HELD, not run. Since
  GitHub's 2026-06 policy change, GITHUB_TOKEN-authored
  PR commits create `pull_request` runs stuck at
  `action_required`, and no API can approve non-fork
  held runs. That is why auto-update's branch pushes and
  PR creation use the gale-recipes-automation App token
  — App-authored events run unheld. Everything else
  stays on GITHUB_TOKEN deliberately: pages.yml hooks
  the scheduled Auto-Update run because build-run events
  don't fire, and build.yml's post-promote commit-back
  produces one ignorable held run pair per PR while the
  required ledger-check is credited via its dispatched
  run's commit status (gh#146). Don't widen the App
  token's use to build.yml's commits.
- build.yml's update-recipes job commits binaries onto
  the PR branch, never main. After a promote, pull the
  PR branch before pushing more commits; any push after
  approval moves the tip and requires re-applying
  `approved-for-build` to re-authorize.
- SC2016 warnings are suppressed in
  `.github/actionlint.yaml` — jq and GraphQL use `$` for
  their own variables, not shell expansion.
