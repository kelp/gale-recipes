#!/bin/bash
# Integration smoke test for .github/scripts/auto-update.sh.
#
# Mocks gh / curl / shasum / git via a PATH-injected shim
# dir so check_recipe runs end-to-end without hitting the
# network. Covers the decision paths:
#
#   1. up_to_date         — upstream matches current.
#   2. non-semver         — new tag fails the shape allowlist.
#   3. cooldown           — first-observation set to now.
#   4. tampered (sha256)  — same version, different sha256.
#   5. tampered (repo_id) — repo deleted+recreated.
#   6. ownership-change   — owner_id changed; PR labeled.
#   7. ghsa-on-upstream   — bumped-to version is in advisory;
#                            PR opened as draft + label.
#   8. swh-archived       — SH returns 200; PR body says so.
#
# Mocks pr-create as a recorder; PR-creation cases inspect
# the recorded argv to confirm --draft / --label.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/recipes/t/" "$WORK/_data" "$WORK/scripts" \
         "$WORK/.github/scripts"
cp "$REPO_ROOT/scripts/update_recipe.py" "$WORK/scripts/"
cp "$REPO_ROOT/scripts/check_ghsa.py"     "$WORK/scripts/"
cp "$REPO_ROOT/.github/scripts/auto-update.sh" \
   "$WORK/.github/scripts/"

cat > "$WORK/recipes/t/testpkg.toml" <<'RECIPE'
[package]
name = "testpkg"
version = "1.0.0"

[source]
repo = "example/testpkg"
url = "https://github.com/example/testpkg/archive/refs/tags/v1.0.0.tar.gz"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
released_at = "2020-01-01"

[build]
steps = ["true"]
RECIPE

SHIM="$WORK/shim"
mkdir -p "$SHIM"
export PATH="$SHIM:$PATH"

# signed_commit_to_branch resolves the repo from
# GITHUB_REPOSITORY; pin it so the gh shim can match its
# API calls without a `gh repo view` fallback.
export GITHUB_REPOSITORY="example/origin"

write_shim() {
  local name="$1"
  cat > "$SHIM/$name"
  chmod +x "$SHIM/$name"
}

# `gh` shim. Mocks the calls auto-update.sh issues, gated
# on env vars set per case.
#   MOCK_TAG, MOCK_PUBLISHED_AT       — release info
#   MOCK_REPO_ID, MOCK_OWNER_ID       — repo metadata
#   MOCK_GHSA_JSON                    — security-advisories array (raw JSON)
#   MOCK_TAG_OBJECT_TYPE              — "commit" or "tag"
#   MOCK_TAG_OBJECT_SHA               — commit sha to return
#   MOCK_NO_RELEASE                   — set to 1 to make
#                                       /releases/latest 404
#   MOCK_TAGS_JSON                    — /repos/.../tags response
#   MOCK_COMMIT_DATE                  — date returned by
#                                       /commits/<sha> --jq
#   PR_LOG                            — file path; pr-create argv recorded
write_shim gh <<'GH'
#!/bin/bash
joined="$*"
case "$joined" in
  "api /repos/example/testpkg/releases/latest")
    if [ "${MOCK_NO_RELEASE:-0}" = "1" ]; then
      echo "HTTP 404: Not Found" >&2
      exit 1
    fi
    jq -cn --arg tag "${MOCK_TAG:-v1.0.0}" \
           --arg pub "${MOCK_PUBLISHED_AT:-2026-04-24T00:00:00Z}" \
           '{tag_name: $tag, published_at: $pub}'
    exit 0
    ;;
  "api /repos/example/testpkg/tags?per_page=100")
    printf '%s' "${MOCK_TAGS_JSON:-[]}"
    exit 0
    ;;
  "api /repos/example/testpkg/commits/"*)
    # gh's --jq is server-side; mock by emitting the
    # filter's expected result directly.
    printf '%s' "${MOCK_COMMIT_DATE:-2026-04-24}"
    exit 0
    ;;
  "api /repos/example/testpkg")
    jq -cn --arg id "${MOCK_REPO_ID:-12345}" \
           --arg oid "${MOCK_OWNER_ID:-67890}" \
           '{id: ($id|tonumber), owner: {id: ($oid|tonumber)}}'
    exit 0
    ;;
  "api /repos/example/testpkg/security-advisories?state=published&per_page=100")
    printf '%s' "${MOCK_GHSA_JSON:-[]}"
    exit 0
    ;;
  "api /repos/example/testpkg/git/refs/tags/"*)
    jq -cn --arg type "${MOCK_TAG_OBJECT_TYPE:-commit}" \
           --arg sha "${MOCK_TAG_OBJECT_SHA:-abc123}" \
           '{object: {type: $type, sha: $sha}}'
    exit 0
    ;;
  "attestation verify"*)
    echo "no attestations found for the subject" >&2
    exit 1
    ;;
  "pr create"*)
    [ -n "${PR_LOG:-}" ] && printf '%s\n' "$*" > "$PR_LOG"
    echo "https://github.com/example/repo/pull/1"
    exit 0
    ;;
  # signed_commit_to_branch path: main ref lookup, branch
  # ref creation, GraphQL createCommitOnBranch.
  "api repos/example/origin/git/ref/heads/main"*)
    echo "mainsha000"
    exit 0
    ;;
  "api -X POST repos/example/origin/git/refs"*)
    echo '{}'
    exit 0
    ;;
  "api graphql"*)
    echo '{}'
    exit 0
    ;;
  # verify.yml dispatch. VERIFY_LOG records attempts; the
  # first MOCK_VERIFY_FAIL_COUNT attempts fail.
  "workflow run verify.yml"*)
    [ -z "${VERIFY_LOG:-}" ] && exit 0
    printf '%s\n' "$*" >> "$VERIFY_LOG"
    attempts=$(wc -l < "$VERIFY_LOG")
    [ "${MOCK_VERIFY_FAIL_COUNT:-0}" -ge "$attempts" ] && exit 1
    exit 0
    ;;
  # ledger-check.yml dispatch. LEDGER_LOG records attempts;
  # the first MOCK_LEDGER_FAIL_COUNT attempts fail.
  "workflow run ledger-check.yml"*)
    [ -z "${LEDGER_LOG:-}" ] && exit 0
    printf '%s\n' "$*" >> "$LEDGER_LOG"
    attempts=$(wc -l < "$LEDGER_LOG")
    [ "${MOCK_LEDGER_FAIL_COUNT:-0}" -ge "$attempts" ] && exit 1
    exit 0
    ;;
esac
echo "unmocked gh call: $*" >&2
exit 1
GH

# `curl` shim. Differentiates SH probe (HEAD/GET against
# softwareheritage.org with -w '%{http_code}') from
# tarball download (-o <file>).
write_shim curl <<'CURL'
#!/bin/bash
# Detect SH probe — it always passes -w '%{http_code}'.
if printf '%s\n' "$@" | grep -q 'softwareheritage.org'; then
  printf '%s' "${MOCK_SWH_CODE:-404}"
  exit 0
fi
# Tarball path: write a stub with at least 1000 bytes.
out=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2 ;;
    *) shift ;;
  esac
done
printf 'stub-tarball-contents-at-least-1000-bytes-long' > "$out"
head -c 2000 /dev/urandom >> "$out"
exit 0
CURL

write_shim shasum <<'SHASUM'
#!/bin/bash
echo "${MOCK_SHA256:-dead}  $2"
SHASUM

write_shim git <<'GIT'
#!/bin/bash
case "$1" in
  ls-remote) exit 2 ;;   # branch does not exist
  *) exit 0 ;;
esac
GIT

cd "$WORK"

# Run check_recipe and match a fixed substring against its
# combined output. Pure-bash matching: `run_case 2>&1 |
# grep -q` is a race — grep -q exits at first match, the
# still-running script SIGPIPEs on its remaining output,
# and pipefail turns exit 141 into a test failure. Bites
# on slower CI runners, rarely locally. LAST_OUT keeps the
# output for FAIL diagnostics.
LAST_OUT=""
expect_case() {
  local pattern="$1"
  LAST_OUT=$(run_case 2>&1)
  [[ "$LAST_OUT" == *"$pattern"* ]]
}

run_case() {
  bash .github/scripts/auto-update.sh testpkg
}

# ---------------------------------------------------------
# 1. up_to_date
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_TAG="v1.0.0" MOCK_SHA256="aaaa" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 \
expect_case 'OK testpkg' \
  && echo "PASS 1_up_to_date" \
  || { echo "FAIL 1_up_to_date"; printf '%s\n' "$LAST_OUT"; exit 1; }

# ---------------------------------------------------------
# 2. non-semver
# ---------------------------------------------------------
MOCK_TAG="v1.0.0-rc1" MOCK_SHA256="aaaa" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 \
expect_case 'non-semver tag 1.0.0-rc1' \
  && echo "PASS 2_non_semver" \
  || { echo "FAIL 2_non_semver"; exit 1; }

# ---------------------------------------------------------
# 3. cooldown — fresh first observation
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_TAG="v1.1.0" MOCK_SHA256="bbbb" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=deadbeef \
expect_case 'COOLDOWN testpkg' \
  && echo "PASS 3_cooldown" \
  || { echo "FAIL 3_cooldown"; exit 1; }

jq -e '.recipes.testpkg.first_observed_version == "1.1.0"
       and .recipes.testpkg.first_observed_sha256 == "bbbb"
       and .recipes.testpkg.first_observed_commit_sha == "deadbeef"
       and (.recipes.testpkg.first_observed_at | length > 0)
       and .recipes.testpkg.repo_id == "12345"
       and .recipes.testpkg.owner_id == "67890"
       and .recipes.testpkg.source_type == "release"
       and .recipes.testpkg.swh_archived == true
       and .recipes.testpkg.swh_revision == "deadbeef"' \
   _data/upstream.json >/dev/null \
  && echo "PASS 3a_state_recorded" \
  || { echo "FAIL 3a_state_recorded"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 4. tampered (sha256) — same version, sha256 differs
# ---------------------------------------------------------
MOCK_TAG="v1.1.0" MOCK_SHA256="cccc" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=deadbeef \
expect_case 'TAMPERED testpkg: sha256 mismatch' \
  && echo "PASS 4_tampered_sha256" \
  || { echo "FAIL 4_tampered_sha256"; exit 1; }

jq -e '.recipes.testpkg.status == "tampered"' _data/upstream.json \
  >/dev/null \
  && echo "PASS 4a_status_tampered" \
  || { echo "FAIL 4a_status_tampered"; exit 1; }

# ---------------------------------------------------------
# 5. tampered (repo_id) — repo replaced. Reset state, then
#    re-prime with one ID and re-run with a different one.
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_TAG="v1.0.0" MOCK_SHA256="aaaa" MOCK_REPO_ID=11111 \
MOCK_OWNER_ID=22222 \
run_case >/dev/null 2>&1
MOCK_TAG="v1.0.0" MOCK_SHA256="aaaa" MOCK_REPO_ID=99999 \
MOCK_OWNER_ID=22222 \
expect_case 'TAMPERED testpkg: repo_id changed' \
  && echo "PASS 5_repo_replaced" \
  || { echo "FAIL 5_repo_replaced"; exit 1; }

# ---------------------------------------------------------
# 6. ownership change — owner_id differs but repo_id same.
#    On a bump path so PR-create runs.
# ---------------------------------------------------------
rm -f _data/upstream.json
# Prime: outdated, then sit through cooldown via age 0 days
# isn't reachable. Instead, prime first_observed at an old
# date by running once with a known sha and then editing
# upstream.json's first_observed_at to 30 days ago.
MOCK_TAG="v1.1.0" MOCK_SHA256="bbbb" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=deadbeef \
run_case >/dev/null 2>&1
old_iso=$(python3 -c "
from datetime import datetime, timedelta, timezone
print((datetime.now(timezone.utc) - timedelta(days=30))
        .strftime('%Y-%m-%dT%H:%M:%SZ'))")
jq --arg t "$old_iso" \
   '.recipes.testpkg.first_observed_at = $t' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

PR_LOG="$WORK/pr.log"
MOCK_TAG="v1.1.0" MOCK_SHA256="bbbb" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=44444 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=deadbeef PR_LOG="$PR_LOG" \
run_case >/dev/null 2>&1

grep -q 'ownership-change' "$PR_LOG" \
  && echo "PASS 6_ownership_change_label" \
  || { echo "FAIL 6_ownership_change_label"; \
       cat "$PR_LOG"; exit 1; }

# ---------------------------------------------------------
# 7. GHSA hit on upstream — PR opened as draft + label.
#    Reuses the cooldown-old upstream.json from case 6 but
#    bumps to a different version so branch dedup passes.
# ---------------------------------------------------------
ghsa_json='[{"ghsa_id":"GHSA-xxxx","cve_id":"CVE-2026-1",
             "severity":"high","state":"published",
             "html_url":"https://example/advisory",
             "vulnerabilities":[{"vulnerable_version_range":">=1.0.0 <2.0.0"}]}]'
old_iso2=$(python3 -c "
from datetime import datetime, timedelta, timezone
print((datetime.now(timezone.utc) - timedelta(days=30))
        .strftime('%Y-%m-%dT%H:%M:%SZ'))")
# Re-prime upstream.json to track v1.2.0 with old first-obs.
jq --arg t "$old_iso2" \
   '.recipes.testpkg.first_observed_version = "1.2.0"
    | .recipes.testpkg.first_observed_sha256 = "dddd"
    | .recipes.testpkg.first_observed_at = $t
    | .recipes.testpkg.owner_id = "44444"' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

PR_LOG2="$WORK/pr2.log"
MOCK_TAG="v1.2.0" MOCK_SHA256="dddd" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=44444 MOCK_GHSA_JSON="$ghsa_json" \
MOCK_SWH_CODE=200 MOCK_TAG_OBJECT_SHA=deadbeef \
PR_LOG="$PR_LOG2" \
run_case >/dev/null 2>&1

pr2_content=$(cat "$PR_LOG2")
case "$pr2_content" in
  *--draft*) echo "PASS 7_ghsa_draft" ;;
  *) echo "FAIL 7_ghsa_draft"; cat "$PR_LOG2"; exit 1 ;;
esac
case "$pr2_content" in
  *vulnerability*) echo "PASS 7a_ghsa_label" ;;
  *) echo "FAIL 7a_ghsa_label"; cat "$PR_LOG2"; exit 1 ;;
esac

# Confirm vulnerabilities recorded in upstream.json.
jq -e '.recipes.testpkg.vulnerabilities[0].cve_id == "CVE-2026-1"
       and (.recipes.testpkg.vulnerabilities[0].applies_to | index("upstream"))' \
   _data/upstream.json >/dev/null \
  && echo "PASS 7b_ghsa_in_json" \
  || { echo "FAIL 7b_ghsa_in_json"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 8. tag fallback — release endpoint 404s, /tags returns
#    semver tags, script picks the highest and records the
#    observation (no PR yet — fresh first observation sits
#    in cooldown).
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_NO_RELEASE=1 \
MOCK_TAGS_JSON='[{"name":"v2.0.0"},{"name":"v1.5.0"},{"name":"v1.0.0"}]' \
MOCK_TAG_OBJECT_SHA=tagsha2 MOCK_COMMIT_DATE="2026-04-24" \
MOCK_SHA256="eeee" MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
MOCK_SWH_CODE=200 \
expect_case 'COOLDOWN testpkg' \
  && echo "PASS 8_tag_fallback_observed" \
  || { echo "FAIL 8_tag_fallback_observed"; exit 1; }

jq -e '.recipes.testpkg.status == "outdated"
       and .recipes.testpkg.latest_version == "2.0.0"
       and .recipes.testpkg.source_type == "tag"
       and .recipes.testpkg.first_observed_commit_sha == "tagsha2"
       and .recipes.testpkg.latest_released_at == "2026-04-24"' \
   _data/upstream.json >/dev/null \
  && echo "PASS 8a_tag_fallback_state" \
  || { echo "FAIL 8a_tag_fallback_state"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 9. tag fallback — /tags returns only non-semver names.
#    Script records untracked with a tag-specific reason.
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_NO_RELEASE=1 \
MOCK_TAGS_JSON='[{"name":"experimental"},{"name":"main-build"}]' \
MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
expect_case 'no semver tags on example/testpkg' \
  && echo "PASS 9_tag_fallback_no_semver" \
  || { echo "FAIL 9_tag_fallback_no_semver"; exit 1; }

jq -e '.recipes.testpkg.status == "untracked"
       and (.recipes.testpkg.reason | contains("no semver tags"))' \
   _data/upstream.json >/dev/null \
  && echo "PASS 9a_state_untracked" \
  || { echo "FAIL 9a_state_untracked"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 10. tag fallback — highest tag equals the recipe's
#     current version → up_to_date with source_type=tag.
# ---------------------------------------------------------
rm -f _data/upstream.json
# Earlier bump-path tests mutated the recipe via
# update_recipe.py; reset it so the version we compare
# against the mocked tag is known.
cat > recipes/t/testpkg.toml <<'RECIPE'
[package]
name = "testpkg"
version = "1.0.0"

[source]
repo = "example/testpkg"
url = "https://github.com/example/testpkg/archive/refs/tags/v1.0.0.tar.gz"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
released_at = "2020-01-01"

[build]
steps = ["true"]
RECIPE
MOCK_NO_RELEASE=1 \
MOCK_TAGS_JSON='[{"name":"v1.0.0"},{"name":"v0.9.0"}]' \
MOCK_TAG_OBJECT_SHA=tagsha1 MOCK_COMMIT_DATE="2026-04-24" \
MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
expect_case 'OK testpkg' \
  && echo "PASS 10_tag_up_to_date" \
  || { echo "FAIL 10_tag_up_to_date"; exit 1; }

jq -e '.recipes.testpkg.status == "up_to_date"
       and .recipes.testpkg.source_type == "tag"' \
   _data/upstream.json >/dev/null \
  && echo "PASS 10a_state_up_to_date" \
  || { echo "FAIL 10a_state_up_to_date"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 11. commit-SHA tamper — same version, same sha256, but
#     the tag now points at a different commit. Catches a
#     force-pushed tag whose tarball happens to hash the
#     same as the prior observation.
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_TAG="v1.1.0" MOCK_SHA256="ffff" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=cafebabe \
run_case >/dev/null 2>&1
MOCK_TAG="v1.1.0" MOCK_SHA256="ffff" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=deadbeef \
expect_case 'TAMPERED testpkg: commit SHA changed' \
  && echo "PASS 11_commit_sha_tamper" \
  || { echo "FAIL 11_commit_sha_tamper"; exit 1; }

jq -e '.recipes.testpkg.status == "tampered"
       and (.recipes.testpkg.reason | contains("commit SHA changed"))' \
   _data/upstream.json >/dev/null \
  && echo "PASS 11a_status_tampered" \
  || { echo "FAIL 11a_status_tampered"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 12. prefixed-semver tags accepted — covers tags like
#     llvmorg-22.1.6, openssl-4.0.0, gopls/v0.22.0,
#     bun-v1.3.14 that older releases of the script
#     rejected as "non-semver".
# ---------------------------------------------------------
for case_idx in 12a 12b 12c 12d; do
  case "$case_idx" in
    12a) tag="llvmorg-22.1.6"; expect_ver="22.1.6" ;;
    12b) tag="openssl-4.0.0";  expect_ver="4.0.0"  ;;
    12c) tag="gopls/v0.22.0";  expect_ver="0.22.0" ;;
    12d) tag="bun-v1.3.14";    expect_ver="1.3.14" ;;
  esac
  rm -f _data/upstream.json
  # Reset recipe so we can compare cleanly.
  cat > recipes/t/testpkg.toml <<'RECIPE'
[package]
name = "testpkg"
version = "0.1.0"

[source]
repo = "example/testpkg"
url = "https://github.com/example/testpkg/archive/refs/tags/v0.1.0.tar.gz"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
released_at = "2020-01-01"

[build]
steps = ["true"]
RECIPE
  out=$(MOCK_TAG="$tag" MOCK_SHA256="aaaa" MOCK_REPO_ID=12345 \
        MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
        MOCK_TAG_OBJECT_SHA=deadbeef \
        run_case 2>&1)
  # Must NOT be rejected as non-semver. Acceptable
  # outcomes: COOLDOWN (fresh observation) or PR creation.
  if echo "$out" | grep -q 'non-semver tag'; then
    echo "FAIL ${case_idx}_prefixed_semver_${tag}"
    echo "$out"
    exit 1
  fi
  jq -e --arg v "$expect_ver" \
     '.recipes.testpkg.latest_version == $v
      and .recipes.testpkg.status != "untracked"' \
     _data/upstream.json >/dev/null \
    && echo "PASS ${case_idx}_prefixed_semver" \
    || { echo "FAIL ${case_idx}_prefixed_semver"; \
         echo "  tag=$tag expected_version=$expect_ver"; \
         jq . _data/upstream.json; exit 1; }
done

# Helper: reset the test recipe to a given version.
reset_recipe() {
  local ver="$1"
  cat > recipes/t/testpkg.toml <<RECIPE
[package]
name = "testpkg"
version = "$ver"

[source]
repo = "example/testpkg"
url = "https://github.com/example/testpkg/archive/refs/tags/v${ver}.tar.gz"
sha256 = "0000000000000000000000000000000000000000000000000000000000000000"
released_at = "2020-01-01"

[build]
steps = ["true"]
RECIPE
}

# ---------------------------------------------------------
# 13. downgrade guard, release path — upstream's latest
#     release is OLDER than the recipe (lagging mirror,
#     un-promoted release). Must not open a downgrade PR;
#     records up_to_date with an "ahead" reason.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "2.0.0"
MOCK_TAG="v1.5.0" MOCK_SHA256="aaaa" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 \
expect_case 'AHEAD testpkg' \
  && echo "PASS 13_downgrade_release" \
  || { echo "FAIL 13_downgrade_release"; exit 1; }

jq -e '.recipes.testpkg.status == "up_to_date"
       and .recipes.testpkg.latest_version == "1.5.0"
       and (.recipes.testpkg.reason | contains("ahead"))' \
   _data/upstream.json >/dev/null \
  && echo "PASS 13a_downgrade_state" \
  || { echo "FAIL 13a_downgrade_state"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 14. downgrade guard, tag path — highest tag is older
#     than the recipe (mirror/wget case).
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "2.0.0"
MOCK_NO_RELEASE=1 \
MOCK_TAGS_JSON='[{"name":"v1.5.0"},{"name":"v1.0.0"}]' \
MOCK_TAG_OBJECT_SHA=tagsha3 MOCK_COMMIT_DATE="2026-04-24" \
MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
expect_case 'AHEAD testpkg' \
  && echo "PASS 14_downgrade_tag" \
  || { echo "FAIL 14_downgrade_tag"; exit 1; }

# ---------------------------------------------------------
# 15. version ceiling — recipe pinned below 2; upstream
#     released 2.0.0 but a newer in-line 1.x tag exists.
#     Resolution must come from the tag list filtered to
#     versions strictly below the ceiling (the openssl 3.x
#     case: /releases/latest is 4.x forever, yet 3.6.x
#     security updates must keep flowing).
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
mkdir -p .github
printf 'testpkg 2\n' > .github/auto-update-ceilings.txt
MOCK_TAG="v2.0.0" \
MOCK_TAGS_JSON='[{"name":"v2.0.0"},{"name":"v1.5.0"},{"name":"v1.0.0"}]' \
MOCK_TAG_OBJECT_SHA=tagsha4 MOCK_COMMIT_DATE="2026-04-24" \
MOCK_SHA256="abab" MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
MOCK_SWH_CODE=200 \
expect_case 'COOLDOWN testpkg' \
  && echo "PASS 15_ceiling_in_range_bump" \
  || { echo "FAIL 15_ceiling_in_range_bump"; exit 1; }

jq -e '.recipes.testpkg.status == "outdated"
       and .recipes.testpkg.latest_version == "1.5.0"' \
   _data/upstream.json >/dev/null \
  && echo "PASS 15a_ceiling_state" \
  || { echo "FAIL 15a_ceiling_state"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 16. version ceiling, exclusive bound — no tag strictly
#     below the ceiling exists. v1.0.0 itself must NOT
#     satisfy ceiling 1 (exclusive). Records untracked.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
printf 'testpkg 1\n' > .github/auto-update-ceilings.txt
MOCK_TAG="v2.0.0" \
MOCK_TAGS_JSON='[{"name":"v2.0.0"},{"name":"v1.0.0"}]' \
MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
expect_case 'no tags below version ceiling' \
  && echo "PASS 16_ceiling_exclusive" \
  || { echo "FAIL 16_ceiling_exclusive"; exit 1; }

jq -e '.recipes.testpkg.status == "untracked"
       and (.recipes.testpkg.reason | contains("ceiling"))' \
   _data/upstream.json >/dev/null \
  && echo "PASS 16a_ceiling_untracked" \
  || { echo "FAIL 16a_ceiling_untracked"; \
       jq . _data/upstream.json; exit 1; }
rm -f .github/auto-update-ceilings.txt

# ---------------------------------------------------------
# 17. tag fallback accepts recipe-name-prefixed tags
#     (openssl-3.6.2 style) and ranks them against plain
#     v-tags by stripped version.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
MOCK_NO_RELEASE=1 \
MOCK_TAGS_JSON='[{"name":"testpkg-1.2.0"},{"name":"v1.1.0"}]' \
MOCK_TAG_OBJECT_SHA=tagsha5 MOCK_COMMIT_DATE="2026-04-24" \
MOCK_SHA256="cdcd" MOCK_REPO_ID=12345 MOCK_OWNER_ID=67890 \
MOCK_SWH_CODE=200 \
expect_case 'COOLDOWN testpkg' \
  && echo "PASS 17_name_prefixed_fallback" \
  || { echo "FAIL 17_name_prefixed_fallback"; exit 1; }

jq -e '.recipes.testpkg.latest_version == "1.2.0"' \
   _data/upstream.json >/dev/null \
  && echo "PASS 17a_name_prefixed_version" \
  || { echo "FAIL 17a_name_prefixed_version"; \
       jq . _data/upstream.json; exit 1; }

# ---------------------------------------------------------
# 18. verify dispatch retry — first two dispatches fail,
#     third succeeds. PR path must attempt up to 3 times.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
# Prime first observation, then age it past the cooldown.
MOCK_TAG="v1.3.0" MOCK_SHA256="eeee" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha6 \
run_case >/dev/null 2>&1
old_iso3=$(python3 -c "
from datetime import datetime, timedelta, timezone
print((datetime.now(timezone.utc) - timedelta(days=30))
        .strftime('%Y-%m-%dT%H:%M:%SZ'))")
jq --arg t "$old_iso3" \
   '.recipes.testpkg.first_observed_at = $t' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

VLOG="$WORK/verify.log"
rm -f "$VLOG"
MOCK_TAG="v1.3.0" MOCK_SHA256="eeee" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha6 \
VERIFY_LOG="$VLOG" MOCK_VERIFY_FAIL_COUNT=2 \
VERIFY_DISPATCH_RETRY_DELAY=0 \
run_case >/dev/null 2>&1

[ -f "$VLOG" ] && [ "$(wc -l < "$VLOG")" -eq 3 ] \
  && echo "PASS 18_verify_retry" \
  || { echo "FAIL 18_verify_retry"; \
       cat "$VLOG" 2>/dev/null; exit 1; }

# ---------------------------------------------------------
# 19. verify dispatch exhausted — all attempts fail; the
#     failure must surface in GITHUB_STEP_SUMMARY instead
#     of scrolling away as a log line.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
MOCK_TAG="v1.4.0" MOCK_SHA256="abcd" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha7 \
run_case >/dev/null 2>&1
jq --arg t "$old_iso3" \
   '.recipes.testpkg.first_observed_at = $t' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

VLOG2="$WORK/verify2.log"
SUMMARY="$WORK/step_summary.md"
rm -f "$VLOG2" "$SUMMARY"
MOCK_TAG="v1.4.0" MOCK_SHA256="abcd" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha7 \
VERIFY_LOG="$VLOG2" MOCK_VERIFY_FAIL_COUNT=99 \
VERIFY_DISPATCH_RETRY_DELAY=0 \
GITHUB_STEP_SUMMARY="$SUMMARY" \
run_case >/dev/null 2>&1

grep -q 'verify.yml dispatch failed' "$SUMMARY" 2>/dev/null \
  && echo "PASS 19_verify_failure_summary" \
  || { echo "FAIL 19_verify_failure_summary"; \
       cat "$SUMMARY" 2>/dev/null; exit 1; }

# ---------------------------------------------------------
# 20. ledger-check dispatch — the bot PR's branch commit is
#     GITHUB_TOKEN-authored, so its pull_request event is
#     suppressed; without an explicit dispatch the required
#     Ledger Check would sit "Expected" forever. The PR path
#     must dispatch ledger-check.yml on the new branch.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
MOCK_TAG="v1.6.0" MOCK_SHA256="beef" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha8 \
run_case >/dev/null 2>&1
jq --arg t "$old_iso3" \
   '.recipes.testpkg.first_observed_at = $t' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

LLOG="$WORK/ledger.log"
rm -f "$LLOG"
MOCK_TAG="v1.6.0" MOCK_SHA256="beef" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha8 \
LEDGER_LOG="$LLOG" VERIFY_DISPATCH_RETRY_DELAY=0 \
run_case >/dev/null 2>&1

grep -q -- '--ref auto-update/testpkg-1.6.0' "$LLOG" 2>/dev/null \
  && echo "PASS 20_ledger_check_dispatch" \
  || { echo "FAIL 20_ledger_check_dispatch"; \
       cat "$LLOG" 2>/dev/null; exit 1; }

# ---------------------------------------------------------
# 21. ledger-check dispatch retry — auto-update.yml's
#     GITHUB_TOKEN dispatches fail transiently (and failed
#     with HTTP 403 in production before actions: write was
#     granted). First two attempts fail, the third succeeds;
#     the PR path must attempt up to 3 times, same as the
#     verify dispatch.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
MOCK_TAG="v1.7.0" MOCK_SHA256="feed" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha9 \
run_case >/dev/null 2>&1
jq --arg t "$old_iso3" \
   '.recipes.testpkg.first_observed_at = $t' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

LLOG2="$WORK/ledger2.log"
rm -f "$LLOG2"
MOCK_TAG="v1.7.0" MOCK_SHA256="feed" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha9 \
LEDGER_LOG="$LLOG2" MOCK_LEDGER_FAIL_COUNT=2 \
VERIFY_DISPATCH_RETRY_DELAY=0 \
run_case >/dev/null 2>&1

[ -f "$LLOG2" ] && [ "$(wc -l < "$LLOG2")" -eq 3 ] \
  && echo "PASS 21_ledger_dispatch_retry" \
  || { echo "FAIL 21_ledger_dispatch_retry"; \
       cat "$LLOG2" 2>/dev/null; exit 1; }

# ---------------------------------------------------------
# 22. ledger-check dispatch exhausted — all attempts fail;
#     the failure must surface in GITHUB_STEP_SUMMARY (a
#     required check stuck at "Expected" with no visible
#     cause is the exact failure mode this dispatch exists
#     to prevent), not scroll away as a WARN log line.
# ---------------------------------------------------------
rm -f _data/upstream.json
reset_recipe "1.0.0"
MOCK_TAG="v1.8.0" MOCK_SHA256="face" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha10 \
run_case >/dev/null 2>&1
jq --arg t "$old_iso3" \
   '.recipes.testpkg.first_observed_at = $t' \
   _data/upstream.json > _data/upstream.json.new \
  && mv _data/upstream.json.new _data/upstream.json

LLOG3="$WORK/ledger3.log"
LSUMMARY="$WORK/ledger_step_summary.md"
rm -f "$LLOG3" "$LSUMMARY"
MOCK_TAG="v1.8.0" MOCK_SHA256="face" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=tagsha10 \
LEDGER_LOG="$LLOG3" MOCK_LEDGER_FAIL_COUNT=99 \
VERIFY_DISPATCH_RETRY_DELAY=0 \
GITHUB_STEP_SUMMARY="$LSUMMARY" \
run_case >/dev/null 2>&1

grep -q 'ledger-check.yml dispatch failed' "$LSUMMARY" 2>/dev/null \
  && echo "PASS 22_ledger_failure_summary" \
  || { echo "FAIL 22_ledger_failure_summary"; \
       cat "$LSUMMARY" 2>/dev/null; exit 1; }

echo "All smoke cases passed."
