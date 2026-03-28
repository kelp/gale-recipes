# gale-recipes

Official recipe repository for
[Gale](https://github.com/kelp/gale). Each recipe
describes how to build a package from source. CI builds
every recipe on macOS and Linux, pushes prebuilt
binaries to GHCR, and attests provenance via Sigstore.

## Layout

Recipes are TOML files, organized by first letter.
Binary metadata lives in separate `.binaries.toml`
files managed by CI.

```
recipes/
  j/
    jq.toml             # recipe (human-authored)
    jq.binaries.toml    # binary index (CI-managed)
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

Build steps run in a clean shell with `${PREFIX}`,
`${VERSION}`, `${JOBS}`, `${OS}`, `${ARCH}`, and
`${PLATFORM}` available.

See [docs/creating-recipes.md](docs/creating-recipes.md)
for the full guide.

## Development

Install dev tools:

```
gale sync --local
```

Or let direnv activate automatically on cd.

Lint recipes and workflows:

```
just lint
```

Update gale from source:

```
just update-gale
```

## Contributing

Add a recipe at `recipes/<first-letter>/<name>.toml`.

Get source sha256:

```
curl -sL <url> | shasum -a 256
```

Build and test:

```
gale build --local recipes/<letter>/<name>.toml
```

Install locally:

```
gale install <name> --recipe recipes/<letter>/<name>.toml
```

Lint before committing:

```
just lint
```
