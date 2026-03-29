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
   Binary metadata (`.binaries.toml`) and signatures
   (`.sig`) are CI-managed. CI never modifies recipe
   files.

5. **Self-contained builds.** `gale build` auto-detects
   the sibling recipes directory and resolves build deps
   locally. No external registry needed during builds.

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
with per-platform SHA256 digests. Signs recipes.
Commits via GraphQL `createCommitOnBranch` mutation
(auto-signed "Verified").

## Non-Obvious Details

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

### Recipe signing

CI signs recipes with ed25519 when `RECIPE_SIGNING_KEY`
secret is set. Detached signatures stored as
`<recipe>.sig` alongside recipe files.
