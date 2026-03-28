# TODO

## Recipes to Create

Sorted by dependency order — build deps first, then
packages that need them. Deps in parentheses; **bold**
means we already have the recipe.

### Tier 0: Leaf Dependencies

These are build/runtime deps for packages below. Must
come first.

- [ ] openssl — TLS library (autotools). Needed by:
  curl, git, wget, rsync, ruby, rustup, zellij, atuin,
  uv, mise, awscli, mariadb, postgresql
- [ ] gettext — i18n library (autotools). Needed by:
  git, wget, neovim
- [ ] pcre2 — regex library (autotools). Needed by:
  git, fish
- [ ] libidn2 — internationalized domain names
  (autotools). Needed by: curl, wget
- [ ] zstd — compression (cmake, **already a dep of
  gcc**). Needed by: curl, rsync
- [ ] libogg — audio codec (autotools). Needed by: flac
- [ ] gmp — arbitrary precision math (autotools).
  Needed by: gcc, coreutils

### Tier 1: Core System Tools

- [x] gnumake — build automation (autotools, no deps)
- [x] lua — scripting language (make, no deps)
- [ ] coreutils — GNU core utilities (autotools;
  deps: gmp)
- [ ] openssl (from tier 0, listed here for ordering)

### Tier 2: Simple Rust and Go Packages

#### Rust (deps: **rust**)

- [x] difftastic
- [x] dust
- [x] hyperfine
- [x] procs
- [x] tealdeer
- [x] trippy
- [x] zoxide
- [x] zellij
- [x] tree-sitter
- [x] deadnix
- [x] statix

#### Go (deps: **go**)

- [x] chezmoi
- [x] doggo
- [x] gh
- [x] scc
- [x] yq
- [x] doctl

### Tier 3: Rust/Go with Extra Build Deps

- [x] gping — (deps: **rust**, **pkgconf**)
- [x] uv — (deps: **rust**, **pkgconf**)
- [x] atuin — (deps: **rust**)
- [ ] mise — version manager (deps: **rust**, **cmake**,
  **pkgconf**, openssl)
- [ ] rustup — Rust toolchain manager (deps: **rust**,
  **pkgconf**, openssl)
- [ ] flac — audio codec (deps: **pkgconf**, libogg)

### Tier 4: C/C++ System Packages

- [x] lsof — list open files
- [x] unzip — archive extraction
- [ ] curl — HTTP client (autotools; deps: openssl,
  **pkgconf**, zstd, libidn2, libssh2, libnghttp2)
- [ ] wget — file downloader (autotools; deps: openssl,
  **pkgconf**, gettext, libidn2)
- [ ] git — version control (autotools; deps: openssl,
  **pkgconf**, gettext, pcre2)
- [ ] rsync — file sync (autotools; deps: openssl,
  zstd, lz4, xxhash)
- [ ] fish — shell (cmake; deps: **rust**, **cmake**,
  pcre2)
- [ ] mtr — network diagnostics (autotools; deps:
  **pkgconf**)
- [ ] traceroute — network diagnostics (make)

### Zig

- [ ] vibeutils — modern Unix coreutils with git-aware
  ls, colored output, Nerd Font icons (Zig; deps: zig
  toolchain; github.com/kelp/vibeutils)

### Tier 5: Languages and Runtimes

- [ ] gcc — compiler (autotools; deps: gmp, isl,
  libmpc, mpfr, zstd, **gnumake**)
- [ ] ruby — language (autotools; deps: openssl,
  **rust**, **pkgconf**, libyaml)
- [ ] nodejs — JavaScript runtime (complex build)
- [ ] bun — JS runtime (Zig/C++, complex build)

### Tier 6: Package Managers (need their runtime first)

- [ ] pnpm — Node.js package manager (deps: nodejs)

### Tier 7: Heavy / Complex

- [ ] neovim — text editor (cmake; deps: **cmake**,
  gettext, **tree-sitter**, luajit, libuv)
- [ ] btop — system monitor (cmake; deps: gcc)
- [ ] fastfetch — system info (cmake; many deps)
- [ ] mariadb — MySQL client (cmake; deps: openssl,
  **pkgconf**, **cmake**, pcre2, zstd, lz4)
- [ ] postgresql — PostgreSQL client (autotools; deps:
  openssl)
- [ ] awscli2 — AWS CLI (cmake; deps: openssl, python)
- [ ] google-cloud-sdk — gcloud CLI (Python bundle)

### Tier 8: Binary-Only / Unusual

- [ ] 1password-cli — binary-only (no source build)
- [ ] nixfmt — Haskell (needs GHC toolchain)
- [ ] signal-cli — Java (needs JDK)
- [ ] xclip — clipboard, Linux only (autotools)

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [ ] Source download cache in gale (`--cache-dir` flag)
  to avoid re-downloading tarballs in CI
