# Build failure tally

Running record of build failures observed while promoting recipes,
kept so we can spot systemic causes and improve gale / the build
system instead of patching one recipe at a time. Append new
failures; don't delete resolved ones (they're the evidence).

Latest batch: 2026-07-23, mass `approved-for-build` on 29 open
auto-update PRs (#196-#224), which dispatched `build.yml` for each
against CI gale **0.21.2**.

## Systemic causes seen so far

### S1. gale farm soname bug (fixed in v0.21.3, CI still on 0.21.2)

gale's `farm.Populate` skipped symlinks, so libtool soname aliases
(`libpcre2-8.so.0` -> `libpcre2-8.so.0.x.y`,
`libz.so.1` -> `libz.so.1.3.x`, etc.) never landed in
`~/.gale/lib`. On Linux the post-build `scripts/check_install.py`
DT_NEEDED pass then fails for the alias even when the dependency is
correctly declared and built. macOS is masked because
`canonicalDepName` rewrites refs at build time.

- Fix merged as kelp/gale#181, released in gale **v0.21.3**
  (2026-07-23).
- CI's `build-gale` job builds gale from `recipes/g/gale.toml`,
  pinned to **0.21.2** on `main`.
- gale-recipes **PR #226** bumped `recipes/g/gale.toml` to 0.21.3;
  **MERGED to main 2026-07-23**. So the fix is on main, but the 29
  in-flight builds were dispatched pinned to PR head SHAs that
  branched from main BEFORE #226, so their `build-gale` job still
  compiles 0.21.2. Picking up the fix requires merging main into
  each failed PR (to update its `gale.toml`) and re-approving, or a
  re-dispatch that resolves gale from current main.
- Implication: every failure of the form "DT_NEEDED `<soname>` not
  found via RUNPATH" for an **already-declared** dynamic dep is
  this bug, not a recipe defect. Landing #226 and re-triggering
  the batch should clear the whole class. Do not "fix" these
  recipes.

### S2. Toolchain floor (MSRV) outruns the pinned toolchain

An upstream release raises its minimum rustc/edition above what
the registry ships. Bare `build = ["rust"]` resolves to the
registry's latest, so nothing in the dependent recipe can satisfy
the new floor until the toolchain recipe is bumped.

### S4. Build exceeds the 180-minute CI job timeout

`build-chunk.yml` sets `timeout-minutes: 180` per matrix job. A
recipe whose from-source build runs longer is cancelled (shows as
"cancelled", not "failure") mid-compile. Not a recipe defect and
not infra flakiness; a real CI-budget problem. Confirmed via the
job's final log line `Terminate orphan process: pid (gale)` (the
gale build was still running at the 3h mark). nodejs #210 hit this
on ALL THREE platforms: `./configure && make -j${JOBS}` builds
node plus bundled V8 cold (new version 26.5.0 -> no cached binary),
and V8 alone is a multi-hour compile. Options: raise the timeout
for heavy recipes, confirm sccache actually caches the C++ objects
(a warm re-run may finish under 3h), or give node-class recipes a
dedicated higher-timeout cell.

### S3. Newly-introduced transitive native dep, undeclared

An upstream version starts pulling a new native library (via a new
Cargo feature / -sys crate). The dependent recipe never declared
it, so gale bakes no farm RUNPATH entry and the DT_NEEDED is
unresolvable. Distinct from S1: here the dep is genuinely missing
from the recipe. (These can *also* hit S1 for the new dep's
soname alias, so they need both the declaration and gale 0.21.3.)

## Per-PR failures

| PR | Recipe | Platforms | Category | Root cause | Status |
|----|--------|-----------|----------|------------|--------|
| #225 | atuin 18.17.1 | all 3 | S2 | atuin raised MSRV to rustc 1.97.0; registry rust pinned 1.96.0. Recipe already correct. | Blocked by decision: wait for normal rust auto-update to land 1.97.0. No recipe edit. |
| #209 | eza 0.23.5 | linux only | S3 | eza 0.23.5 pulls libgit2-sys -> libz-sys, dynamically links `libz.so.1`; recipe declared no zlib. | **Fixed + verified.** Added `build=["pkgconf","rust"]`, `runtime=["zlib"]` (mirrors git-delta). Pushed to PR branch; `verify.yml` re-ran GREEN on all platforms incl. Linux. Ready to re-approve for promote. |
| #222 | fish 4.8.1 | linux only | S1 (hypothesis) | `libpcre2-8.so.0` / `libpcre2-32.so.0` DT_NEEDED not farmed. pcre2 recipe builds both widths (`--enable-pcre2-32`); fish already declares `runtime=["pcre2"]`. Dep is declared, so points at the farm soname bug. | No recipe fix yet. Expected to resolve when CI gale is 0.21.3 (#226). See open question below. |
| #223 | libpsl 0.23.0 | linux only | S3 (needs investigation) | `lib/libpsl.so.5.3.7: DT_NEEDED libicuuc.so.74` unresolved. libpsl declares NO deps (`build=[]`) and there is NO icu recipe in the registry. libpsl's autotools `--enable-runtime` autodetects the host's system libicu at configure time and links it; darwin sidesteps this with `--disable-runtime`, Linux does not. | Not fixed. Real fix is non-trivial: add an icu recipe + declare it, or pin `--enable-runtime=libidn2` for determinism, or `--disable-runtime` on Linux (feature strip, discouraged). Needs a decision. |

| #224 | ruby 4.0.6 | linux only | S1 + S3 (mixed) | Two DT_NEEDED failures: `libffi.so.8` (libffi IS declared `runtime` -> S1 farm bug) and `libgmp.so.10` (gmp NOT declared anywhere -> S3, ruby links gmp for Bignum). | Split fix: gmp needs declaring (S3); libffi should resolve under gale 0.21.3 (S1). Not fixed. Corroborates S1: another declared dep whose `.so.N` alias isn't farmed. |

## Resolved questions (answered this session)

- **verify.yml and build.yml use DIFFERENT gale versions.** CONFIRMED
  from the verify log (`GALE_VERSION: v0.21.3`): verify.yml downloads
  the gale **release binary** pinned to `recipes/g/gale.toml`'s
  version, while build.yml's `build-gale` job **compiles gale from
  the recipe tree at the PR's SHA**. On a PR branched before #226,
  verify runs gale 0.21.3 (fix present) but build compiles 0.21.2
  (fix absent). This is why eza passed verify but failed build, and
  why merging main (bumping the branch's gale.toml to 0.21.3) fixes
  build.yml. This gap is itself a finding for the reviewer: the
  pre-merge gate and the publishing build can run different gale.
- **Does #226 clear the pure-S1 failures?** CONFIRMED. fish #222,
  fixed by merging main ALONE (no recipe edit), passed verify.yml
  green on all platforms. S1 is real and #226 resolves it.

## Final dispositions (2026-07-23)

| PR | Fix | Result |
|----|-----|--------|
| #209 eza | +zlib dep | verify green, re-approved for promote |
| #222 fish | merge main only (S1) | verify green, re-approved |
| #220 nushell | +zlib dep | verify green, re-approved |
| #224 ruby | +gmp dep (+ merge main for libffi S1) | verify green, re-approved |
| #223 libpsl | +libidn2 +libunistring, `--enable-runtime=libidn2` | BLOCKED on #227 |
| #210 nodejs | none (S4 timeout) | cancelled at 180min on all platforms; needs re-run (warm cache) or a higher timeout |
| #225 atuin | none (MSRV) | blocked pending rust 1.97 auto-update |
| #227 libunistring (NEW) | new base recipe | opened; prerequisite for #223 |

libpsl uncovered a second-order dep: `--enable-runtime=libidn2`
needs a standalone `libunistring` at configure time, but gale's
libidn2 recipe bundles unistring (`--with-included-libunistring`)
so no standalone package is published. Deps resolve from the
**published registry** in verify (only `--recipe` is passed, not
`--recipes <dir>`), so a brand-new dep recipe can't be bundled into
the same PR, it must be published first. Hence #227 (libunistring)
before #223 (libpsl). Reviewer note: this "new dep must be promoted
before its consumer can verify" ordering is a sharp edge worth a
documented workflow or a `--recipes`-in-verify escape hatch.

## Observations for the build-system reviewer

Seed notes for whoever looks at preventing these. Verify before
acting; some are hypotheses.

1. **The batch was launched against a gale with a known,
   already-fixed bug.** The single highest-leverage prevention is
   gating promote on the current gale release, or auto-bumping
   `recipes/g/gale.toml` the moment a gale release ships, so CI
   never builds recipes with a stale gale. #226 should probably
   land before re-running the batch.
2. **DT_NEEDED failures are diagnosable but the signal is buried.**
   gale already prints a good hint ("undeclared-dep — add to
   runtime; unresolvable @rpath/DT_NEEDED — stop linking or
   declare the provider"). Worth surfacing the S1-vs-S3
   distinction automatically: if the missing soname's *base*
   library IS a declared dep, it's the farm bug (S1); if not, it's
   an undeclared dep (S3). CI could label the failure.
3. **verify.yml did not catch S1/S3 before promote.** Both eza and
   fish presumably passed verify.yml earlier (or verify ran on an
   older gale / older recipe). Understand why the pre-merge gate
   missed a linkage failure the privileged build hits. If verify
   and build use different gale versions, that gap is a bug.
4. **Toolchain-floor (S2) breakages have no early warning.** An
   MSRV bump only shows up as an exit-101 deep in a build log.
   Auto-update could parse upstream `rust-version` and flag when a
   PR needs a toolchain the registry can't supply, before promote.
5. **Static-vs-dynamic policy is applied per recipe, by hand.**
   Recipes pulling the same -sys crates (libgit2-sys, libz-sys)
   independently rediscover the same dep list. A shared "this
   crate needs these native deps" table, or a lint that cross-
   checks a Rust recipe's `Cargo.lock` -sys crates against its
   declared deps, would prevent S3 recurring.
