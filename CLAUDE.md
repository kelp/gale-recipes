# CLAUDE.md

Official index repository for
[Gale](https://github.com/kelp/gale). This repo publishes
version-keyed TOML under `index/`. Gale fetches those
artifacts, pins them in a v2 lock, and activates them
through generation snapshots.

This is the content repo; the tool lives at `../gale`.
Admission records `tree_digest` with `gale admit`. Do
not invent `tree_digest`. Do not add `[build]` steps.

Format and layout: [`README.md`](README.md). CI:
[`docs/dev/ci-architecture.md`](docs/dev/ci-architecture.md).

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
- **`gale install` and `gale build` cannot work here.**
  Artifact hosts are blocked; those commands fail
  slowly. A PreToolUse hook blocks them. `gale lint` is
  offline and is the local gate.
- `gh` and `api.github.com` are unavailable; GitHub work
  goes through the GitHub MCP tools.

## Adding a package

Run `gale admit` on Darwin/arm64 (see
`.github/workflows/admit-darwin.yml`). Land the printed
fragment under `index/<letter>/<name>.toml`. Do not
invent `tree_digest`. `just lint` must pass.

Do not add leftover source recipes. The catalog is
`index/` only.

## Gotchas

- **No `[build]` blocks.** Those left with the farm.
- **No `.binaries.toml` ledgers.** Do not recreate them.
- **No `.versions` sidecars.** Do not recreate them.
- Leftover `gale info` / `gale outdated` still fetch
  `recipes/<letter>/<name>.toml` from this `main` and
  404. Install / sync / update / lock read `index/`.
