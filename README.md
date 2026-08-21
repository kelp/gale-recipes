# gale-recipes

Recipe repository for [Gale](https://github.com/kelp/gale).

Each recipe is a TOML file that describes how to build
a package from source. CI builds every recipe on macOS
ARM64 and Linux AMD64, pushes binaries to GHCR, and
attests provenance via Sigstore. The binaries are a
cache. The recipe is the source of truth.

## Layout

Recipes live in letter-bucketed directories. CI manages
binary indexes and version history alongside each recipe.

```
recipes/
  j/
    jq.toml             # recipe — human-authored
    jq.binaries.toml    # binary index + ledger — CI-managed
index/
  j/
    jq.toml             # fetch catalog — authored by gale admit
```

The fetch catalog under `index/` is letter-bucketed like
recipes. Each file is an index document: `gale admit`
prints the artifact tables; do not invent `tree_digest`.
`gale lint` validates those files. First entries are
Darwin/arm64 (`jq`, `ripgrep`, `fd`, `just`, `gh`,
`direnv`, `gofumpt`, `golangci-lint`, `uv`, `go`).

`.versions` sidecars were a compat index for gale v0.16.5.
The format is retired and every file has been deleted; the
`[[history]]` ledger below carries what they carried. Do
not recreate one
([`docs/dev/ci-architecture.md`](docs/dev/ci-architecture.md)).

Each `.binaries.toml` has two parts. The head mirror (a
top-level `version` plus one `[<platform>]` table per
platform) is what deployed gale clients parse. Below it,
`[[history]]` blocks form an append-only ledger: one entry
per published `<version>-<revision>`, recording each
platform's archive `sha256` and GHCR `manifest_digest`.
The ledger is unbounded by design — entries are never
rewritten or dropped, and the required Ledger Check rejects
any PR that tries. Pruning old entries would be a
deliberate, ruleset-visible act, not routine maintenance.

## Recipe Format

```toml
[package]
name = "jq"
version = "1.8.1"
description = "Lightweight and flexible command-line JSON processor"
license = "MIT"
homepage = "https://jqlang.github.io/jq"

[source]
repo = "jqlang/jq"
url = "https://github.com/jqlang/jq/releases/download/jq-1.8.1/jq-1.8.1.tar.gz"
sha256 = "2be64e71..."

[build]
steps = [
  "./configure --prefix=${PREFIX} --with-oniguruma=builtin",
  "make -j${JOBS}",
  "make install",
]
```

Build steps run in a clean shell. Available variables:

| Variable | Value |
|----------|-------|
| `${PREFIX}` | Install destination |
| `${VERSION}` | Package version |
| `${JOBS}` | CPU count |
| `${OS}` | `darwin` or `linux` |
| `${ARCH}` | `arm64` or `amd64` |
| `${PLATFORM}` | `darwin-arm64` or `linux-amd64` |

## Contributing

Create a recipe:

```sh
gale import homebrew <name>          # starting point
curl -sL <url> | shasum -a 256      # verify sha256
```

Write it to `recipes/<first-letter>/<name>.toml`.
Build and lint:

```sh
gale build recipes/<letter>/<name>.toml
just lint
```

See [docs/creating-recipes.md](docs/creating-recipes.md)
for build patterns (Cargo, Go, autotools, cmake) and
dependency conventions.

## Development

Dev tools are managed by gale itself:

```sh
gale sync --recipes recipes  # install from local recipes
just lint            # gale lint + actionlint
just update-gale     # rebuild gale from source
```

Direnv activates the environment automatically on cd.
