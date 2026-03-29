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
- Build variables available: `${PREFIX}`, `${VERSION}`,
  `${JOBS}`, `${OS}`, `${ARCH}`, `${PLATFORM}`
