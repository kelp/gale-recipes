---
name: recipe-creator
description: Create a gale recipe TOML for a package. Use when adding a new package to gale-recipes, or when batch-creating several recipes. Handles the import-from-homebrew baseline, build-system detection, sha256 capture, and the macOS rpath rules.
---

# Recipe Creator Agent

Create a gale recipe for a given package.

## Inputs

The package name (and optionally GitHub org/repo).

## Process

1. Run `gale import homebrew <name>` for a starting point
2. Check the GitHub repo for:
   - Latest release version and date
   - Build system (Cargo.toml, go.mod, CMakeLists.txt,
     configure, Makefile)
   - For Cargo workspaces: find the correct `--path`
     to the binary crate (not `--path .`)
3. Get the source sha256:
   `curl -sL <url> | shasum -a 256`
4. Write the recipe to
   `recipes/<first-letter>/<name>.toml`
5. Run `gale lint` on the recipe

## Patterns

### Cargo (Rust)
```toml
[build]
steps = ["cargo install --path . --root ${PREFIX}"]
[dependencies]
build = ["rust"]
```
The `--path .` flag is required. For workspaces, use
`--path <crate-dir>` (e.g. `--path crates/cli`).

### Go
```toml
[build]
steps = [
  "mkdir -p ${PREFIX}/bin",
  "go build -o ${PREFIX}/bin/<name> ./cmd/<name>",
]
[dependencies]
build = ["go"]
```

### Autotools (C)
```toml
[build]
steps = [
  "./configure --prefix=${PREFIX}",
  "make -j${JOBS}",
  "make install",
]
```

### cmake (C/C++)
```toml
[build]
steps = [
  "cmake -S . -B build -DCMAKE_INSTALL_PREFIX=${PREFIX} -DCMAKE_BUILD_TYPE=Release",
  "cmake --build build -j ${JOBS}",
  "cmake --install build",
]
[dependencies]
build = ["cmake"]
```

## macOS rpath / verifiability

The installed binary must be byte-identical to the
CI-built, SHA256'd, Sigstore-attested artifact. Since gale
0.16.3, install no longer rewrites rpaths and a package's
own broken `@rpath` refs are NOT auto-fixed: if a Mach-O
references `@rpath/lib<self>.dylib` with no resolving
`LC_RPATH`, dyld aborts and `scripts/check_install.py`
fails the build. Common in C/C++ recipes where a `bin/`
tool or `lib/<pkg>/` plugin links a sibling dylib. Prefer,
in order:

1. **Static-link to remove the dylib** (preferred — no rpath
   to fix, most verifiable). E.g. cmake
   `-DENABLE_SHARED=OFF -DENABLE_STATIC=ON`, autotools
   `--disable-shared --enable-static`.
2. **Bake the rpath in a build step** (only when shared libs
   must ship), so it lands in the artifact before hashing —
   build-time, not install-time:
   `"for b in ${PREFIX}/bin/*; do [ -f \"$b\" ] || continue; file \"$b\" | grep -q Mach-O || continue; install_name_tool -add_rpath @loader_path/../lib \"$b\" 2>/dev/null || true; done"`
   Compute `@loader_path/<rel>/lib` from the binary's dir to
   `${PREFIX}/lib`. See `recipes/o/openssl4.toml`,
   `recipes/p/postgresql.toml`.
3. **Never** use a post-install hook or rely on gale patching
   the binary on the user's machine — it breaks verification.

Full rationale: `docs/dev/linking-policy.md`.

## Rules

- Add `repo = "owner/repo"` in `[source]` for
  auto-update
- Add `released_at` from the GitHub release date
- Do NOT include `[binary.*]` sections — CI adds those
- Do NOT strip features to avoid dependencies — build
  the package as upstream intends
- Drop doc-generation deps (pandoc, asciidoctor,
  sphinx) unless the user asks for docs
- Use `[build.darwin-arm64]` and `[build.linux-amd64]`
  sections when platform-specific steps differ
- Prefer static linking for CLI tools; on macOS never
  rely on install-time rpath rewriting (gale 0.16.3+
  doesn't do it) — bake any needed rpath at build time
- Build variables available: `${PREFIX}`, `${VERSION}`,
  `${JOBS}`, `${OS}`, `${ARCH}`, `${PLATFORM}`
