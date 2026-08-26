#!/usr/bin/env bash
# PreToolUse(Bash) guard: refuse `gale install|build|sync` in an agent sandbox.
#
# Artifact hosts are blocked by the egress policy. The command
# burns minutes and then fails. `gale lint` is untouched.
#
# Escape hatch: prefix the command with GALE_ALLOW_NETWORK_INSTALL=1.

set -uo pipefail

command_line="$(jq -r '.command // empty' 2>/dev/null <<<"${CLAUDE_TOOL_INPUT:-}")"
[ -n "$command_line" ] || exit 0

grep -q 'GALE_ALLOW_NETWORK_INSTALL=1' <<<"$command_line" && exit 0

cmd_start='(^|[;&|(][[:space:]]*)'
if grep -Eq "${cmd_start}(\./)?gale[[:space:]]+(install|build|sync)([[:space:]]|$)" <<<"$command_line"; then
  cat >&2 <<'MSG'
BLOCKED: gale install/sync cannot work in this sandbox.
gale build is gone.

The egress policy blocks artifact hosts. The command will burn
minutes and then fail. Details: docs/dev/agent-environment.md.

Index changes are validated locally with `gale lint`. What works here:
  gale lint index/<letter>/<name>.toml     offline index validation
  just lint                                index lint + actionlint
  just test                                the python script suite

Override with GALE_ALLOW_NETWORK_INSTALL=1 if you really mean it.
MSG
  exit 2
fi

exit 0
