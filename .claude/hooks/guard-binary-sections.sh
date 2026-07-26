#!/usr/bin/env bash
# PreToolUse(Edit|Write) guard: binary metadata is CI-managed, not hand-edited.
#
# `.binaries.toml` files (head mirror + append-only [[history]] ledger) are
# written only by build.yml via scripts/write_binaries.py. Inline
# `[binary.<platform>]` sections in a recipe are equally off-limits.
#
# This used to be an inline one-liner in settings.json that grepped the WHOLE
# tool input for "[binary.", so it also blocked edits to docs that merely
# mention the string. It now looks at the target path and the written content
# separately.

set -uo pipefail

input="${CLAUDE_TOOL_INPUT:-}"
[ -n "$input" ] || exit 0

file_path="$(jq -r '.file_path // .filePath // empty' 2>/dev/null <<<"$input")"
[ -n "$file_path" ] || exit 0

case "$file_path" in
  *.binaries.toml)
    echo "BLOCK: .binaries.toml is written by CI (build.yml -> scripts/write_binaries.py). Do not edit it by hand." >&2
    exit 2
    ;;
  recipes/*/*.toml | */recipes/*/*.toml) ;;
  *) exit 0 ;;
esac

# Only the content actually being written matters, not the whole payload.
content="$(jq -r '.content // .new_string // empty' 2>/dev/null <<<"$input")"
if grep -q '^\[binary\.' <<<"$content"; then
  echo "BLOCK: [binary.<platform>] sections are managed by CI - do not add them to a recipe." >&2
  exit 2
fi

exit 0
