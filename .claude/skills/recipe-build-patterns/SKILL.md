---
name: recipe-build-patterns
description: Per-buildsystem patterns for writing gale recipe build steps — autotools, cargo, go, cmake, and zig. Use when authoring or editing a recipe's [build] steps, or when a recipe build fails at the configure/compile/install stage.
---

# Recipe Build Patterns

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

**Zig** (vibeutils, zls, zmx): Always pass
`-Dcpu=baseline` to `zig build`. The default target is
`native`, which bakes in whatever instructions the CI
runner happens to have; the resulting binary then SIGILLs
on real-world targets that lack them (AMD EPYC Milan
without AVX-512, older Intel, cloud VMs). Baseline = SSE2
on x86_64, armv8.0-a on aarch64; perf cost is negligible
for CLI tools and the binary runs everywhere in the
architecture family. Symptom of a missed flag is
"Illegal instruction at address ..." on `bin/<tool>` —
which masquerades as a system fault, especially when the
broken tool is a coreutils replacement on PATH ahead of
GNU. If the upstream pins a specific zig version (check
`build.zig.zon` for `minimum_zig_version`), pin the build
dep accordingly — see `recipes/z/zig15.toml` for the
parallel-install pattern when upstream lags zig releases.
