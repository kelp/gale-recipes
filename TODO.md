# TODO

## Recipes to Create

- [ ] 1password-cli (binary-only)
- [ ] neovim gettext fix (macOS iconv linker error)

## Done

113 recipes:

actionlint, age, autoconf, atuin, automake, awscli,
bandwhich, bash, bat, btop, bun, bzip2, chezmoi, cmake,
coreutils, curl, deadnix, difftastic, direnv, docker,
doctl, doggo, duckdb, duf, dust, eza, fastfetch, fd,
fish, flac, fzf, gale, gettext, gh, git, git-delta,
git-lfs, glow, gmp, gnumake, go, gofumpt, golangci-lint,
google-cloud-sdk, gping, grpcurl, helix, helm, httpstat,
hyperfine, jless, jq, just, k9s, kubectl, lazygit, less,
libevent, libidn2, libogg, libtool, libyaml, lsof, lua,
mariadb, micro, mise, mongosh, mosh, mtr, neovim, nmap,
nodejs, openssl, ouch, patchelf, pcre2, pigz, pkgconf,
pnpm, podman, postgresql, procs, protobuf, pscale,
python, redis, ripgrep, rsync, ruby, rust, rustup, scc,
shfmt, socat, sqlite, starship, statix, tealdeer,
terraform, tig, tmux, tokei, traceroute, tree,
tree-sitter, trippy, unzip, uv, vibeutils, wget, xh, xz,
yq, zellij, zig, zoxide, zsh, zstd

## Reproducible Builds

- [ ] **Deterministic build investigation** — run
  `gale audit` against each recipe. Document which
  produce identical hashes when rebuilt from source.
  For those that don't, identify causes (timestamps,
  embedded paths, build IDs, link ordering). Track
  per-recipe status and fixes.

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [x] `gale build` injects `${VERSION}` from recipe
- [x] Binary index separation (`.binaries.toml` files)
- [x] CI downloads gale release binary (no Go build)
- [x] Source tarball cache (`~/.gale/cache/`)
- [x] Build logs uploaded as artifacts on failure
- [x] Recipe signing in CI
- [x] Post-edit gale lint hook
- [x] Recipe-creator agent definition
- [ ] `.tar.xz` extraction support in gale
- [ ] GNU auto-update (gitweb/FTP version detection)
