---
name: new-recipe
description: Scaffold a new gale recipe TOML file from a GitHub repo
disable-model-invocation: true
---

# New Recipe

Create a new gale recipe TOML file for a CLI tool.

## Usage

`/new-recipe <github-org/repo>` or `/new-recipe <name>`

## Steps

1. **Resolve the repo.** If the user gives a short name
   (e.g. "bat"), search GitHub for it. If they give
   `org/repo`, use that directly.

2. **Fetch the latest release** via `gh api`:
   ```bash
   gh api "/repos/<org>/<repo>/releases/latest"
   ```
   Extract the tag name and published date.

3. **Detect the build system.** Check the repo root for:
   - `Cargo.toml` -> Cargo recipe
   - `go.mod` -> Go recipe
   - `configure` or `Makefile.am` -> Autotools recipe
   - `CMakeLists.txt` -> CMake recipe
   - `Makefile` -> Make recipe

   Use `gh api` to list repo contents:
   ```bash
   gh api "/repos/<org>/<repo>/contents" --jq '.[].name'
   ```

4. **Determine the source URL.** Prefer the tarball from
   `/archive/refs/tags/<tag>.tar.gz`. If the project
   ships release tarballs (autotools projects often do),
   check the release assets.

5. **Download and hash the tarball:**
   ```bash
   curl -sL "<url>" -o /tmp/recipe-src.tar.gz
   shasum -a 256 /tmp/recipe-src.tar.gz | awk '{print $1}'
   ```

6. **Detect dependencies.** For Cargo projects, build deps
   are `["rust"]`. For Go, `["go"]`. For autotools,
   typically `["autoconf", "automake", "libtool"]`. Check
   existing recipes in the repo for patterns.

7. **Write the recipe file** to
   `recipes/<first-letter>/<name>.toml` using this
   template:

### Cargo template

```toml
[package]
name = "<name>"
version = "<version>"
description = "<description from GitHub>"
license = "<license>"
homepage = "<homepage>"

[source]
repo = "<org/repo>"
url = "<tarball-url>"
sha256 = "<sha256>"
released_at = "<published-date>"

[build]
steps = [
  "cargo install --path . --root ${PREFIX}",
]

[dependencies]
build = ["rust"]
```

### Go template

```toml
[package]
name = "<name>"
version = "<version>"
description = "<description from GitHub>"
license = "<license>"
homepage = "<homepage>"

[source]
repo = "<org/repo>"
url = "<tarball-url>"
sha256 = "<sha256>"
released_at = "<published-date>"

[build]
steps = [
  "mkdir -p ${PREFIX}/bin",
  "go build -o ${PREFIX}/bin/<name>",
]

[dependencies]
build = ["go"]
```

### Autotools template

```toml
[package]
name = "<name>"
version = "<version>"
description = "<description from GitHub>"
license = "<license>"
homepage = "<homepage>"

[source]
repo = "<org/repo>"
url = "<tarball-url>"
sha256 = "<sha256>"
released_at = "<published-date>"

[build]
steps = [
  "./configure --prefix=${PREFIX}",
  "make -j${JOBS}",
  "make install",
]

[dependencies]
build = ["autoconf", "automake", "libtool"]
```

## Rules

- The `--path .` flag is REQUIRED for cargo install.
  Without it, cargo fetches from crates.io.
- Go has no install-to-prefix convention. Always use
  `mkdir -p ${PREFIX}/bin` then `go build -o`.
- For autotools, add `--disable-docs` and
  `--disable-maintainer-mode` when supported.
- Bundle dependencies when possible (e.g.
  `--with-oniguruma=builtin` for jq).
- Do NOT add `[binary.*]` sections. CI populates those.
- Check existing recipes in the repo for reference.
