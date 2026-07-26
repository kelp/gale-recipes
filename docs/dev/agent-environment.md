# Agent Sandbox Environment

Reference for AI coding agents working in `gale-recipes`. The shared
environment facts — egress allowlist, running as root, the Go toolchain — live
in [`../../../gale/docs/dev/agent-environment.md`](../../../gale/docs/dev/agent-environment.md)
and are not repeated here. This document covers what is specific to the recipe
repo: what you can actually run, and what you cannot.

## The short version

```sh
just agent-bootstrap   # install gale, just, actionlint; blocks if already running
just agent-status      # what landed, and what failed
just lint              # gale lint on every recipe + actionlint
just test              # 218 python tests, ~3s
```

## Bootstrap

`scripts/agent-bootstrap.sh` installs into `~/.local/bin` (already first on
`PATH`) and is registered as a `SessionStart` hook. It is **asynchronous**, so
a fresh session can reach you before `gale` exists. To wait, run it again — it
takes an flock, so a second invocation blocks until the first finishes.

It installs three things:

| Tool | Source |
| --- | --- |
| `gale` | built from the sibling `../gale` checkout when present, else the release pinned in `recipes/g/gale.toml` |
| `actionlint` | `go install`, or a release tarball at the `gale.toml` pin |
| `just` | GitHub release tarball |

No Python setup is needed: every script under `scripts/` is stdlib-only and
needs only Python 3.11+ (for `tomllib`).

Status: `~/.cache/gale-agent-bootstrap/status-recipes`, or `just agent-status`.

## Recipes cannot be built here

`gale build` and `gale install` depend on hosts the sandbox egress policy
blocks — GHCR's blob host for prebuilt binaries, and go.dev / gnu.org /
codeload / ci-artifacts.rust-lang.org for the source-build fallback. They do
not fail fast: a measured `gale install just` spent 3m11s compiling rustc
before dying. A `PreToolUse` hook blocks them; override with
`GALE_ALLOW_NETWORK_INSTALL=1` if you have a reason.

**This means you cannot validate a recipe by building it.** The local gate is
`gale lint`, which is pure offline TOML validation. The real gate is CI:
`verify.yml` rebuilds every changed recipe on all eligible platforms and
smoke-tests the binary. Write the recipe carefully, lint it, and let CI build
it — do not weaken a recipe to make something pass locally.

The same applies to `scripts/check_install.py`, `scripts/run_smoke.py` and
`scripts/verify_binary.py`: they inspect an **installed** package under
`~/.gale/pkg/`, so they have nothing to look at until a real install exists.
They run in CI, not here.

## What runs locally

Everything below is offline and fast.

| Command | What it is |
| --- | --- |
| `just test` | the `scripts/` unit suite (218 tests, stdlib `unittest`) |
| `bash scripts/test_auto_update_sh.sh` | end-to-end smoke of `auto-update.sh` via PATH shims |
| `bash scripts/test_verify_upstream_attestation.sh` | attestation 404-classification unit test |
| `python3 scripts/check_ledger.py --base origin/main` | the required merge gate |
| `gale lint recipes/<letter>/<name>.toml` | recipe validation |
| `just lint` | `gale lint` over every recipe, then `actionlint` |
| `just gen-pages` | build the dashboard into `_site/` |

`test.yml` is the CI workflow that mirrors the first three. The rest of CI —
`build.yml`, `build-chunk.yml`, `promote.yml`, `auto-update.yml`,
`drift-check.yml`, `reproducibility.yml` — needs write tokens, GHCR, or
network and is not reproducible locally.

Anything network-bound is the exception: `scripts/check_registry_coherence.py`
and `scripts/audit_binaries.py` read GHCR anonymously, so they work only as far
as the manifest API, not blobs.

## Editing hooks

`.claude/settings.json` wires four hooks. Two exist to stop you doing
CI-managed work by hand:

- **`guard-binary-sections.sh`** (PreToolUse) — rejects any write to a
  `.binaries.toml`, and any `[binary.<platform>]` section added to a recipe.
  Those are written only by `build.yml` via `scripts/write_binaries.py`.
- **`lint-recipe.sh`** (PostToolUse) — parses every `.toml` you write, then
  runs `gale lint` on recipes. It is skipped, not failed, while the bootstrap
  is still installing `gale`.

## Stale artifacts to ignore

- `.direnv/` holds a dangling symlink into `/nix/store` from a macOS machine.
  There is no `/nix` here and no `direnv`. Do not source it or `direnv allow`.
- `index.tsv` is vestigial — 48 rows against 193 recipes, and nothing reads or
  writes it. Do not try to keep it in sync.
- The tracked `_data/upstream.json` is a seed. The live copy lives on the
  `dashboard-data` branch; the in-tree one is weeks stale by design.
- `gale.toml` and `gale.lock` have drifted (`difftastic`, `fish`, `gh`,
  `git-delta` are pinned but unlocked). Neither file is used by the sandbox —
  the bootstrap puts tools on `PATH` directly.

## Before editing a recipe

Read [`../../CLAUDE.md`](../../CLAUDE.md) and
[`linking-policy.md`](linking-policy.md). The two rules that get violated most
often by agents:

1. **Do not strip features or drop dependencies to make a build pass.** If a
   dependency is missing, add a recipe for it.
2. **Prefer static linking for CLI tools; never force it for libraries,
   language runtimes, or anything meant to be linked against.**
