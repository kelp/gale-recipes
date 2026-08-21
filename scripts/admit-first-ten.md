# Admitting the first ten

Index artifacts come from `gale admit` only. Do not
invent `tree_digest`. Do not set `attestation`.

A published `[versions."X"]` is immutable. Every
platform that version will carry must be admitted
before the block is committed. `gale lint --base`
refuses adding a platform later.

Phase 1 platforms: `darwin/arm64`. `darwin/amd64`
only if that admit succeeds. Linux waits for
Milestone 6.

Build gale from `main` (index-lint dispatch or later):

```
go build -o gale ./cmd/gale/
```

Darwin host (codesign is required):

```
./gale admit \
  --archive <local-asset> \
  --name <name> \
  --version <ver> \
  --os darwin \
  --arch arm64 \
  --url <https-url> \
  --hash-source computed \
  --file <src>:<dest>:<644|755>
```

Prefer `--hash-source upstream-sha256sums --sha256 <hex>`
when an upstream checksum file verified.

Wrap stdout in:

```
[package]
name = "..."
description = "..."
license = "..."
homepage = "..."
repo = "owner/repo"
latest = "<ver>"
```

Write `index/<first-letter>/<name>.toml`. Then
`gale lint` that file. If it exists on `main`,
also `gale lint --base <old> <new>`.

Packages in this heading: jq, ripgrep, fd, just,
gh, go, gofumpt, golangci-lint, direnv, uv.

`go` needs a full GOROOT file map or a later
directory-map change. Do not extend PlaceMapped
in the lint-gate PR.

A macOS admit workflow lands with the first
catalog PR, not as an empty stub here.
