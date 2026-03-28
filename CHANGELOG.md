# Changelog

All notable changes to gale-recipes are documented here.

## Unreleased

### Added
- 27 new recipes: actionlint, atuin, bzip2, chezmoi,
  deadnix, difftastic, doctl, doggo, dust, gh, gnumake,
  gping, hyperfine, lsof, lua, openssl, ouch, procs,
  scc, statix, tealdeer, tree-sitter, trippy, unzip,
  uv, yq, zellij, zoxide, zstd
- docs/creating-recipes.md authoring guide
- TODO.md with prioritized recipe list from home.nix
- justfile with lint target (gale lint + actionlint)
- gale.toml project profile with actionlint
- actionlint.yaml config (suppresses SC2016 for jq/GraphQL)
- .gitignore for .direnv/ and .gale/ caches
- Version tracking files (.versions) for all recipes
- Build provenance attestation via actions/attest (SLSA,
  Sigstore-signed; verify with `gh attestation verify`)

### Changed
- CI builds only changed recipes instead of rebuilding all
  on every push (push/PR use git diff, workflow_dispatch
  retains build-all behavior)
- Gale binary built once per platform and shared via
  artifact instead of rebuilt in every matrix job
- Added build dependency caching (Cargo, Go, pip, npm,
  gale package store, gale source tarball cache)
- Added concurrency control to cancel superseded builds
- Hardened update-recipes job with nullglob and
  build-skipped guards
- Updated all GitHub Actions to latest major versions:
  checkout v6, setup-go v6, cache v5, upload-artifact v7,
  download-artifact v8
- Replaced REST API commit chain (blob/tree/commit/ref)
  with single GraphQL createCommitOnBranch mutation
- Switched dev environment from nix flake to gale
- Rust recipe: production-optimized build (thin LTO,
  codegen-units=1, jemalloc, profiler runtime), vendored
  OpenSSL via --enable-cargo-native-static
- Rust build branded as "(gale)" via --release-description
- CI uses `gale build --local` for sibling recipe
  resolution of build dependencies
- Gale recipe updated to v0.2.0
- Removed doc-only build deps (pandoc, asciidoctor,
  autoconf) from eza, ripgrep, jq
- Added missing go build dep to direnv and lazygit
- Build logs uploaded as artifacts on failure for
  easier debugging
- Binary verify step: added -v flag for lua-style
  binaries

### Fixed
- Race condition: cancel-in-progress now applies to all
  events, preventing lost binary-section updates from
  concurrent pushes
- Fragile sed-based binary section removal; replaced with
  awk that handles end-of-file and trims accumulated blank
  lines
- Rust recipe: removed broken OPENSSL_NO_VENDOR=0 (the
  variable disables vendoring when set to any value)
- Base64 line wrapping in GraphQL commit (Linux base64
  wraps at 76 chars; GitHub API rejects newlines)
- gh api graphql --input conflict with -f query flag
- Cargo workspace recipes: statix (--path bin), trippy
  (--path crates/trippy), tree-sitter (--path crates/cli)
- Unzip: restored bzip2 support with proper build dep

## 2026-03-27

### Added
- cmake, pkgconf, lazygit, rust recipes
- patchelf recipe (autotools build for Linux ELF fixup)
- Go recipe (build from source with bootstrap)
- direnv recipe

### Changed
- jq: removed static linking flags, relies on post-build
  dylib fixup for portable binaries
- pkgconf: removed static flags, builds with shared libs
- rust recipe: set sysconfdir for install step
- CLAUDE.md: added recipe format reference, verify step,
  static linking guidance
- CI: fixed verify step for Linux and macOS compatibility

### Fixed
- jq static linking caused build failures on some platforms

## 2026-03-26

### Added
- Auto-update workflow: daily check for upstream releases
  with 3-day cooldown, creates PRs for review
- Binary verification step: test that built binaries
  actually run before pushing to GHCR
- Claude Code hooks and new-recipe skill
- Claude Code Review and PR Assistant workflows
- `repo` and `released_at` fields to all recipes for
  auto-update support

### Changed
- Bot commits signed via GitHub API (shows "Verified")
- update-recipes job runs even when some builds fail
- OCI source annotation added to GHCR push

### Fixed
- Auto-update continues on per-recipe errors instead of
  aborting
- Binary verification step edge cases

### Updated
- jq 1.7.1 -> 1.8.1

## 2026-03-25

### Added
- Initial recipe set: bat, eza, fd, fzf, git-delta, just,
  jq, ripgrep, starship
- Build farm CI workflow (GitHub Actions): builds every
  recipe on macOS ARM64 and Linux AMD64, pushes tar.zst
  binaries to GHCR via ORAS, updates binary sections in
  recipe TOMLs
- README with recipe format and directory layout
- CLAUDE.md with build environment docs

### Fixed
- Cargo recipes: added `--path .` flag to prevent fetching
  from crates.io
- fzf build step: Go binary output path
- ORAS push path validation error
- Cross-repo checkout for gale in CI
- Actions updated to v5
