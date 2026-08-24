#!/usr/bin/env bash
# agent-bootstrap.sh — install the index-lint toolchain in an
# agent sandbox.
#
# Agent containers ship python3 and git but not gale, just or
# actionlint, so `just lint` cannot run out of the box. This
# installs the three missing tools. Nothing else is needed:
# every script under scripts/ is stdlib-only Python (>= 3.11
# for tomllib). See docs/dev/agent-environment.md.
#
# gale install cannot work here. gale build is gone.
# `gale lint` is offline and is the local gate for
# index documents.
#
# Properties, matching ../gale/scripts/agent-bootstrap.sh:
#
#   Idempotent   Every step is skipped when already satisfied.
#   Serialized   An flock means a second invocation BLOCKS until
#                the first finishes. That is the wait primitive.
#   Best-effort  One failed tool never aborts the rest; failures
#                land in the status file.
#
# Usage:
#   scripts/agent-bootstrap.sh          # no-op unless CLAUDE_CODE_REMOTE is set
#   scripts/agent-bootstrap.sh --force  # run anywhere (also: just agent-bootstrap)

set -uo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin_dir="$HOME/.local/bin"
state_dir="$HOME/.cache/gale-agent-bootstrap"
status_file="$state_dir/status-recipes"
lock_file="$state_dir/lock-recipes"

# Index-linting gale (post GHCR delete, kelp/gale#306).
# Bump when the index-lint dispatch on gale main changes.
GALE_FALLBACK_SHA="dbd2446"
ACTIONLINT_VERSION="1.7.12"
JUST_VERSION="1.48.0"

force=0
[ "${1:-}" = "--force" ] && force=1

if [ "$force" -eq 0 ] && [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  echo "agent-bootstrap: not a remote agent container; skipping (use --force to override)"
  exit 0
fi

mkdir -p "$bin_dir" "$state_dir"

if [ "${GALE_BOOTSTRAP_LOCKED:-}" != "1" ]; then
  export GALE_BOOTSTRAP_LOCKED=1
  exec flock "$lock_file" "${BASH_SOURCE[0]}" "$@"
fi

record() { printf '%-16s %s\n' "$1" "$2" >>"$status_file"; }

note() { echo "agent-bootstrap: $*"; }

: >"$status_file"
record "started" "$(date -u +%Y-%m-%dT%H:%M:%SZ) repo=$repo_root"

arch_slug() {
  case "$(uname -m)" in
    x86_64 | amd64) echo "amd64" ;;
    aarch64 | arm64) echo "arm64" ;;
    *) echo "" ;;
  esac
}

just_arch_slug() {
  case "$(uname -m)" in
    x86_64 | amd64) echo "x86_64" ;;
    aarch64 | arm64) echo "aarch64" ;;
    *) echo "" ;;
  esac
}

# member is a `find -name` glob, not a literal: release layouts differ.
install_release_tarball() {
  local name="$1" url="$2" member="$3"
  if [ -x "$bin_dir/$name" ]; then
    record "$name" "ok (already present)"
    return 0
  fi
  note "downloading $name from $url"
  local tmp
  tmp="$(mktemp -d)"
  if curl -fsSL --retry 3 --retry-delay 2 --retry-all-errors "$url" -o "$tmp/asset.tar.gz" &&
    tar -xzf "$tmp/asset.tar.gz" -C "$tmp" &&
    find "$tmp" -type f -name "$member" -perm -u+x -exec install -m 0755 {} "$bin_dir/$name" \; &&
    [ -x "$bin_dir/$name" ]; then
    record "$name" "ok ($url)"
  else
    record "$name" "FAILED ($url)"
  fi
  rm -rf "$tmp"
}

# 1. gale. Prefer the sibling checkout so the linter matches
#    the CLI under development. Solo-clone fallback builds the
#    named index-linting commit; do not download a release
#    binary that cannot lint index documents.
if [ -d "$repo_root/../gale/cmd/gale" ] && command -v go >/dev/null 2>&1; then
  note "building gale from the sibling ../gale checkout"
  if (cd "$repo_root/../gale" && go build -o "$bin_dir/gale" ./cmd/gale/); then
    record "gale" "ok (built from ../gale)"
  else
    record "gale" "FAILED (go build ../gale/cmd/gale)"
  fi
elif command -v go >/dev/null 2>&1; then
  note "cloning kelp/gale at ${GALE_FALLBACK_SHA}"
  src="$(mktemp -d)"
  if git clone --depth 1 https://github.com/kelp/gale.git "$src/gale" &&
    git -C "$src/gale" fetch --depth 1 origin "${GALE_FALLBACK_SHA}" &&
    git -C "$src/gale" checkout FETCH_HEAD &&
    (cd "$src/gale" && go build -o "$bin_dir/gale" ./cmd/gale/); then
    record "gale" "ok (kelp/gale@${GALE_FALLBACK_SHA})"
  else
    record "gale" "FAILED (clone/build kelp/gale@${GALE_FALLBACK_SHA})"
  fi
  rm -rf "$src"
else
  record "gale" "SKIPPED (no sibling checkout, no go)"
fi

# 2. actionlint — the second half of `just lint`.
if command -v actionlint >/dev/null 2>&1 && [ -x "$bin_dir/actionlint" ]; then
  record "actionlint" "ok (already present)"
elif command -v go >/dev/null 2>&1; then
  note "installing actionlint"
  if GOBIN="$bin_dir" go install github.com/rhysd/actionlint/cmd/actionlint@latest 2>&1 | tail -3; then
    record "actionlint" "ok (go install)"
  else
    record "actionlint" "FAILED (go install)"
  fi
else
  install_release_tarball actionlint \
    "https://github.com/rhysd/actionlint/releases/download/v${ACTIONLINT_VERSION}/actionlint_${ACTIONLINT_VERSION}_linux_$(arch_slug).tar.gz" \
    actionlint
fi

# 3. just
if [ -n "$(just_arch_slug)" ]; then
  install_release_tarball just \
    "https://github.com/casey/just/releases/download/${JUST_VERSION}/just-${JUST_VERSION}-$(just_arch_slug)-unknown-linux-musl.tar.gz" \
    just
else
  record "just" "SKIPPED (unsupported arch $(uname -m))"
fi

if python3 -c 'import sys, tomllib; assert sys.version_info >= (3, 11)' 2>/dev/null; then
  record "python3" "ok ($(python3 --version 2>&1))"
else
  record "python3" "FAILED (need >= 3.11 for tomllib)"
fi

if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export GOBIN=$bin_dir"
    echo "export PATH=$bin_dir:\$PATH"
  } >>"$CLAUDE_ENV_FILE"
fi

if grep -q FAILED "$status_file"; then
  record "finished" "with failures — see lines above"
else
  record "finished" "all tools ready"
fi

cat "$status_file"
