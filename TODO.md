# TODO

## Recipes to Create

- [ ] 1password-cli (binary-only)

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

Investigated 2026-03-30. Not worth pursuing. Archive
packaging is now deterministic (symlink fixup, zstd
concurrency=1, ZERO_AR_DATE) but compiled binaries
differ due to Mach-O LC_UUID, embedded paths in .la/.pc
files, and ar timestamps. Achieving full determinism
would require Nix-level isolation (fixed build paths,
sandboxed toolchain). The `gale audit` command exists
but isn't useful until this is solved.

## Auto-Update Agent

- [ ] **Cron workflow** — daily workflow. For each
  recipe with `[source].repo`, query
  `gh api /repos/{owner}/{repo}/releases/latest`.
- [ ] **Cooldown enforcement** — skip versions less
  than 3 days old (from upstream release date).
  Security patches can be fast-tracked manually.
- [ ] **PR per update** — each version bump creates a
  PR with updated version, SHA256, and source URL.
  CI builds on both platforms.
- [ ] **AI build recovery** — when a version bump
  breaks the build, use Claude Code SDK to read the
  error and attempt a recipe fix. Falls back to
  opening a GitHub issue if the fix fails.

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
- [ ] GNU auto-update (gitweb/FTP version detection)
