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
files, signs recipes, and commits back via GraphQL
(auto-signed "Verified"). workflow_dispatch builds all
or a named recipe.

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
