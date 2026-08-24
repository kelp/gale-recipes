# CI Architecture

gale-recipes is the fetch index. Gale does not
compile packages and does not ship bottles. CI
lints index documents and admits Darwin/arm64
artifacts. The first ten also have linux/amd64.
It does not push GHCR or write ledgers.

## Workflows

### `test.yml` — Script Tests

Runs on every pull request and every push to `main`.
No path filters, so required checks can report on
docs-only PRs.

- `test` — `python3 -m unittest discover` under
  `scripts/`
- `index-lint` — build a pinned gale and run
  `scripts/lint_index.sh`
- `zizmor` — GitHub Actions security lint. Fails
  the job on findings. Not SARIF-only.

Protect-main still requires the `ledger-check`
context (ruleset 17473700). `test.yml` posts that
name as a retired shim. After the ruleset requires
`test` and `index-lint` instead, delete the shim.

### `admit-darwin.yml` — Admit Darwin

Runs `gale admit` on macos-26 for packages in the
admit manifest that are not already on `origin/main`.
Uploads fragments. Does not commit. `tree_digest`
comes from admit stdout only.

### `index-update.yml` — Index Update

Daily (and `workflow_dispatch`). Finds GitHub
releases newer than `package.latest`, waits three
days after `published_at`, admits darwin/arm64, and
opens one PR per package. Never pushes `main`.
`tree_digest` comes from `gale admit`. This is not
`auto-update.yml`.

## Retired farm CI

`build.yml`, `build-chunk.yml`, `verify.yml`,
`promote.yml`, `ledger-check.yml`, `auto-update.yml`,
`reproducibility.yml`, `drift-check.yml`, and
`pages.yml` left with the farm. Do not recreate them.

GitHub Pages is off. Do not recreate `pages.yml`.
The `dashboard-data` branch is leftover farm state
and is gone.
