# TODO

Active work first, in priority order within each section.
Sections themselves ordered by priority.

## Active

### Auto-update coverage (largest concrete gap)

63 of 191 recipes (33%) have status `untracked` in
`_data/upstream.json`. None of the supply-chain hardening
runs for them: no first-observation cooldown, no tamper
detection, no GHSA cross-check, no SWH cross-check. The
bucket includes openssl, curl, git, go, python, postgres,
sqlite, llvm, bash, gettext, gnumake, libtool — the
foundation packages where a substituted tarball has the
largest blast radius.

- [ ] **Loosen non-semver filter.** Accept prefixed semver:
  `openssl-X.Y.Z`, `llvmorg-X.Y.Z`,
  `<subcomponent>/vX.Y.Z`. Currently rejected as
  `untracked`; ~9 recipes.
- [ ] **Generic-mirror / GNU FTP fetcher.** Directory-
  listing parser → newest semver. Covers the ~32 recipes
  with no `[source].repo` field (autoconf, automake, bash,
  bison, coreutils, gettext, gmp, gnumake, libtool, ...).
- [ ] **Multi-source mirror cross-check** (fold into the
  FTP fetcher). Compare `ftp.gnu.org` against regional
  `ftpmirror` hosts; sha mismatch flips status to
  `tampered`. Closest analog to the SWH cross-check for
  non-GitHub sources.

### Risk tiers for recipes

Every recipe gets the same 7-day baseline cooldown and
the same review treatment regardless of blast radius.
openssl, curl, git, and the compilers warrant stricter
policy: longer cooldown than baseline (e.g. 14d),
mandatory attestation (promote into
`.github/auto-update-attest-required.txt`), two-reviewer
requirement via CODEOWNERS. Same machinery, calibrated
by impact.

- [ ] Define a `[package].tier` field (default `standard`;
  values `standard` | `trust-anchor`) with lint
  enforcement.
- [ ] Auto-update workflow honors tier: longer cooldown,
  attestation required when available.
- [ ] CODEOWNERS entry for trust-anchor recipes.

### Vulnerability scanning on built binaries

Static linking hides upstream CVEs from source-level
scanners. A CVE in libcurl shipped inside a static `git`
binary is invisible to a GHSA query on `git/git`. Scan the
published `tar.zst` and surface matches.

- [ ] Trivy/Grype against `tar.zst` in `build.yml`.
- [ ] Aggregate results into `_data/upstream.json` for the
  dashboard.

### Smoke coverage

7 of 192 recipes have a `[smoke]` section. Catches runtime
regressions the static rpath check can't see. Most
valuable where the binary handles untrusted bytes or
provides crypto primitives.

- [ ] Add `[smoke]` to trust-anchor recipes first: curl,
  wget, git, gh, openssl, python, ruby, nodejs.
- [ ] Then build deps: cmake, gnumake, autoconf, automake,
  bison.
- [ ] Then broader catalog over time.

### Nightly fresh-env smoke workflow

What this catches (GHCR is content-addressed, so blob
substitution would already fail the pull):

- Install logic that worked in CI's environment breaks on
  an empty store (missing rpath, hardcoded build paths).
- Archive completeness regressions (file dropped from the
  archive, still present in build tree, smoke passed on
  the build machine).
- Smoke-command regressions across runtime layers.

- [ ] Workflow pulls each recipe's published archive from
  GHCR into a clean temp store and runs `[smoke]`.
- [ ] Triggers on schedule; failures open an issue.

### Build-vs-runtime dep audit

Correctness bug with security consequence: misclassified
shared libs break `.gale-deps.toml` staleness detection,
so CVE-patch rebuilds may not cascade to dependents.

- [ ] One-pass audit script: for each recipe, walk the
  installed binaries' dynamic deps and flag shared libs
  that appear only in `[dependencies].build`.

## Deferred

Reasons may change; revisit if a specific failure mode
demands it.

- **OSV.dev query.** Ecosystem-keyed; little signal for
  GitHub-source recipes. Revisit when we ship more
  language-ecosystem packages.
- **Release-cadence anomaly detection.** High false-
  positive rate.
- **`git tag -v` for signed tags.** Low upstream coverage;
  key-pinning relocates the maintainer-change problem.
- **Cosign / Sigstore for non-`gh` ecosystems.** Defer
  until a recipe specifically needs it.
- **OpenSSF Scorecard floor.** Fuzzy metric; high FP
  without careful tuning.
- **SBOM publication (CycloneDX/SPDX).** Busywork without
  an internal consumer; revisit if the vuln scanner
  pipeline needs it.

## Speculative

Ideas worth keeping a note on. No commitment to ever
ship.

- **AI build-failure diagnosis comment.** When a version-
  bump PR's CI fails, a Claude-generated comment could
  summarize the likely cause (MSRV bump, configure flag
  rename, dep soname change) to cut human triage time.
  Strict constraint: diagnose only, never edit recipe
  files — AI-authored edits to build steps expand attack
  surface (e.g., upstream INSTALL docs that include
  `curl … | sh` bootstrap steps leaking into a recipe).
  Reframed from the earlier "AI build recovery" idea,
  which proposed auto-applied fixes.

## Reproducible Builds

Investigated 2026-03-30. Full bit-for-bit determinism not
worth pursuing — would require Nix-level isolation (fixed
build paths, sandboxed toolchain). Archive packaging is
already deterministic (symlink fixup, zstd concurrency=1,
ZERO_AR_DATE) but compiled binaries differ due to Mach-O
LC_UUID, embedded paths in `.la`/`.pc` files, and ar
timestamps. Partial wins (strip LC_UUID, strip embedded
build paths, strip ar timestamps) remain available
incrementally if a specific need surfaces. `gale audit`
exists but isn't useful until this is solved.

## Done

### Auto-update agent

- Daily cron workflow against GitHub releases, with
  fallback to `/repos/{repo}/tags` for projects that
  don't publish releases (git/git, golang/go,
  python/cpython, postgres/postgres, etc.). `source_type`
  recorded per entry.
- 7-day first-observation cooldown. Anchored to our own
  download timestamp, not upstream `published_at`.
  Resilient to retag.
- Tarball tamper detection: sha256 mismatch on
  already-observed version flips status to `tampered`,
  halts PR.
- Tag tamper detection: commit-SHA mismatch on the same
  tag flips status to `tampered`. Catches force-pushed
  tags whose tarball happens to hash the same
  (synthesized release tarballs, mirror snapshot lag).
- Upstream attestation via `gh attestation verify`;
  `.github/auto-update-attest-required.txt` allowlist
  promotes specific upstreams from optional to required.
- Non-semver filter for release candidates and dated tags
  (now scheduled for loosening — see Active).
- URL rewriter handles version-in-path mirror URLs
  (kernel.org, go.dev, python.org) in addition to GitHub
  release-asset and tag-archive shapes.
- PR per update with branch-name dedup.
- GitHub Security Advisories cross-check via
  `scripts/check_ghsa.py`.
- Software Heritage cross-check (annotated tags handled).
- Repo-identity / maintainer-change detection (`repo_id`,
  `owner_id` stored in `upstream.json`).

### Infrastructure

- Recipe linter (`gale lint`).
- `gale build --local` for CI dep resolution.
- `gale build` injects `${VERSION}` from recipe.
- Binary index separation (`.binaries.toml` files).
- CI downloads gale release binary (no Go build).
- Source tarball cache (`~/.gale/cache/`).
- Build logs uploaded as artifacts on failure.
- Recipe signing in CI.
- Post-edit gale lint hook.
- Recipe-creator agent definition.
- Static rpath check (`check_install.py`).
- Smoke test runner (`run_smoke.py`).

### Recipes

192 recipes shipped. Authoritative count:

```
ls recipes/*/*.toml | grep -v binaries | wc -l
```
