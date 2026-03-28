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
- [ ] pcre2 and gettext above double as runtime deps

### Tier 1: Core System Tools

No gale recipe deps beyond tier 0. High value —
many packages need these at build time.

- [ ] gnumake — build automation (autotools, no deps)
- [ ] coreutils — GNU core utilities (autotools;
  deps: gmp)
- [ ] lua — scripting language (make, no deps)
- [ ] openssl (from tier 0, listed here for ordering)

### Tier 2: Simple Rust and Go Packages

Depend only on **rust** or **go** (already have both).
Easy wins, can be batched.

#### Rust (deps: **rust**)

- [ ] difftastic — syntax-aware diffs
- [ ] dust — better du
- [ ] hyperfine — CLI benchmarking
- [ ] procs — better ps
- [ ] tealdeer — tldr man pages
- [ ] trippy — network diagnostics
- [ ] zoxide — smart cd
- [ ] zellij — terminal multiplexer (deps: **rust**,
  openssl)
- [ ] tree-sitter — parser generator (Rust CLI + C lib)
- [ ] deadnix — find dead Nix code
- [ ] statix — Nix linter

#### Go (deps: **go**)

- [ ] chezmoi — dotfile manager
- [ ] doggo — DNS lookup tool
- [ ] gh — GitHub CLI
- [ ] scc — code line counter
- [ ] yq — YAML/JSON/TOML processor
- [ ] doctl — DigitalOcean CLI

### Tier 3: Rust/Go with Extra Build Deps

Need **pkgconf**, **cmake**, or other recipes beyond
the base toolchain.

- [ ] gping — graphical ping (deps: **rust**,
  **pkgconf**)
- [ ] uv — Python package manager (deps: **rust**,
  **pkgconf**, openssl)
- [ ] atuin — shell history sync (deps: **rust**,
  protobuf)
- [ ] mise — version manager (deps: **rust**, **cmake**,
  **pkgconf**, openssl)
- [ ] rustup — Rust toolchain manager (deps: **rust**,
  **pkgconf**, openssl)
- [ ] flac — audio codec (deps: **pkgconf**, libogg)

### Tier 4: C/C++ System Packages

Autotools or cmake builds with multiple deps.

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
- [ ] lsof — list open files (autotools, minimal deps)
- [ ] unzip — archive extraction (make, no deps)
- [ ] traceroute — network diagnostics (make)

### Zig

- [ ] vibeutils — modern Unix coreutils with git-aware
  ls, colored output, Nerd Font icons (Zig; deps: zig
  toolchain; github.com/kelp/vibeutils)

### Tier 5: Languages and Runtimes

Complex builds, many deps.

- [ ] gcc — compiler (autotools; deps: gmp, isl,
  libmpc, mpfr, zstd, gnumake)
- [ ] ruby — language (autotools; deps: openssl,
  **rust**, **pkgconf**, libyaml)
- [ ] nodejs — JavaScript runtime (complex build)
- [ ] bun — JS runtime (Zig/C++, complex build)

### Tier 6: Package Managers (need their runtime first)

- [ ] pnpm — Node.js package manager (deps: nodejs)

### Tier 7: Heavy / Complex

Many deps, large builds, or unusual build systems.

- [ ] neovim — text editor (cmake; deps: **cmake**,
  gettext, tree-sitter, luajit, libuv)
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

- [ ] Source download cache in gale (`--cache-dir` flag)
  to avoid re-downloading tarballs in CI
- [ ] Recipe linter (`gale lint`) — tracked in
  ../gale/TODO.md
