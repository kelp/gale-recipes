# gale-recipes

Fetch index for [Gale](https://github.com/kelp/gale).

Gale fetches upstream CLI binaries, pins their hashes
in a lockfile, and puts them on PATH. It does not
compile packages. It does not ship bottles.

This repo names those binaries. Each document under
`index/` is version-keyed TOML: URL, `sha256`,
`hash_source`, `tree_digest`, `format`, and a file
map. Gale fetches what the document names.
Not-in-index is an error.

## Layout

```
index/
  j/
    jq.toml             # authored by gale admit
```

The catalog is letter-bucketed. `gale admit` prints
the artifact tables; do not invent `tree_digest`.
`gale lint` validates those files.

Current Darwin/arm64 entries include the first ten
(`jq`, `ripgrep`, `fd`, `just`, `gh`, `direnv`,
`gofumpt`, `golangci-lint`, `uv`, `go`) and a later
growth wave (`fzf`, `age`, `shfmt`, `actionlint`, `yq`,
`shellcheck`, `starship`, `zoxide`). The first ten
also have `linux/amd64`.

## Adding a package

See [docs/writing-recipes.md](docs/writing-recipes.md).

```sh
gale admit --archive <file> --name <name> ...
gale lint index/<letter>/<name>.toml
```

Do not write `[build] steps`. Fetch is the only
installer.

## Development

```sh
just lint    # index lint + actionlint
just test    # scripts/ unit tests
```

`gale install` cannot run in the agent sandbox.
Do not use it as proof.
