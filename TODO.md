# TODO

## Recipes to Create

- [ ] awscli (deps: cmake, openssl, python)
- [ ] google-cloud-sdk (Python bundle)
- [ ] 1password-cli (binary-only)
- [ ] neovim gettext fix (macOS iconv linker error)

## Done

95 recipes:

actionlint, autoconf, atuin, automake, bandwhich, bash,
bat, btop, bun, bzip2, chezmoi, cmake, coreutils, curl,
deadnix, difftastic, direnv, doctl, doggo, duf, dust,
eza, fastfetch, fd, fish, flac, fzf, gale, gettext, gh,
git, git-delta, git-lfs, gmp, gnumake, go, gofumpt,
golangci-lint, gping, helm, hyperfine, jq, just, kubectl,
lazygit, less, libevent, libidn2, libogg, libtool,
libyaml, lsof, lua, mariadb, mise, mtr, neovim, nmap,
nodejs, openssl, ouch, patchelf, pcre2, pigz, pkgconf,
pnpm, postgresql, procs, protobuf, ripgrep, rsync, ruby,
rust, rustup, scc, shfmt, sqlite, starship, statix,
tealdeer, terraform, tig, tmux, tokei, traceroute, tree,
tree-sitter, trippy, unzip, uv, vibeutils, wget, xh, xz,
yq, zellij, zig, zoxide, zsh, zstd

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [x] `gale build` injects `${VERSION}` from recipe
- [x] Binary index separation (`.binaries.toml` files)
- [x] CI downloads gale release binary (no Go build)
- [x] Source tarball cache (`~/.gale/cache/`)
- [x] Build logs uploaded as artifacts on failure
- [x] Recipe signing in CI
- [ ] `.tar.xz` extraction support in gale
- [ ] GNU auto-update support (gitweb/FTP mirror
  version detection)
