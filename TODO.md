# TODO

## Recipes to Create

Ordered by dependency chain. Build deps come before
the packages that need them. Checked items have recipes.

### Foundation (deps for everything else)

- [x] openssl
- [x] pkgconf
- [x] cmake
- [x] bzip2
- [x] zstd
- [x] rust
- [x] go

### Leaf Libraries

Needed by packages below. No gale deps beyond
foundation.

- [ ] gettext — needed by: git, wget, neovim
- [ ] pcre2 — needed by: git, fish
- [ ] libidn2 — needed by: curl, wget
- [ ] libogg — needed by: flac
- [ ] libyaml — needed by: ruby
- [ ] gmp — needed by: coreutils

### Tier 1: Simple Rust (deps: rust)

- [x] atuin
- [x] bat
- [x] deadnix
- [x] difftastic
- [x] dust
- [x] eza
- [x] fd
- [x] git-delta
- [x] hyperfine
- [x] just
- [x] ouch
- [x] procs
- [x] ripgrep
- [x] starship
- [x] statix
- [x] tealdeer
- [x] tree-sitter
- [x] trippy
- [x] zellij
- [x] zoxide

### Tier 1: Simple Go (deps: go)

- [x] actionlint
- [x] chezmoi
- [x] doctl
- [x] doggo
- [x] fzf
- [x] gh
- [x] lazygit
- [x] scc
- [x] yq

### Tier 1: Simple C (no gale deps)

- [x] gnumake
- [x] lua
- [x] patchelf
- [x] unzip (deps: bzip2)
- [x] lsof
- [ ] coreutils (deps: gmp)
- [ ] traceroute
- [ ] mtr (deps: pkgconf)

### Tier 2: Rust with Extra Deps

- [x] gping (deps: rust, pkgconf)
- [x] uv (deps: rust, pkgconf)
- [ ] mise (deps: rust, cmake, pkgconf, openssl)
- [ ] rustup (deps: rust, pkgconf, openssl)
- [ ] flac (deps: pkgconf, libogg)

### Tier 3: Needs openssl + leaf libs

- [ ] curl (deps: openssl, pkgconf, zstd, libidn2)
- [ ] wget (deps: openssl, pkgconf, gettext, libidn2)
- [ ] git (deps: openssl, pkgconf, gettext, pcre2)
- [ ] rsync (deps: openssl, zstd)
- [ ] ruby (deps: openssl, rust, pkgconf, libyaml)
- [ ] postgresql (deps: openssl)

### Tier 4: Needs tier 3 or complex deps

- [ ] fish (deps: rust, cmake, pcre2)
- [ ] nodejs
- [ ] mariadb (deps: openssl, pkgconf, cmake, pcre2,
  zstd)
- [ ] btop (deps: cmake)
- [ ] fastfetch (deps: cmake, pkgconf)
- [ ] awscli (deps: cmake, openssl)
- [ ] google-cloud-sdk

### Tier 5: Needs runtimes

- [ ] pnpm (deps: nodejs)
- [ ] bun

### Zig

- [ ] vibeutils (deps: zig toolchain)

### Binary-Only

- [ ] 1password-cli

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [x] `gale build` injects `${VERSION}` from recipe
- [x] Binary index separation (`.binaries.toml` files)
- [x] CI downloads gale release binary (no Go build)
- [x] Source tarball cache (`~/.gale/cache/`)
- [x] Build logs uploaded as artifacts on failure
- [ ] Source download cache (`--cache-dir` flag in gale)
