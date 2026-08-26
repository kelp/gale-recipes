# Agent Sandbox Environment

Reference for AI coding agents working in `gale-recipes`.
The shared environment facts — egress allowlist, running
as root, the Go toolchain — live in
[`../../../gale/docs/dev/agent-environment.md`](../../../gale/docs/dev/agent-environment.md)
and are not repeated here.

## The short version

```sh
just agent-bootstrap   # install gale, just, actionlint; blocks if already running
just agent-status      # what landed, and what failed
just lint              # index lint + actionlint
just test              # scripts/ unit tests
```

## Bootstrap

`scripts/agent-bootstrap.sh` installs into `~/.local/bin`
and is registered as a `SessionStart` hook. It is
**asynchronous**, so a fresh session can reach you before
`gale` exists. To wait, run it again — it takes an flock,
so a second invocation blocks until the first finishes.

It installs three things:

| Tool | Source |
|------|--------|
| `gale` | sibling `../gale` `go build` when present, else a shallow clone of `kelp/gale` at a named index-linting commit |
| `actionlint` | `go install`, or a release tarball at the hardcoded pin |
| `just` | GitHub release tarball |

No Python setup is needed: every script under `scripts/`
is stdlib-only and needs Python 3.11+ (for `tomllib`).

Status: `~/.cache/gale-agent-bootstrap/status-recipes`,
or `just agent-status`.

## Index documents cannot be installed here

`gale install` depends on hosts the sandbox egress
policy blocks. It does not fail fast. `gale build` is
gone. A `PreToolUse` hook blocks both; override with
`GALE_ALLOW_NETWORK_INSTALL=1` if you have a reason.

The local gates are `just lint` and `just test`. The
real gate is `test.yml`. Never weaken an index document
to make something pass locally.

## What runs locally

Everything below is offline and fast.

| Command | What it is |
|---------|------------|
| `just test` | the `scripts/` unit suite (stdlib `unittest`) |
| `gale lint index/<letter>/<name>.toml` | index validation |
| `just lint` | `scripts/lint_index.sh` then actionlint |

## Editing hooks

`.claude/settings.json` wires three hooks:

- **`session-start.sh`** — starts the bootstrap.
- **`block-gale-install.sh`** — refuses
  `gale install|build|sync`.
- **`lint-index.sh`** — parses every `.toml` you write,
  then runs `gale lint` on index documents. It is
  skipped, not failed, while the bootstrap is still
  installing `gale`.

## Stale artifacts to ignore

- `.direnv/` may hold a dangling symlink from a macOS
  machine. There is no `/nix` here and no `direnv`.
- The `dashboard-data` branch is leftover farm state
  and is gone. GitHub Pages is off.
