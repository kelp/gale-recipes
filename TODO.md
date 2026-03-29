# TODO

## Recipes to Create

### Build Tools

- [ ] autoconf
- [ ] automake
- [ ] libtool
- [ ] protobuf

### Hard / Complex

- [ ] neovim (deps: cmake, gettext, tree-sitter,
  luajit, libuv)
- [ ] awscli (deps: cmake, openssl, python)
- [ ] google-cloud-sdk (Python bundle)
- [ ] bun (Zig/C++, complex build)

### Binary-Only

- [ ] 1password-cli

### Compression

- [ ] xz — library + CLI (needed for .tar.xz support)

## Done

88 recipes shipped:

actionlint, atuin, bandwhich, bash, bat, btop, bzip2,
chezmoi, cmake, coreutils, curl, deadnix, difftastic,
direnv, doctl, doggo, duf, dust, eza, fastfetch, fd,
fish, flac, fzf, gale, gettext, gh, git, git-delta,
git-lfs, gmp, gnumake, go, gofumpt, golangci-lint,
gping, helm, hyperfine, jq, just, kubectl, lazygit,
less, libevent, libidn2, libogg, libyaml, lsof, lua,
mariadb, mise, mtr, nmap, nodejs, openssl, ouch,
patchelf, pcre2, pigz, pkgconf, pnpm, postgresql,
procs, ripgrep, rsync, ruby, rust, rustup, scc, shfmt,
sqlite, starship, statix, tealdeer, terraform, tig,
tmux, tokei, traceroute, tree, tree-sitter, trippy,
unzip, uv, vibeutils, wget, xh, yq, zellij, zig,
zoxide, zsh, zstd

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [x] `gale build` injects `${VERSION}` from recipe
- [x] Binary index separation (`.binaries.toml` files)
- [x] CI downloads gale release binary (no Go build)
- [x] Source tarball cache (`~/.gale/cache/`)
- [x] Build logs uploaded as artifacts on failure
- [x] Recipe signing in CI
- [ ] Source download cache (`--cache-dir` flag in gale)
- [ ] `.tar.xz` extraction support in gale
