# Agent Workflow for Recipe Creation

This repository uses Claude Code agents to create
and maintain gale recipes at scale. This document
describes the tools, skills, and methodology.

## Overview

Recipes are created by dispatching parallel agents,
each building one recipe. A single session can produce
dozens of recipes by running 5 agents at a time.

## Skills

### `/new-recipe <name>`

Creates a single recipe interactively. Steps:

1. `gale import homebrew <name>` for a baseline
2. Check GitHub for latest release and build system
3. Compute sha256 from source tarball
4. Write recipe to `recipes/<letter>/<name>.toml`
5. Run `gale lint` to verify

### `/batch-recipes <name1> <name2> ...`

Creates multiple recipes in parallel. Dispatches up
to 5 `programmer` agents, each following the
recipe-creator agent pattern. Skips packages that
already have recipes.

## Agent: recipe-creator

Defined in `.claude/agents/recipe-creator.md`. Contains
the full pattern reference for all build systems:

- **Cargo** (Rust): `cargo install --path . --root ${PREFIX}`
- **Go**: `mkdir -p ${PREFIX}/bin && go build -o ${PREFIX}/bin/<name>`
- **Autotools** (C): `./configure --prefix=${PREFIX} && make && make install`
- **cmake** (C/C++): `cmake -S . -B build && cmake --build build && cmake --install build`
- **Prebuilt binary** (zig, bun, shellcheck): download platform-specific archive, verify sha256, copy binary

## Hooks

### Post-edit gale lint

Defined in `.claude/settings.json`. Automatically runs
`gale lint` on any recipe file after editing. Catches
missing deps, bad sha256, and wrong paths before CI.

### Pre-edit binary section block

Blocks edits that contain `[binary.` — binary metadata
lives in `.binaries.toml` files managed by CI.

### Post-edit TOML syntax check

Validates TOML syntax on every `.toml` file edit.

## Methodology

### Starting a recipe

1. Run `gale import homebrew <name>` — gives version,
   sha256, description, license, deps
2. Check Homebrew output for build system detection
3. Look at the GitHub repo for the correct build
   command (Makefile, build.zig, Cargo.toml, etc.)

### Build system detection

| File in repo | Build system | Pattern |
|---|---|---|
| `Cargo.toml` | Cargo | `cargo install --path .` |
| `go.mod` | Go | `go build -o` |
| `configure` | Autotools | `./configure && make` |
| `CMakeLists.txt` | cmake | `cmake -S . -B build` |
| `Makefile` only | make | `make && make install` |
| `build.zig` | Zig | `zig build --prefix` |

### Common gotchas

- **Cargo workspaces**: `--path .` fails on virtual
  manifests. Check for `[workspace]` without
  `[package]` in root Cargo.toml. Use
  `--path <crate-dir>` instead.
- **Go entrypoints**: Many Go projects put main in
  `./cmd/<name>/`. Use `go build -o ... ./cmd/<name>`.
- **Autotools release tarballs**: Ship pre-generated
  `configure` — no autoconf/automake needed.
- **Doc-only deps**: Drop pandoc, asciidoctor, sphinx
  unless the user asks for docs.
- **Platform-specific builds**: Use
  `[build.darwin-arm64]` and `[build.linux-amd64]`
  when configure flags or URLs differ per platform.

### Batch workflow

1. Identify packages to create
2. Check which already have recipes
3. Dispatch 5 agents in parallel
4. Lint each recipe as agents complete
5. Commit and push the batch
6. Repeat with next 5
