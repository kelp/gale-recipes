# TODO

## Recipes to Create

### Build Tools

- [ ] autoconf
- [ ] automake
- [ ] libtool
- [ ] protobuf

### Libraries

- [ ] sqlite — embedded database
- [ ] xz — compression library

### Shells

- [ ] bash — macOS ships 3.2 (2007)
- [ ] zsh — macOS version is dated
- [ ] tmux — terminal multiplexer

### Editors

- [ ] neovim (deps: cmake, gettext, tree-sitter,
  luajit, libuv)

### Rust CLI Tools

- [ ] bandwhich — network bandwidth monitor
- [ ] shellcheck — shell script linter (Haskell, but
  check if Rust port exists)
- [ ] tokei — code statistics
- [ ] xh — modern HTTP client

### Go CLI Tools

- [ ] duf — modern df
- [ ] shfmt — shell formatter
- [ ] tig — git TUI (C, not Go)

### Git Ecosystem

- [ ] git-lfs — large file storage

### Network

- [ ] nmap — network scanner

### Compression

- [ ] pigz — parallel gzip

### Containers / Cloud

- [ ] kubectl — Kubernetes CLI (Go)
- [ ] terraform — infrastructure as code (Go)
- [ ] helm — Kubernetes packages (Go)
- [ ] awscli (deps: cmake, openssl)
- [ ] google-cloud-sdk

### Zig

- [ ] zig — toolchain
- [ ] vibeutils (deps: zig)
- [ ] bun (deps: zig)

### Binary-Only

- [ ] 1password-cli

## Done

67 recipes shipped:

actionlint, atuin, bat, btop, bzip2, chezmoi, cmake,
coreutils, curl, deadnix, difftastic, direnv, doctl,
doggo, dust, eza, fastfetch, fd, fish, flac, fzf,
gale, gettext, gh, git, git-delta, gmp, gnumake, go,
gofumpt, golangci-lint, gping, hyperfine, jq, just,
lazygit, libidn2, libogg, libyaml, lsof, lua,
mariadb, mise, mtr, nodejs, openssl, ouch, patchelf,
pcre2, pkgconf, pnpm, postgresql, procs, ripgrep,
rsync, ruby, rust, rustup, scc, starship, statix,
tealdeer, tree-sitter, traceroute, trippy, unzip, uv,
wget, yq, zellij, zoxide, zstd

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [x] `gale build` injects `${VERSION}` from recipe
- [x] Binary index separation (`.binaries.toml` files)
- [x] CI downloads gale release binary (no Go build)
- [x] Source tarball cache (`~/.gale/cache/`)
- [x] Build logs uploaded as artifacts on failure
- [ ] Source download cache (`--cache-dir` flag in gale)
