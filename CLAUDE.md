# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code)
when working with code in this repository.

## Overview

Official recipe repository for
[Gale](https://github.com/kelp/gale). Each recipe is a
TOML file describing how to build a CLI tool from source.
See README.md for the format and layout.

## Recipe Format

```toml
[package]
name = "jq"                   # required
version = "1.8.1"             # required
description = "JSON processor"
license = "MIT"
homepage = "https://..."

[source]
url = "https://..."           # required
sha256 = "abc123..."          # required
repo = "jqlang/jq"            # for auto-update
released_at = "2025-07-01"    # for update cooldown

[build]
steps = ["./configure ...", "make -j${JOBS}", "make install"]

[dependencies]
build = ["autoconf", "automake"]
runtime = []

[binary.darwin-arm64]          # prebuilt, added by CI
url = "https://ghcr.io/..."
sha256 = "..."
```

## Testing a Recipe

Build from the sibling gale repo:

```
cd ../gale && go build -o gale ./cmd/gale/
./gale build ../gale-recipes/recipes/<letter>/<name>.toml
```

Verify the binary after build:

```
tmpdir=$(mktemp -d)
python3 -c "import tarfile; tarfile.open('<name>-<ver>.tar.zst','r:*').extractall('$tmpdir')"
$tmpdir/bin/<name> --version
rm -rf $tmpdir
```

## Build Environment

Build steps run in a clean shell with two variables:

- `${PREFIX}` — install destination directory
- `${JOBS}` — CPU count for parallel make

## Build Patterns

**Autotools** (jq): Use `--disable-docs
--disable-maintainer-mode` to skip optional tooling.
Bundle dependencies when possible
(`--with-oniguruma=builtin`). Prefer static linking
(`--disable-shared --enable-all-static`) to avoid
dylib path issues in the installed binary.

**Cargo** (bat, fd, ripgrep, starship): Always use
`cargo install --path . --root ${PREFIX}`. The `--path .`
flag is required — without it cargo fetches from
crates.io instead of building local source.

**Go** (fzf): No install-to-prefix convention. Use
`mkdir -p ${PREFIX}/bin` then
`go build -o ${PREFIX}/bin/<name>`.

## Two-Repo Architecture

This is the content repo. The tool lives at `../gale`.

- **gale-recipes** (this repo) — recipe TOML files. CI
  builds every recipe on each platform, pushes tar.zst
  binaries to GHCR via ORAS, and updates
  `[binary.<platform>]` sections in the recipe TOML.
- **gale** — the CLI tool. Pulls prebuilt binaries from
  GHCR when available, falls back to source builds.

**CI flow**: on push or schedule, GitHub Actions builds
changed recipes on macOS and Linux runners, pushes
tar.zst to GHCR, updates binary sections, commits back.

## Gotchas

- Recipes imported via `gale import homebrew <name>` carry
  a BSD-2-Clause attribution comment. The heuristic parser
  may produce warnings — review before committing.
- eza requires Rust edition2024 (newer than rustc 1.82).
- Autotools clock-skew errors are handled by gale's build
  module (timestamp reset), not the recipe.
