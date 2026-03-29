# gale-recipes

Official recipe repository for
[Gale](https://github.com/kelp/gale). Each recipe
describes how to build a package from source. CI builds
changed recipes on macOS and Linux, pushes prebuilt
binaries to GHCR, and attests provenance via Sigstore.

## Layout

Recipes are TOML files, organized by first letter.
Binary metadata lives in separate `.binaries.toml`
files managed by CI.

```
recipes/
  j/
    jq.toml             # recipe (human-authored)
    jq.binaries.toml    # binary index (CI-managed)
    jq.versions         # version history
```

## Recipe Format

```toml
[package]
name = "jq"
version = "1.8.1"
description = "Lightweight and flexible command-line JSON processor"
license = "MIT"
homepage = "https://jqlang.github.io/jq"

[source]
repo = "jqlang/jq"
url = "https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-1.8.1.tar.gz"
sha256 = "2be64e71..."

[build]
steps = [
  "./configure --prefix=${PREFIX} --with-oniguruma=builtin",
  "make -j${JOBS}",
  "make install",
]
```

Build steps run in a clean shell with `${PREFIX}`,
`${VERSION}`, `${JOBS}`, `${OS}`, `${ARCH}`, and
`${PLATFORM}` available.

## Development

Install dev tools:

```
gale sync --local
```

Or let direnv activate automatically on cd.

Common tasks:

```
just lint          # lint recipes + workflows
just update-gale   # rebuild gale from source
```

## Contributing

Add a recipe at `recipes/<first-letter>/<name>.toml`.
Build and verify it works:

```
gale build recipes/<letter>/<name>.toml
just lint
```

See [docs/creating-recipes.md](docs/creating-recipes.md)
for the full recipe authoring guide.

## Automated Recipe Creation

This repository uses Claude Code agents to create
recipes at scale. The `/batch-recipes` skill dispatches
parallel agents that each import from Homebrew, adapt
to gale patterns, and lint the result.

See [docs/dev/agent-workflow.md](docs/dev/agent-workflow.md)
for the agent skills, methodology, and batch workflow.

See [docs/dev/ci-architecture.md](docs/dev/ci-architecture.md)
for CI design goals and non-obvious implementation
details.
