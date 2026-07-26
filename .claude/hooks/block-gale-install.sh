#!/usr/bin/env bash
# PreToolUse(Bash) guard: refuse `gale install|build|sync` in an agent sandbox.
#
# Recipes cannot be built here. The egress proxy allows ghcr.io's token and
# manifest endpoints but blocks the blob host
# (pkg-containers.githubusercontent.com), so gale resolves a prebuilt binary,
# fails to download it, and falls back to a source build — whose upstream
# hosts (go.dev, ftp.gnu.org, codeload, ci-artifacts.rust-lang.org) are
# blocked too. A measured `gale install just` spent 3m11s compiling rustc
# before dying.
#
# `gale lint` is untouched: it is pure offline TOML validation and is the
# local gate for recipe edits.
#
# Escape hatch: prefix the command with GALE_ALLOW_NETWORK_INSTALL=1.

set -uo pipefail

command_line="$(jq -r '.command // empty' 2>/dev/null <<<"${CLAUDE_TOOL_INPUT:-}")"
[ -n "$command_line" ] || exit 0

grep -q 'GALE_ALLOW_NETWORK_INSTALL=1' <<<"$command_line" && exit 0

# Match only at a command position — start of line or after a separator — so
# `echo gale install ...` and `grep "gale build" docs/` are not flagged.
cmd_start='(^|[;&|(][[:space:]]*)'
if grep -Eq "${cmd_start}(\./)?gale[[:space:]]+(install|build|sync)([[:space:]]|$)" <<<"$command_line"; then
  cat >&2 <<'MSG'
BLOCKED: gale install/build/sync cannot work in this sandbox.

The egress proxy blocks GHCR's blob host, so the binary path fails, and the
source-build fallback's upstream hosts are blocked too. The command will burn
minutes and then fail. Details: docs/dev/agent-environment.md.

Recipe changes are validated locally with `gale lint` and built in CI by
verify.yml. What works here:
  gale lint recipes/<letter>/<name>.toml   offline recipe validation
  just lint                                gale lint + actionlint
  just test                                the python script suite
  python3 scripts/check_ledger.py --base origin/main

Override with GALE_ALLOW_NETWORK_INSTALL=1 if you really mean it.
MSG
  exit 2
fi

exit 0
