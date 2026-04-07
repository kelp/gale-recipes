# Linking Policy

This repository should **prefer static linking for CLI
packages where practical**.

The goal is simple: binaries installed by Gale should be
predictable, portable, and resistant to missing-runtime-
dep breakage. Static linking reduces rpath complexity,
shrinks the runtime dependency surface, and makes GHCR
prebuilt binaries more reliable on fresh machines.

## Default Rules

### CLI tools

Prefer static linking when practical.

Examples:
- Go and Rust CLIs are usually naturally self-contained.
- C and C++ CLIs should prefer static linkage of
  third-party deps where that is straightforward.
- On Linux, prefer static linkage of the C++ runtime
  where feasible.

### Libraries

Do **not** force static linking by default.

If the main output is a library intended for other
packages to link against, shared libraries are normal
and often required.

### Language runtimes and plugin ecosystems

Do **not** force static linking by default.

Examples:
- Python
- Ruby
- Node.js
- Perl
- Java
- packages that load modules/plugins dynamically

These ecosystems usually expect shared objects, runtime
loading, or toolchain-native layouts.

## Platform Guidance

### Linux

Preferred default:
- static link non-system deps where practical
- static link C++ runtime where practical
- keep **glibc dynamic** unless a recipe explicitly
  targets full static linking

Why not full static glibc everywhere?
- it is often brittle
- upstream build systems frequently do not expect it
- it adds complexity without much benefit for many
  packages

If a Linux package uses shared deps, make sure runtime
paths are correct and work from a prebuilt binary on a
fresh machine.

### macOS

Full static linking is usually not viable.

Preferred default:
- static link what is practical
- otherwise use dynamic linking with correct rpaths
  and fixups

For macOS packages, correctness of install names and
rpaths matters more than trying to force impossible
fully static builds.

## Decision Heuristic

When adding or updating a recipe, ask:

1. Is this a **CLI tool**?
   - If yes, prefer static linking where practical.
2. Is this a **library or runtime**?
   - If yes, do not force static linking.
3. Is full static linking likely to fight the platform?
   - On macOS: usually yes.
   - On Linux: maybe, especially for glibc.
4. Will dynamic linking make the prebuilt fragile?
   - If yes, either move toward static linkage or ensure
     runtime search paths are correct.

## What Counts as "Practical"

Static linking is practical when it does **not** require:
- patching upstream heavily
- replacing major parts of the build system
- breaking standard runtime behavior
- shipping a visibly reduced-feature build

If static linking would significantly distort the build,
prefer the upstream-supported dynamic build and make the
runtime paths correct.

## Recipe Author Expectations

- Prefer static linkage for CLI tools when it is a clean,
  upstream-compatible choice.
- Do not delete features or optional integrations just to
  avoid dealing with linking.
- If a package genuinely needs shared deps, declare them
  correctly and make sure the resulting prebuilt works.
- If a package needs a newer compiler/toolchain to make
  the preferred linking strategy work, solve that at the
  toolchain level rather than by adding ad hoc per-runner
  hacks.

## Future Direction

Longer term, Gale should support explicit toolchain
selection for recipes so modern C++ packages can use a
packaged LLVM toolchain cleanly. That is the right fix
for packages whose modern language/library requirements
exceed the default CI runner toolchain.
