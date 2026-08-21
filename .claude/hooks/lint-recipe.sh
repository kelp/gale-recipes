#!/usr/bin/env bash
# PostToolUse(Edit|Write): parse every .toml, and `gale lint`
# every index document.

set -uo pipefail

file_path="$(jq -r '.file_path // .filePath // empty' 2>/dev/null <<<"${CLAUDE_TOOL_INPUT:-}")"
[ -n "$file_path" ] || exit 0
[ -f "$file_path" ] || exit 0

case "$file_path" in
  *.toml) ;;
  *) exit 0 ;;
esac

if ! python3 -c "import tomllib, sys; tomllib.load(open(sys.argv[1],'rb'))" "$file_path"; then
  echo "Invalid TOML syntax: $file_path" >&2
  exit 2
fi

case "$file_path" in
  index/*/*.toml | */index/*/*.toml) ;;
  *) exit 0 ;;
esac

if ! command -v gale >/dev/null 2>&1; then
  echo "note: gale not on PATH yet (bootstrap may still be running); skipped 'gale lint $file_path'" >&2
  exit 0
fi

if ! gale lint "$file_path"; then
  exit 2
fi

exit 0
