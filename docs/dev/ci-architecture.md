# CI Architecture

## Design Goals

1. **Build only what changed.** Push events detect
   changed recipes via git diff. workflow_dispatch
   builds all or a named recipe.

2. **Fast feedback.** Gale release binary downloaded
   (not built from source). Build dep cache persists
   between runs. Source tarball cache avoids
   re-downloads.

3. **Correct binaries.** Every built archive is
   verified (binary must run with --version or similar).
   Sigstore attestation proves provenance.

4. **Clean separation.** Recipes are human-authored.
   Binary metadata and version history (`.binaries.toml`,
   head mirror plus `[[history]]` ledger) are CI-managed.
   CI never modifies recipe files.

5. **Self-contained builds.** `gale build` auto-detects
   the sibling recipes directory and resolves build deps
   locally. No external registry needed during builds.

## Merge Flow

One writer. Pre-merge, the unprivileged `verify.yml`
builds and smoke-tests a PR's changed recipes with no
write-capable token. A maintainer then applies the
`approved-for-build` label, and `promote.yml` dispatches
the privileged `build.yml` pinned to the reviewed head
SHA. That run builds every eligible platform (the
declared `[package].platforms` are authoritative — no
skipped cells), attests provenance via Sigstore, pushes
tar.zst to GHCR via ORAS, and commits `.binaries.toml`
(the v0.16.5-readable head mirror plus the append-only
`[[history]]` ledger) back onto the PR branch via
GraphQL, auto-signed "Verified" and
`expectedHeadOid`-locked to the reviewed SHA.

Recipe, binaries, and ledger therefore merge to main
atomically in the PR. CI never writes to main; the
dashboard republishes from the merge push
(`pages.yml`).

A reconcile is the same flow done by hand: branch from
main, dispatch `build.yml` at that branch, merge the PR.

## Workflow Structure

```
discover → build-gale → build (matrix) → update-recipes
```

### discover

Runs on `ubuntu-latest`. Detects which recipes changed:

- **Push**: `git diff` between before/after SHAs
- **PR**: three-dot diff against base branch
- **workflow_dispatch with recipe**: single recipe
- **workflow_dispatch without recipe**: all recipes

Outputs a JSON array of recipe names for the matrix.

### build-gale

Downloads the gale release binary (not built from
source). One job per platform. Uploads as artifact
for build jobs.

### build (matrix)

`recipes × platforms` matrix. Each job:

1. Checkout recipes repo
2. Download gale artifact
3. Restore build dep cache (`~/.gale/pkg`, `~/.gale/cache`,
   Cargo/Go registries)
4. `gale build <recipe>` (auto-resolves deps from
   sibling recipes)
5. Verify binary runs
6. Attest provenance via Sigstore
7. Push tar.zst to GHCR via ORAS
8. Upload build metadata as artifact
9. On failure: upload build log as artifact

### update-recipes

Runs after all builds. Writes `.binaries.toml` files
with per-platform SHA256 digests and the appended
`[[history]]` ledger entry. Commits via GraphQL
`createCommitOnBranch` mutation (auto-signed "Verified").

## Non-Obvious Details

### Bridge invariants (deployed v0.16.5 clients)

Two invariants protected gale v0.16.5 clients in the
field. **Step 3 of the cutover (#100 / #94) has landed:
CI no longer writes `.versions`**, so the second one is
retired and the first now only has to survive the soak.

1. **Merge-commit-only.** Still in force. Do not enable
   squash or rebase merges on this repo while `.versions`
   files exist — a squashed history breaks the commit
   pins those files already contain.
2. ~~**The two-commit append.**~~ Retired. `build.yml`
   commits `.binaries.toml` only; there is no second
   `.versions` commit to preserve. The old shape existed
   so a `.versions` entry could point at a commit whose
   tree held both the recipe and its binaries.

**The 193 `.versions` files stay on disk, deliberately.**
They are frozen — no new entries land — but a client
still on the `.versions` path can keep resolving every
version already recorded there. That is the whole point
of the soak: stopping the writes fails *silently* for a
stale client (it freezes at the last-written "latest"
and stops seeing new versions), while deleting the files
would strand it outright.

**Step 4, a separate PR after the soak, *deletes* every
`.versions` file.** Deletion is the safe end shape;
reformatting them in place would hard-fail old clients
and is forbidden. Do not touch `recipes/*/*.versions`
for any other reason — not to tidy them, not to
regenerate them. Merge-commit-only lifts with step 4.

### The ledger and the Ledger Check

Each `.binaries.toml` carries an append-only
`[[history]]` ledger below the v0.16.5-readable head
mirror. The required Ledger Check
(`.github/workflows/ledger-check.yml` →
`scripts/check_ledger.py`) makes "version changed =>
ledger entry appended" the sole merge gate, and rejects
any rewrite of prior history.

Expect this on version bumps: **verify green does not
mean mergeable.** A version-bump PR's Ledger Check stays
red until promote publishes and commits the ledger. That
is the design working, not flakiness.

The daily registry-coherence audit
(`scripts/check_registry_coherence.py`, via
`drift-check.yml`) covers the one gap in-tree checks
cannot see: external mutation of GHCR content. Its
"immutable tag conflict" failure ships its own recovery
— bump the revision to republish.

### Per-recipe runner overrides

`.github/runner-overrides.json` maps
`{recipe: {platform: runner_os}}` and redirects a single
`(recipe, platform)` cell onto a different GitHub-hosted
runner image. `load_runner_overrides` in
`scripts/chunk_recipes.py` parses it and `build_cells`
applies it, so `build.yml` and `verify.yml` — both of
which route through the chunker — agree by construction.
`reproducibility.yml` does not consult it (its matrix is
hardcoded; see the comment there).

Three properties worth remembering:

- **Values are allowlisted** (`ALLOWED_RUNNER_OVERRIDES`).
  `build.yml` picks `runs-on` from files at the reviewed
  SHA, so the allowlist keeps a merged override on a known
  hosted runner instead of an attacker-supplied label. An
  unknown image is a hard error, not a silent fallback.
- **An override never adds or removes a cell.** It only
  swaps `os`. An override naming a platform the recipe is
  not eligible for is a no-op.
- **`verify.yml` triggers on the sidecar itself** and
  re-verifies every recipe it names, so an override-only
  PR still exercises the affected builds.

Current entries — both zig 0.15.2 pins whose link step
cannot resolve libSystem against the macos-26 runner's
SDK, so their darwin cells run on `macos-15`:

| Recipe | Platform | Runner | Why |
|---|---|---|---|
| herdr | darwin-arm64 | macos-15 | vendored libghostty-vt requires zig 0.15.2 (#106) |
| zmx | darwin-arm64 | macos-15 | bundled ghostty requires zig 0.15.2 (#194) |

Drop an entry once its upstream supports a newer zig.

### sccache passthrough

If `sccache` is on the host PATH (in CI it arrives via
`mozilla-actions/sccache-action`), gale's build sandbox
auto-sets `RUSTC_WRAPPER=sccache` and forwards these
host env vars into the build:

- any `SCCACHE_*` key (`SCCACHE_GHA_ENABLED`,
  `SCCACHE_DIR`, `SCCACHE_BUCKET`, …)
- `ACTIONS_CACHE_URL`, `ACTIONS_RUNTIME_TOKEN`,
  `ACTIONS_RESULTS_URL`, `ACTIONS_CACHE_SERVICE_V2`

The trigger condition is just `sccache` being
resolvable on the host PATH. Nothing is needed in the
recipe — `cargo install` picks up `RUSTC_WRAPPER`
automatically. A recipe can set its own `RUSTC_WRAPPER`
under `[build] env` (including `""` to opt out) to
override the auto-wiring.

### Concurrency

```yaml
concurrency:
  group: build-${{ github.ref }}
  cancel-in-progress: true
```

Later pushes cancel in-progress builds. Safe because
the later push's diff range includes the earlier
push's changes.

### GITHUB_TOKEN commits don't re-trigger

CI commits use `GITHUB_TOKEN`, which GitHub does not
trigger workflows for. This prevents infinite loops.
Switching to a PAT or App token would require
commit-message filtering.

### Binary index files

`.binaries.toml` files contain version + per-platform
SHA256. The GHCR URL is derived from the recipe name
and SHA256 (deterministic, not stored). CI overwrites
the entire file on each build — no append/strip logic.

### GraphQL commit

Uses `createCommitOnBranch` mutation with
`expectedHeadOid` as an optimistic lock. If the branch
moved (concurrent push), the commit fails. The
`cancel-in-progress` concurrency group prevents this
in practice.

Base64 encoding uses `base64 -w0` (no line wrapping)
because the GitHub API rejects newlines in base64
content.

### Build dep caching

`~/.gale/pkg` (installed packages) and `~/.gale/cache`
(source tarballs) are cached between CI runs. Cache key
is based on recipe file hashes, not commit SHA, to
avoid churning the 10GB cache limit.

Each matrix job restores the same cache snapshot
independently (separate VMs). First run after a recipe
change re-downloads deps; subsequent runs skip them.

### Attestation

`actions/attest@v4` generates SLSA build provenance
for every built archive. Signed via Sigstore, uploaded
to Rekor transparency log. Verify with:

```
gh attestation verify <archive> -R kelp/gale-recipes
```

### Changed-recipe detection edge cases

- **Force push**: Falls back to building all recipes
- **Null SHA** (first push): Builds all recipes
- **Deleted recipes**: Filtered out (file must exist)
- **Binary-only changes** (`.binaries.toml`): Excluded
  from detection — won't trigger rebuilds

### Recipe trust model

Recipes are trusted via HTTPS to this repo plus the
`[source] sha256` pinned in every recipe. Prebuilt
binaries carry Sigstore attestations verified by
`gale verify`. No per-recipe signatures — the
two-commit sign-after-recipe workflow previously used
created a race window that broke `gale update` against
a just-pushed recipe, and the signing key lived in the
same CI secrets surface as repo write access, so sigs
didn't actually widen the trust perimeter.
