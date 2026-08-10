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
  7 days after a release before proposing an upgrade

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

Each list accepts entries in either of two forms:

```toml
[dependencies]
build = ["curl", "expat", "gnumake", "pkgconf"]
runtime = [
  "zlib",
  { name = "openssl", version = ">=3.6.0-1" },
]
```

- **Bare string** — resolves to whatever the current
  registry says is latest. No constraint; the installer
  accepts any version the resolver returns. This is the
  default for everything the catalog ships today.
- **Inline table** — pins the dep against a version
  constraint. Keys: `name` (required) and `version`
  (optional constraint expression). The expression uses
  the same syntax as `.gale-deps.toml` range
  constraints: `"=1.2.3-2"` (exact), `">=1.2.3-2"`
  (floor), `"<2.0.0"` (ceiling), or any of `>`, `>=`,
  `<`, `<=`, `=`. A bare `"1.2.3"` means `=1.2.3-1`.

The constraint is enforced at install time. If the
resolved dep's version doesn't satisfy it, the install
fails with a message naming the dep, the required
constraint, and the version actually found. Bare deps
skip the check entirely.

Pin a dep when a soname or ABI change in it would
require rebuilding the dependent. Leave it bare when the
dep is ABI-stable across revisions, or when the
dependent statically links it.

CI records the resolved (name, version, revision)
closure each build was linked against into a
per-platform `deps` array-of-tables inside
`.binaries.toml`. That block is informational — the
archive's own `.gale-deps.toml` stays authoritative for
staleness detection. See
[`../../gale/docs/revisions.md`](../../gale/docs/revisions.md).

### [binary.<platform>] (CI-managed)

```toml
[binary.darwin-arm64]
url = "https://ghcr.io/v2/kelp/gale-recipes/..."
sha256 = "..."
```

Do not write these by hand. CI adds them after a
successful build and push to GHCR.

#### Binary trust policy

A recipe that ships an *inline* `[binary.<platform>]`
section — rare, since CI-produced binaries go through
the separate `.binaries.toml` path — may declare a
`trust` field:

- `trust = "sigstore"` (**default when omitted**) — the
  binary must be served from `ghcr.io` and carry a
  Sigstore attestation tied to gale-recipes CI. This is
  the fail-safe default: forgetting the field enforces
  attestation, it does not bypass it.
- `trust = "sha256-only"` — the binary comes from an
  upstream host that doesn't publish attestations keyed
  to our signing identity (a vendor CDN, a language
  toolchain release artifact). Only the SHA256 is
  verified, and a recipe must opt in explicitly.

Typos in `[binary.<platform>]` field names fail parsing,
the same strict-schema rule that applies to `[package]`
and `[source]`.

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

Install straight from the local recipe:

```
gale install <name> --recipe recipes/<letter>/<name>.toml
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

1. Queries the GitHub API for the latest release (falls
   back to `/tags` for projects without releases)
2. Waits 7 days after our first observation (cooldown)
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
