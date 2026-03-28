# Creating Gale Recipes

A recipe is a TOML file that tells gale how to build a
CLI tool from source. This guide walks through creating
one from scratch.

## Quick Start

1. Find the tool's GitHub repo and latest release
2. Create `recipes/<first-letter>/<name>.toml`
3. Fill in the recipe fields
4. Test with `gale build recipes/<letter>/<name>.toml`
5. Verify the built binary runs

## Recipe Location

Recipes are organized by first letter of the tool name:

```
recipes/
  a/actionlint.toml
  b/bat.toml
  f/fd.toml
  f/fzf.toml
  j/jq.toml
```

## Recipe Structure

Every recipe needs three sections: `[package]`,
`[source]`, and `[build]`.

### [package] (required)

```toml
[package]
name = "actionlint"
version = "1.7.11"
description = "Static checker for GitHub Actions workflow files"
license = "MIT"
homepage = "https://github.com/rhysd/actionlint"
```

All fields are required. Use the SPDX license identifier.

### [source] (required)

```toml
[source]
repo = "rhysd/actionlint"
url = "https://github.com/rhysd/actionlint/archive/refs/tags/v1.7.11.tar.gz"
sha256 = "a2c073d2aac12e9fe6b5b82f0bc1780d08b04bd6a331958cd783e46ee48e9cdf"
released_at = "2026-02-14"
```

- `url` and `sha256` are required
- `repo` enables automatic version updates (daily CI
  check). Use the `owner/repo` format.
- `released_at` sets a cooldown — auto-update waits
  3 days after a release before proposing an upgrade

Get the sha256 for a source tarball:

```
curl -sL <url> | shasum -a 256
```

#### Source URL patterns

Most GitHub projects use one of two URL patterns:

**Archive** (preferred — deterministic tarball):
```
https://github.com/<owner>/<repo>/archive/refs/tags/v<version>.tar.gz
```

**Release download** (when the project provides its own
tarball, e.g. with bundled deps or generated files):
```
https://github.com/<owner>/<repo>/releases/download/v<version>/<name>-<version>.tar.gz
```

The tag format varies by project — some use `v1.2.3`,
others use `1.2.3` or `<name>-1.2.3`. Check the
project's releases page.

### [build] (required)

```toml
[build]
steps = [
  "mkdir -p ${PREFIX}/bin",
  "go build -o ${PREFIX}/bin/actionlint ./cmd/actionlint",
]
```

Steps run in a clean shell inside the extracted source
directory. Two variables are available:

- `${PREFIX}` — install destination (bin/, lib/, etc.)
- `${JOBS}` — CPU count for parallel make

### [dependencies] (optional)

```toml
[dependencies]
build = ["go"]
runtime = []
```

- `build` — tools needed at compile time (resolved by
  gale from other recipes)
- `runtime` — libraries needed at run time

### [binary.<platform>] (CI-managed)

```toml
[binary.darwin-arm64]
url = "https://ghcr.io/v2/kelp/gale-recipes/..."
sha256 = "..."
```

Do not write these by hand. CI adds them after a
successful build and push to GHCR.

## Build Patterns by Language

### Go

Go has no install-to-prefix convention. Create the bin
directory and build directly into it.

```toml
[build]
steps = [
  "mkdir -p ${PREFIX}/bin",
  "go build -o ${PREFIX}/bin/<name>",
]

[dependencies]
build = ["go"]
```

If the main package is in a subdirectory:

```toml
steps = [
  "mkdir -p ${PREFIX}/bin",
  "go build -o ${PREFIX}/bin/<name> ./cmd/<name>",
]
```

### Rust (Cargo)

Always use `--path .` to build from local source.
Without it, cargo fetches from crates.io instead.

```toml
[build]
steps = [
  "cargo install --path . --root ${PREFIX}",
]

[dependencies]
build = ["rust"]
```

Some Rust projects need additional build dependencies:

```toml
[dependencies]
build = ["cmake", "pkgconf", "rust"]
```

### Autotools (C/C++)

The standard configure/make/install pattern:

```toml
[build]
steps = [
  "./configure --prefix=${PREFIX} --disable-docs",
  "make -j${JOBS}",
  "make install",
]
```

Tips:
- Use `--disable-docs --disable-maintainer-mode` to
  skip optional tooling that may not be available
- Bundle dependencies when possible (e.g.
  `--with-oniguruma=builtin`) to avoid external libs
- Clock-skew errors from timestamps in tarballs are
  handled by gale's build module automatically

### CMake

```toml
[build]
steps = [
  "cmake -B build -DCMAKE_INSTALL_PREFIX=${PREFIX}",
  "cmake --build build -j ${JOBS}",
  "cmake --install build",
]

[dependencies]
build = ["cmake"]
```

## Testing

Build the recipe locally:

```
gale build recipes/<letter>/<name>.toml
```

Verify the binary works:

```
tmpdir=$(mktemp -d)
python3 -c "
import tarfile
tarfile.open('<name>-<ver>.tar.zst','r:*').extractall('$tmpdir')
"
$tmpdir/bin/<name> --version
rm -rf $tmpdir
```

## Importing from Homebrew

Gale can generate a recipe from a Homebrew formula:

```
gale import homebrew <name>
```

Imported recipes carry a BSD-2-Clause attribution
comment. The heuristic parser may produce warnings —
review the output before committing. Build steps often
need manual adjustment.

## Auto-Update Support

Recipes with a `repo` field are checked daily for new
upstream releases. The auto-update agent:

1. Queries the GitHub API for the latest release
2. Waits 3 days after release (cooldown)
3. Downloads the new source tarball and computes sha256
4. Creates a PR updating version, url, sha256, and
   released_at
5. Removes `[binary.*]` sections (triggers rebuild on
   merge)

To opt out of auto-update, omit the `repo` field.

## Checklist

Before submitting a new recipe:

- [ ] File is at `recipes/<first-letter>/<name>.toml`
- [ ] All `[package]` fields filled in
- [ ] `sha256` matches the source URL
- [ ] `repo` field set for auto-update
- [ ] Build tested with `gale build`
- [ ] Binary runs (`--version` or `--help`)
- [ ] No `[binary.*]` sections (CI adds these)
