# Changelog

All notable changes to gale-recipes are documented here.

## Unreleased

### Added
- dtc recipe (v1.7.2) — Device Tree Compiler and
  libfdt, builds via plain `make` with the
  Python/YAML/Valgrind hooks disabled.
- glib recipe (v2.88.1) — GNOME core library, meson
  build with relocatable pkgconfig disabled so consumers
  link against absolute store paths.
- tio recipe (v3.9) — serial-device I/O tool. Depends
  on the new glib recipe plus lua.
- `.github/workflows/reproducibility.yml` — manual
  `workflow_dispatch` job that builds a recipe twice on
  each of the three CI platforms (`darwin-arm64`,
  `linux-amd64`, `linux-arm64`) and diffs the resulting
  tar.zst archives. Closes the loop on gale's
  determinism work (SOURCE_DATE_EPOCH from
  `[source].released_at`, scoped HOME/TMPDIR,
  deterministic touchAll, validate-before-swap on the
  generation). Honors `[package].platforms` — recipes
  that don't support the matrix leg skip with a notice.
  On mismatch, uploads both archives + build logs as a
  forensics artifact. Manual-only (running on every
  push would double CI minutes).
- `update-recipes` now bakes the resolved dep closure
  into `.binaries.toml` as a per-platform
  `deps = [...]` array of tables, extracted from each
  archive's `.gale-deps.toml`. Empty closures are
  omitted. The archive's own `.gale-deps.toml` remains
  authoritative for staleness; the `.binaries.toml`
  copy is informational. Old gale clients tolerate the
  new field (sub-table parser ignores `deps`).
- `[[repos]]` (tap) usage section in `gale-recipes/CLAUDE.md`
  covering the binary-trust policy and inline
  `[binary.<platform>]` requirement for tap recipes.

### Changed
- `build.yml` now embeds the recipe revision in each
  `.binaries.toml` `version` field as `X.Y.Z-N` whenever
  `[package].revision > 1`. Recipes at revision 1 keep
  the bare version. Brings the index format in line with
  how the resolver already keys archives in the registry,
  and lets `gale update` distinguish a pure
  revision-bump rebuild from a no-op. All existing
  `.binaries.toml` files were regenerated under the new
  rule (one-line `version` change per recipe; sha256
  blocks untouched).
- `gale.lock`: re-pinned `httpie` to match the resolver
  output against the updated registry index.
- `update-recipes` is now serialized via a job-level
  `concurrency: { group: update-recipes-main,
  cancel-in-progress: false }`. Prevents races between
  push-to-main and `workflow_dispatch` runs (the
  GraphQL commit's `expectedHeadOid` already gives an
  optimistic lock, but a loser's `.versions` append +
  `.binaries.toml` writes would have been discarded
  silently).
- `update-recipes` iterates recipes in sorted order
  (was unspecified-order map iteration). Output diffs
  between runs no longer reorder the same writes.
- `update-recipes` now writes a recipe's
  `.binaries.toml` only when metadata from every
  expected platform is present, computed per-recipe as
  the intersection of the CI matrix and the recipe's
  declared `[package].platforms`. Falls back to the
  full matrix when the field is absent. A 2/3 failed
  matrix no longer publishes a partial
  `.binaries.toml` to main; for platform-filtered
  recipes (e.g. `traceroute` on linux only) the
  expected count matches the declared platforms, not
  the full matrix.
- jq: drops `libonig.*` and `oniguruma.pc` after
  `make install`. The recipe builds with
  `--with-oniguruma=builtin` (static link), but autotools
  still installed the shared library and pkg-config file,
  causing a recurring `farm conflict: libonig.5.dylib
  claimed by both "jq" and "oniguruma"` warning on every
  sync. Required before gale propagates farm conflicts as
  install errors.
- git: statically links curl, expat, pcre2, zstd, and
  libidn2 so git-remote-http no longer depends on those
  dylibs at runtime. Fixes a dyld failure class where a
  curl (or other dep) upgrade broke `git pull` until git
  was rebuilt. openssl stays dynamic for security update
  flexibility.
- expat: switched from cmake to autotools so the build
  produces `libexpat.a` alongside the shared library.
  cmake for this version ignores `EXPAT_BUILD_STATIC` and
  ships shared-only; dependents (e.g. git) need the static
  archive to link statically.
- gale: bumped recipe to v0.14.0 for the architectural
  review hardening — tap resolver chain, binary trust
  policy, dep version constraints, ETag registry cache,
  build-env scrubbing, deterministic source builds,
  generation validate-before-swap, and store-gen lock.
  See gale's CHANGELOG.md for the full v0.14.0 entry.
- gale: bumped recipe to v0.12.1 for the gc regression
  fix (v0.12.0 reaped canonical revision dirs actively
  referenced by the generation)
- gale: bumped recipe to v0.12.0 for recipe revisions,
  shared dylib farm, soft-migration, `gale inspect`,
  install-time Mach-O signing, and `gale doctor --repair`
  codesign walk
- gale: bumped recipe to v0.11.3 for the no-op update
  generation rebuild fix
- CI now pins the Gale build bootstrap version to v0.11.3
  instead of resolving the latest release dynamically
- CI rebuilds transitive dependents when a recipe changes.
  `scripts/expand_changed.py` reads changed recipe names,
  walks every recipe's `[dependencies]` (build/runtime/
  platform, bare-string and table-form alike), inverts the
  graph, and expands the build matrix to the full dependent
  closure. A revision bump on openssl now pre-builds every
  dependent in one CI run instead of cascading into local
  source rebuilds for each user. `check_install.py` also
  learned to accept table-form dep declarations.

### Added
- linux-arm64 build support for 15 recipes:
  1password-cli, bun, coreutils, gmp, go,
  google-cloud-sdk, libtool, lsof, lua, openssl,
  pnpm, rust, shellcheck, traceroute, zig
- docs/linux-recipe-fixes.md documenting pre-existing
  Linux build failures and fix plan

### Previously added
- 27 new recipes: actionlint, atuin, bzip2, chezmoi,
  deadnix, difftastic, doctl, doggo, dust, gh, gnumake,
  gping, hyperfine, lsof, lua, openssl, ouch, procs,
  scc, statix, tealdeer, tree-sitter, trippy, unzip,
  uv, yq, zellij, zoxide, zstd
- zmx recipe (v0.4.2, Zig terminal session persistence)
- mandoc recipe (v1.14.6, UNIX manpage compiler toolset)
- vibeutils: added mandoc runtime dependency for man
  page support
- bison, expat, oniguruma recipes
- Build All Recipes workflow (build-all.yml) that
  dispatches build.yml in batches of 32

### Changed
- CI fetches latest gale release dynamically instead
  of hardcoded version
- CI caches gale binary, only downloads on new release
- build.yml accepts comma-separated recipe names
- Verify step handles script binaries (Perl, Python)
  that can't run outside their install prefix
- CI now treats Gale's `unsupported platform` build
  result as a skip instead of failing the whole matrix
- build.yml now uses `actions/cache@v5`

### Fixed
- gale: bumped recipe to v0.11.2 for generation
  reliability fixes and `doctor --repair`
- zig: fixed lib path for 0.15.2 prebuilt tarball
  (layout changed from lib/zig/ to lib/)
- autoconf: added m4 build and runtime dependency
- automake: added autoconf build dependency
- sqlite: added readline/ncurses dep flags and ncurses
  link flags for linux
- google-cloud-sdk: fixed symlinks to use relative paths
- libgit2: changed to shared libs (BUILD_SHARED_LIBS=ON)
- python: removed --enable-shared flag
- git-delta, starship: renamed zlib-ng-compat dep to zlib
- justfile: updated --source flag to --path for gale 0.8.0
- llvm: restricted prebuilt bootstrap recipe to Linux
  platforms where it is currently supported in CI
- gale: corrected v0.11.1 source tarball sha256
- btop: disabled upstream CMake tests during package
  builds so Linux LLVM builds do not fail in GoogleTest
  discovery before install

## 2026-04-01

### Fixed
- statix: added --locked to cargo install (dependency
  resolution broke clap derive macro without lockfile)
- mise: added --locked to cargo install and cmake/pkgconf
  build deps (lzma-rust2 crate failed without lockfile)
- sqlite: fixed description, enabled FTS3/FTS5/RTREE/
  JSON1/COLUMN_METADATA features, added readline support
- libyaml: fixed description, corrected released_at date,
  fixed homepage to HTTPS
- postgresql: added pkgconf build dep for meson to find
  openssl/zlib/readline
- mariadb: added bison build dep
- libgit2: enabled SSH support (USE_SSH=ON), added
  libssh2 and pkgconf deps
- dbus: added expat build and runtime dep
- gopls: combined build steps, added version ldflags
  for smaller binary with embedded version
- statix: updated repo/homepage/url from nerdypepper to
  oppiliappan (author renamed)

### Changed
- Prebuilt binary recipes (1password-cli, pnpm,
  google-cloud-sdk) use ${VERSION} in build step URLs
  for easier version bumps
- git recipe: added RUNTIME_PREFIX, explicit LIBPCREDIR,
  CC, CFLAGS, and LDFLAGS passthrough
- Added gale as dev dependency with lockfile
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
