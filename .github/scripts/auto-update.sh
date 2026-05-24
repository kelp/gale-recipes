#!/bin/bash
# Auto-update agent: checks upstream GitHub releases for
# every recipe, writes a status entry to _data/upstream.json,
# and (for recipes past the cooldown) opens a PR with the
# version bump.
#
# The 7-day cooldown is *first-observation based*: the clock
# starts the first time we download the new version's tarball
# and record its sha256. An upstream re-tag that swaps
# contents without changing the version string resets the
# clock AND raises a `tampered` status — either via a sha256
# mismatch on the same version, or via a commit-SHA mismatch
# on the same tag (covers tag mutations that don't change
# the tarball bytes).
#
# Optional upstream attestation verification runs via
# `gh attestation verify`. Outcomes:
#   - verified    → proceed with PR
#   - unattested  → proceed (most upstreams don't attest yet)
#   - invalid     → status=tampered, skip PR
# Repos listed in `.github/auto-update-attest-required.txt`
# promote `unattested` to `invalid`.
#
# Non-semver tags (`1.0-rc1`, date stamps with dashes, etc.)
# are recorded as `untracked` with a reason; no PR is opened.
# PR de-dup is a remote branch-existence check, not a title
# search.
#
# The dashboard generator reads _data/upstream.json to render
# "upstream X.Y.Z · Nd ago" pills. A recipe without a
# `source.repo` field is recorded as status="untracked".
set -uo pipefail

COOLDOWN_DAYS="${COOLDOWN_DAYS:-7}"
FILTER="${1:-}"

PRIOR_JSON="_data/upstream.json"
ATTEST_REQUIRED_FILE=".github/auto-update-attest-required.txt"

# Output accumulator for _data/upstream.json. One JSON
# object per line, keyed by recipe name; collated after the
# main loop runs.
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT
NDJSON="$TMP_DIR/entries.ndjson"
: > "$NDJSON"

NOW_ISO=$(date -u '+%Y-%m-%dT%H:%M:%SZ')

# Space GitHub API calls out across the run (300–900 ms
# between recipes) so ~150 tracked recipes land over
# minutes rather than seconds.
jitter_sleep() {
  local n=$(( (RANDOM % 7) + 3 ))
  sleep "0.${n}"
}

# Read a field from the prior run's upstream.json entry for
# a given recipe. Returns empty string if the file, entry,
# or field is missing.
prior_field() {
  local name="$1" field="$2"
  if [ -f "$PRIOR_JSON" ]; then
    jq -r --arg n "$name" --arg f "$field" \
       '.recipes[$n][$f] // ""' "$PRIOR_JSON" 2>/dev/null
  fi
}

# True iff this repo is on the attestation-required list.
# Repos on the list promote "unattested" to "invalid".
attest_required() {
  local repo="$1"
  [ -f "$ATTEST_REQUIRED_FILE" ] && \
    grep -qFx "$repo" "$ATTEST_REQUIRED_FILE"
}

# Verify upstream GitHub attestation for a downloaded
# tarball. Echoes one of: verified | unattested | invalid.
# Exit status mirrors: 0 for verified/unattested, 1 for
# invalid.
#
# `gh attestation verify` doesn't have a clean exit code
# split between "no attestations" and "real failure", so
# we parse stderr. Three flavors of "no attestations":
#   - "no attestations found" / "no matching attestations"
#     (older gh, sometimes seen on bundle-mode calls)
#   - HTTP 404 against /attestations/sha256:... (current
#     real-world wording: the attestations API returns 404
#     when nothing is attested for that artifact's digest).
# Anything else — signature mismatch, transparency-log
# failure, network error against a different endpoint —
# stays "invalid" so we don't mask real problems.
verify_upstream_attestation() {
  local tarball="$1" repo="$2"
  local owner="${repo%/*}"
  local err="$TMP_DIR/att.err"
  if gh attestation verify "$tarball" --owner "$owner" \
       --format json >/dev/null 2>"$err"; then
    echo "verified"
    return 0
  fi
  if grep -qi "no attestations" "$err" \
     || grep -qi "no matching attestations" "$err" \
     || grep -qE 'HTTP 404.*/attestations/sha256:' "$err"; then
    echo "unattested"
    return 0
  fi
  echo "invalid"
  return 1
}

# Resolve a tag's commit sha, dereferencing annotated tags.
# Annotated tags (most large projects use them) point to a
# tag object that points to the commit; lightweight tags
# point straight to the commit. Empty string on failure.
swh_resolve_commit() {
  local repo="$1" tag="$2"
  local ref obj_type obj_sha
  ref=$(gh api "/repos/${repo}/git/refs/tags/${tag}" 2>/dev/null) \
    || { echo ""; return; }
  obj_type=$(echo "$ref" | jq -r '.object.type // empty')
  obj_sha=$(echo "$ref" | jq -r '.object.sha // empty')
  if [ "$obj_type" = "tag" ] && [ -n "$obj_sha" ]; then
    obj_sha=$(gh api "/repos/${repo}/git/tags/${obj_sha}" \
                --jq '.object.sha // empty' 2>/dev/null)
  fi
  echo "$obj_sha"
}

# Ask Software Heritage whether a commit has been archived.
# Echoes one of: archived | not-archived | error.
# SH is the only third-party signal we have that doesn't
# flow through GitHub. "not-archived" is common for very
# fresh tags; the cooldown gives SH time to crawl.
swh_check() {
  local sha="$1"
  if [ -z "$sha" ]; then
    echo "error"
    return
  fi
  local code
  code=$(curl -sS -o /dev/null -m 15 -w '%{http_code}' \
    "https://archive.softwareheritage.org/api/1/revision/${sha}/" \
    2>/dev/null) || { echo "error"; return; }
  case "$code" in
    200) echo "archived" ;;
    404) echo "not-archived" ;;
    *)   echo "error" ;;
  esac
}

# Append one recipe's upstream status to NDJSON. Trailing
# `extra` is a JSON object merged into the entry; use it
# for first_observed_* and attestation fields.
emit_upstream() {
  local name="$1" status="$2"
  local current="${3:-}" latest="${4:-}"
  local released="${5:-}" url="${6:-}" reason="${7:-}"
  local extra="${8:-"{}"}"
  jq -cn \
    --arg name "$name" \
    --arg status "$status" \
    --arg current "$current" \
    --arg latest "$latest" \
    --arg released "$released" \
    --arg url "$url" \
    --arg reason "$reason" \
    --arg checked "$NOW_ISO" \
    --argjson extra "$extra" \
    '{($name): (
       {status: $status, current_version: $current, checked_at: $checked}
       + (if $latest   != "" then {latest_version: $latest}         else {} end)
       + (if $released != "" then {latest_released_at: $released}   else {} end)
       + (if $url      != "" then {latest_release_url: $url}        else {} end)
       + (if $reason   != "" then {reason: $reason}                 else {} end)
       + $extra
     )}' >> "$NDJSON"
}

# Extract a top-level TOML string field's value. First match
# at column 0 wins, same heuristic the original script used.
get_field() {
  local file="$1" field="$2"
  grep "^${field}" "$file" | head -1 | sed 's/.*= *"//' | sed 's/".*//'
}

check_recipe() {
  local file="$1"
  local name version repo url source_sha256 old_released_at
  name=$(get_field "$file" name)
  version=$(get_field "$file" version)
  repo=$(get_field "$file" repo)
  url=$(get_field "$file" url)
  source_sha256=$(get_field "$file" sha256)
  old_released_at=$(get_field "$file" released_at)

  if [ -z "$repo" ]; then
    echo "SKIP $name: no repo field"
    emit_upstream "$name" "untracked" "$version" "" "" "" \
      "no source.repo field"
    return
  fi

  jitter_sleep

  # Repo-identity: stable IDs that survive renames but
  # change on delete-and-recreate (repo_id) or transfer
  # (owner_id). Repo-id mismatch is a hard tamper signal —
  # the URL we trusted now points to a different
  # repository.
  local repo_meta="" repo_id="" owner_id=""
  repo_meta=$(gh api "/repos/${repo}" 2>/dev/null) || repo_meta=""
  if [ -n "$repo_meta" ]; then
    repo_id=$(echo "$repo_meta" | jq -r '.id // empty')
    owner_id=$(echo "$repo_meta" | jq -r '.owner.id // empty')
  fi

  local prior_repo prior_repo_id prior_owner_id
  prior_repo=$(prior_field "$name" repo)
  prior_repo_id=$(prior_field "$name" repo_id)
  prior_owner_id=$(prior_field "$name" owner_id)

  # Comparison is meaningful only when the recipe still
  # declares the same upstream repo. A human-edited
  # `[source].repo` legitimately replaces history.
  local repo_replaced=0 owner_changed=0
  if [ -n "$prior_repo_id" ] && [ "$prior_repo" = "$repo" ] \
       && [ -n "$repo_id" ] && [ "$prior_repo_id" != "$repo_id" ]; then
    repo_replaced=1
  fi
  if [ -n "$prior_owner_id" ] && [ "$prior_repo" = "$repo" ] \
       && [ -n "$owner_id" ] && [ "$prior_owner_id" != "$owner_id" ] \
       && [ "$repo_replaced" -eq 0 ]; then
    owner_changed=1
  fi

  if [ "$repo_replaced" -eq 1 ]; then
    echo "TAMPERED $name: repo_id changed (${prior_repo_id} -> ${repo_id})"
    local rr_extra
    rr_extra=$(jq -cn \
      --arg repo "$repo" --arg rid "$repo_id" --arg oid "$owner_id" \
      --arg prid "$prior_repo_id" \
      '{repo: $repo, repo_id: $rid, owner_id: $oid,
        prior_repo_id: $prid}')
    emit_upstream "$name" "tampered" "$version" "" "" "" \
      "repo_id changed: was ${prior_repo_id}, now ${repo_id}" \
      "$rr_extra"
    return
  fi

  # Resolve the latest upstream version. Prefer
  # /releases/latest (excludes drafts and pre-releases by
  # default); fall back to /tags for projects that publish
  # tags without releases (git/git, golang/go, python/cpython,
  # postgres/postgres, sqlite/sqlite, qemu/qemu, ...).
  local source_type="release"
  local release_json="" tags_json=""
  local new_tag="" published_at=""
  local swh_revision=""
  if release_json=$(gh api "/repos/${repo}/releases/latest" 2>/dev/null); then
    new_tag=$(echo "$release_json" | jq -r '.tag_name')
    published_at=$(echo "$release_json" | jq -r '.published_at[:10]')
  else
    source_type="tag"
    if ! tags_json=$(gh api "/repos/${repo}/tags?per_page=100" 2>/dev/null); then
      echo "SKIP $name: no releases or tags accessible for $repo"
      emit_upstream "$name" "untracked" "$version" "" "" "" \
        "no releases or tags accessible on ${repo}"
      return
    fi
    # Pick the highest semver-shaped tag. Reuses the same
    # shape rule the post-fetch non-semver filter applies to
    # release tags, so behaviour is symmetric across sources.
    new_tag=$(echo "$tags_json" \
                | jq -r '.[].name' \
                | grep -E '^v?[0-9]+(\.[0-9]+)*$' \
                | sort -V \
                | tail -1)
    if [ -z "$new_tag" ]; then
      echo "SKIP $name: no semver tags on $repo"
      emit_upstream "$name" "untracked" "$version" "" "" "" \
        "no releases and no semver tags on ${repo}"
      return
    fi
    # Tag-source recipes have no release-publication date.
    # Use the tag commit's committer date. Resolve via the
    # existing helper so annotated tags are dereferenced
    # the same way SWH lookup does it.
    swh_revision=$(swh_resolve_commit "$repo" "$new_tag")
    if [ -n "$swh_revision" ]; then
      published_at=$(gh api "/repos/${repo}/commits/${swh_revision}" \
                       --jq '.commit.committer.date[:10]' 2>/dev/null \
                       || echo "")
    fi
  fi
  local release_url="https://github.com/${repo}/releases/tag/${new_tag}"

  # Strip common prefixes: v, name-.
  local new_version="$new_tag"
  new_version="${new_version#v}"
  new_version="${new_version#"${name}-"}"

  # GHSA query: published advisories on the upstream repo,
  # matched against current and new versions. Runs once per
  # recipe per day even when up_to_date so the dashboard
  # surfaces CVEs against currently-shipped versions too.
  local ghsa_json="[]"
  local advisories
  if advisories=$(gh api \
        "/repos/${repo}/security-advisories?state=published&per_page=100" \
        2>/dev/null); then
    ghsa_json=$(printf '%s' "$advisories" | python3 scripts/check_ghsa.py - \
                  "current=${version}" "upstream=${new_version}" \
                  2>/dev/null) || ghsa_json="[]"
  fi

  # Identity fields that ride along on every observation.
  # source_type distinguishes /releases/latest (the default)
  # from the /tags fallback used for projects that don't
  # publish releases.
  local id_extra
  id_extra=$(jq -cn \
    --arg repo "$repo" --arg rid "$repo_id" --arg oid "$owner_id" \
    --arg src "$source_type" \
    --argjson vulns "$ghsa_json" \
    '{repo: $repo, source_type: $src}
     + (if $rid != "" then {repo_id: $rid}     else {} end)
     + (if $oid != "" then {owner_id: $oid}    else {} end)
     + (if ($vulns|length) > 0 then {vulnerabilities: $vulns} else {} end)')

  if [ "$new_version" = "$version" ]; then
    echo "OK $name: up to date ($version)"
    emit_upstream "$name" "up_to_date" "$version" "$new_version" \
      "$published_at" "$release_url" "" "$id_extra"
    return
  fi

  # Defensive non-semver filter. /releases/latest already
  # excludes prereleases, but some projects ship release
  # candidates as "latest" (no prerelease flag), or use
  # date-with-dash version schemes like 2025-04-21 that
  # would break our url-rewriting heuristics.
  if ! printf '%s' "$new_version" | grep -qE '^[0-9]+(\.[0-9]+)*$'; then
    echo "SKIP $name: non-semver tag $new_version"
    emit_upstream "$name" "untracked" "$version" "$new_version" \
      "$published_at" "$release_url" \
      "non-semver tag: $new_version"
    return
  fi

  # Build new URL by rewriting old tag and old version.
  local old_tag new_url
  if echo "$url" | grep -q '/archive/refs/tags/'; then
    old_tag=$(echo "$url" | sed 's|.*/archive/refs/tags/||' | sed 's|\.tar\.gz$||')
  elif echo "$url" | grep -q '/releases/download/'; then
    old_tag=$(echo "$url" | sed 's|.*/releases/download/||' | sed 's|/.*||')
  elif echo "$url" | grep -qF -- "$version"; then
    # No tag pattern, but URL embeds the version literally —
    # common for mirror URLs that tag-source recipes use
    # (kernel.org/.../git-2.53.0.tar.xz,
    # go.dev/dl/go1.26.1.src.tar.gz,
    # python.org/ftp/python/3.14.4/Python-3.14.4.tgz).
    # Skip the tag-substitution step; the version-only sed
    # below does the work.
    old_tag=""
  else
    echo "ERROR $name: unrecognized URL pattern"
    emit_upstream "$name" "outdated" "$version" "$new_version" \
      "$published_at" "$release_url" \
      "unrecognized URL pattern for auto-rewrite"
    return
  fi
  if [ -n "$old_tag" ]; then
    new_url=$(echo "$url" | sed "s|${old_tag}|${new_tag}|g")
    new_url=$(echo "$new_url" | sed "s|${version}|${new_version}|g")
  else
    new_url=$(echo "$url" | sed "s|${version}|${new_version}|g")
  fi

  # Download and hash tarball BEFORE the cooldown decision:
  # the sha256 anchors the first-observation clock and the
  # attestation check.
  local tarball new_sha256 filesize
  tarball=$(mktemp "$TMP_DIR/tarball.XXXXXX")
  if ! curl -sL "$new_url" -o "$tarball"; then
    echo "ERROR $name: failed to download $new_url"
    emit_upstream "$name" "outdated" "$version" "$new_version" \
      "$published_at" "$release_url" \
      "download failed: $new_url"
    return
  fi
  filesize=$(wc -c < "$tarball" | tr -d ' ')
  if [ "$filesize" -lt 1000 ]; then
    echo "ERROR $name: download too small (${filesize} bytes), likely 404"
    emit_upstream "$name" "outdated" "$version" "$new_version" \
      "$published_at" "$release_url" \
      "download too small: ${filesize} bytes"
    return
  fi
  new_sha256=$(shasum -a 256 "$tarball" | awk '{print $1}')

  # Upstream attestation verification.
  local attestation attest_ok=1
  attestation=$(verify_upstream_attestation "$tarball" "$repo") || attest_ok=0
  local attest_invalid=0
  if [ "$attest_ok" -eq 0 ]; then
    attest_invalid=1
  elif [ "$attestation" = "unattested" ] && attest_required "$repo"; then
    attest_invalid=1
    attestation="required-but-missing"
  fi

  # Software Heritage cross-check. Independent of GitHub's
  # trust chain — every other gate flows through GH. SH
  # crawl lag is real but should clear inside the cooldown
  # window for popular tags. Tag-source path already
  # resolved swh_revision when looking up the tag's commit
  # date; release-source path resolves it here.
  if [ -z "$swh_revision" ]; then
    swh_revision=$(swh_resolve_commit "$repo" "$new_tag")
  fi
  local swh_status
  swh_status=$(swh_check "$swh_revision")

  # First-observation clock state.
  local prior_ver prior_sha prior_first prior_commit
  prior_ver=$(prior_field "$name" first_observed_version)
  prior_sha=$(prior_field "$name" first_observed_sha256)
  prior_first=$(prior_field "$name" first_observed_at)
  prior_commit=$(prior_field "$name" first_observed_commit_sha)

  local first_observed_at="$NOW_ISO"
  local first_observed_sha256="$new_sha256"
  local first_observed_version="$new_version"
  local first_observed_commit_sha="$swh_revision"
  local tamper_reason=""
  if [ "$prior_ver" = "$new_version" ] && [ -n "$prior_first" ]; then
    if [ "$prior_sha" = "$new_sha256" ]; then
      first_observed_at="$prior_first"
      # Commit-SHA drift on the same tag is an independent
      # tamper signal — catches force-pushed tags whose
      # tarball happens to hash the same (synthesized
      # release tarballs, mirror snapshot lag). Only fires
      # when both prior and current SHAs are known;
      # missing values are treated as "no observation" so
      # backwards-compat upgrades and transient API
      # failures don't produce false tamper.
      if [ -n "$prior_commit" ] && [ -n "$swh_revision" ] \
           && [ "$prior_commit" != "$swh_revision" ]; then
        tamper_reason="commit SHA changed on tag ${new_tag}: was ${prior_commit}, now ${swh_revision}"
      fi
    else
      tamper_reason="sha256 mismatch on ${new_version}: was ${prior_sha}, now ${new_sha256}"
    fi
  fi

  local clock_extra
  clock_extra=$(jq -cn \
    --arg fov "$first_observed_version" \
    --arg fos "$first_observed_sha256" \
    --arg foa "$first_observed_at" \
    --arg foc "$first_observed_commit_sha" \
    --arg att "$attestation" \
    --arg swhs "$swh_status" \
    --arg swhr "$swh_revision" \
    '{first_observed_version: $fov,
      first_observed_sha256: $fos,
      first_observed_at: $foa,
      attestation: $att,
      swh_archived: ($swhs == "archived"),
      swh_status: $swhs}
     + (if $foc  != "" then {first_observed_commit_sha: $foc} else {} end)
     + (if $swhr != "" then {swh_revision: $swhr} else {} end)')

  # Merge identity fields (repo_id, owner_id,
  # vulnerabilities) collected earlier with this run's
  # clock + attestation + SH data.
  local extra
  extra=$(jq -cn --argjson a "$id_extra" --argjson b "$clock_extra" \
            '$a + $b')

  # Tamper cases — no PR.
  if [ "$attest_invalid" -eq 1 ]; then
    local reason="attestation $attestation"
    [ "$attestation" = "invalid" ] && reason="attestation verification failed"
    echo "TAMPERED $name: $reason"
    emit_upstream "$name" "tampered" "$version" "$new_version" \
      "$published_at" "$release_url" "$reason" "$extra"
    return
  fi
  if [ -n "$tamper_reason" ]; then
    echo "TAMPERED $name: $tamper_reason"
    emit_upstream "$name" "tampered" "$version" "$new_version" \
      "$published_at" "$release_url" "$tamper_reason" "$extra"
    return
  fi

  # Record outdated with full metadata before gating decisions.
  emit_upstream "$name" "outdated" "$version" "$new_version" \
    "$published_at" "$release_url" "" "$extra"

  # Cooldown is anchored to first_observed_at, not upstream's
  # published_at. A maintainer retagging to reset the clock
  # doesn't change our first-observation timestamp.
  local now_epoch first_epoch age_days
  now_epoch=$(date +%s)
  first_epoch=$(date -d "$first_observed_at" +%s 2>/dev/null \
    || date -j -f "%Y-%m-%dT%H:%M:%SZ" "$first_observed_at" +%s 2>/dev/null)
  age_days=$(( (now_epoch - first_epoch) / 86400 ))
  if [ "$age_days" -lt "$COOLDOWN_DAYS" ]; then
    echo "COOLDOWN $name: first observed ${age_days}d ago (need $COOLDOWN_DAYS)"
    return
  fi

  # Branch-name dedup. Deterministic name means a strict
  # equality check against the remote is enough. Robust
  # against prefix collisions (zstd vs zstd-cli).
  local branch="auto-update/${name}-${new_version}"
  if git ls-remote --exit-code --heads origin "$branch" >/dev/null 2>&1; then
    echo "SKIP $name: branch $branch already exists"
    return
  fi

  echo "UPDATE $name: $version -> $new_version (tag: $new_tag)"

  # Edit recipe via the Python helper. The helper verifies
  # the old value before replacing, so the sha256 edit is
  # safe even with binary sections still present.
  python3 scripts/update_recipe.py set-field \
    "$file" version "$version" "$new_version" \
    || { echo "ERROR $name: version edit failed"; return; }
  python3 scripts/update_recipe.py set-field \
    "$file" url "$url" "$new_url" \
    || { echo "ERROR $name: url edit failed"; return; }
  python3 scripts/update_recipe.py set-field \
    "$file" sha256 "$source_sha256" "$new_sha256" \
    || { echo "ERROR $name: sha256 edit failed"; return; }
  if [ -n "$old_released_at" ]; then
    python3 scripts/update_recipe.py set-field \
      "$file" released_at "$old_released_at" "$published_at" \
      || echo "WARN $name: released_at edit failed (non-fatal)"
  fi
  python3 scripts/update_recipe.py strip-binary "$file"

  # NO_PR=1 short-circuits the PR step — useful for
  # bulk local backfills where the caller commits to
  # main directly.
  if [ "${NO_PR:-0}" = "1" ]; then
    echo "EDITED $name $new_version (NO_PR set, no branch/PR)"
    return
  fi

  # PR.
  git checkout -b "$branch"
  git add "$file"
  git commit -m "Update ${name} to ${new_version}"
  git push -u origin "$branch"

  local source_line=""
  if [ "$source_type" = "tag" ]; then
    source_line="
- **Source:** git tag (upstream does not publish GitHub Releases)"
  fi
  local attest_line=""
  case "$attestation" in
    verified)   attest_line="- **Attestation:** verified (\`gh attestation verify\`)" ;;
    unattested) attest_line="- **Attestation:** upstream does not publish attestations" ;;
  esac
  local swh_line=""
  case "$swh_status" in
    archived)     swh_line="- **Software Heritage:** archived (\`${swh_revision}\`)" ;;
    not-archived) swh_line="- **Software Heritage:** not yet archived (crawl lag)" ;;
    error)        swh_line="- **Software Heritage:** check failed" ;;
  esac

  # Pull GHSA matches that affect new_version into a
  # bullet list. This is what flips the PR to draft.
  local upstream_vulns
  upstream_vulns=$(printf '%s' "$ghsa_json" \
    | jq -r '[.[] | select(.applies_to | index("upstream"))] |
             map("- **" + (.cve_id // .ghsa_id // "advisory") +
                 "** (" + (.severity // "?") + "): " +
                 (.html_url // "")
             ) | join("\n")')

  local vulns_section=""
  local extra_labels=()
  local draft_flag=()
  if [ -n "$upstream_vulns" ]; then
    vulns_section="
## Security advisories on the bumped-to version

${upstream_vulns}

This PR is marked **draft** because the new version
matches a published GitHub Security Advisory. Bumping
*to* the fix is legitimate — confirm the advisory is
satisfied, then mark ready-for-review."
    extra_labels+=("--label" "vulnerability")
    draft_flag+=("--draft")
  fi
  if [ "$owner_changed" -eq 1 ]; then
    vulns_section="${vulns_section}

## Ownership change

The upstream's owner_id changed since our last
observation (was ${prior_owner_id}, now ${owner_id}).
The repository was likely transferred to a different
account. Verify the new maintainer is trusted before
merging."
    extra_labels+=("--label" "ownership-change")
  fi

  gh pr create ${draft_flag[@]+"${draft_flag[@]}"} \
    --title "Update ${name} to ${new_version}" \
    --body "$(cat <<PRBODY
## Auto-update

- **Package:** ${name}
- **Version:** ${version} -> ${new_version}
- **Upstream:** ${release_url}${source_line}
- **First observed:** ${first_observed_at} (${age_days}d ago)
${attest_line}
${swh_line}

Binary sections removed — CI will rebuild and
repopulate them when this PR is merged.${vulns_section}
PRBODY
)" \
    --label "auto-update" ${extra_labels[@]+"${extra_labels[@]}"}
  git checkout main

  echo "PR created for $name $new_version"
}

# Allow tests to source this file for its functions without
# triggering the recipe loop. Bash sets $BASH_SOURCE[0]
# to the script path and $0 to "bash" when sourced.
if [ "${BASH_SOURCE[0]}" != "$0" ]; then
  return 0
fi

# Find recipes to check.
if [ -n "$FILTER" ]; then
  letter="${FILTER:0:1}"
  file="recipes/${letter}/${FILTER}.toml"
  if [ ! -f "$file" ]; then
    echo "Recipe not found: $file"
    exit 1
  fi
  check_recipe "$file"
else
  for file in recipes/*/*.toml; do
    check_recipe "$file" || true
  done
fi

# Collate NDJSON entries into _data/upstream.json. When
# FILTER is set we only ran one recipe — merge into any
# existing file rather than overwriting the full index.
mkdir -p _data
if [ -n "$FILTER" ] && [ -f _data/upstream.json ]; then
  jq -s --arg gen "$NOW_ISO" --slurpfile existing _data/upstream.json '
    {generated_at: $gen,
     recipes: (($existing[0].recipes // {}) + (add // {}))}
  ' "$NDJSON" > _data/upstream.json.new
else
  jq -s --arg gen "$NOW_ISO" '
    {generated_at: $gen, recipes: (add // {})}
  ' "$NDJSON" > _data/upstream.json.new
fi
mv _data/upstream.json.new _data/upstream.json
echo "Wrote _data/upstream.json ($(jq '.recipes | length' _data/upstream.json) recipes)"
