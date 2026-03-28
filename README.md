# gale-recipes

Official recipe repository for [Gale](https://github.com/kelp/gale).

## Layout

Recipes are TOML files organized by first letter:

```
recipes/
  b/bat.toml
  f/fd.toml
  j/jq.toml
  r/ripgrep.toml
```

## Recipe Format

```toml
[package]
name = "jq"
version = "1.7.1"
description = "Lightweight and flexible command-line JSON processor"
license = "MIT"
homepage = "https://jqlang.github.io/jq"

[source]
url = "https://github.com/jqlang/jq/releases/download/jq-1.7.1/jq-1.7.1.tar.gz"
sha256 = "478c9ca..."

[build]
steps = [
  "./configure --prefix=${PREFIX} --with-oniguruma=builtin",
  "make -j${JOBS}",
  "make install",
]

[dependencies]
build = ["autoconf", "automake", "libtool"]
```

## Development

Install dev tools with gale:

```
gale sync
```

Or let direnv activate automatically if you have
`use gale` in your shell (see `gale hook direnv`).

Lint workflows:

```
actionlint
```

## Contributing

See [docs/creating-recipes.md](docs/creating-recipes.md)
for a full guide.

Add a recipe file under `recipes/<first-letter>/<name>.toml`.
Build and test it locally:

```
gale build recipes/<letter>/<name>.toml
```

Install from a local recipe:

```
gale install <name> --recipe recipes/<letter>/<name>.toml
```
