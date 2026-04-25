# TODO

## Recipes to Create

- [ ] 1password-cli (binary-only)

## Done

113 recipes:

actionlint, age, autoconf, atuin, automake, awscli,
bandwhich, bash, bat, btop, bun, bzip2, chezmoi, cmake,
coreutils, curl, deadnix, difftastic, direnv, docker,
doctl, doggo, duckdb, duf, dust, eza, fastfetch, fd,
fish, flac, fzf, gale, gettext, gh, git, git-delta,
git-lfs, glow, gmp, gnumake, go, gofumpt, golangci-lint,
google-cloud-sdk, gping, grpcurl, helix, helm, httpstat,
hyperfine, jless, jq, just, k9s, kubectl, lazygit, less,
libevent, libidn2, libogg, libtool, libyaml, lsof, lua,
mariadb, micro, mise, mongosh, mosh, mtr, neovim, nmap,
nodejs, openssl, ouch, patchelf, pcre2, pigz, pkgconf,
pnpm, podman, postgresql, procs, protobuf, pscale,
python, redis, ripgrep, rsync, ruby, rust, rustup, scc,
shfmt, socat, sqlite, starship, statix, tealdeer,
terraform, tig, tmux, tokei, traceroute, tree,
tree-sitter, trippy, unzip, uv, vibeutils, wget, xh, xz,
yq, zellij, zig, zoxide, zsh, zstd

## Reproducible Builds

Investigated 2026-03-30. Not worth pursuing. Archive
packaging is now deterministic (symlink fixup, zstd
concurrency=1, ZERO_AR_DATE) but compiled binaries
differ due to Mach-O LC_UUID, embedded paths in .la/.pc
files, and ar timestamps. Achieving full determinism
would require Nix-level isolation (fixed build paths,
sandboxed toolchain). The `gale audit` command exists
but isn't useful until this is solved.

## Auto-Update Agent

- [x] **Cron workflow** — daily workflow. For each
  recipe with `[source].repo`, query
  `gh api /repos/{owner}/{repo}/releases/latest`.
- [x] **Cooldown enforcement** — anchored to our own
  first-observation timestamp, not upstream's
  `published_at`. Resilient to retag attacks.
- [x] **Tamper detection** — sha256 mismatch on an
  already-observed version flips status to `tampered`,
  halts PR, surfaces on dashboard.
- [x] **Upstream attestation** — `gh attestation verify`
  on every downloaded tarball.
  `.github/auto-update-attest-required.txt` allowlist
  promotes specific upstreams from optional to required.
- [x] **Non-semver filter** — release-candidate and
  date-stamped tags recorded as `untracked`.
- [x] **PR per update** — branch-name dedup, Python
  helper for TOML edits, binary sections stripped.
- [ ] **AI build recovery** — when a version bump
  breaks the build, use Claude Code SDK to read the
  error and attempt a recipe fix. Falls back to
  opening a GitHub issue if the fix fails.

### Supply-Chain Hardening (next pass)

The 3-day cooldown buys time. The follow-ups below
turn that wait into active signal-gathering — querying
what the ecosystem learned about the artifact while we
sat on it.

**Tier 1 — shipped**

- [x] **GitHub Security Advisories query.** Matches
  current and bumped-to versions against published GHSAs
  via `scripts/check_ghsa.py`. PR opens as draft with
  `vulnerability` label when bumped-to matches.
  Currently-shipped matches surface on the dashboard
  even on `up_to_date` rows.
- [x] **Software Heritage cross-check.** Tag's commit
  is dereferenced (annotated tags handled) and queried
  against SH's `/api/1/revision/{sha}/`. Result lands in
  `swh_archived` + `swh_revision` and the PR body.
- [x] **Repo-identity / maintainer-change detection.**
  Stable repo_id and owner_id stored in upstream.json.
  repo_id mismatch on the same declared `[source].repo`
  → status `tampered`, no PR. owner_id mismatch with
  same repo_id → PR labeled `ownership-change` with the
  prior/current IDs in the body.

**Tier 2 — defer**

- [ ] **OSV.dev query.** Broader than GHSA but keyed by
  ecosystem (PyPI/npm/Crates), so adds little for
  GitHub-source recipes. Worth it once we ship more
  language-ecosystem packages.
- [ ] **Release-cadence anomaly.** We already store
  `latest_released_at` history; flag projects whose
  cadence breaks (quarterly project drops a midnight
  release). Cheap heuristic, high false-positive rate.
- [ ] **`git tag -v` for signed tags.** Low coverage,
  and pinning a key per upstream relocates the
  maintainer-change problem.

**Tier 3 — wait**

- [ ] **Cosign / Sigstore for non-`gh` ecosystems.**
  PyPI now signs, npm has provenance — but each
  ecosystem has its own verification path. Defer until
  a specific recipe demands it.
- [ ] **Reproducible-build verification.** High value
  where applicable; single-digit recipe coverage today.
  Revisit when rebuilderd-style projects gain reach.
- [ ] **OpenSSF Scorecard floor.** Fuzzy metric. Many
  great single-maintainer projects score poorly;
  thresholding without careful tuning is high-FP.
- [ ] **Multi-source mirror compare.** Powerful but
  rarely applicable to our catalog.

## Infrastructure

- [x] Recipe linter (`gale lint`)
- [x] `gale build --local` for CI dep resolution
- [x] `gale build` injects `${VERSION}` from recipe
- [x] Binary index separation (`.binaries.toml` files)
- [x] CI downloads gale release binary (no Go build)
- [x] Source tarball cache (`~/.gale/cache/`)
- [x] Build logs uploaded as artifacts on failure
- [x] Recipe signing in CI
- [x] Post-edit gale lint hook
- [x] Recipe-creator agent definition
- [x] Static rpath check (`check_install.py`)
- [x] Smoke test runner (`run_smoke.py`)
- [ ] Add `[smoke]` sections to more recipes
      (curl, python, fish, etc.)
- [ ] Nightly fresh-env smoke workflow (pull from GHCR
      into empty store after `update-recipes` lands)
- [ ] Audit recipes for build-vs-runtime dep
      misclassification (shared libs in `build` only)
- [ ] GNU auto-update (gitweb/FTP version detection)
