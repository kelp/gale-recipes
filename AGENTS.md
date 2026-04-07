# AGENTS.md

Guidance for AI coding agents working in `gale-recipes`.

## Core Rule

Prefer static linking for CLI tools where practical.

- On **Linux**, prefer static linking of non-system deps
  and the C++ runtime where feasible, but keep glibc
  dynamic unless a recipe explicitly needs full static.
- On **macOS**, full static linking is usually not
  viable, so prefer dynamic linking with correct rpaths
  and post-build fixups.
- Do **not** force static linking for libraries,
  language runtimes, plugin hosts, or packages intended
  to be linked against by other packages.

## Recipe Principle

Do not remove functionality just to make a build pass.
If a dependency is required, package it or declare it.

## More Detail

See `docs/dev/linking-policy.md`.
