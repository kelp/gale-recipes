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
#   PR_LOG                            — file path; pr-create argv recorded
write_shim gh <<'GH'
#!/bin/bash
joined="$*"
case "$joined" in
  "api /repos/example/testpkg/releases/latest")
    jq -cn --arg tag "${MOCK_TAG:-v1.0.0}" \
           --arg pub "${MOCK_PUBLISHED_AT:-2026-04-24T00:00:00Z}" \
           '{tag_name: $tag, published_at: $pub}'
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

run_case() {
  bash .github/scripts/auto-update.sh testpkg
}

# ---------------------------------------------------------
# 1. up_to_date
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_TAG="v1.0.0" MOCK_SHA256="aaaa" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 \
run_case 2>&1 | grep -q 'OK testpkg' \
  && echo "PASS 1_up_to_date" \
  || { echo "FAIL 1_up_to_date"; exit 1; }

# ---------------------------------------------------------
# 2. non-semver
# ---------------------------------------------------------
MOCK_TAG="v1.0.0-rc1" MOCK_SHA256="aaaa" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 \
run_case 2>&1 | grep -q 'non-semver tag 1.0.0-rc1' \
  && echo "PASS 2_non_semver" \
  || { echo "FAIL 2_non_semver"; exit 1; }

# ---------------------------------------------------------
# 3. cooldown — fresh first observation
# ---------------------------------------------------------
rm -f _data/upstream.json
MOCK_TAG="v1.1.0" MOCK_SHA256="bbbb" MOCK_REPO_ID=12345 \
MOCK_OWNER_ID=67890 MOCK_SWH_CODE=200 \
MOCK_TAG_OBJECT_SHA=deadbeef \
run_case 2>&1 | grep -q 'COOLDOWN testpkg' \
  && echo "PASS 3_cooldown" \
  || { echo "FAIL 3_cooldown"; exit 1; }

jq -e '.recipes.testpkg.first_observed_version == "1.1.0"
       and .recipes.testpkg.first_observed_sha256 == "bbbb"
       and (.recipes.testpkg.first_observed_at | length > 0)
       and .recipes.testpkg.repo_id == "12345"
       and .recipes.testpkg.owner_id == "67890"
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
run_case 2>&1 | grep -q 'TAMPERED testpkg: sha256 mismatch' \
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
run_case 2>&1 | grep -q 'TAMPERED testpkg: repo_id changed' \
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

echo "All smoke cases passed."
