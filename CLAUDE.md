# CLAUDE.md

Official index repository for
[Gale](https://github.com/kelp/gale). Gale fetches
upstream CLI binaries from this catalog, pins them
in a v2 lock, and activates them through generation
snapshots. It does not compile packages. It does
not ship bottles.

This is the content repo; the tool lives at `../gale`.
Admission records `tree_digest` with `gale admit`. Do
not invent `tree_digest`. Do not add `[build]` steps.

Format and layout: [`README.md`](README.md). Adding a
package:
[`docs/writing-recipes.md`](docs/writing-recipes.md).
CI: [`docs/dev/ci-architecture.md`](docs/dev/ci-architecture.md).

## Agent Sandbox Environment

Agent containers have no `gale`, `just`, `actionlint` or
`direnv`. A `SessionStart` hook runs
`scripts/agent-bootstrap.sh` in the background. Full
reference:
[`docs/dev/agent-environment.md`](docs/dev/agent-environment.md).

- **The bootstrap is async.** To wait for it, run it
  again — `just agent-bootstrap` takes an flock and
  blocks until the in-flight run finishes.
  `just agent-status` shows what landed.
- **`gale install` cannot work here.** Artifact hosts
  are blocked; that command fails slowly. `gale build`
  is gone. A PreToolUse hook blocks both. `gale lint`
  is offline and is the local gate.
- `gh` and `api.github.com` are unavailable; GitHub work
  goes through the GitHub MCP tools.

## Adding a package

Run `gale admit` on Darwin/arm64 (see
`.github/workflows/admit-darwin.yml`). Linux/amd64
for the first ten is `scripts/admit_linux.py`.
Land the printed fragment under
`index/<letter>/<name>.toml`. Do not invent
`tree_digest`. `just lint` must pass.

The catalog is `index/` only. Version bumps are
`index-update.yml`: 3-day lag, Darwin admit, PR
only. Do not recreate farm `auto-update.yml`.

## Gotchas

- **No `[build]` blocks.** Gale does not compile
  packages.
- **No `.binaries.toml` ledgers.** Do not recreate them.
- **No `.versions` sidecars.** Do not recreate them.
- Leftover `gale info` still reads a recipe cache and
  is not the index. Resolve verbs (`install`, `update`,
  `lock`, `outdated`) read `index/`.
