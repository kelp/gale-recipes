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
`[build]` steps. Optional: `[dependencies]`,
`[binary.<platform>]` (added by CI).

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

## Adding a Recipe

Recipes live at `recipes/<first-letter>/<name>.toml`.
Get source sha256:

```
curl -sL <url> | shasum -a 256
```

## Build Environment

Build steps run in a clean shell with two variables:

- `${PREFIX}` — install destination directory
- `${JOBS}` — CPU count for parallel make

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

## Two-Repo Architecture

This is the content repo. The tool lives at `../gale`.

- **gale-recipes** (this repo) — recipe TOML files for
  all packages: system tools, languages, compilers,
  libraries, CLI utilities. CI builds changed recipes
  on each platform, pushes tar.zst binaries to GHCR
  via ORAS, attests provenance, and updates
  `[binary.<platform>]` sections in the recipe TOML.
- **gale** — the package manager. Pulls prebuilt
  binaries from GHCR when available, falls back to
  source builds.

**CI flow**: on push, GitHub Actions detects changed
recipes via git diff, builds only those on macOS ARM64
and Linux AMD64 runners, attests provenance via Sigstore,
pushes tar.zst to GHCR via ORAS, updates binary sections,
and commits back via GraphQL (auto-signed "Verified").
workflow_dispatch builds all or a named recipe.

## Linting

Lint recipes:

```
gale lint recipes/**/*.toml
```

Lint workflows with actionlint:

```
actionlint
```

SC2016 warnings are suppressed in
`.github/actionlint.yaml` — jq and GraphQL use `$`
for their own variables, not shell expansion.

## Dev Environment

`gale.toml` + `.envrc` provide dev tools via gale and
direnv. Run `gale sync --local` to install from local
recipes, or let direnv activate automatically on cd.

## Gotchas

- Recipes imported via `gale import homebrew <name>` carry
  a BSD-2-Clause attribution comment. The heuristic parser
  may produce warnings — review before committing.
- eza requires Rust edition2024 (newer than rustc 1.82).
- Autotools clock-skew errors are handled by gale's build
  module (timestamp reset), not the recipe.
- CI commits use GITHUB_TOKEN so they don't re-trigger
  workflows. Switching to a PAT or App token would cause
  an infinite rebuild loop — add commit-message filtering
  first.
