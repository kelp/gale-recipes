# Changelog

All notable changes to gale-recipes are documented here.

## Unreleased

### Added
- Darwin admit inputs for `go` 1.26.1 (official
  `go.dev/dl` GOROOT tarball, one `--file` per
  top-level name, directory dests 755). Catalog
  TOML waits on macos-26 `gale admit` after the
  directory-map gale pin.
- Darwin/arm64 catalog entry for `uv` 0.12.5
  (`uv` and `uvx`). Artifact tables are
  `gale admit` stdout from macos-26.
- Darwin/arm64 catalog entries for `gofumpt`
  0.11.0 and `golangci-lint` 2.13.1. Artifact
  tables are `gale admit` stdout from macos-26.
- Darwin/arm64 catalog entries for `gh` 2.98.0
  and `direnv` 2.37.1. Artifact tables are
  `gale admit` stdout from macos-26.
- Darwin/arm64 catalog entries for `jq` 1.8.2,
  `ripgrep` 15.2.0, `fd` 10.4.2, and `just` 1.58.0.
  Artifact tables are `gale admit` stdout from
  macos-26; `tree_digest` was not invented.
- Index lint gate for the future fetch catalog
  under `index/`. Layout is `index/<letter>/<name>.toml`.
  `scripts/lint_index.sh` no-ops when both HEAD and
  INDEX_BASE have no catalog files, refuses a wipe of
  every index file, and uses a pinned gale to run
  `gale lint` once files exist. No catalog entries yet.
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
- Zig build pattern section in `CLAUDE.md` covering
  `-Dcpu=baseline` and the `zig15` parallel-install
  fallback for recipes whose `build.zig.zon` pins a
  pre-0.16 minimum.

### Changed
- **CI no longer writes `.versions`** — step 3 of the
  bridge cutover (#100, #94). `build.yml`'s two-commit
  append is gone: `update-recipes` commits
  `.binaries.toml` and stops. The two-commit shape only
  ever existed so a `.versions` entry could point at a
  commit whose tree held both the recipe and its
  binaries; every supported client (gale >= v0.20.0)
  resolves latest *and* historical `@version` installs
  from the `[[history]]` ledger instead.
  `scripts/gen_status_page.py` now sources each recipe
  page's version history from that ledger rather than
  the `.versions` sidecar, and renders ledger entries
  written before the per-entry `commit` field (#141)
  with an unlinked commit cell.
  The files were left frozen on disk through a soak
  window; step 4 (below) deleted them.
- `verify.yml` drops the second full compile per verify
  job (#95). Verify never publishes an archive, so it no
  longer runs `gale build`; a single `gale install --recipe`
  now does the one build, populates the dependency farm, and
  lands the binary at its real store path.
  `scripts/check_install.py` scans that installed prefix
  (`~/.gale/pkg/<name>/<version>-<revision>`, resolved from
  the recipe when no `--prefix`/`--archive` is given) instead
  of an extracted archive; the installed tree carries the same
  files and baked rpaths, so the static rpath check is
  equivalent. Because the restore-only dep cache repopulates
  `~/.gale/pkg` and the installer returns MethodCached (no
  build) when the target already exists, verify now evicts
  `~/.gale/pkg/<recipe>` before the install so it always
  exercises a real build; deps stay cached, halving
  heavy-recipe verify time. `build-chunk.yml` keeps both
  steps.
- vibeutils: pinned build dep to `zig15` (revision 4).
  `build.zig.zon` declares `minimum_zig_version =
  0.15.1` and the source still uses `std.fs.cwd` etc.,
  which Zig 0.16 moved to `std.Io.Dir.cwd`. The default
  `zig` dep is now 0.16, so source builds were failing
  with "no member named 'cwd'". Revert when vibeutils
  source migrates to 0.16.
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

### Removed
- **All 193 `recipes/*/*.versions` files** — step 4, the
  final step of the bridge cutover (#100, #94). Deletion,
  never reformatting: rewriting them in place would have
  hard-failed v0.16.5 clients, which is why every prior
  step refused to touch them. Nothing read them: step 3
  moved `scripts/gen_status_page.py` onto the
  `[[history]]` ledger, and a repo-wide grep across
  workflows, `scripts/`, tests, and docs found no
  surviving reader. The dashboard still writes 193 recipe
  pages with full history tables (297 ledger entries),
  sourced entirely from `.binaries.toml`.

  The soak between steps 3 and 4 was shortened by
  maintainer decision. The adoption gate holds: every
  active machine runs gale >= v0.20.0, which resolves
  latest *and* historical `@version` installs from the
  ledger (kelp/gale#148, #141). Recovery is a revert —
  the files are in git history and clients fetch them
  from `raw.githubusercontent.com/.../main`.
- **Merge-commit-only** is lifted. It was load-bearing
  only because `.versions` lines pinned commits that had
  to stay reachable; with no such pins, squash and rebase
  merges are safe. Nothing in-repo enforced it — the
  in-repo change is documentation
  (`docs/dev/ci-architecture.md`, `CLAUDE.md`,
  `README.md`); re-enabling squash/rebase is a
  maintainer-side change in the repo's GitHub merge
  settings.

### Fixed
- ledger-check: the `workflow_dispatch` run promote fires after
  its GITHUB_TOKEN commits now posts a `ledger-check` commit
  status on the PR head SHA instead of relying on the dispatch
  check-run. GitHub does not link a dispatch-created check
  suite to the open PR, so the required-check rollup ignored
  the green check-run and the PR sat BLOCKED until a manual
  empty commit re-fired a `pull_request` run (done by hand for
  PR #136 and PR #145). A commit status carries no check-suite
  linkage and is read straight off the head SHA, so it credits
  ruleset 17473700's required `ledger-check` context whatever
  event ran the check. Posted only on workflow_dispatch
  (pull_request runs already produce a linked, credited
  check-run, and a fork PR's read-only GITHUB_TOKEN cannot
  POST a status), with the same 3-attempt retry as build.yml's
  dispatch step (#146).
- `build-chunk.yml`: retry the two `actions/attest`
  provenance steps (file subject and manifest OCI
  referrer) up to three times with backoff before
  failing. Transient `Failed to persist attestation:
  Requires authentication` 401s from the GitHub API had
  been failing otherwise-green build legs and gating the
  `update-recipes` publish, forcing manual reruns.
  `actions/attest` is a `uses:` step and can't ride the
  shell `for attempt` retry loop the build/oras-push
  steps use, so the attempts chain via
  `continue-on-error` + step-outcome guards; the final
  attempt keeps no `continue-on-error`, so a persistent
  failure still hard-fails the job (this absorbs
  transient 401s, it does not make attestation
  optional) (#78).
- vibeutils, zls, zmx: added `-Dcpu=baseline` to the
  `zig build` steps so binaries don't bake in the CI
  runner's CPU-specific instructions. Without it,
  `vibeutils 0.9.3-2` and `zmx 0.6.0-1` SIGILLed at
  startup on AMD EPYC Milan (no AVX-512) — the runner
  had AVX-512 and Zig emitted `vptestnmb` etc. that the
  Milan host then refused to execute. Baseline = SSE2 on
  x86_64, armv8.0-a on aarch64; perf cost is negligible
  for these CLI tools. Symptom of a missed flag is
  `Illegal instruction at address …`, which masquerades
  as a system fault — especially when the broken tool
  is a coreutils replacement on PATH ahead of GNU
  (vibeutils' broken `timeout` silently broke the SSH
  commit-signing wrapper). Bumps revisions on vibeutils,
  zls, and zmx.

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
