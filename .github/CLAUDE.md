# CLAUDE.md — .github

Guidance for the workflows in this directory.
`../docs/dev/ci-architecture.md` holds the merge flow,
the bridge invariants, and the ledger rules; the root
`CLAUDE.md` holds the auto-merge prohibition; this file
holds the auto-update mechanics.

## Auto-update workflow

`.github/workflows/auto-update.yml` runs daily and, for
each recipe with a `[source].repo`, queries the upstream's
latest GitHub release. All status (up_to_date / outdated /
tampered / untracked) is written to `_data/upstream.json`
for the dashboard; version-bump PRs are opened under the
`auto-update/<name>-<version>` branch name, authored by
the `gale-recipes-automation` GitHub App (installation
token minted in auto-update.yml) so their `pull_request`
CI runs start without manual workflow approval.

The 7-day cooldown is a supply-chain gate, not a
scheduling delay. Its timestamp comes from our own
*first-observation* clock (recorded in `upstream.json`
alongside the tarball's sha256 and the tag's commit
SHA), not upstream's tag publish date — a maintainer
re-tagging to reset `published_at` does not move our
clock. Either signal flipping flags `tampered`, halts
the PR, and surfaces on the dashboard: sha256 change
on an already-observed version (tarball substitution),
or commit-SHA change on the same tag (force-pushed
tag whose tarball happens to hash the same — covers
synthesized release tarballs and mirror snapshot
lag). The workflow also runs `gh attestation verify`
against each downloaded tarball; repos listed in
`.github/auto-update-attest-required.txt` require a
valid attestation.

### Where the clock lives, and why it fails closed

The `dashboard-data` branch is **the** operational store
for `_data/upstream.json` — not a workaround for main's
required `ledger-check`, which is merely what forced the
move (#99). main tracks **no** copy: a fossil reachable
only on a failure path is worse than none, so
`auto-update.yml` seeds the working tree from
`dashboard-data` and nothing else, and `pages.yml` renders
without upstream columns when it can't read it.

Git is the right home for this file for the same reason it
is the right home for the ledger: the clock is a security
input, and a branch gives `git log` over every mutation —
who wrote it, when, and what changed. Object storage would
buy an unsigned mutable blob whose last writer cannot be
reconstructed. That is the argument #102 itself makes
against R2-for-the-integrity-index, and it applies here
too; #102 is closed on that basis.

**The seed step fails closed** (`exit 1`). Prior state that
reads empty resets `first_observed_at` to *now* for every
recipe, so the 7-day cooldown passes immediately across the
whole corpus and `first_observed_sha256` /
`first_observed_commit_sha` lose their baseline — a silent
downgrade of a supply-chain gate. Two shapes previously
caused exactly that and are now gone: `git show >
_data/upstream.json` truncates the destination *before* git
runs, so a failed read left a zero-byte clock (the step now
redirects into a temp file and `mv`s on success), and a
transient `git fetch` failure fell back to main's tracked
copy, whose months-old `generated_at` made every cooldown
pass. The fetch retries 3 times, then the run stops.
Bootstrapping a fresh clock is a deliberate manual commit
to `dashboard-data`, never an automatic fallback.

For upstreams that publish tags without GitHub
Releases (git/git, golang/go, python/cpython,
postgres/postgres, sqlite/sqlite, etc.), the workflow
falls back to `/repos/{owner}/{repo}/tags`, picks the
highest semver tag, and feeds it through the same
gates. `upstream.json` records `source_type` as
`"release"` or `"tag"` per entry.

Non-semver tags (release candidates, dated builds with
dashes, etc.) are recorded as `untracked` and skipped.

See also `docs/dev/upstream-tracking.md` for the
`upstream.json` data shape and how to add a non-GitHub
livecheck rule.
