#!/usr/bin/env bash
# agent-bootstrap.sh — install the recipe-authoring toolchain in an agent sandbox.
#
# Agent containers ship python3 and git but not gale, just or actionlint, so
# `just lint` and the PostToolUse recipe-lint hook cannot run out of the box.
# This installs the three missing tools. Nothing else is needed: every script
# under scripts/ is stdlib-only Python (>= 3.11 for tomllib), so there is no
# pip step. See docs/dev/agent-environment.md.
#
# Note that recipes cannot be BUILT here — `gale build` and `gale install`
# depend on hosts the sandbox egress policy blocks. `gale lint` is fully
# offline and is the local gate; real builds happen in CI (verify.yml).
#
# Properties, matching ../gale/scripts/agent-bootstrap.sh:
#
#   Idempotent   Every step is skipped when already satisfied.
#   Serialized   An flock means a second invocation BLOCKS until the first
#                finishes. That is the wait primitive: to wait for the
#                background session-start bootstrap, just run this script.
#   Best-effort  One failed tool never aborts the rest; failures land in the
#                status file.
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

# Same awk idiom build.yml uses to read the gale version out of its recipe —
# the pin lives in the repo, never in this script.
recipe_version() {
  awk -F'"' '/^version[[:space:]]*=/ { print $2; exit }' "$repo_root/recipes/$1/$2.toml"
}

pin() {
  awk -F'"' -v key="$1" '
    $0 ~ "^[[:space:]]*" key "[[:space:]]*=" { print $2; exit }
  ' "$repo_root/gale.toml"
}

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

# member is a `find -name` glob, not a literal: release layouts differ. just
# and actionlint ship a plain `<name>` inside a directory; gale's tarball is a
# single file named gale-v<ver>-<os>-<arch>.
install_release_tarball() {
  local name="$1" url="$2" member="$3"
  if [ -x "$bin_dir/$name" ]; then
    record "$name" "ok (already present)"
    return 0
  fi
  note "downloading $name from $url"
  local tmp
  tmp="$(mktemp -d)"
  # Retry: the egress proxy returns an occasional transient 502 on release
  # assets, and a bootstrap that gives up on one is worse than a slow one.
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

# 1. gale. Prefer the sibling checkout so the linter matches the CLI under
#    development; fall back to the release this repo pins for CI, so the
#    bootstrap still works when gale-recipes is cloned on its own.
if [ -d "$repo_root/../gale/cmd/gale" ] && command -v go >/dev/null 2>&1; then
  note "building gale from the sibling ../gale checkout"
  if (cd "$repo_root/../gale" && go build -o "$bin_dir/gale" ./cmd/gale/); then
    record "gale" "ok (built from ../gale)"
  else
    record "gale" "FAILED (go build ../gale/cmd/gale)"
  fi
else
  gale_version="$(recipe_version g gale)"
  arch="$(arch_slug)"
  if [ -n "$gale_version" ] && [ -n "$arch" ]; then
    # Release assets embed the leading v twice: gale-v<ver>-<os>-<arch>.tar.gz.
    install_release_tarball gale \
      "https://github.com/kelp/gale/releases/download/v${gale_version}/gale-v${gale_version}-$(uname -s | tr '[:upper:]' '[:lower:]')-${arch}.tar.gz" \
      "gale-v${gale_version}-*"
  else
    record "gale" "SKIPPED (no sibling checkout, no pinned release for this platform)"
  fi
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
    "https://github.com/rhysd/actionlint/releases/download/v$(pin actionlint)/actionlint_$(pin actionlint)_linux_$(arch_slug).tar.gz" \
    actionlint
fi

# 3. just — every documented command in CLAUDE.md goes through it. The pin
#    lives in the gale repo's gale.toml; this repo does not pin just.
just_version="1.48.0"
if [ -n "$(just_arch_slug)" ]; then
  install_release_tarball just \
    "https://github.com/casey/just/releases/download/${just_version}/just-${just_version}-$(just_arch_slug)-unknown-linux-musl.tar.gz" \
    just
else
  record "just" "SKIPPED (unsupported arch $(uname -m))"
fi

# 4. check_ledger.py diffs against origin/main and needs real history.
if [ "$(git -C "$repo_root" rev-parse --is-shallow-repository 2>/dev/null)" = "true" ]; then
  git -C "$repo_root" fetch --unshallow origin main >/dev/null 2>&1 &&
    record "git-history" "ok (unshallowed)" ||
    record "git-history" "FAILED (fetch --unshallow)"
else
  record "git-history" "ok (full history)"
fi

# scripts/ is stdlib-only; record the interpreter so a version regression is
# visible rather than mysterious (tomllib needs >= 3.11).
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
