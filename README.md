# gale-recipes

Index repository for [Gale](https://github.com/kelp/gale).

Each document under `index/` is version-keyed TOML that
names an upstream artifact: URL, `sha256`,
`hash_source`, `tree_digest`, `format`, and a file map.
Gale fetches those artifacts. Not-in-index is an error.

## Layout

```
index/
  j/
    jq.toml             # fetch catalog — authored by gale admit
```

The fetch catalog is letter-bucketed. Each file is an
index document: `gale admit` prints the artifact tables;
do not invent `tree_digest`. `gale lint` validates those
files.

Current Darwin/arm64 entries include the first ten
(`jq`, `ripgrep`, `fd`, `just`, `gh`, `direnv`,
`gofumpt`, `golangci-lint`, `uv`, `go`) and a later
growth wave (`fzf`, `age`, `shfmt`, `actionlint`, `yq`,
`shellcheck`, `starship`, `zoxide`). The first ten
also have `linux/amd64`.

Source-build recipes, `.binaries.toml` ledgers, and
promote / verify-build CI are gone. Do not recreate
them.

## Development

```sh
just lint    # index lint + actionlint
just test    # scripts/ unit tests
```

`gale install` and `gale build` cannot run in the agent
sandbox. Do not use them as proof.
