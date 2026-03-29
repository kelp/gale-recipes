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
    jq.binaries.toml    # binary index — CI-managed
    jq.versions         # version history
```

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
gale sync --local    # install from local recipes
just lint            # gale lint + actionlint
just update-gale     # rebuild gale from source
```

Direnv activates the environment automatically on cd.
