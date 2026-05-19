#!/bin/bash
# Unit test for verify_upstream_attestation in
# .github/scripts/auto-update.sh.
#
# The real `gh attestation verify` emits one of several
# error patterns depending on why verification failed:
#   - "no attestations found" (rare; old gh versions)
#   - "HTTP 404: Not Found" with /attestations/sha256:...
#     URL (current real-world wording for "no attestations
#     exist on this artifact")
#   - other errors (real verification failure, network, etc.)
#
# We must classify the 404 case as "unattested", not
# "invalid". The original grep only matched the "no
# attestations" wording, so every real repo got flagged
# tampered.

set -uo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

SHIM="$WORK/shim"
mkdir -p "$SHIM"
export PATH="$SHIM:$PATH"

write_gh_shim() {
  cat > "$SHIM/gh" <<'GH'
#!/bin/bash
# verify-only stub. Emits MOCK_ATTEST_STDERR to stderr and
# exits with MOCK_ATTEST_EXIT (default 1, since both the
# 404 and the verification-failed paths exit non-zero).
case "$*" in
  "attestation verify"*)
    printf '%s\n' "${MOCK_ATTEST_STDERR:-no attestations found for the subject}" >&2
    exit "${MOCK_ATTEST_EXIT:-1}"
    ;;
esac
echo "unmocked gh: $*" >&2
exit 1
GH
  chmod +x "$SHIM/gh"
}
write_gh_shim

# Source just the functions, not the recipe loop.
cd "$WORK"
# shellcheck source=/dev/null
. "$REPO_ROOT/.github/scripts/auto-update.sh"

mkdir -p .github
: > .github/auto-update-attest-required.txt
ATTEST_REQUIRED_FILE=".github/auto-update-attest-required.txt"

# Create a dummy tarball so the function can pass it in.
echo "tarball-bytes" > "$WORK/x.tar.gz"

fail=0

check() {
  local label="$1" stderr="$2" want="$3"
  local got
  got=$(MOCK_ATTEST_STDERR="$stderr" \
        verify_upstream_attestation "$WORK/x.tar.gz" "example/repo" \
        2>/dev/null || true)
  if [ "$got" = "$want" ]; then
    echo "PASS $label"
  else
    echo "FAIL $label: got=$got want=$want"
    fail=1
  fi
}

# Existing wording — already handled.
check "1_no_attestations_message" \
      "no attestations found for the subject" \
      "unattested"

# Real-world wording from gh 2.x — currently mis-classified
# as invalid → tampered. Should be "unattested".
check "2_http_404_attestations_endpoint" \
      "Error: HTTP 404: Not Found (https://api.github.com/orgs/rhysd/attestations/sha256:454800bd4f854592bcfe79b161f71d56e35940eb7016e48a26dd356adc9d400a?per_page=30&predicate_type=https://slsa.dev/provenance/v1)" \
      "unattested"

# Generic 404 not pointing at the attestations endpoint
# should still be invalid (could be a different bug; don't
# silently swallow).
check "3_unrelated_404_stays_invalid" \
      "Error: HTTP 404: Not Found (https://api.github.com/repos/foo/bar)" \
      "invalid"

# A real verification failure (signature mismatch) — wording
# typically contains "verification failed". Stays invalid.
check "4_signature_failure_invalid" \
      "Loaded digest sha256:abc for file://x.tar.gz. Sigstore verification failed: signature mismatch" \
      "invalid"

exit "$fail"
